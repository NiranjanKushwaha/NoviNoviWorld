"""Clip renderers: Mock (free, ffmpeg placeholder motion) and Comfy (real image-to-video on the GPU)."""
from __future__ import annotations

import os

from ..util import StudioError, ffmpeg, extract_last_frame
from .comfy_client import ComfyClient, find_video_output, prepare


def need_file(path: str, what: str) -> str:
    if not path or not os.path.exists(path):
        raise StudioError(f"{what} not found: {path}")
    return path


class Renderer:
    def render(self, job: dict, out_path: str, prev_clip: str = "") -> str:
        raise NotImplementedError


class MockRenderer(Renderer):
    """Zoom/pan placeholder clip so the whole pipeline can be tested at zero cost."""

    def __init__(self, fps: int = 24, fail_ids=()):
        self.fps, self.fail_ids, self.calls = fps, set(fail_ids), []

    def render(self, job, out_path, prev_clip=""):
        self.calls.append(job["job_id"])
        if job["job_id"] in self.fail_ids:
            self.fail_ids.discard(job["job_id"])  # fail once, succeed on retry
            raise StudioError(f"mock failure for {job['job_id']}")
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        src = need_file(job["ref_image"], "reference image")
        if prev_clip and os.path.exists(prev_clip):
            src = extract_last_frame(prev_clip, out_path + ".last.png")
        w, h, n = job["width"], job["height"], job["frames"]
        vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
              f"zoompan=z='min(zoom+0.0006,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={w}x{h}:fps={self.fps},"
              f"format=yuv420p")
        ffmpeg(["-i", src, "-vf", vf, "-frames:v", n, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", out_path])
        return out_path


class ComfyRenderer(Renderer):
    def __init__(self, client: ComfyClient, template: dict, fps: int = 24, should_abort=None):
        self.client, self.template, self.fps, self.should_abort = client, template, fps, should_abort

    def render(self, job, out_path, prev_clip=""):
        start = need_file(job["ref_image"], "reference image")
        if prev_clip and os.path.exists(prev_clip):
            start = extract_last_frame(prev_clip, out_path + ".last.png")
        values = {"image": self.client.upload(start), "prompt": job["prompt"], "negative": job["negative"],
                  "seed": int(job["seed"]), "frames": int(job["frames"]), "width": int(job["width"]),
                  "height": int(job["height"]), "fps": self.fps, "prefix": job["job_id"]}
        if job.get("audio"):
            values["audio"] = self.client.upload(job["audio"])
        wf = prepare(self.template, values)
        pid = self.client.queue(wf)
        outputs = self.client.wait(pid, self.should_abort)
        item = find_video_output(outputs)
        self.client.download(item, out_path)
        if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
            raise StudioError(f"downloaded clip for {job['job_id']} is empty")
        return out_path
