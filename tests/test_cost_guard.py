from src.studio_core.gpu.cost_guard import BudgetPolicy, CostGuard, estimate_cost


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def adv(self, minutes):
        self.t += minutes * 60


def mk(tmp_path, **kw):
    clk = Clock()
    pol = BudgetPolicy(budget_inr=100, hourly_inr=60, **kw)
    return CostGuard(str(tmp_path / "c.json"), pol, clk), clk


def test_cost_accrues_and_rounds_up(tmp_path):
    g, clk = mk(tmp_path)
    g.start_session()
    clk.adv(10.5)  # 11 billable minutes at Rs1/min
    assert g.spent() == 11.0
    assert g.end_session() == 11.0 and g.state["session"] is None


def test_warn_then_hard_stop(tmp_path):
    g, clk = mk(tmp_path, idle_minutes=1000)
    g.start_session()
    clk.adv(75)
    assert g.check().action == "warn"
    g.activity()
    clk.adv(20)
    d = g.check()
    assert d.action == "shutdown" and "budget" in d.reason


def test_idle_and_max_session(tmp_path):
    g, clk = mk(tmp_path, idle_minutes=5, max_session_minutes=30)
    g.start_session()
    clk.adv(6)
    assert "idle" in g.check().reason
    g.activity()
    clk.adv(4)
    assert g.check().action == "ok"
    for _ in range(8):
        clk.adv(4)
        g.activity()
    assert "session" in g.check().reason


def test_persists_across_instances(tmp_path):
    g, clk = mk(tmp_path)
    g.start_session()
    clk.adv(20)
    g.end_session()
    g2 = CostGuard(str(tmp_path / "c.json"), g.policy, clk)
    assert g2.spent() == 20.0


def test_can_afford_and_gst(tmp_path):
    g, clk = mk(tmp_path, gst_pct=18)
    g.start_session()
    assert g.can_afford(60) and not g.can_afford(3600 * 2)
    clk.adv(60)
    assert g.spent() == 70.8


def test_estimate_cost():
    e = estimate_cost(600, 5, 3, BudgetPolicy(hourly_inr=90), setup_minutes=30)
    assert e["cost_inr"] > 0 and e["gpu_hours"] > 0.5
