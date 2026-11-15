import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EP = "ep01_rainbow_slide"


@pytest.mark.skipif(not os.path.isdir(os.path.join(ROOT, "episodes", EP, "audio", "hindi")),
                    reason="needs the real ep01 audio")
def test_full_pipeline_with_mock_gpu(tmp_path):
    data = tmp_path / "proj"
    shutil.copytree(os.path.join(ROOT, "assets"), data / "assets")
    shutil.copytree(os.path.join(ROOT, "episodes", EP, "audio"), data / "episodes" / EP / "audio")
    shutil.copy(os.path.join(ROOT, "studio.py"), data / "studio.py")
    (data / "studio_config.json").write_text(json.dumps({"gen_width": 640, "gen_height": 352}))
    env = dict(os.environ, STUDIO_ROOT=str(data))

    def cli(*a):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "movie_studio.py"), *a], env=env,
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stdout + p.stderr
        return p.stdout

    cli("init", EP)
    assert "OK" in cli("validate", EP)
    assert "22 clips" in cli("plan", EP)
    assert "'done': 22" in cli("render", EP, "--provider", "mock")
    out_text = cli("assemble", EP, "--size", "720p")
    mp4 = data / "episodes" / EP / "exports" / f"{EP}_hindi_720p.mp4"
    assert mp4.exists() and "wrote" in out_text
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate",
                            "-show_entries", "format=duration", "-of", "json", str(mp4)],
                           capture_output=True, text=True, check=True)
    info = json.loads(probe.stdout)
    kinds = {s["codec_type"] for s in info["streams"]}
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert kinds == {"video", "audio"} and (v["width"], v["height"]) == (1280, 720)
    assert float(info["format"]["duration"]) == pytest.approx(89.25, abs=0.6)
    # second render is fully cached: no new clips rendered
    assert "'done': 0" in cli("render", EP, "--provider", "mock")
