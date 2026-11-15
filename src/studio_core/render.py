"""Final assembly: normalize clips, concat, mux mixed audio, optional burned-in subtitles."""
from __future__ import annotations

import os

from .timing import Timeline
from .util import StudioError, ffmpeg, probe_duration

SIZES = {"720p": (1280, 720), "1080p": (1920, 1080), "vertical": (720, 1280), "vertical1080": (1080, 1920)}


def normalize_clip(src: str, dst: str, width: int, height: int, fps: int, duration: float) -> str:
    """Scale-crop to the target frame, force fps, freeze last frame if short, trim to exact length."""
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
          f"fps={fps},tpad=stop_mode=clone:stop_duration=3,trim=duration={duration:.4f},"
          f"setpts=PTS-STARTPTS,format=yuv420p")
    ffmpeg(["-i", src, "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            "-r", fps, dst])
    return dst


def concat_copy(parts: list, dst: str, workdir: str) -> str:
    lst = os.path.join(workdir, "concat_" + os.path.basename(dst) + ".txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '" + os.path.abspath(p).replace("'", "'\\''") + "'\n")
    ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", dst])
    return dst


def assemble(tl: Timeline, shot_clips: dict, audio: str, out_mp4: str, workdir: str,
             size: str = "720p", subtitles_ass: str = "", crf: int = 18) -> str:
    """shot_clips: {shot_id: [segment mp4 paths in order]} matching tl.shots[].segments."""
    if size not in SIZES:
        raise StudioError(f"unknown size '{size}', choose from {sorted(SIZES)}")
    w, h = SIZES[size]
    os.makedirs(workdir, exist_ok=True)
    parts = []
    for st in tl.shots:
        clips = shot_clips.get(st.shot_id) or []
        if len(clips) != len(st.segments):
            raise StudioError(f"shot {st.shot_id}: expected {len(st.segments)} clips, got {len(clips)}")
        for i, (clip, dur) in enumerate(zip(clips, st.segments)):
            if not os.path.exists(clip):
                raise StudioError(f"missing clip {clip}")
            parts.append(normalize_clip(clip, os.path.join(workdir, f"n_{st.shot_id}_{i:02d}.mp4"),
                                        w, h, tl.fps, dur))
    video_only = concat_copy(parts, os.path.join(workdir, "video_only.mp4"), workdir)
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)
    args = ["-i", video_only, "-i", audio, "-map", "0:v:0", "-map", "1:a:0"]
    cwd = None
    if subtitles_ass:
        # relative name + cwd avoids filter-path escaping problems
        local = os.path.join(workdir, "subs.ass")
        if os.path.abspath(subtitles_ass) != os.path.abspath(local):
            with open(subtitles_ass, "rb") as a, open(local, "wb") as b:
                b.write(a.read())
        args += ["-vf", "ass=subs.ass", "-c:v", "libx264", "-preset", "medium", "-crf", crf, "-pix_fmt", "yuv420p"]
        cwd = workdir
        out_arg = os.path.abspath(out_mp4)
    else:
        args += ["-c:v", "copy"]
        out_arg = out_mp4
    args += ["-c:a", "aac", "-b:a", "192k", "-t", f"{tl.total:.3f}", "-movflags", "+faststart", out_arg]
    ffmpeg(args, cwd=cwd)
    got = probe_duration(out_mp4)
    if abs(got - tl.total) > 0.6:
        raise StudioError(f"final duration {got:.2f}s differs from timeline {tl.total:.2f}s")
    return out_mp4
