"""Small shared helpers: subprocess wrappers, JSON IO, hashing."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess


class StudioError(RuntimeError):
    """Any expected pipeline failure (bad input, ffmpeg error, budget stop)."""


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-12:])
        head = " ".join(str(c) for c in cmd[:6])
        raise StudioError(f"command failed ({p.returncode}): {head} ...\n{tail}")
    return p


def ffmpeg(args, cwd=None):
    return run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], cwd=cwd)


def probe_duration(path: str) -> float:
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path])
    return float(p.stdout.strip())


def atomic_write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.replace(tmp, path)
    except OSError:  # some mounts forbid replace/delete: fall back to in-place write
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            os.remove(tmp)
        except OSError:
            pass


def write_json(path: str, obj) -> None:
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def spec_hash(parts: dict) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def extract_last_frame(video: str, out_png: str) -> str:
    ffmpeg(["-sseof", "-0.2", "-i", video, "-frames:v", "1", "-update", "1", out_png])
    return out_png
