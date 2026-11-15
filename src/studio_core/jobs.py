"""SQLite job queue: one job per <=5s clip, content-hash caching, resume after crash."""
from __future__ import annotations

import os
import sqlite3
import time

from .manifest import Episode
from .prompts import build_prompt
from .timing import Timeline, model_frames
from .util import file_sha256, spec_hash

SCHEMA = """CREATE TABLE IF NOT EXISTS jobs(
  job_id TEXT PRIMARY KEY, ord INTEGER, shot_id TEXT, seg_idx INTEGER, spec_hash TEXT,
  status TEXT, attempts INTEGER DEFAULT 0, frames INTEGER, duration REAL, prompt TEXT, negative TEXT,
  seed INTEGER, ref_image TEXT, width INTEGER, height INTEGER, out_path TEXT, error TEXT, updated REAL)"""


def plan_jobs(ep: Episode, tl: Timeline, characters: dict, root: str, gen_size=(1280, 704),
              model_tag: str = "ltx-i2v-v1") -> list:
    """Expand the timeline into clip jobs. Segment N>0 chains from the last frame of segment N-1."""
    jobs, order = [], 0
    for st in tl.shots:
        shot = ep.shot(st.shot_id)
        ref = os.path.join(root, shot.ref_image)
        ref_sha = file_sha256(ref) if os.path.exists(ref) else "missing"
        talking = bool(shot.speaker and shot.dialogue)
        pos, neg = build_prompt(shot, characters, talking=talking)
        prev = ""
        for i, seg in enumerate(st.segments):
            frames = model_frames(seg, tl.fps)
            h = spec_hash({"m": model_tag, "p": pos, "n": neg, "seed": shot.seed + i, "ref": ref_sha,
                           "f": frames, "w": gen_size[0], "h": gen_size[1], "prev": prev, "i": i})
            jobs.append({"job_id": f"{st.shot_id}_{i:02d}", "ord": order, "shot_id": st.shot_id, "seg_idx": i,
                         "spec_hash": h, "frames": frames, "duration": seg, "prompt": pos, "negative": neg,
                         "seed": shot.seed + i, "ref_image": shot.ref_image, "width": gen_size[0], "height": gen_size[1]})
            prev, order = h, order + 1
    return jobs


class JobStore:
    def __init__(self, path: str, root: str = ""):
        self.root = root  # project root: stored paths are relative to it so the DB survives moving machines
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        try:
            self._open(path, exclusive=False)
        except sqlite3.OperationalError:  # filesystems without file locks (FUSE/network mounts)
            self._open(path, exclusive=True)

    def _open(self, path: str, exclusive: bool) -> None:
        db = sqlite3.connect(path, check_same_thread=False)
        try:
            db.row_factory = sqlite3.Row
            if exclusive:
                db.execute("PRAGMA locking_mode=EXCLUSIVE")
            db.execute("PRAGMA journal_mode=TRUNCATE")  # truncate, never delete, the journal
            db.execute(SCHEMA)
            db.commit()
        except sqlite3.OperationalError:
            db.close()
            raise
        self.db = db

    def _abs(self, p):
        return p if (not p or os.path.isabs(p) or not self.root) else os.path.join(self.root, p)

    def _rel(self, p):
        if p and self.root and os.path.isabs(p):
            r = os.path.relpath(p, self.root)
            return p if r.startswith("..") else r
        return p

    def _row(self, r):
        d = dict(r)
        d["ref_image"], d["out_path"] = self._abs(d.get("ref_image")), self._abs(d.get("out_path"))
        return d

    def upsert(self, jobs: list) -> dict:
        """Insert new jobs; reset those whose spec changed; keep finished ones whose file still exists."""
        res = {"new": 0, "changed": 0, "cached": 0, "requeued": 0}
        for j in jobs:
            row = self.db.execute("SELECT * FROM jobs WHERE job_id=?", (j["job_id"],)).fetchone()
            cols = ("job_id", "ord", "shot_id", "seg_idx", "spec_hash", "frames", "duration", "prompt",
                    "negative", "seed", "ref_image", "width", "height")
            if row is None:
                self.db.execute(f"INSERT INTO jobs({','.join(cols)},status,attempts,updated) VALUES("
                                f"{','.join('?' * len(cols))},'pending',0,?)",
                                [j[c] for c in cols] + [time.time()])
                res["new"] += 1
            elif row["spec_hash"] != j["spec_hash"]:
                sets = ",".join(f"{c}=?" for c in cols[1:])
                self.db.execute(f"UPDATE jobs SET {sets},status='pending',attempts=0,out_path=NULL,error=NULL,"
                                f"updated=? WHERE job_id=?", [j[c] for c in cols[1:]] + [time.time(), j["job_id"]])
                res["changed"] += 1
            elif row["status"] == "done" and row["out_path"] and os.path.exists(self._abs(row["out_path"])):
                self.db.execute("UPDATE jobs SET ref_image=? WHERE job_id=?", (j["ref_image"], j["job_id"]))
                res["cached"] += 1
            elif row["status"] in ("running", "done"):
                self.db.execute("UPDATE jobs SET status='pending',ref_image=?,updated=? WHERE job_id=?",
                                (j["ref_image"], time.time(), j["job_id"]))
                res["requeued"] += 1
            else:
                self.db.execute("UPDATE jobs SET ref_image=? WHERE job_id=?", (j["ref_image"], j["job_id"]))
        self.db.commit()
        return res

    def claim_next(self):
        row = self.db.execute(
            """SELECT j.* FROM jobs j WHERE j.status='pending' AND (j.seg_idx=0 OR EXISTS(
                 SELECT 1 FROM jobs p WHERE p.shot_id=j.shot_id AND p.seg_idx=j.seg_idx-1 AND p.status='done'))
               ORDER BY j.ord LIMIT 1""").fetchone()
        if row is None:
            return None
        self.db.execute("UPDATE jobs SET status='running',updated=? WHERE job_id=?", (time.time(), row["job_id"]))
        self.db.commit()
        return self._row(row)

    def mark_done(self, job_id: str, out_path: str) -> None:
        self.db.execute("UPDATE jobs SET status='done',out_path=?,error=NULL,updated=? WHERE job_id=?",
                        (self._rel(out_path), time.time(), job_id))
        self.db.commit()

    def mark_failed(self, job_id: str, error: str, max_attempts: int = 2) -> str:
        row = self.db.execute("SELECT attempts FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        attempts = (row["attempts"] if row else 0) + 1
        status = "failed" if attempts >= max_attempts else "pending"
        self.db.execute("UPDATE jobs SET status=?,attempts=?,error=?,updated=? WHERE job_id=?",
                        (status, attempts, error[:500], time.time(), job_id))
        self.db.commit()
        return status

    def release(self, job_id: str) -> None:
        self.db.execute("UPDATE jobs SET status='pending',updated=? WHERE job_id=?", (time.time(), job_id))
        self.db.commit()

    def requeue_running(self) -> int:
        n = self.db.execute("UPDATE jobs SET status='pending' WHERE status='running'").rowcount
        self.db.commit()
        return n

    def reset(self, shot_id: str = "", failed_only: bool = False) -> int:
        q, args = "UPDATE jobs SET status='pending',attempts=0,out_path=NULL,error=NULL", []
        conds = []
        if shot_id:
            conds.append("shot_id=?")
            args.append(shot_id)
        if failed_only:
            conds.append("status='failed'")
        n = self.db.execute(q + (" WHERE " + " AND ".join(conds) if conds else ""), args).rowcount
        self.db.commit()
        return n

    def stats(self) -> dict:
        out = {"pending": 0, "running": 0, "done": 0, "failed": 0}
        for r in self.db.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status"):
            out[r["status"]] = r["c"]
        out["total"] = sum(out.values())
        return out

    def all(self) -> list:
        return [self._row(r) for r in self.db.execute("SELECT * FROM jobs ORDER BY ord")]

    def get(self, job_id: str):
        r = self.db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row(r) if r else None

    def shot_clips(self) -> dict:
        """{shot_id: [clip paths]} only for shots whose every segment is done."""
        by: dict = {}
        for j in self.all():
            by.setdefault(j["shot_id"], []).append(j)
        return {s: [j["out_path"] for j in js] for s, js in by.items() if all(j["status"] == "done" for j in js)}

    def close(self) -> None:
        self.db.close()
