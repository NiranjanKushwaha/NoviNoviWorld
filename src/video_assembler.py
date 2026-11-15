"""
NoviNovi World: Multi-Platform Video Assembler
Assembles video clips/scenes into:
1. YouTube Widescreen 16:9 (1920x1080)
2. Instagram Reels / Shorts 9:16 (1080x1920)
Enforces broadcast standards: libx264, yuv420p (no black screen), AAC stereo, and faststart moov atom.
"""

import os
import glob
import subprocess

def assemble_final_video(clips_or_images: list, audio_track: str, output_path: str, is_vertical: bool = False, clip_duration: float = 5.0):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    n = len(clips_or_images)
    if n == 0:
        raise ValueError("No input clips or images provided for assembly.")

    inputs = []
    filter_parts = []

    for i, item in enumerate(clips_or_images):
        inputs.extend(["-loop", "1", "-t", str(clip_duration), "-i", item])
        if is_vertical:
            filter_parts.append(
                f"[{i}:v]scale=-1:8000:out_range=limited,zoompan=z='min(zoom+0.0015,1.3)':d={int(clip_duration*30)}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,scale=out_range=limited,format=yuv420p[v{i}]"
            )
        else:
            filter_parts.append(
                f"[{i}:v]scale=8000:-1:out_range=limited,zoompan=z='min(zoom+0.0012,1.25)':d={int(clip_duration*30)}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=30,scale=out_range=limited,format=yuv420p[v{i}]"
            )

    concat_inputs = "".join([f"[v{i}]" for i in range(n)])
    full_filter = f"{';'.join(filter_parts)};{concat_inputs}concat=n={n}:v=1:a=0[vout]"

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-i", audio_track,
        "-filter_complex", full_filter,
        "-map", "[vout]", "-map", f"{n}:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest", output_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_path
