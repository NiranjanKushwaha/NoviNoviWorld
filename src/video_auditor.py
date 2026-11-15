"""
NoviNovi World: Video Quality Auditor & Reviewer
Validates video files for YouTube & Instagram compatibility.
"""

import os
import json
import subprocess

def audit_video_file(video_path: str) -> dict:
    if not os.path.exists(video_path):
        return {"error": f"File not found: {video_path}"}

    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        video_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    data = json.loads(res.stdout)

    v_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration", 0.0))

    report = {
        "file": os.path.basename(video_path),
        "duration": round(duration, 2),
        "resolution": f"{v_stream.get('width', 0)}x{v_stream.get('height', 0)}" if v_stream else "N/A",
        "video_codec": v_stream.get("codec_name", "") if v_stream else "N/A",
        "pixel_format": v_stream.get("pix_fmt", "") if v_stream else "N/A",
        "audio_codec": a_stream.get("codec_name", "") if a_stream else "None",
        "status": "PASS"
    }

    if report["video_codec"] not in ["h264", "libx264"]:
        report["status"] = "FAIL (Video codec must be H.264)"
    elif report["pixel_format"] != "yuv420p":
        report["status"] = "FAIL (Pixel format must be yuv420p)"
    elif not a_stream:
        report["status"] = "FAIL (Missing audio stream)"

    return report
