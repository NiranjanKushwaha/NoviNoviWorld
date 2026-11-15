import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.studio_core import b3d, manifest as M, timing  # noqa: E402
from src.studio_core.util import StudioError, ffmpeg  # noqa: E402


def test_pick_motion_from_action_text():
    assert b3d.pick_motion("Fast Spiral Rainbow Water Slide Zoom") == "slide"
    assert b3d.pick_motion("Tree Climbing Physics") == "climb"
    assert b3d.pick_motion("Chubby Bear Belly Dance & Berry Munching") == "belly"
    assert b3d.pick_motion("Treehouse Balcony Victory Dance") == "dance"
    assert b3d.pick_motion("Soft Marshmallow Landing, Sharing Fruit & Hugging") == "share"
    assert b3d.pick_motion("Running & Hopping across forest path") == "hop_run"
    assert b3d.pick_motion("something unknown") == "cheer"


def test_species_of():
    assert b3d.species_of("baby bunny") == "bunny"
    assert b3d.species_of("baby bluebird") == "bird"
    assert b3d.species_of("Toby the turtle") == "turtle"


def _tone_with_gap(path):
    # 1 s tone, 1 s silence, 1 s tone (finite, mono 16 kHz)
    ffmpeg(["-f", "lavfi", "-i", "aevalsrc=if(between(t\\,1\\,2)\\,0\\,0.6*sin(2*PI*220*t)):d=3:s=16000", path])


def test_mouth_envelope_follows_the_voice(tmp_path):
    wav = str(tmp_path / "t.wav")
    _tone_with_gap(wav)
    env = b3d.mouth_envelope(wav, 24, 72)
    assert len(env) == 72
    assert env[10][0] > 0.5 and env[60][0] > 0.5      # speaking
    assert env[36][0] < 0.1                            # silence in the middle closes the mouth
    assert all(0.0 <= o <= 1.0 and 0.0 <= w <= 1.0 for o, w in env)


def test_mouth_envelope_respects_voice_offset(tmp_path):
    wav = str(tmp_path / "t.wav")
    ffmpeg(["-f", "lavfi", "-i", "sine=frequency=220:duration=1", wav])
    env = b3d.mouth_envelope(wav, 24, 48, offset=0.5)
    assert env[3][0] == 0.0                            # before the voice starts
    assert env[20][0] > 0.5


def test_mouth_envelope_bad_audio_is_a_clear_error(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    with pytest.raises(StudioError):
        b3d.mouth_envelope(str(bad), 24, 10)


def _episode():
    sh = [M.Shot("s01", 1, "Novi", "Running & Hopping", {"hindi": "x"}, ["Novi"]),
          M.Shot("s02", 2, "Mimi", "Belly Dance", {"hindi": "y"}, ["Mimi", "Novi"])]
    return M.Episode("e", "t", ["hindi"], 24, sh)


def test_build_spec_roles_and_frames(tmp_path):
    ep = _episode()
    st = timing.ShotTiming("s02", 0.0, 2.0, 0.3, 1.0, [2.0])
    chars = {"Mimi": {"species": "bear cub"}, "Novi": {"species": "baby bunny"}}
    spec = b3d.build_spec(ep, ep.shot("s02"), st, chars, "", "preview", "eevee", "")
    assert spec["frames"] == 48 and spec["motion"] == "belly"
    assert [(c["name"], c["role"], c["species"]) for c in spec["characters"]] == [
        ("Mimi", "lead", "bear"), ("Novi", "support", "bunny")]
    assert spec["res"] == [640, 360] and len(spec["mouth"]) == 48


def test_build_spec_unknown_quality():
    ep = _episode()
    st = timing.ShotTiming("s01", 0.0, 2.0)
    with pytest.raises(StudioError):
        b3d.build_spec(ep, ep.shot("s01"), st, {}, "", "8k", "eevee", "")


def _fake_runner(spec_path, log):
    import json
    spec = json.load(open(spec_path))
    n = spec["frames"] if "frame_range" not in spec else spec["frame_range"][1] - spec["frame_range"][0] + 1
    start = 1 if "frame_range" not in spec else spec["frame_range"][0]
    ffmpeg(["-f", "lavfi", "-i", "color=c=0x66cc88:s=160x90:r=24", "-frames:v", n, "-start_number", start,
            os.path.join(spec["out_dir"], "f_%04d.png")])


def test_render_shot_encodes_and_caches(tmp_path):
    ep = _episode()
    st = timing.ShotTiming("s01", 0.0, 1.0, 0.0, 0.0, [1.0])
    spec = b3d.build_spec(ep, ep.shot("s01"), st, {"Novi": {"species": "bunny"}}, "", "preview", "eevee", "")
    calls = []

    def runner(sp, lg):
        calls.append(1)
        _fake_runner(sp, lg)

    out = b3d.render_shot(spec, str(tmp_path), runner=runner)
    assert os.path.exists(out) and os.path.getsize(out) > 500
    b3d.render_shot(spec, str(tmp_path), runner=runner)          # identical spec: reused
    assert len(calls) == 1
    b3d.render_shot(dict(spec, seed=99), str(tmp_path), runner=runner)   # changed spec: re-rendered
    assert len(calls) == 2


def test_render_shot_reports_missing_frames(tmp_path):
    ep = _episode()
    st = timing.ShotTiming("s01", 0.0, 1.0)
    spec = b3d.build_spec(ep, ep.shot("s01"), st, {}, "", "preview", "eevee", "")
    with pytest.raises(StudioError, match="expected 24 frames"):
        b3d.render_shot(spec, str(tmp_path), runner=lambda sp, lg: None)
