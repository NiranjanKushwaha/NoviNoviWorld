"""Queue runner: obeys the cost guard and ALWAYS tries to stop the GPU on exit."""
from __future__ import annotations

import os
import time

from ..util import StudioError


def run_queue(store, renderer, provider, guard, clips_dir: str, max_attempts: int = 2,
              max_consecutive_failures: int = 3, gpu_sec_per_clip_sec: float = 10.0, log=print) -> dict:
    result = {"done": 0, "failed": 0, "stopped_by": "finished", "spent_inr": 0.0, "auto_stopped": False}
    os.makedirs(clips_dir, exist_ok=True)
    store.requeue_running()
    consecutive = 0
    try:
        provider.start()
        guard.start_session()
        while True:
            d = guard.check()
            if d.action == "shutdown":
                result["stopped_by"] = d.reason
                log(f"STOP: {d.reason}")
                break
            if d.action == "warn":
                log(f"warning: {d.reason} (Rs{d.remaining_inr} left)")
            job = store.claim_next()
            if job is None:
                break
            if not guard.can_afford(job["duration"] * gpu_sec_per_clip_sec):
                store.release(job["job_id"])  # stays pending for a later, funded run
                result["stopped_by"] = "budget would be exceeded by next clip"
                log("STOP: next clip would exceed budget")
                break
            out = os.path.join(clips_dir, f"{job['job_id']}.mp4")
            prev = ""
            if job["seg_idx"] > 0:
                p = store.get(f"{job['shot_id']}_{job['seg_idx'] - 1:02d}")
                prev = p["out_path"] if p else ""
            t0 = time.time()
            try:
                renderer.render(job, out, prev)
                store.mark_done(job["job_id"], out)
                guard.activity()
                result["done"] += 1
                consecutive = 0
                log(f"done {job['job_id']} in {time.time() - t0:.1f}s")
            except Exception as e:  # noqa: BLE001 - any renderer error must not kill the loop
                status = store.mark_failed(job["job_id"], str(e), max_attempts)
                consecutive += 1
                log(f"FAIL {job['job_id']} ({status}): {str(e)[:160]}")
                if status == "failed":
                    result["failed"] += 1
                if consecutive >= max_consecutive_failures:
                    result["stopped_by"] = f"{consecutive} failures in a row"
                    log("STOP: too many consecutive failures")
                    break
    except StudioError as e:
        result["stopped_by"] = str(e)
        log(f"STOP: {e}")
    finally:
        store.requeue_running()
        guard.end_session(result["stopped_by"])
        result["auto_stopped"] = bool(provider.stop())
        result["spent_inr"] = guard.spent()
    return result
