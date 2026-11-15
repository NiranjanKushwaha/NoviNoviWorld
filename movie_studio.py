#!/usr/bin/env python3
"""AntiGravity Movie Studio CLI. Free local steps first; the paid GPU is only used by `render --provider manual`.

  python movie_studio.py init ep01_rainbow_slide     # build manifest.json from the legacy episode
  python movie_studio.py validate ep01_rainbow_slide
  python movie_studio.py plan ep01_rainbow_slide     # timeline + job queue + cost estimate (no GPU)
  python movie_studio.py render ep01_rainbow_slide --provider mock
  python movie_studio.py assemble ep01_rainbow_slide
  python movie_studio.py status ep01_rainbow_slide
  python movie_studio.py tts EP --cmd "python tools/gpu_tts.py --text-file {text_file} --out {out} --ref {ref}"
"""
from __future__ import annotations

import argparse
import os
import sys

CODE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("STUDIO_ROOT") or CODE  # data root (tests point this at a temp copy)
sys.path.insert(0, CODE)

from src.studio_core import manifest as M                      # noqa: E402
from src.studio_core import audio_mix, b3d, jobs, legacy, prompts, render, subtitles, timing, tts  # noqa: E402
from src.studio_core.gpu import comfy_client, cost_guard, providers, renderers, worker   # noqa: E402
from src.studio_core.util import StudioError, read_json, write_json                       # noqa: E402

DEFAULT_CFG = {"budget_inr": 800.0, "hourly_inr": 91.0, "gst_pct": 18.0, "size": "720p",
               "gen_width": 1280, "gen_height": 704, "comfy_url": "", "stop_command": "",
               "workflow": "workflows/i2v_api.json", "gpu_sec_per_video_sec": 9.0, "attempts": 3.0,
               "idle_minutes": 10.0, "max_session_minutes": 180.0}


def cfg_load(root=ROOT) -> dict:
    cfg = dict(DEFAULT_CFG)
    p = os.path.join(root, "studio_config.json")
    if os.path.exists(p):
        cfg.update(read_json(p))
    return cfg


class Ctx:
    def __init__(self, ep_id: str, root: str = ROOT, lang: str = "hindi"):
        self.root, self.id, self.lang = root, ep_id, lang
        self.dir = os.path.join(root, "episodes", ep_id)
        self.cfg = cfg_load(root)
        self.work = os.path.join(self.dir, "work")
        self.manifest_path = os.path.join(self.dir, "manifest.json")

    def episode(self):
        if not os.path.exists(self.manifest_path):
            raise StudioError(f"no manifest at {self.manifest_path}; run: movie_studio.py init {self.id}")
        return M.load(self.manifest_path)

    def characters(self):
        return prompts.load_characters(os.path.join(self.root, "characters.json"))

    def audio_map(self, ep) -> dict:
        d = os.path.join(self.dir, "audio", self.lang)
        out = {}
        if os.path.isdir(d):
            for s in ep.shots:
                for f in sorted(os.listdir(d)):
                    if f.startswith(f"scene_{s.scene:02d}_") and f.endswith((".mp3", ".wav")):
                        out[s.shot_id] = os.path.join(d, f)
                        break
        return out

    def timeline(self, ep):
        return timing.build_timeline(ep, self.lang, self.audio_map(ep))

    def policy(self):
        c = self.cfg
        return cost_guard.BudgetPolicy(c["budget_inr"], c["hourly_inr"], c["gst_pct"],
                                       idle_minutes=c["idle_minutes"], max_session_minutes=c["max_session_minutes"])

    def store(self):
        return jobs.JobStore(os.path.join(self.work, "jobs.sqlite"), self.root)

    def plan(self, ep, tl):
        gs = (int(self.cfg["gen_width"]), int(self.cfg["gen_height"]))
        return jobs.plan_jobs(ep, tl, self.characters(), self.root, gs)


def cmd_init(a):
    c = Ctx(a.episode)
    os.makedirs(c.dir, exist_ok=True)
    if os.path.exists(c.manifest_path) and not a.force:
        print(f"manifest exists: {c.manifest_path} (use --force to overwrite)")
        return 0
    scenes = legacy.load_legacy_scenes(os.path.join(ROOT, "studio.py"))
    ep = legacy.episode_from_legacy(scenes, a.episode, a.title or a.episode)
    M.save(ep, c.manifest_path)
    chars = os.path.join(ROOT, "characters.json")
    if not os.path.exists(chars):
        prompts.save_default_characters(chars)
    print(f"created {c.manifest_path} ({len(ep.shots)} shots) and characters.json")
    return 0


def cmd_validate(a):
    c = Ctx(a.episode, lang=a.lang)
    ep = c.episode()
    problems = M.validate(ep, ROOT)
    for p in problems:
        print("PROBLEM:", p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_plan(a):
    c = Ctx(a.episode, lang=a.lang)
    ep = c.episode()
    tl = c.timeline(ep)
    js = c.plan(ep, tl)
    st = c.store()
    res = st.upsert(js)
    write_json(os.path.join(c.work, "timeline.json"), tl.to_dict())
    clip_s = sum(j["duration"] for j in js)
    est = cost_guard.estimate_cost(tl.total, c.cfg["gpu_sec_per_video_sec"], c.cfg["attempts"], c.policy())
    print(f"{len(ep.shots)} shots, {len(js)} clips, video {tl.total:.1f}s ({clip_s:.1f}s of generated clips)")
    print(f"queue: {res}")
    print(f"estimated GPU: {est['gpu_hours']} h  ~ Rs{est['cost_inr']:.0f} (budget Rs{c.cfg['budget_inr']:.0f})")
    return 0


def _build_provider(a, c):
    if a.provider == "mock":
        return providers.MockProvider(), None
    url = a.comfy_url or c.cfg["comfy_url"]
    if not url:
        raise StudioError("--comfy-url (or comfy_url in studio_config.json) is required for --provider manual")
    return providers.ManualPodProvider(url, c.cfg["stop_command"]), url


def cmd_render(a):
    c = Ctx(a.episode, lang=a.lang)
    ep = c.episode()
    tl = c.timeline(ep)
    st = c.store()
    st.upsert(c.plan(ep, tl))
    if a.retry_failed:
        print(f"re-queued {st.reset(failed_only=True)} failed clip(s)")
    prov, url = _build_provider(a, c)
    if a.provider == "mock":
        pol = cost_guard.BudgetPolicy(budget_inr=1e9, hourly_inr=0.0, idle_minutes=1e9, max_session_minutes=1e9)
        guard = cost_guard.CostGuard(os.path.join(c.work, "cost_mock.json"), pol)
        rend = renderers.MockRenderer(ep.fps)
    else:
        guard = cost_guard.CostGuard(os.path.join(ROOT, "cost_state.json"), c.policy())
        client = comfy_client.ComfyClient(url)
        wf = comfy_client.load_template(os.path.join(ROOT, c.cfg["workflow"]))
        rend = renderers.ComfyRenderer(client, wf, ep.fps, lambda: guard.check().action == "shutdown")
        print(f"GPU billing assumed Rs{c.cfg['hourly_inr']}/h, budget Rs{c.cfg['budget_inr']}")
    res = worker.run_queue(st, rend, prov, guard, os.path.join(c.work, "clips"))
    print(res, st.stats())
    return 0 if res["failed"] == 0 and st.stats()["pending"] == 0 else 2


def cmd_assemble(a):
    c = Ctx(a.episode, lang=a.lang)
    ep = c.episode()
    tl = c.timeline(ep)
    st = c.store()
    clips = st.shot_clips()
    missing = [s.shot_id for s in ep.shots if s.shot_id not in clips]
    if missing:
        raise StudioError(f"clips not ready for shots: {missing} (run render first)")
    am = c.audio_map(ep)
    os.makedirs(c.work, exist_ok=True)
    voice = audio_mix.build_voice_track(tl, am, os.path.join(c.work, "voice.wav"))
    bgm = audio_mix.synth_bgm(os.path.join(c.work, "bgm.wav"))
    mixed = audio_mix.mix_with_bgm(voice, bgm, os.path.join(c.work, "mix.m4a"), tl.total)
    w, h = render.SIZES[a.size or c.cfg["size"]]
    cues = subtitles.build_cues(ep, tl)
    ass = os.path.join(c.work, "subs.ass")
    open(ass, "w", encoding="utf-8").write(subtitles.to_ass(cues, w, h))
    open(os.path.join(c.work, "subs.srt"), "w", encoding="utf-8").write(subtitles.to_srt(cues))
    out = a.out or os.path.join(c.dir, "exports", f"{c.id}_{c.lang}_{a.size or c.cfg['size']}.mp4")
    render.assemble(tl, clips, mixed, out, os.path.join(c.work, "asm"), a.size or c.cfg["size"],
                    ass if a.subs else "")
    print("wrote", out)
    return 0


def cmd_status(a):
    c = Ctx(a.episode, lang=a.lang)
    st = c.store()
    print(st.stats())
    for j in st.all():
        print(f"  {j['job_id']:8} {j['status']:8} tries={j['attempts']} {j['error'] or ''}")
    p = os.path.join(ROOT, "cost_state.json")
    if os.path.exists(p):
        g = cost_guard.CostGuard(p, c.policy())
        print(f"GPU spent Rs{g.spent()} / Rs{c.cfg['budget_inr']}")
    return 0


def cmd_cost(a):
    c = Ctx(a.episode or "x", lang=a.lang)
    est = cost_guard.estimate_cost(a.minutes * 60, c.cfg["gpu_sec_per_video_sec"], c.cfg["attempts"], c.policy())
    print(f"{a.minutes} min video -> ~{est['gpu_hours']} GPU h ~ Rs{est['cost_inr']:.0f} "
          f"(~Rs{est['cost_inr'] / a.minutes:.0f}/min incl. setup; GST {c.cfg['gst_pct']:.0f}% assumed)")
    return 0


def cmd_tts(a):
    c = Ctx(a.episode, lang=a.lang)
    ep = c.episode()
    out_dir = os.path.join(c.dir, "audio", a.lang)
    made = tts.generate_episode_audio(ep, tts.CommandTTS(a.cmd), a.lang, out_dir, c.characters(),
                                      overwrite=a.overwrite, ext=a.ext)
    print(f"{len(made)} voice lines in {out_dir}")
    return 0


def cmd_keyframes(a):
    c = Ctx(a.episode, lang=a.lang)
    ep, chars = c.episode(), c.characters()
    lines = [f"# Image prompts for {ep.title}", "",
             "Generate each image in Antigravity (or any image tool) at 16:9, then save it at the path shown.", "",
             "## Character sheets (generate these first, then attach them as reference for every shot)", ""]
    for n in chars:
        lines += [f"### {n}  ->  save as `assets/characters/sheets/{n.lower()}.png`", "", prompts.sheet_prompt(n, chars), ""]
    lines += ["## Shot keyframes", ""]
    for s in ep.shots:
        lines += [f"### {s.shot_id}  ->  save as `assets/keyframes/{ep.episode_id}/{s.shot_id}.png`", "",
                  prompts.still_prompt(s, chars), ""]
    out = os.path.join(c.dir, "keyframe_prompts.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    print("wrote", out)
    return 0


def cmd_use_keyframes(a):
    c = Ctx(a.episode, lang=a.lang)
    ep = c.episode()
    n = 0
    for s in ep.shots:
        rel = f"assets/keyframes/{ep.episode_id}/{s.shot_id}.png"
        if os.path.exists(os.path.join(ROOT, rel)):
            s.ref_image, n = rel, n + 1
    M.save(ep, c.manifest_path)
    print(f"{n}/{len(ep.shots)} shots now use their own keyframe")
    return 0


def cmd_blender(a):
    """Render the episode as real 3D shots in Blender (no GPU rental), then assemble the movie."""
    from dataclasses import replace
    c = Ctx(a.episode, lang=a.lang)
    ep, am, chars = c.episode(), None, c.characters()
    tl = c.timeline(ep)
    am = c.audio_map(ep)
    want = [x for x in a.shots.split(",") if x] if a.shots else [s.shot_id for s in ep.shots]
    unknown = [x for x in want if x not in {s.shot_id for s in ep.shots}]
    if unknown:
        raise StudioError(f"unknown shot ids: {unknown}")
    runner = b3d.default_runner(b3d.find_blender())
    wd, clips = os.path.join(c.work, "b3d"), {}
    for st in tl.shots:
        if st.shot_id not in want:
            continue
        bd = os.path.join(ROOT, "assets", "backdrops", c.id, f"{st.shot_id}.png")
        spec = b3d.build_spec(ep, ep.shot(st.shot_id), st, chars, am.get(st.shot_id, ""), a.quality, a.engine, "",
                              bd if os.path.exists(bd) else "")
        print(f"[{st.shot_id}] {spec['motion']}, {spec['frames']} frames, {a.engine} {a.quality} ...", flush=True)
        clips[st.shot_id] = b3d.render_shot(spec, wd, runner=runner, force=a.force,
                                            frames=(1, a.test_frames) if a.test_frames else ())
        print("   ->", clips[st.shot_id], flush=True)
    if a.test_frames or a.shots or a.no_assemble:
        print("rendered clips only (no movie assembled: --shots/--test-frames/--no-assemble)")
        return 0
    tl3 = timing.Timeline(tl.language, tl.fps, [replace(s, segments=[s.duration]) for s in tl.shots])
    os.makedirs(c.work, exist_ok=True)
    voice = audio_mix.build_voice_track(tl, am, os.path.join(c.work, "voice.wav"))
    bgm = audio_mix.synth_bgm(os.path.join(c.work, "bgm.wav"))
    mixed = audio_mix.mix_with_bgm(voice, bgm, os.path.join(c.work, "mix.m4a"), tl.total)
    cues = subtitles.build_cues(ep, tl)
    open(os.path.join(c.work, "subs.srt"), "w", encoding="utf-8").write(subtitles.to_srt(cues))
    size = "1080p" if a.quality == "1080p" else "720p"
    out = a.out or os.path.join(c.dir, "exports", f"{c.id}_{c.lang}_3d_{a.quality}.mp4")
    render.assemble(tl3, {k: [v] for k, v in clips.items()}, mixed, out, os.path.join(c.work, "asm3d"), size, "")
    print("wrote", out)
    return 0


def cmd_voices(a):
    import runpy
    sys.argv = ["studio.py", "voices"]
    runpy.run_path(os.path.join(ROOT, "studio.py"), run_name="__main__")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="movie_studio", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, ep=True, **kw):
        p = sub.add_parser(name, **kw)
        if ep:
            p.add_argument("episode")
        p.add_argument("--lang", default="hindi")
        p.set_defaults(fn=fn)
        return p
    p = add("init", cmd_init)
    p.add_argument("--title", default="")
    p.add_argument("--force", action="store_true")
    add("validate", cmd_validate)
    add("plan", cmd_plan)
    p = add("render", cmd_render)
    p.add_argument("--provider", choices=["mock", "manual"], default="mock")
    p.add_argument("--comfy-url", default="")
    p.add_argument("--retry-failed", action="store_true", help="put failed clips back in the queue first")
    p = add("assemble", cmd_assemble)
    p.add_argument("--size", choices=sorted(render.SIZES), default="")
    p.add_argument("--out", default="")
    p.add_argument("--subs", action="store_true", help="burn subtitles into the video (default: none; .srt is still written)")
    add("status", cmd_status)
    p = add("cost", cmd_cost, ep=False)
    p.add_argument("--minutes", type=float, default=1.0)
    p.add_argument("episode", nargs="?", default="")
    add("voices", cmd_voices, ep=False)
    add("keyframes", cmd_keyframes)
    add("use-keyframes", cmd_use_keyframes)
    p = add("blender", cmd_blender)
    p.add_argument("--quality", choices=sorted(b3d.QUALITY), default="720p")
    p.add_argument("--engine", choices=["eevee", "cycles", "workbench"], default="eevee")
    p.add_argument("--shots", default="", help="comma list, e.g. s01,s03 (renders clips only)")
    p.add_argument("--test-frames", type=int, default=0, help="render only the first N frames of each shot")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-assemble", action="store_true")
    p.add_argument("--out", default="")
    p = add("tts", cmd_tts)
    p.add_argument("--ext", default="wav", help="audio file extension the command writes (wav, mp3)")
    p.add_argument("--cmd", required=True, help="shell template using {text_file} {out} {ref} {lang} {speaker}")
    p.add_argument("--overwrite", action="store_true")
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except StudioError as e:
        print("ERROR:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
