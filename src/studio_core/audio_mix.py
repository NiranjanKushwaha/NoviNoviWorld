"""Voice track from the timeline, original placeholder BGM, ducked mix, loudness normalisation."""
from __future__ import annotations

from .timing import Timeline
from .util import ffmpeg, StudioError

SR = 44100
FMT = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"

# C - F - Am - G, 4 s each: simple original lullaby pad (no copyright issues)
_CHORDS = [(261.63, 329.63, 392.00), (349.23, 440.00, 523.25), (220.00, 261.63, 329.63), (196.00, 246.94, 293.66)]


def build_voice_track(tl: Timeline, audio_for_shot: dict, out_wav: str) -> str:
    """Place each line at its shot offset; silence elsewhere; exact timeline length."""
    inputs, chains, labels = [], [], []
    idx = 0
    for st in tl.shots:
        path = audio_for_shot.get(st.shot_id)
        if path:
            inputs += ["-i", path]
            lead = int(round(st.voice_offset * 1000))
            chains.append(f"[{idx}:a]aresample={SR},aformat=channel_layouts=stereo,adelay={lead}|{lead},"
                          f"apad=whole_dur={st.duration:.4f},atrim=0:{st.duration:.4f},asetpts=N/SR/TB[a{idx}]")
            labels.append(f"[a{idx}]")
            idx += 1
        else:
            chains.append(f"anullsrc=r={SR}:cl=stereo:d={st.duration:.4f}[s{len(labels)}_{st.shot_id}]")
            labels.append(f"[s{len(labels)}_{st.shot_id}]")
    graph = ";".join(chains) + f";{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]"
    ffmpeg([*inputs, "-filter_complex", graph, "-map", "[out]", "-ar", SR, "-c:a", "pcm_s16le", out_wav])
    return out_wav


def synth_bgm(out_wav: str, bars: int = 4) -> str:
    """Generate a gentle looping pad (bars x 4 s). Replace with a licensed track any time."""
    parts, labels = [], []
    for i in range(bars):
        f = _CHORDS[i % len(_CHORDS)]
        expr = "+".join(f"0.07*sin(2*PI*{x}*t)" for x in f)
        parts.append(f"aevalsrc='{expr}|{expr}':d=4:s={SR},afade=t=in:d=0.5,afade=t=out:st=3.5:d=0.5[c{i}]")
        labels.append(f"[c{i}]")
    graph = ";".join(parts) + f";{''.join(labels)}concat=n={bars}:v=0:a=1,tremolo=f=0.4:d=0.15[out]"
    ffmpeg(["-filter_complex", graph, "-map", "[out]", "-c:a", "pcm_s16le", out_wav])
    return out_wav


def mix_with_bgm(voice_wav: str, bgm: str, out_audio: str, total: float, bgm_gain: float = 0.35,
                 duck: bool = True) -> str:
    """BGM loops under the voice, ducks while someone speaks, then -16 LUFS normalisation."""
    fade_st = max(0.0, total - 2.0)
    bg = f"[1:a]volume={bgm_gain},atrim=0:{total:.3f},afade=t=in:d=1,afade=t=out:st={fade_st:.3f}:d=2,asetpts=N/SR/TB,{FMT}[bg]"
    if duck:
        graph = (f"{bg};[0:a]{FMT},asplit=2[v1][v2];[bg][v2]sidechaincompress=threshold=0.02:ratio=8:attack=20:"
                 f"release=350[ducked];[v1][ducked]amix=inputs=2:duration=first:dropout_transition=0,"
                 f"loudnorm=I=-16:TP=-1.5:LRA=11[out]")
    else:
        graph = f"{bg};[0:a]{FMT}[vv];[vv][bg]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    ffmpeg(["-i", voice_wav, "-stream_loop", "-1", "-i", bgm, "-filter_complex", graph, "-map", "[out]",
            "-ar", SR, "-t", f"{total:.3f}", out_audio])
    return out_audio


def normalize_only(voice_wav: str, out_audio: str) -> str:
    ffmpeg(["-i", voice_wav, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", SR, out_audio])
    return out_audio
