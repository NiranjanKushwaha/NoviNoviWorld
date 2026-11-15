"""Episode manifest: the single source of truth for scenes, shots and prompts."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, asdict

from .util import read_json, write_json, StudioError

SCHEMA_VERSION = 1


@dataclass
class Shot:
    shot_id: str
    scene: int
    speaker: str = ""
    action: str = ""
    dialogue: dict = field(default_factory=dict)  # language -> text
    characters: list = field(default_factory=list)
    ref_image: str = ""  # path relative to project root
    motion_prompt: str = ""
    camera: str = "medium shot, gentle camera movement"
    seed: int = 0
    min_duration: float = 3.0


@dataclass
class Episode:
    episode_id: str
    title: str
    languages: list = field(default_factory=lambda: ["hindi"])
    fps: int = 24
    shots: list = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def shot(self, shot_id: str) -> Shot:
        for s in self.shots:
            if s.shot_id == shot_id:
                return s
        raise StudioError(f"unknown shot: {shot_id}")


def stable_seed(episode_id: str, shot_id: str) -> int:
    h = hashlib.sha256(f"{episode_id}:{shot_id}".encode()).hexdigest()
    return int(h[:8], 16) % (2 ** 31 - 1)


def to_dict(ep: Episode) -> dict:
    return asdict(ep)


def from_dict(d: dict) -> Episode:
    shots = [Shot(**s) for s in d.get("shots", [])]
    ep = Episode(
        episode_id=d["episode_id"],
        title=d.get("title", d["episode_id"]),
        languages=list(d.get("languages", ["hindi"])),
        fps=int(d.get("fps", 24)),
        shots=shots,
        schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
    )
    for s in ep.shots:
        if not s.seed:
            s.seed = stable_seed(ep.episode_id, s.shot_id)
    return ep


def save(ep: Episode, path: str) -> None:
    write_json(path, to_dict(ep))


def load(path: str) -> Episode:
    d = read_json(path)
    if int(d.get("schema_version", 1)) > SCHEMA_VERSION:
        raise StudioError(f"manifest schema {d['schema_version']} is newer than supported {SCHEMA_VERSION}")
    return from_dict(d)


def validate(ep: Episode, root: str = "") -> list:
    """Return a list of human-readable problems (empty list means valid)."""
    errs = []
    if ep.fps not in (24, 25, 30):
        errs.append(f"fps {ep.fps} not in (24, 25, 30)")
    if not ep.shots:
        errs.append("episode has no shots")
    seen = set()
    for s in ep.shots:
        if s.shot_id in seen:
            errs.append(f"duplicate shot_id {s.shot_id}")
        seen.add(s.shot_id)
        if s.min_duration <= 0:
            errs.append(f"{s.shot_id}: min_duration must be > 0")
        if not s.motion_prompt.strip():
            errs.append(f"{s.shot_id}: empty motion_prompt")
        for lang in ep.languages:
            if s.speaker and not s.dialogue.get(lang, "").strip():
                errs.append(f"{s.shot_id}: speaker '{s.speaker}' has no {lang} dialogue")
        if root and s.ref_image and not os.path.exists(os.path.join(root, s.ref_image)):
            errs.append(f"{s.shot_id}: ref_image missing: {s.ref_image}")
        if not s.ref_image:
            errs.append(f"{s.shot_id}: ref_image not set")
    return errs
