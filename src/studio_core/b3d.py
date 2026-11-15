"""3D shots through headless Blender: lip-sync envelope -> shot spec -> render -> mp4 clip."""
from __future__ import annotations

import array
import glob
import math
import os
import shutil
import subprocess
import sys

from .util import StudioError, ffmpeg, file_sha256, spec_hash, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "blender3d"))
BLENDER_CANDIDATES = ["/opt/homebrew/bin/blender", "/Applications/Blender.app/Contents/MacOS/Blender",
                      "/usr/local/bin/blender", "blender"]

# (keyword in the shot's action text, motion name); first match wins
MOTION_RULES = [("slide", "slide"), ("climb", "climb"), ("shar", "share"), ("hug", "share"), ("belly", "belly"),
                ("dance", "dance"), ("fly", "flutter"), ("flutter", "flutter"), ("step", "walk_slow"),
                ("walk", "walk_slow"), ("hop", "hop_run"), ("run", "hop_run")]

QUALITY = {  # name -> (width, height, eevee samples)
    "preview": (640, 360, 8), "720p": (1280, 720, 32), "1080p": (1920, 1080, 48)}


def find_blender() -> str:
    env = os.environ.get("BLENDER")
    if env:
        return env
    for c in BLENDER_CANDIDATES:
        p = c if os.path.isabs(c) else shutil.which(c)
        if p and os.path.exists(p):
            return p
    raise StudioError("Blender not found. Install: brew install --cask blender  (or set BLENDER=/path/to/blender)")


def pick_motion(action: str) -> str:
    a = (action or "").lower()
    for key, motion in MOTION_RULES:
        if key in a:
            return motion
    return "cheer"


def species_of(text: str) -> str:
    t = (text or "").lower()
    for key, sp in (("bunny", "bunny"), ("rabbit", "bunny"), ("bear", "bear"), ("bird", "bird"), ("turtle", "turtle")):
        if key in t:
            return sp
    return "bunny"


def mouth_envelope(audio: str, fps: int, n_frames: int, offset: float = 0.0) -> list:
    """Per-frame [openness 0..1, width 0..1] from the voice; fast attack, slower release."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", audio, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise StudioError(f"cannot decode audio for lip-sync: {audio}\n{p.stderr.decode(errors='ignore')[-300:]}")
    smp = array.array("h")
    smp.frombytes(p.stdout[: len(p.stdout) // 2 * 2])
    if sys.byteorder == "big":
        smp.byteswap()
    win = 16000 // fps
    rms, zcr = [], []
    for f in range(n_frames):
        a = int(round((f / fps - offset) * 16000))
        seg = smp[a:a + win] if a >= 0 else array.array("h")
        if len(seg) < win // 2:
            rms.append(0.0)
            zcr.append(0.0)
            continue
        rms.append(math.sqrt(sum(x * x for x in seg) / len(seg)))
        zcr.append(sum(1 for i in range(1, len(seg)) if (seg[i - 1] < 0) != (seg[i] < 0)) / len(seg))
    ref = sorted(rms)[int(len(rms) * 0.92)] if any(rms) else 1.0
    ref = max(ref, 1.0)
    out, prev = [], 0.0
    for r, z in zip(rms, zcr):
        raw = max(0.0, min(1.0, (r / ref) ** 0.8)) if r > 0.07 * ref else 0.0
        prev = max(raw, prev * 0.6)
        out.append([round(prev, 3), round(max(0.0, min(1.0, z / 0.25)), 3)])
    return out


def build_spec(ep, shot, st, characters: dict, audio: str, quality: str, engine: str, out_dir: str,
               backdrop: str = "", cam_override: str = "") -> dict:
    if quality not in QUALITY:
        raise StudioError(f"unknown quality '{quality}', choose from {sorted(QUALITY)}")
    w, h, samples = QUALITY[quality]
    n = max(1, int(round(st.duration * ep.fps)))
    names = list(shot.characters or ([shot.speaker] if shot.speaker else []))
    if not names:
        raise StudioError(f"shot {shot.shot_id} has no characters")
    chars = [{"name": nm, "species": species_of(characters.get(nm, {}).get("species", nm)),
              "role": "lead" if nm == shot.speaker else "support"} for nm in names]
    if not any(c["role"] == "lead" for c in chars):
        chars[0]["role"] = "lead"
    mouth = mouth_envelope(audio, ep.fps, n, st.voice_offset) if audio else [[0.0, 0.5]] * n
    return {"shot_id": shot.shot_id, "scene": shot.scene, "fps": ep.fps, "frames": n, "res": [w, h],
            "engine": engine, "samples": samples, "out_dir": out_dir, "characters": chars,
            "motion": pick_motion(shot.action), "camera": cam_override or shot.camera, "mouth": mouth,
            "seed": shot.seed or shot.scene, "backdrop": backdrop}


def default_runner(blender: str):
    script = os.path.join(SCRIPT_DIR, "render_shot.py")

    def run_blender(spec_path: str, log_path: str) -> None:
        with open(log_path, "w", encoding="utf-8") as lg:
            p = subprocess.run([blender, "-b", "-noaudio", "-P", script, "--", spec_path],
                               stdout=lg, stderr=subprocess.STDOUT)
        if p.returncode != 0:
            tail = open(log_path, encoding="utf-8", errors="ignore").read().splitlines()[-15:]
            raise StudioError("Blender failed:\n" + "\n".join(tail))

    return run_blender


def render_shot(spec: dict, workdir: str, runner=None, force: bool = False, frames: tuple = ()) -> str:
    """Render one shot to <workdir>/<shot>.mp4; skipped when an identical render already exists."""
    sid = spec["shot_id"]
    os.makedirs(workdir, exist_ok=True)
    out_mp4 = os.path.join(workdir, f"{sid}.mp4")
    stamp = out_mp4 + ".hash"
    code_hash = file_sha256(os.path.join(SCRIPT_DIR, "studio3d.py"))
    sig = spec_hash({"spec": {k: v for k, v in spec.items() if k != "out_dir"}, "code": code_hash, "frames": list(frames)})
    if not force and os.path.exists(out_mp4) and os.path.exists(stamp) and open(stamp).read().strip() == sig:
        return out_mp4
    frame_dir = os.path.join(workdir, f"{sid}_frames")
    os.makedirs(frame_dir, exist_ok=True)
    for old in glob.glob(os.path.join(frame_dir, "f_*.png")):
        try:
            os.remove(old)
        except OSError:
            pass
    spec = dict(spec, out_dir=frame_dir)
    if frames:
        spec["frame_range"] = list(frames)
    spec_path = os.path.join(workdir, f"{sid}_spec.json")
    write_json(spec_path, spec)
    (runner or default_runner(find_blender()))(spec_path, os.path.join(workdir, f"{sid}_render.log"))
    want = (frames[1] - frames[0] + 1) if frames else spec["frames"]
    got = sorted(glob.glob(os.path.join(frame_dir, "f_*.png")))
    if len(got) != want:
        raise StudioError(f"shot {sid}: expected {want} frames, Blender produced {len(got)} (see {sid}_render.log)")
    ffmpeg(["-framerate", spec["fps"], "-start_number", frames[0] if frames else 1, "-i",
            os.path.join(frame_dir, "f_%04d.png"), "-c:v", "libx264", "-crf", 16, "-preset", "veryfast",
            "-pix_fmt", "yuv420p", out_mp4])
    with open(stamp, "w") as fh:
        fh.write(sig)
    shutil.rmtree(frame_dir, ignore_errors=True)
    return out_mp4
