"""Unit tests on a synthetic fixture repo: pkg with a known import graph,
a lazy-import cycle, and enough files to build zones."""
import subprocess
from pathlib import Path

import pytest

from buzz.analyze import analyze, short_names
from buzz.questions import generate_questions, make_followup
from buzz import engine
from buzz.model import LAZY, TOP

FILES = {
    "pkg/__init__.py": "from .core import Core\n",
    # core imports render lazily; render imports core top-level -> cycle if eager
    "pkg/core.py": (
        "from .base import Base\nfrom .util import helper\n"
        "def show():\n    from .render import draw\n    return draw\n"
    ),
    "pkg/render.py": "from .core import Core\nfrom .base import Base\n",
    "pkg/base.py": "import os\n",
    "pkg/util.py": "from .base import Base\n",
    "pkg/table.py": "from .core import Core\nfrom .base import Base\n",
    "pkg/text.py": "from .base import Base\nfrom .util import helper\n",
    "pkg/extras/fmt.py": "from ..text import t\n",
    "pkg/demo.py": (
        "from .table import T\n"
        "if __name__ == '__main__':\n    from .render import draw\n"
    ),
}


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("fixture")
    for rel, content in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    env_cfg = ["-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", *env_cfg, "add", "."], cwd=root, check=True)
    subprocess.run(["git", *env_cfg, "commit", "-qm", "init"], cwd=root, check=True)
    # a co-change pair with no import edge: base + demo twice
    for i in range(2):
        (root / "pkg/base.py").write_text(f"import os\n# {i}\n")
        (root / "pkg/demo.py").write_text(FILES["pkg/demo.py"] + f"# {i}\n")
        subprocess.run(["git", *env_cfg, "commit", "-qam", f"c{i}"], cwd=root, check=True)
    return root


@pytest.fixture(scope="module")
def world(repo):
    w = analyze(repo)
    generate_questions(w)
    return w


def test_short_names():
    assert short_names(["pkg", "pkg.a", "pkg.b", "pkg.sub.c"]) == {
        "pkg": "pkg", "pkg.a": "a", "pkg.b": "b", "pkg.sub.c": "sub.c"}


def test_graph_edges(world):
    def kind(a, b):
        return next((e.kind for e in world.edges if e.src == a and e.dst == b), None)
    assert kind("core", "base") == TOP
    assert kind("core", "render") == LAZY          # function-level import
    assert kind("render", "core") == TOP
    assert kind("demo", "render") is None          # __main__ block ignored
    assert kind("demo", "table") == TOP
    assert kind("extras.fmt", "text") == TOP       # relative ..text resolved
    assert kind("pkg", "core") == TOP              # __init__ named after package


def test_metrics_and_roles(world):
    assert world.modules["base"].in_degree >= 4
    roles = {m.role for m in world.modules.values()}
    assert "boss" in roles
    assert all(m.zone for m in world.modules.values())


def test_cycle_question_exists(world):
    cycles = [q for q in world.questions.values() if q.qtype == "cycle"]
    assert cycles, "lazy cycle core->render should generate a question"
    q = cycles[0]
    assert q.truth["src"] == "render" and q.truth["dst"] == "core"


def test_walk_answer_and_unlock(world):
    s = engine.new_session(world)
    q = next(q for q in world.questions.values() if q.qtype == "cycle")
    r = engine.answer(world, s, q.id, "walk", ["render", "core"])
    assert r["correct"] and s.xp == q.xp
    assert engine.TUNNEL in s.abilities
    # answering again is refused, progress never removed
    with pytest.raises(engine.GameError):
        engine.answer(world, s, q.id, "walk", ["render", "core"])


def test_wrong_walk_reveals_and_spawns_followup(world):
    s = engine.new_session(world)
    walks = [q for q in world.questions.values()
             if q.qtype == "walk" and not q.boss]
    if not walks:
        pytest.skip("fixture generated no walk question")
    q = walks[0]
    bad = [q.truth["src"], q.truth["src"], q.truth["dst"]]
    r = engine.answer(world, s, q.id, "walk", bad)
    assert not r["correct"] and s.xp == 0
    assert q.truth["example"] == r["q"].truth["example"]
    if r["followup"]:
        fq = engine.get_question(world, s, r["followup"])
        r2 = engine.answer(world, s, fq.id, "edge",
                           [fq.truth["src"], fq.truth["dst"]])
        assert r2["correct"] and s.xp > 0


def test_hint_ladder_costs(world):
    s = engine.new_session(world)
    q = next(q for q in world.questions.values() if q.qtype == "cycle")
    engine.hint(world, s, q.id)
    r = engine.answer(world, s, q.id, "walk", ["render", "core"])
    assert r["gained"] == round(q.xp * 0.8)


def test_hint_level3_reveals(world):
    s = engine.new_session(world)
    q = next(q for q in world.questions.values() if q.qtype == "cycle")
    engine.hint(world, s, q.id)
    engine.hint(world, s, q.id)
    lvl, text = engine.hint(world, s, q.id)
    assert lvl == 3 and s.resolved[q.id] == "revealed" and s.xp == 0


def test_movement_rules(world):
    s = engine.new_session(world)
    here = s.here
    outs = [e for e in world.out_edges(here)]
    if outs:
        e = next((e for e in outs if e.kind == TOP), None)
        if e:
            engine.go(world, s, e.dst)
            assert s.here == e.dst
            engine.go(world, s, here)  # fast travel back
            assert s.here == here
    hidden = next(m for m in world.modules if m not in s.seen)
    with pytest.raises(engine.GameError):
        engine.go(world, s, hidden)


def test_sealed_tunnel_blocked(world):
    s = engine.new_session(world)
    # place player at core; render is lazy target -> sealed
    engine._arrive(world, s, "core")
    ok, why = engine.can_travel(world, s, "render")
    assert not ok and "SEALED" in why
    s.abilities.append(engine.TUNNEL)
    ok, _ = engine.can_travel(world, s, "render")
    assert ok


def test_resolve_module_fuzzy(world):
    assert engine.resolve_module(world, "CORE") == "core"
    with pytest.raises(engine.GameError):
        engine.resolve_module(world, "nope")


def test_world_roundtrip(world, tmp_path):
    p = tmp_path / "w.json"
    world.save(p)
    from buzz.model import World
    w2 = World.load(p)
    assert set(w2.modules) == set(world.modules)
    assert len(w2.questions) == len(world.questions)
    assert w2.questions[next(iter(w2.questions))].truth


def test_no_duplicate_question_signatures(world):
    seen = set()
    for q in world.questions.values():
        t = q.truth
        sig = (q.qtype, t.get("src"), t.get("dst"), t.get("target"), t.get("module"))
        assert sig not in seen, f"duplicate question: {sig}"
        seen.add(sig)


def test_scout_flight_to_seen(world):
    s = engine.new_session(world)
    seen_unvisited = [m for m in s.seen if m not in s.discovered]
    if not seen_unvisited:
        pytest.skip("start reveals nothing unvisited")
    # pick one that is NOT adjacent via an out-edge of here
    adj = {e.dst for e in world.out_edges(s.here)}
    far = [m for m in seen_unvisited if m not in adj]
    target = (far or seen_unvisited)[0]
    ok, how = engine.can_travel(world, s, target)
    assert ok


def test_probe(world):
    out = engine.probe(world, "core", "base")
    assert "top-level import" in out
    out2 = engine.probe(world, "core", "render")
    assert "sealed tunnel" in out2


def test_point_verb(world):
    hubs = [q for q in world.questions.values() if q.qtype == "hub"]
    if not hubs:
        pytest.skip("fixture too small for hub question")
    q = hubs[0]
    s = engine.new_session(world)
    r = engine.answer(world, s, q.id, "point", [q.truth["module"]])
    assert r["correct"]


def test_victory_two_stage(world):
    s = engine.new_session(world)
    boss_qs = [q for q in world.questions.values() if q.boss]
    s.boss_open = True
    for q in boss_qs:
        s.resolved[q.id] = "correct"
    # trigger post-answer bookkeeping via any remaining question
    remaining = [q for q in world.questions.values() if q.id not in s.resolved]
    if not remaining or not boss_qs:
        pytest.skip("fixture lacks boss/regular split")
    engine._post_answer(world, s, remaining[0])
    clearable = {z for z in world.zones
                 if any(x.zone == z and not x.boss for x in world.questions.values())}
    need = min(3, len(clearable))
    if len(s.cleared) < need:
        assert not s.victory, "boss down alone must not end the campaign"
    for q in world.questions.values():
        s.resolved[q.id] = "correct"
    engine._post_answer(world, s, remaining[0])
    assert s.victory


def test_region_retry_flow(world):
    regions = [q for q in world.questions.values()
               if q.qtype == "region" and len(q.truth["region"]) >= 2]
    if not regions:
        pytest.skip("no multi-member region in fixture")
    q = regions[0]
    s = engine.new_session(world)
    truth = q.truth["region"]
    near_miss = truth[:-1] + ["__NOPE__"]
    near_miss = [m for m in near_miss if m in world.modules] or truth[:-1]
    r1 = engine.answer(world, s, q.id, "region", near_miss)
    assert r1.get("retry") and q.id not in s.resolved
    assert "missed:" not in r1["note"]          # counts only, no names
    r2 = engine.answer(world, s, q.id, "region", truth)
    assert r2["correct"]
    assert r2["gained"] < q.xp                  # retry discount applied


def test_rank_monotonic(world):
    s = engine.new_session(world)
    prev = engine.rank(world, s)
    order = ["Egg", "Larva", "Worker", "Forager", "Royal Guard", "Queen Bee"]
    for q in world.questions.values():
        s.xp += q.xp
        s.max_xp += q.xp * 2   # poor accuracy must not demote
        cur = engine.rank(world, s)
        assert order.index(cur) >= order.index(prev)
        prev = cur


def test_scout_reveals_names_only(world):
    s = engine.new_session(world)
    zid = next(iter(world.zones))
    engine.scout(world, s, zid)
    for m in world.zones[zid].members:
        assert m in s.seen
        assert m == s.here or m not in s.discovered


def test_reveal_prompt_modules_no_answer_leak(world):
    s = engine.new_session(world)
    for q in world.questions.values():
        before = set(s.seen)
        engine.reveal_prompt_modules(world, s, q)
        leaked = set(s.seen) - before
        if q.qtype == "hub":
            assert q.truth["module"] not in leaked
        if q.qtype == "walk":
            interior = set(q.truth["example"][1:-1])
            assert not (leaked & interior)


def test_gate_accepts_any_cut_vertex():
    # gate questions need a bigger graph than the fixture; verify the
    # point-verb accept-list logic directly instead
    from buzz.model import World, Question, Module, Zone
    w = World(repo="x", sha="y")
    for n in ("a", "g", "b"):
        w.modules[n] = Module(name=n, path=n, zone="z1")
    w.zones["z1"] = Zone(id="z1", name="Z", members=["a", "g", "b"])
    w.questions["q1"] = Question(
        id="q1", zone="z1", qtype="gate", verb="point", prompt="",
        truth={"a": "a", "b": "b", "module": "g", "accepted": ["g"]}, xp=10)
    from buzz.model import Session
    s = Session(here="a", discovered=["a"], seen=["a"])
    r = engine.answer(w, s, "q1", "point", ["g"])
    assert r["correct"]


def test_peek_remote_look(world):
    s = engine.new_session(world)
    target = next((m for m in s.seen if m != s.here), None)
    if target is None:
        pytest.skip("nothing seen from start")
    here = s.here
    engine.peek(world, s, target)
    assert s.here == here and target in s.discovered
    with pytest.raises(engine.GameError):
        engine.peek(world, s, next(m for m in world.modules if m not in s.seen))


def test_zone_edges_dump(world):
    zid = next(iter(world.zones))
    out = engine.zone_edges(world, zid)
    assert out and out[0].startswith("top-level import edges")


def test_walk_package_hop_forgiven():
    from buzz.model import World, Question, Module, Zone, Edge, Session
    w = World(repo="x", sha="y")
    for n in ("a", "pkg", "pkg.sub"):
        w.modules[n] = Module(name=n, path=n, zone="z1")
    w.zones["z1"] = Zone(id="z1", name="Z", members=list(w.modules))
    w.edges = [Edge("a", "pkg"), Edge("pkg", "pkg.sub")]
    w.questions["q1"] = Question(
        id="q1", zone="z1", qtype="walk", verb="walk", prompt="",
        truth={"src": "a", "dst": "pkg.sub", "example": ["a", "pkg", "pkg.sub"]},
        xp=10)
    s = Session(here="a", discovered=["a"], seen=["a"])
    r = engine.answer(w, s, "q1", "walk", ["a", "pkg.sub"])
    assert r["correct"], "skipping the parent-package hop must be forgiven"


def test_detour_rejects_avoided_module():
    from buzz.model import World, Question, Module, Zone, Edge, Session
    w = World(repo="x", sha="y")
    for n in ("a", "g", "h", "b"):
        w.modules[n] = Module(name=n, path=n, zone="z1")
    w.zones["z1"] = Zone(id="z1", name="Z", members=list(w.modules))
    w.edges = [Edge("a", "g"), Edge("g", "b"), Edge("a", "h"), Edge("h", "b")]
    w.questions["q1"] = Question(
        id="q1", zone="z1", qtype="detour", verb="walk", prompt="",
        truth={"src": "a", "dst": "b", "avoid": "g",
               "example": ["a", "h", "b"]}, xp=30)
    s = Session(here="a", discovered=["a"], seen=["a"])
    r = engine.answer(w, s, "q1", "walk", ["a", "g", "b"])
    assert not r["correct"] and "touches g" in r["note"]
    s2 = Session(here="a", discovered=["a"], seen=["a"])
    r2 = engine.answer(w, s2, "q1", "walk", ["a", "h", "b"])
    assert r2["correct"]


def test_walk_retry_then_correct(world):
    s = engine.new_session(world)
    q = next(q for q in world.questions.values() if q.qtype == "cycle")
    ex = q.truth["example"]
    bad = [ex[0], ex[0], ex[-1]]
    r1 = engine.answer(world, s, q.id, "walk", bad)
    assert r1.get("retry") and q.id not in s.resolved
    r2 = engine.answer(world, s, q.id, "walk", ex)
    assert r2["correct"] and 0 < r2["gained"] < q.xp
    assert "your chain checks out" in r2["explain"]


def test_elder_and_hotspot_verbs():
    from buzz.model import World, Question, Module, Zone, Session
    w = World(repo="x", sha="y")
    for n, born, commits in (("a", "2019-01-01", 30), ("b", "2022-01-01", 5)):
        w.modules[n] = Module(name=n, path=n, zone="z1", born=born,
                              commits=commits)
    w.zones["z1"] = Zone(id="z1", name="Z", members=["a", "b"])
    w.questions["q1"] = Question(
        id="q1", zone="z1", qtype="elder", verb="edge", prompt="",
        truth={"src": "a", "dst": "b", "born_src": "2019-01-01",
               "born_dst": "2022-01-01"}, xp=15)
    w.questions["q2"] = Question(
        id="q2", zone="z1", qtype="hotspot", verb="point", prompt="",
        truth={"module": "a", "commits": 30}, xp=15)
    s = Session(here="a", discovered=["a"], seen=["a"])
    r = engine.answer(w, s, "q1", "edge", ["a", "b"])
    assert r["correct"] and "2019" in r["explain"]
    s2 = Session(here="a", discovered=["a"], seen=["a"])
    r2 = engine.answer(w, s2, "q1", "edge", ["b", "a"])
    assert not r2["correct"] and "wrong direction" in r2["note"]
    r3 = engine.answer(w, s, "q2", "point", ["a"])
    assert r3["correct"]


def test_who_and_cross_zone_edges(world):
    out = engine.who(world, "base")
    assert any("core" in ln for ln in out)
    zid = world.modules["base"].zone
    dump = engine.zone_edges(world, zid)
    assert dump[0].startswith("top-level import edges")


def test_streak_bonus_and_reset(world):
    s = engine.new_session(world)
    qs = [q for q in world.questions.values() if q.qtype == "walk" and not q.boss]
    if len(qs) < 1:
        pytest.skip("no walk questions")
    s.streak = 4
    q = qs[0]
    r = engine.answer(world, s, q.id, "walk", q.truth["example"])
    assert r["correct"] and r["gained"] == round(q.xp * 1.2)
    assert s.streak == 5
    # a reveal breaks the streak
    s2 = engine.new_session(world)
    s2.streak = 3
    cyc = next(q for q in world.questions.values() if q.qtype == "cycle")
    engine.hint(world, s2, cyc.id)
    engine.hint(world, s2, cyc.id)
    engine.hint(world, s2, cyc.id)
    assert s2.streak == 0


def test_patch_and_scar_verbs():
    from buzz.model import World, Question, Module, Zone, Session
    w = World(repo="x", sha="y")
    for n in ("a", "b", "c"):
        w.modules[n] = Module(name=n, path=n, zone="z1", commits=5)
    w.zones["z1"] = Zone(id="z1", name="Z", members=["a", "b", "c"])
    w.questions["q1"] = Question(
        id="q1", zone="z1", qtype="patch", verb="point", prompt="",
        truth={"module": "b", "anchor": "a", "subject": "fix thing",
               "date": "2024-01-01", "suspects": ["b", "c"]}, xp=25)
    w.questions["q2"] = Question(
        id="q2", zone="z1", qtype="scar", verb="point", prompt="",
        truth={"module": "c", "subject": "Revert fix", "date": "2024-02-02"},
        xp=20)
    s = Session(here="a", discovered=["a"], seen=["a"])
    r = engine.answer(w, s, "q1", "point", ["b"])
    assert r["correct"] and "chronicle" in r["explain"]
    r2 = engine.answer(w, s, "q2", "point", ["c"])
    assert r2["correct"] and "scar" in r2["explain"]


def test_events_captured(world):
    # fixture repo has focused commits touching base+demo together
    assert isinstance(world.events, list)


def test_authored_lore_validation_and_play(world):
    from buzz import author
    z = next(iter(world.zones))
    mods = world.zones[z].members
    if len(mods) < 4:
        pytest.skip("zone too small")
    good = {"zone": z, "prompt": "Which module in this district owns the "
            "shared low-level primitives every renderer builds on, per its "
            "class definitions?", "answer": mods[0],
            "suspects": mods[:4], "lesson": "primitives sit at the bottom",
            "hint": "look for the class everything subclasses"}
    leak = dict(good, prompt=f"Which module, named {mods[0]}, owns the "
                "primitives that everything builds on in this district?")
    bad_zone = dict(good, zone="z99")
    r = author.apply_authored(world, [good, leak, bad_zone])
    assert len(r["added"]) == 1 and len(r["rejected"]) == 2
    qid = r["added"][0]
    s = engine.new_session(world)
    res = engine.answer(world, s, qid, "point", [mods[0]])
    assert res["correct"] and "where it lives" in res["explain"]
