import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src.studio_core.gpu import comfy_client as cc
from src.studio_core.gpu.renderers import ComfyRenderer
from src.studio_core.util import StudioError, probe_duration

TEMPLATE = {"1": {"class_type": "LoadImage", "inputs": {"image": "{{image}}"}},
            "2": {"class_type": "Gen", "inputs": {"text": "{{prompt}} | {{negative}}", "seed": "{{seed}}",
                                                  "length": "{{frames}}", "w": "{{width}}", "prefix": "{{prefix}}"}}}


def test_fill_keeps_types_and_detects_leftovers():
    wf = cc.fill_workflow(TEMPLATE, {"image": "a.png", "prompt": "p", "negative": "n", "seed": 5, "frames": 121,
                                     "width": 1280, "prefix": "s01"})
    assert wf["2"]["inputs"]["seed"] == 5 and wf["2"]["inputs"]["text"] == "p | n"
    assert cc.leftover_placeholders(wf) == []
    with pytest.raises(StudioError):
        cc.prepare(TEMPLATE, {"image": "a.png"})


def test_find_video_output():
    out = {"9": {"images": [{"filename": "x.png"}], "videos": [{"filename": "y.mp4"}]}}
    assert cc.find_video_output(out)["filename"] == "y.mp4"
    with pytest.raises(StudioError):
        cc.find_video_output({"1": {}})


@pytest.fixture()
def server(tmp_path):
    mp4 = tmp_path / "fake.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x96:d=1:r=24",
                    "-pix_fmt", "yuv420p", str(mp4)], check=True)
    state = {"queued": [], "polls": 0, "uploads": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _json(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path.startswith("/system_stats"):
                return self._json({"ok": 1})
            if self.path.startswith("/history/"):
                state["polls"] += 1
                if state["polls"] < 2:
                    return self._json({})
                return self._json({"p1": {"status": {"status_str": "success"},
                                          "outputs": {"5": {"videos": [{"filename": "o.mp4", "subfolder": "", "type": "output"}]}}}})
            if self.path.startswith("/view"):
                data = mp4.read_bytes()
                self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
                return self.wfile.write(data)
            self.send_response(404); self.end_headers()

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            if self.path == "/upload/image":
                state["uploads"].append(len(body))
                return self._json({"name": "uploaded.png"})
            if self.path == "/prompt":
                state["queued"].append(json.loads(body))
                return self._json({"prompt_id": "p1"})
            self._json({})

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", state
    srv.shutdown()


def test_client_roundtrip_and_renderer(server, tmp_path):
    url, state = server
    client = cc.ComfyClient(url, poll=0.01)
    assert client.healthy()
    img = tmp_path / "ref.png"
    img.write_bytes(b"\x89PNG fake")
    r = ComfyRenderer(client, TEMPLATE, 24)
    job = {"job_id": "s01_00", "ref_image": str(img), "prompt": "hi", "negative": "bad", "seed": 7, "frames": 25,
           "width": 640, "height": 384}
    out = r.render(job, str(tmp_path / "out" / "s01_00.mp4"))
    assert probe_duration(out) > 0.5
    sent = state["queued"][0]["prompt"]
    assert sent["1"]["inputs"]["image"] == "uploaded.png" and sent["2"]["inputs"]["seed"] == 7


def test_wait_aborts_on_guard(server):
    url, _ = server
    client = cc.ComfyClient(url, poll=0.01)
    with pytest.raises(StudioError, match="aborted"):
        client.wait("never", should_abort=lambda: True)


def test_wait_times_out(server):
    url, state = server
    client = cc.ComfyClient(url, poll=0.01, max_wait=0.05)
    state["polls"] = -10 ** 6
    with pytest.raises(StudioError, match="timeout"):
        client.wait("p1")
