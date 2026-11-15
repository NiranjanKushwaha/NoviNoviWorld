"""Audio-driven timeline: shot length follows the spoken line, not a fixed 6 seconds."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

from .manifest import Episode
from .util import probe_duration, StudioError


@dataclass
class ShotTiming:
    shot_id: str
    start: float
    duration: float
    voice_offset: float = 0.0
    voice_duration: float = 0.0
    segments: list = field(default_factory=list)  # per-clip generation lengths, sum == duration


@dataclass
class Timeline:
    language: str
    fps: int
    shots: list = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(self.shots[-1].start + self.shots[-1].duration, 3) if self.shots else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total"] = self.total
        return d

    @staticmethod
    def from_dict(d: dict) -> "Timeline":
        return Timeline(d["language"], int(d["fps"]), [ShotTiming(**s) for s in d["shots"]])


def snap(seconds: float, fps: int) -> float:
    """Round up to a whole number of frames."""
    return math.ceil(seconds * fps - 1e-9) / fps


def split_segments(duration: float, max_clip: float, fps: int) -> list:
    """Split into equal frame-aligned clips no longer than max_clip; sums back to duration."""
    n = max(1, math.ceil(duration / max_clip - 1e-9))
    total_frames = round(duration * fps)
    base, extra = divmod(total_frames, n)
    return [(base + (1 if i < extra else 0)) / fps for i in range(n)]


def model_frames(seconds: float, fps: int, step: int = 8) -> int:
    """Frame count in the 8n+1 form that LTX-style video models expect (configurable step)."""
    want = max(1, math.ceil(seconds * fps - 1e-9))
    return step * math.ceil((want - 1) / step) + 1


def build_timeline(ep: Episode, language: str, audio_for_shot: dict, lead_in: float = 0.35,
                   tail: float = 0.55, max_clip: float = 5.0, probe=probe_duration) -> Timeline:
    if language not in ep.languages:
        raise StudioError(f"language '{language}' not in episode languages {ep.languages}")
    t, shots = 0.0, []
    for s in ep.shots:
        path = audio_for_shot.get(s.shot_id)
        if path:
            vd = probe(path)
            dur = max(s.min_duration, vd + lead_in + tail)
            offset = lead_in
        else:
            vd, dur, offset = 0.0, s.min_duration, 0.0
        dur = snap(dur, ep.fps)
        shots.append(ShotTiming(s.shot_id, round(t, 4), round(dur, 4), offset, round(vd, 4),
                                [round(x, 4) for x in split_segments(dur, max_clip, ep.fps)]))
        t += dur
    return Timeline(language, ep.fps, shots)
