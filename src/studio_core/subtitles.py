"""SRT/ASS subtitles generated from the timeline (no manual timing)."""
from __future__ import annotations

import re
import textwrap

from .manifest import Episode
from .timing import Timeline


def _ts_srt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_ass(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def split_cues(text: str, start: float, end: float, max_chars: int = 38, max_lines: int = 2) -> list:
    """Wrap text into cues of <= max_lines lines; time is shared in proportion to length."""
    lines = textwrap.wrap(text.strip(), width=max_chars) or [""]
    groups = [lines[i:i + max_lines] for i in range(0, len(lines), max_lines)]
    weights = [sum(len(x) for x in g) or 1 for g in groups]
    total, span, t, cues = sum(weights), max(end - start, 0.2), start, []
    for g, w in zip(groups, weights):
        d = span * w / total
        cues.append((t, t + d, "\n".join(g)))
        t += d
    return cues


def build_cues(ep: Episode, tl: Timeline, max_chars: int = 38) -> list:
    cues = []
    for st in tl.shots:
        text = re.sub(r"\[[^\]]*\]\s*", "", ep.shot(st.shot_id).dialogue.get(tl.language, "")).strip()
        if not text or st.voice_duration <= 0:
            continue
        a = st.start + st.voice_offset
        cues.extend(split_cues(text, a, a + st.voice_duration, max_chars))
    return cues


def to_srt(cues: list) -> str:
    out = []
    for i, (a, b, text) in enumerate(cues, 1):
        out.append(f"{i}\n{_ts_srt(a)} --> {_ts_srt(b)}\n{text}\n")
    return "\n".join(out)


def to_ass(cues: list, width: int, height: int, font: str = "Arial", size_ratio: float = 0.055) -> str:
    size = int(height * size_ratio)
    margin_v = int(height * 0.07)
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00301030,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,2,"
        f"40,40,{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    rows = [f"Dialogue: 0,{_ts_ass(a)},{_ts_ass(b)},Default,,0,0,0,,{t.replace(chr(10), chr(92) + 'N')}"
            for a, b, t in cues]
    return head + "\n".join(rows) + "\n"
