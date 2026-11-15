import os

from src.studio_core import jobs, manifest as M
from src.studio_core.gpu import cost_guard, providers, renderers, worker
from tests.test_core import make_ep
from src.studio_core import timing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def setup(tmp_path):
    ep = make_ep()
    tl = timing.build_timeline(ep, "hindi", {"s01": "a.mp3"}, probe=lambda p: 9.0)  # s01 -> 2 segments
    js = jobs.plan_jobs(ep, tl, {}, ROOT, (320, 192))
    st = jobs.JobStore(str(tmp_path / "j.sqlite"), ROOT)
    return ep, tl, js, st


def guard(tmp_path, **kw):
    pol = cost_guard.BudgetPolicy(budget_inr=kw.pop("budget", 1e6), hourly_inr=0.0, **kw)
    return cost_guard.CostGuard(str(tmp_path / "cg.json"), pol)


def test_plan_ids_chain_and_hash_stability(tmp_path):
    ep, tl, js, st = setup(tmp_path)
    assert [j["job_id"] for j in js] == ["s01_00", "s01_01", "s02_00"]
    assert all((j["frames"] - 1) % 8 == 0 for j in js)
    ep2, tl2, js2, _ = setup(tmp_path)
    assert [j["spec_hash"] for j in js] == [j["spec_hash"] for j in js2]
    assert js[0]["spec_hash"] != js[1]["spec_hash"]


def test_upsert_cache_and_change(tmp_path):
    ep, tl, js, st = setup(tmp_path)
    assert st.upsert(js)["new"] == 3
    j = st.claim_next()
    f = tmp_path / "c.mp4"
    f.write_bytes(b"x")
    st.mark_done(j["job_id"], str(f))
    assert st.upsert(js) == {"new": 0, "changed": 0, "cached": 1, "requeued": 0}
    js[0]["spec_hash"] = "changed"
    assert st.upsert(js)["changed"] == 1 and st.get("s01_00")["status"] == "pending"


def test_claim_respects_segment_dependency(tmp_path):
    ep, tl, js, st = setup(tmp_path)
    st.upsert(js)
    a = st.claim_next()
    assert a["job_id"] == "s01_00"
    b = st.claim_next()  # s01_01 blocked until s01_00 done -> next available is s02_00
    assert b["job_id"] == "s02_00"
    assert st.claim_next() is None


def test_worker_mock_retries_and_completes(tmp_path):
    ep, tl, js, st = setup(tmp_path)
    st.upsert(js)
    r = renderers.MockRenderer(24, fail_ids={"s01_01"})
    prov = providers.MockProvider()
    res = worker.run_queue(st, r, prov, guard(tmp_path), str(tmp_path / "clips"), log=lambda *a: None)
    assert res["done"] == 3 and res["failed"] == 0 and st.stats()["done"] == 3
    assert prov.started == 1 and prov.stopped == 1
    assert len(st.shot_clips()) == 2


def test_worker_stops_after_consecutive_failures_and_still_stops_gpu(tmp_path):
    ep, tl, js, st = setup(tmp_path)
    st.upsert(js)

    class Boom(renderers.Renderer):
        def render(self, job, out, prev=""):
            raise RuntimeError("gpu on fire")

    prov = providers.MockProvider()
    res = worker.run_queue(st, Boom(), prov, guard(tmp_path), str(tmp_path / "clips"),
                           max_consecutive_failures=2, log=lambda *a: None)
    assert "failures in a row" in res["stopped_by"] and prov.stopped == 1
    assert st.stats()["running"] == 0


def test_worker_budget_stop_leaves_jobs_pending(tmp_path):
    ep, tl, js, st = setup(tmp_path)
    st.upsert(js)
    pol = cost_guard.BudgetPolicy(budget_inr=1.0, hourly_inr=6000.0, idle_minutes=1e9, max_session_minutes=1e9)
    g = cost_guard.CostGuard(str(tmp_path / "cg2.json"), pol)
    prov = providers.MockProvider()
    res = worker.run_queue(st, renderers.MockRenderer(24), prov, g, str(tmp_path / "clips"), log=lambda *a: None)
    assert res["done"] == 0 and st.stats()["pending"] == 3 and prov.stopped == 1
    assert "budget" in res["stopped_by"]


def test_manual_provider_without_stop_command_warns():
    msgs = []
    p = providers.ManualPodProvider("http://127.0.0.1:1", log=msgs.append)
    assert p.stop() is False and "ACTION REQUIRED" in msgs[-1]
    p2 = providers.ManualPodProvider("http://127.0.0.1:1", stop_command="true", log=msgs.append)
    assert p2.stop() is True


def test_stale_absolute_paths_from_another_machine_are_healed(tmp_path):
    ep, tl, js, st = setup(tmp_path)
    st.upsert(js)
    st.db.execute("UPDATE jobs SET ref_image='/old/machine/assets/x.jpg', out_path='/old/machine/c.mp4', status='done'")
    st.db.commit()
    res = st.upsert(js)  # same spec hash, but the old output file does not exist here
    assert res["requeued"] == 3
    job = st.claim_next()
    assert os.path.exists(job["ref_image"]) and job["ref_image"].startswith(ROOT)


def test_missing_reference_image_gives_clear_error(tmp_path):
    import pytest as _p
    from src.studio_core.util import StudioError
    job = {"job_id": "x", "ref_image": str(tmp_path / "nope.jpg"), "width": 64, "height": 64, "frames": 9}
    with _p.raises(StudioError, match="reference image not found"):
        renderers.MockRenderer(24).render(job, str(tmp_path / "o.mp4"))


def test_done_paths_are_stored_relative(tmp_path):
    ep, tl, js, st = setup(tmp_path)
    st.upsert(js)
    j = st.claim_next()
    out = os.path.join(ROOT, "episodes", "zz_clip.mp4")
    st.mark_done(j["job_id"], out)
    raw = st.db.execute("SELECT out_path FROM jobs WHERE job_id=?", (j["job_id"],)).fetchone()[0]
    assert not os.path.isabs(raw) and st.get(j["job_id"])["out_path"] == out
