import os

import pytest

from src.studio_core import manifest as M, subtitles, timing
from src.studio_core.manifest import Episode, Shot


def make_ep():
    shots = [Shot("s01", 1, "Novi", "waves", {"hindi": "नमस्ते दोस्तों, आज हम खेलेंगे", "english": "Hello friends"},
                  ["Novi"], "assets/characters/novi_and_friends.jpg", "Novi waves", seed=11),
             Shot("s02", 2, "", "wide", {}, ["Mimi"], "assets/characters/novi_and_friends.jpg", "Mimi jumps", seed=12)]
    return Episode("t", "T", ["hindi", "english"], 24, shots)


def test_split_segments_sum_and_limit():
    for dur in (3.0, 5.0, 5.04, 9.2, 13.5):
        segs = timing.split_segments(dur, 5.0, 24)
        assert abs(sum(segs) - dur) < 1 / 24 and max(segs) <= 5.0 + 1e-9


def test_model_frames_8n_plus_1():
    assert timing.model_frames(5.0, 24) == 121
    assert (timing.model_frames(3.3, 24) - 1) % 8 == 0
    assert timing.model_frames(3.3, 24) >= round(3.3 * 24)


def test_timeline_uses_audio_length_and_min_duration():
    ep = make_ep()
    tl = timing.build_timeline(ep, "hindi", {"s01": "a.mp3"}, probe=lambda p: 6.0)
    assert tl.shots[0].duration >= 6.0 + 0.35 + 0.55 - 1e-6
    assert tl.shots[1].duration == 3.0 and tl.shots[1].start == tl.shots[0].duration
    assert sum(tl.shots[0].segments) == pytest.approx(tl.shots[0].duration, abs=1e-3)
    assert timing.Timeline.from_dict(tl.to_dict()).total == tl.total


def test_timeline_rejects_unknown_language():
    with pytest.raises(Exception):
        timing.build_timeline(make_ep(), "french", {})


def test_manifest_roundtrip_and_validate(tmp_path):
    ep = make_ep()
    p = tmp_path / "m.json"
    M.save(ep, str(p))
    assert M.load(str(p)).shot("s02").motion_prompt == "Mimi jumps"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert M.validate(ep, root) == []
    ep.shots[0].motion_prompt = ""
    ep.shots[1].shot_id = "s01"
    probs = " ".join(M.validate(ep, root))
    assert "duplicate" in probs and "motion" in probs


def test_stable_seed_is_deterministic():
    assert M.stable_seed("e", "s1") == M.stable_seed("e", "s1") != M.stable_seed("e", "s2")


def test_subtitles_srt_and_ass():
    ep = make_ep()
    tl = timing.build_timeline(ep, "hindi", {"s01": "a.mp3"}, probe=lambda p: 6.0)
    cues = subtitles.build_cues(ep, tl)
    assert cues and all(c[1] > c[0] for c in cues) or all(c["end"] > c["start"] for c in cues)
    srt = subtitles.to_srt(cues)
    assert "-->" in srt and srt.startswith("1\n")
    assert "[Events]" in subtitles.to_ass(cues, 1280, 720)


def test_still_and_sheet_prompts_forbid_text():
    from src.studio_core import prompts
    chars = prompts.load_characters()
    ep = make_ep()
    st = prompts.still_prompt(ep.shots[0], chars)
    assert "no text" in st and "no thumbnail" in st and "baby bunny" in st
    assert "No text labels" in prompts.sheet_prompt("Novi", chars)
