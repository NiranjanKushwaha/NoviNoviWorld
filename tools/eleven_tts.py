#!/usr/bin/env python3
"""ElevenLabs text-to-speech for `movie_studio.py tts --cmd`. Needs env ELEVENLABS_API_KEY.

Example:
  movie_studio.py tts ep01_rainbow_slide --ext mp3 --cmd \
    "python tools/eleven_tts.py --text-file {text_file} --out {out} --voice-id {voice}"
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice-id", required=True)
    ap.add_argument("--model", default="eleven_v3")
    ap.add_argument("--stability", type=float, default=0.5)  # v3: 0 creative, 0.5 natural, 1 robust
    a = ap.parse_args()
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        print("set ELEVENLABS_API_KEY first", file=sys.stderr)
        return 2
    if not a.voice_id:
        print("no voice id: set voice_id for this character in characters.json", file=sys.stderr)
        return 2
    text = open(a.text_file, encoding="utf-8").read().strip()
    body = json.dumps({"text": text, "model_id": a.model,
                       "voice_settings": {"stability": a.stability, "similarity_boost": 0.8}}).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{a.voice_id}?output_format=mp3_44100_128", data=body,
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        audio = urllib.request.urlopen(req, timeout=120).read()
    except urllib.error.HTTPError as e:
        print(f"ElevenLabs HTTP {e.code}: {e.read()[:300]!r}", file=sys.stderr)
        return 1
    with open(a.out, "wb") as fh:
        fh.write(audio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
