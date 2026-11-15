"""Pluggable voice generation: any free engine (edge-tts, Indic Parler, IndicF5, ...) behind one command template."""
from __future__ import annotations

import os
import shlex
import subprocess
import tempfile

from .manifest import Episode
from .util import StudioError, probe_duration

EDGE_CMD = "{python} -m edge_tts"  # placeholder name only; edge voices are generated via studio.py voices


class CommandTTS:
    """Runs a shell template. Placeholders: {text_file} {out} {ref} {voice} {lang} {speaker}.

    The command must write an audio file to {out}. Example (run on the GPU pod):
      python tools/gpu_tts.py --text-file {text_file} --out {out} --ref {ref} --lang {lang}
    """

    def __init__(self, template: str, timeout: float = 600.0):
        if "{out}" not in template or "{text_file}" not in template:
            raise StudioError("TTS command template needs {text_file} and {out}")
        self.template, self.timeout = template, timeout

    def synth(self, text: str, speaker: str, lang: str, out_path: str, ref: str = "", voice: str = "") -> str:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(text)
            tf = f.name
        try:
            q = {k: shlex.quote(str(v)) for k, v in dict(text_file=tf, out=out_path, ref=ref, voice=voice,
                                                         lang=lang, speaker=speaker).items()}
            p = subprocess.run(self.template.format(**q), shell=True, capture_output=True, text=True,
                               timeout=self.timeout)
        finally:
            os.remove(tf) if os.path.exists(tf) else None
        if p.returncode != 0:
            raise StudioError(f"TTS command failed ({p.returncode}): {p.stderr.strip()[-300:]}")
        if not os.path.exists(out_path) or os.path.getsize(out_path) < 200:
            raise StudioError(f"TTS produced no audio for {speaker}")
        if probe_duration(out_path) < 0.2:
            raise StudioError(f"TTS audio for {speaker} is empty")
        return out_path


def generate_episode_audio(ep: Episode, engine: CommandTTS, lang: str, out_dir: str, characters: dict,
                           overwrite: bool = False, ext: str = "wav") -> dict:
    """Write scene_NN_<speaker>.<ext> for every spoken shot; returns {shot_id: path}. Existing files are kept."""
    os.makedirs(out_dir, exist_ok=True)
    made = {}
    for s in ep.shots:
        text = (s.dialogue or {}).get(lang, "").strip()
        if not s.speaker or not text:
            continue
        out = os.path.join(out_dir, f"scene_{s.scene:02d}_{s.speaker.lower()}.{ext}")
        if os.path.exists(out) and not overwrite:
            made[s.shot_id] = out
            continue
        ch = characters.get(s.speaker) or {}
        made[s.shot_id] = engine.synth(text, s.speaker, lang, out, ref=ch.get("voice_ref", ""),
                                       voice=ch.get("voice_id", ""))
    return made
