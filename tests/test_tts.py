import os
import sys

import pytest

from src.studio_core import tts
from src.studio_core.util import StudioError, probe_duration
from tests.test_core import make_ep

FAKE = ("ffmpeg -loglevel error -y -f lavfi -i sine=frequency=440:duration=1.2 {out} "
        "&& test -s {text_file}")


def test_generates_only_spoken_shots_and_skips_existing(tmp_path):
    ep = make_ep()
    chars = {"Novi": {"voice_ref": "ref.wav"}}
    made = tts.generate_episode_audio(ep, tts.CommandTTS(FAKE), "hindi", str(tmp_path), chars)
    assert list(made) == ["s01"] and os.path.basename(made["s01"]) == "scene_01_novi.wav"
    assert probe_duration(made["s01"]) == pytest.approx(1.2, abs=0.2)
    mtime = os.path.getmtime(made["s01"])
    tts.generate_episode_audio(ep, tts.CommandTTS("false {out} {text_file}"), "hindi", str(tmp_path), chars)
    assert os.path.getmtime(made["s01"]) == mtime  # existing file kept, failing command never ran


def test_failure_and_bad_template(tmp_path):
    with pytest.raises(StudioError):
        tts.CommandTTS("echo hi")
    with pytest.raises(StudioError, match="failed"):
        tts.CommandTTS("false {out} {text_file}").synth("x", "Novi", "hindi", str(tmp_path / "a.wav"))
    with pytest.raises(StudioError, match="no audio"):
        tts.CommandTTS("true {out} {text_file}").synth("x", "Novi", "hindi", str(tmp_path / "b.wav"))


def test_text_is_passed_via_file_not_shell(tmp_path):
    cmd = f"{sys.executable} -c \"import sys,shutil;shutil.copy(sys.argv[1], sys.argv[2])\" {{text_file}} {{out}}"
    out = tmp_path / "t.txt"
    with pytest.raises(StudioError):  # copied text is not audio -> rejected, but text with quotes must not break the shell
        tts.CommandTTS(cmd).synth("it's \"quoted\" $(rm -rf /)", "Novi", "hindi", str(out))
    assert "$(rm -rf /)" in out.read_text(encoding="utf-8")
