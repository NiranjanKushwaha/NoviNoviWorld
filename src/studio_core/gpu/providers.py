"""GPU providers. ManualPod works with ANY rented pod that exposes ComfyUI (Race Engineering, GridShare, ...)."""
from __future__ import annotations

import shlex
import subprocess
import time

import requests

from ..util import StudioError


class Provider:
    name = "base"
    endpoint = ""

    def start(self) -> None: ...

    def stop(self) -> bool:
        """Return True if the pod was stopped automatically."""
        return False


class MockProvider(Provider):
    name = "mock"

    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> bool:
        self.stopped += 1
        return True


class ManualPodProvider(Provider):
    """User starts the pod in the provider dashboard and gives its ComfyUI URL.

    Auto-shutdown is only possible if the provider offers a CLI/API: pass it as stop_command
    (e.g. a curl or CLI call). Without it, stop() prints a loud reminder to stop billing by hand.
    """
    name = "manual-pod"

    def __init__(self, endpoint: str, stop_command: str = "", wait_seconds: float = 120.0, log=print,
                 sleep=time.sleep):
        self.endpoint, self.stop_command, self.wait_seconds, self.log, self.sleep = (
            endpoint.rstrip("/"), stop_command, wait_seconds, log, sleep)

    def start(self) -> None:
        deadline = time.time() + self.wait_seconds
        while time.time() < deadline:
            try:
                if requests.get(f"{self.endpoint}/system_stats", timeout=10).ok:
                    return
            except requests.RequestException:
                pass
            self.sleep(3)
        raise StudioError(f"ComfyUI not reachable at {self.endpoint} after {self.wait_seconds:.0f}s")

    def stop(self) -> bool:
        if self.stop_command:
            p = subprocess.run(shlex.split(self.stop_command), capture_output=True, text=True)
            if p.returncode == 0:
                self.log("GPU stop command ran OK.")
                return True
            self.log(f"!! stop command FAILED ({p.returncode}): {p.stderr.strip()[:200]}")
        self.log("!! ACTION REQUIRED: TERMINATE (not just pause/stop) the GPU pod in your provider dashboard NOW. "
                 "Download results first. Then confirm your wallet balance stops dropping.")
        return False
