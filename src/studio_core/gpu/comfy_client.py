"""Minimal ComfyUI HTTP client + workflow placeholder filling. Works with any API-format workflow."""
from __future__ import annotations

import copy
import os
import re
import time
import uuid

import requests

from ..util import StudioError

_PH = re.compile(r"\{\{(\w+)\}\}")


def fill_workflow(template, values: dict):
    """Replace {{name}} placeholders. A string that is only a placeholder keeps the value's type."""
    if isinstance(template, dict):
        return {k: fill_workflow(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [fill_workflow(v, values) for v in template]
    if isinstance(template, str):
        m = _PH.fullmatch(template)
        if m and m.group(1) in values:
            return values[m.group(1)]
        return _PH.sub(lambda mm: str(values.get(mm.group(1), mm.group(0))), template)
    return template


def leftover_placeholders(obj) -> list:
    found = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            found.extend(_PH.findall(x))
    walk(obj)
    return sorted(set(found))


def find_video_output(outputs: dict) -> dict:
    """Pick the first video-like file from a ComfyUI history 'outputs' block."""
    fallback = None
    for node in outputs.values():
        for key in ("videos", "gifs", "images"):
            for item in node.get(key, []) or []:
                name = item.get("filename", "")
                if name.lower().endswith((".mp4", ".webm", ".mov", ".mkv")):
                    return item
                if fallback is None and name:
                    fallback = item
    if fallback:
        return fallback
    raise StudioError("ComfyUI finished but produced no output file")


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 30.0, poll: float = 2.0, max_wait: float = 1800.0):
        self.base = base_url.rstrip("/")
        self.timeout, self.poll, self.max_wait = timeout, poll, max_wait
        self.client_id = uuid.uuid4().hex

    def healthy(self) -> bool:
        try:
            return requests.get(f"{self.base}/system_stats", timeout=self.timeout).ok
        except requests.RequestException:
            return False

    def upload(self, path: str) -> str:
        with open(path, "rb") as fh:
            r = requests.post(f"{self.base}/upload/image", files={"image": (os.path.basename(path), fh)},
                              data={"overwrite": "true", "type": "input"}, timeout=self.timeout * 4)
        r.raise_for_status()
        return r.json()["name"]

    def queue(self, workflow: dict) -> str:
        r = requests.post(f"{self.base}/prompt", json={"prompt": workflow, "client_id": self.client_id},
                          timeout=self.timeout)
        if r.status_code != 200:
            raise StudioError(f"ComfyUI rejected workflow ({r.status_code}): {r.text[:400]}")
        data = r.json()
        if data.get("node_errors"):
            raise StudioError(f"ComfyUI node errors: {str(data['node_errors'])[:400]}")
        return data["prompt_id"]

    def interrupt(self) -> None:
        try:
            requests.post(f"{self.base}/interrupt", timeout=self.timeout)
        except requests.RequestException:
            pass

    def wait(self, prompt_id: str, should_abort=None, sleep=time.sleep, clock=time.time) -> dict:
        t0 = clock()
        while True:
            if should_abort and should_abort():
                self.interrupt()
                raise StudioError("render aborted by cost guard")
            r = requests.get(f"{self.base}/history/{prompt_id}", timeout=self.timeout)
            r.raise_for_status()
            hist = r.json()
            if prompt_id in hist:
                entry = hist[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise StudioError(f"ComfyUI execution error: {str(status.get('messages'))[:400]}")
                if entry.get("outputs"):
                    return entry["outputs"]
            if clock() - t0 > self.max_wait:
                self.interrupt()
                raise StudioError(f"ComfyUI timeout after {self.max_wait}s")
            sleep(self.poll)

    def download(self, item: dict, dest: str) -> str:
        params = {"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                  "type": item.get("type", "output")}
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with requests.get(f"{self.base}/view", params=params, stream=True, timeout=self.timeout * 4) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        return dest


def load_template(path: str) -> dict:
    import json
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def prepare(template: dict, values: dict) -> dict:
    wf = fill_workflow(copy.deepcopy(template), values)
    left = leftover_placeholders(wf)
    if left:
        raise StudioError(f"workflow has unfilled placeholders: {left}")
    return wf
