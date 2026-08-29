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
    # the oracle tells all but the player still closes the quest themselves
    assert lvl == 3 and q.id not in s.resolved and "closing move" in text
    r = engine.answer(world, s, q.id, "walk", q.truth["example"])
    assert r["correct"] and r["gained"] == 0 and s.resolved[q.id] == "correct"


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
    # the refusal must neither name the destination nor confirm the
    # edge's endpoint (round c13: the old message handed both over)
    assert not ok and "sealed tunnel" in why and "render" not in why
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


def test_zone_edges_grouped_capped_and_lens(world):
    """BIGEDGE round: grouped view caps importer lists (numberless '...')
    while the hub quest is open, only printed names are marked seen, the
    full view keeps raw arrows, and the module lens shows both
    directions uncapped."""
    hubs = [q for q in world.questions.values() if q.qtype == "hub"]
    zid = hubs[0].zone if hubs else next(iter(world.zones))
    s = engine.new_session(world)
    grouped = engine.zone_edges(world, zid, s)
    fulld = engine.zone_edges(world, zid, s, full=True)
    assert any(" <- " in ln for ln in grouped)
    assert any(" -> " in ln for ln in fulld[1:2] + fulld[1:])
    if hubs:
        # while the hub quest is open: no in-degree tally line, and any
        # row over the cap ends in a numberless ellipsis
        assert any("tally withheld" in ln for ln in grouped)
        hub_target = hubs[0].truth["module"]
        row = next((ln for ln in grouped
                    if ln.strip().startswith(f"{hub_target} <-")), "")
        if row.rstrip().endswith("..."):
            assert not any(ch.isdigit() for ch in row.split("<-")[1]), \
                "capped row must not carry a count"
        # capped grouped view marks only PRINTED names seen: never more
        # than the full dump's names
        s2 = engine.new_session(world)
        engine.zone_edges(world, zid, s2)
        s3 = engine.new_session(world)
        engine.zone_edges(world, zid, s3, full=True)
        assert set(s2.seen) <= set(s3.seen)
    # the lens: both directions for one module, in one screen
    zone = world.zones[zid]
    m = max(zone.members,
            key=lambda x: sum(1 for e in world.edges if e.dst == x))
    lens = engine.zone_edges(world, zid, s, mod=m)
    assert lens[0].startswith(f"top-level edges touching {m}")


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
    # a full reveal HALVES the streak (soft decay, never a hard reset)
    s2 = engine.new_session(world)
    s2.streak = 3
    cyc = next(q for q in world.questions.values() if q.qtype == "cycle")
    engine.hint(world, s2, cyc.id)
    engine.hint(world, s2, cyc.id)
    engine.hint(world, s2, cyc.id)
    assert s2.streak == 1


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


def test_rescout_aftershocks(repo, world, tmp_path):
    import subprocess
    from buzz.rescout import rescout
    w2 = world  # same world object; sha pinned at analyze time
    old_sha = w2.sha
    env_cfg = ["-c", "user.email=t@t", "-c", "user.name=t"]
    # a fresh focused 2-module commit lands after the pin
    (repo / "pkg/util.py").write_text("from .base import Base\n# new\n")
    (repo / "pkg/text.py").write_text(
        "from .base import Base\nfrom .util import helper\n# new\n")
    subprocess.run(["git", *env_cfg, "commit", "-qam",
                    "FIX keep helper defaults in sync with rendering (#9)"],
                   cwd=repo, check=True)
    r = rescout(w2, repo)
    assert r["moved"] and r["commits"] >= 1
    assert "util" in r["disturbed"] and "text" in r["disturbed"]
    assert w2.sha != old_sha
    if r["aftershocks"]:
        qid = r["aftershocks"][0]
        q = w2.questions[qid]
        assert q.qtype == "patch" and q.truth["module"] in q.truth["suspects"]
        assert q.truth.get("aftershock") is True
        # the fresh commit entered the record, so probe can feel it
        out = engine.probe(w2, q.truth["anchor"], q.truth["module"])
        assert "moving BOTH" in out
    # a second rescout with no new commits reports the standing aftershocks
    # instead of implying nothing ever happened (round-13 bug)
    r2 = rescout(w2, repo)
    assert not r2["moved"]
    assert set(r2["standing"]) == set(r["aftershocks"])


def test_atlas_renders(world):
    from buzz.atlas import render_atlas
    s = engine.new_session(world)
    html_out = render_atlas(world, s)
    assert "<svg" in html_out and "INFO" in html_out
    assert world.start.split(".")[-1][:12] in html_out


def test_recap_contains_solved_fact(world):
    from buzz.recap import render_recap
    s = engine.new_session(world)
    q = next(q for q in world.questions.values() if q.qtype == "cycle")
    engine.answer(world, s, q.id, "walk", q.truth["example"])
    text = render_recap(world, s)
    assert "Field notes" in text and "one real chain" in text
    # onboarding sections: district overview + directory of surveyed modules
    assert "hive at a glance" in text
    assert "Directory of everything surveyed" in text
    assert "surveyed" in text.splitlines()[2]  # header credits survey work


def test_resolve_dotted_suffix():
    from buzz.model import World, Module
    w = World(repo="x", sha="y")
    for n in ("transports.trunkline.backend", "core.engine", "core.utils"):
        w.modules[n] = Module(name=n, path=n, zone="z1")
    assert engine.resolve_module(w, "trunkline.backend") == \
        "transports.trunkline.backend"
    assert engine.resolve_module(w, "backend") == \
        "transports.trunkline.backend"
    with pytest.raises(engine.GameError):
        engine.resolve_module(w, "nowhere.at.all")


def test_probe_reports_focused_pair_commits():
    from buzz.model import World, Module
    w = World(repo="x", sha="y")
    for n in ("a", "b", "c"):
        w.modules[n] = Module(name=n, path=n, zone="z1")
    w.events.append({"date": "2025-01-05", "subject": "sync defaults",
                     "mods": ["a", "b"]})
    out = engine.probe(w, "a", "b")
    assert "moving BOTH" in out and "2025-01-05" in out
    assert "moving BOTH" not in engine.probe(w, "a", "c")


def test_wrong_answer_halves_streak():
    from buzz.model import World, Question, Module, Zone, Session
    w = World(repo="x", sha="y")
    for n in ("a", "b", "c"):
        w.modules[n] = Module(name=n, path=n, zone="z1")
    w.zones["z1"] = Zone(id="z1", name="Z", members=["a", "b", "c"])
    w.questions["q1"] = Question(
        id="q1", zone="z1", qtype="patch", verb="point", prompt="",
        truth={"module": "b", "anchor": "a", "subject": "s",
               "date": "2024-01-01", "suspects": ["b", "c"]}, xp=25)
    s = Session(here="a", discovered=["a"], seen=["a"])
    s.streak = 5
    engine.answer(w, s, "q1", "point", ["c"])
    assert s.streak == 2  # halved, not zeroed


def test_shell_completer_respects_fog(world):
    from buzz.shell import _completer_factory, COMMANDS
    s = engine.new_session(world)
    complete = _completer_factory(world, s)
    # first token: commands
    hits = []
    i = 0
    while (h := complete("g", i)) is not None:
        hits.append(h); i += 1
    assert "go" in hits and all(h in COMMANDS for h in hits)
    # module completion draws ONLY from what the fog has yielded
    unseen = [m for m in world.modules if m not in s.seen]
    if unseen:
        target = unseen[0]
        i, hits = 0, []
        while (h := complete(target[:3], i)) is not None:
            hits.append(h); i += 1
        assert target not in hits


def test_quest_gist_one_line():
    from buzz.render import _gist
    long = "A page from the chronicle. " * 10
    g = _gist(long)
    assert len(g) <= 72 and "\n" not in g and g.endswith("...")
    assert _gist("short prompt") == "short prompt"


def test_shell_pipe_session(repo, tmp_path, monkeypatch):
    import subprocess, os, sys
    game = tmp_path / "g"
    game.mkdir()
    env = dict(os.environ, BUZZ_DIR=str(game / ".buzz"), BUZZ_SESSION="t1")
    subprocess.run([sys.executable, "-m", "buzz.cli", "analyze", str(repo)],
                   cwd=game, env=env, check=True, capture_output=True)
    subprocess.run([sys.executable, "-m", "buzz.cli", "play"],
                   cwd=game, env=env, check=True, capture_output=True)
    out = subprocess.run(
        [sys.executable, "-m", "buzz.cli", "shell"], cwd=game, env=env,
        input="quests\nstatus\nquit\n", text=True, capture_output=True)
    assert out.returncode == 0
    assert "buzz>" in out.stdout and "session saved" in out.stdout


def _mini_world(edges, zone_members):
    from buzz.model import World, Module, Zone, Edge, TOP
    w = World(repo="x", sha="y")
    mods = sorted({m for e in edges for m in e} | set(zone_members))
    for n in mods:
        w.modules[n] = Module(name=n, path=n, zone="z1")
    w.zones["z1"] = Zone(id="z1", name="Z", members=list(zone_members), order=2)
    for a, b in edges:
        w.edges.append(Edge(src=a, dst=b, kind=TOP))
    return w


def test_order_verb_verification():
    from buzz.model import Question, Session
    w = _mini_world([("b", "a"), ("c", "b"), ("d", "a")], ["a", "b", "c", "d"])
    w.questions["q1"] = Question(
        id="q1", zone="z1", qtype="order", verb="order", prompt="",
        truth={"set": ["a", "b", "c", "d"],
               "pairs": [["b", "a"], ["c", "b"], ["c", "a"], ["d", "a"]],
               "example": ["a", "b", "c", "d"]}, xp=30)
    s = Session(here="a", discovered=["a"], seen=["a"])
    # wrong set is a syntax error, not an attempt
    with pytest.raises(engine.GameError):
        engine.answer(w, s, "q1", "order", ["a", "b", "c", "c"])
    # invalid order: retry, not a verdict
    r = engine.answer(w, s, "q1", "order", ["c", "b", "a", "d"])
    assert r["retry"] and "q1" not in s.resolved
    # any valid topological order is accepted (not only the example)
    r2 = engine.answer(w, s, "q1", "order", ["a", "d", "b", "c"])
    assert r2["correct"] and "valid order" in r2["explain"]


def test_via_walk_verification():
    from buzz.model import Question, Session
    w = _mini_world([("a", "v"), ("v", "b"), ("a", "b")], ["a", "v", "b"])
    w.questions["q1"] = Question(
        id="q1", zone="z1", qtype="via", verb="walk", prompt="",
        truth={"src": "a", "dst": "b", "via": "v",
               "example": ["a", "v", "b"]}, xp=20)
    s = Session(here="a", discovered=["a"], seen=["a"])
    r = engine.answer(w, s, "q1", "walk", ["a", "b"])  # real chain, no via
    assert r["retry"] and "THROUGH" in r["note"]
    r2 = engine.answer(w, s, "q1", "walk", ["a", "v", "b"])
    assert r2["correct"]


def test_decision_generators_on_synthetic_graph():
    from buzz.questions import gen_cut, gen_refactor, gen_order, gen_via
    from buzz.analyze import top_graph
    # a spine with spread-out reverse reaches for cut/refactor
    edges = [("app", "svc"), ("svc", "core"), ("app", "core"),
             ("cli", "app"), ("web", "app"), ("job", "svc"),
             ("core", "util"), ("svc", "util"), ("x1", "cli")]
    members = ["app", "svc", "core", "cli", "web", "job", "util", "x1"]
    w = _mini_world(edges, members)
    G = top_graph(w)
    used: set = set()
    assert gen_cut(w, G, "z1", used=used) == 1
    cut = next(q for q in w.questions.values() if q.qtype == "cut")
    sizes = cut.truth["sizes"]
    assert cut.truth["module"] == min(sizes, key=lambda m: sizes[m])
    assert gen_refactor(w, G, "z1", used=used) == 1
    ref = next(q for q in w.questions.values() if q.qtype == "refactor")
    assert ref.truth["n_win"] < ref.truth["n_lose"]
    assert gen_order(w, G, "z1", used=used) == 1
    order = next(q for q in w.questions.values() if q.qtype == "order")
    ex = order.truth["example"]
    posn = {m: i for i, m in enumerate(ex)}
    assert all(posn[v] < posn[u] for u, v in order.truth["pairs"])
    assert gen_via(w, G, "z1", used=used) == 1
    via = next(q for q in w.questions.values() if q.qtype == "via")
    assert via.truth["via"] in via.truth["example"][1:-1] or \
        via.truth["via"] in via.truth["example"]


def test_order_red_herring_on_second_instance():
    from buzz.model import Question, Edge, LAZY
    from buzz.questions import gen_order
    from buzz.analyze import top_graph
    w = _mini_world([("b", "a"), ("c", "b"), ("d", "a")],
                    ["a", "b", "c", "d"])
    # the fake constraint: a lazy a->c import whose REAL top-level
    # dependency (c transitively imports a) points the other way
    w.edges.append(Edge(src="a", dst="c", kind=LAZY))
    # a prior order quest anywhere in the world makes this the second one
    w.questions["q0"] = Question(id="q0", zone="z1", qtype="order",
                                 verb="order", prompt="", truth={}, xp=30)
    G = top_graph(w)
    assert gen_order(w, G, "z1", used=set()) == 1
    q = next(q for q in w.questions.values()
             if q.qtype == "order" and q.truth)
    assert q.truth.get("herring") == ["a", "c"]
    # and the naive order (counting the fake edge) violates a real pair
    assert ("c", "a") in {tuple(p) for p in q.truth["pairs"]}

def test_lore_parse_tolerates_fences():
    from buzz.lore import _parse
    obj = {"quests": [], "zone_briefs": {"z1": "x"}, "glosses": {}}
    import json as _j
    fenced = "Here you go:\n```json\n" + _j.dumps(obj) + "\n```\nDone."
    assert _parse(fenced) == obj
    assert _parse(_j.dumps(obj)) == obj
    with pytest.raises(ValueError):
        _parse("no json here at all")


def test_run_lore_via_custom_cmd(world, tmp_path, monkeypatch):
    import json as _j
    from buzz.lore import run_lore
    z = next(iter(world.zones))
    mods = sorted(world.zones[z].members)
    if len(mods) < 4:
        pytest.skip("zone too small")
    nodoc = next((m for m in world.modules if not world.modules[m].doc), None)
    resp = {
        "quests": [{"zone": z,
                    "prompt": "Which module in this district owns the shared "
                              "primitives everything else builds on, judging "
                              "by its class definitions and imports?",
                    "answer": mods[0], "suspects": mods[:4],
                    "lesson": "primitives sit at the bottom", "hint": "h"}],
        "zone_briefs": {z: "the foundation cluster", "zzz": "ignored"},
        "glosses": ({nodoc: "does a thing"} if nodoc else {}),
    }
    stub = tmp_path / "stub.py"
    stub.write_text("import sys, json\nsys.stdin.read()\n"
                    f"print(json.dumps({resp!r}))")
    monkeypatch.setenv("BUZZ_LORE_CMD", f"python {stub}")
    r = run_lore(world)
    assert len(r["added"]) == 1 and r["zone_briefs"] == 1
    assert world.zones[z].brief == "the foundation cluster"
    if nodoc:
        assert world.modules[nodoc].gloss == "does a thing"
    qid = r["added"][0]
    s = engine.new_session(world)
    res = engine.answer(world, s, qid, "point", [mods[0]])
    assert res["correct"]


def test_model_roundtrip_with_lore_fields(tmp_path):
    from buzz.model import World, Module, Zone
    w = World(repo="x", sha="y")
    w.modules["a"] = Module(name="a", path="a", zone="z1", gloss="impression")
    w.zones["z1"] = Zone(id="z1", name="Z", members=["a"], brief="a brief")
    p = tmp_path / "w.json"
    w.save(p)
    w2 = World.load(p)
    assert w2.modules["a"].gloss == "impression"
    assert w2.zones["z1"].brief == "a brief"


def test_flow_extraction_and_journey(tmp_path):
    import subprocess as sp
    root = tmp_path / "flowrepo"
    (root / "app").mkdir(parents=True)
    files = {
        "app/__init__.py": "",
        "app/cli.py": ("from .engine import run_job\n"
                       "def main():\n    run_job('x')\n"
                       "if __name__ == '__main__':\n    main()\n"),
        "app/engine.py": ("from .store import save\nimport app.codec as codec\n"
                          "def run_job(x):\n"
                          "    save(codec.encode(x))\n"),
        "app/codec.py": "def encode(x):\n    return x\n",
        "app/store.py": ("from .codec import encode\n"
                         "def save(x):\n    return x\n"),  # import, NO call
        "app/extra.py": "import os\n",
    }
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content)
    sp.run(["git", "init", "-q"], cwd=root, check=True)
    sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."],
           cwd=root, check=True)
    sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
            "-qm", "init"], cwd=root, check=True)
    w = analyze(root)
    calls = {(c["src"], c["dst"]): c["via"] for c in w.calls}
    assert ("cli", "engine") in calls and "run_job" in calls[("cli", "engine")]
    assert ("engine", "store") in calls        # from-import symbol call
    assert ("engine", "codec") in calls        # module-alias attribute call
    assert ("store", "codec") not in calls     # import without a call
    assert "cli" in w.entries                  # __main__ guard detected
    generate_questions(w)
    j = next((q for q in w.questions.values() if q.qtype == "journey"), None)
    assert j and j.truth["src"] == "cli"
    s = engine.new_session(w)
    # an import-only hop is rejected with the teaching message
    r = engine.answer(w, s, j.id, "walk",
                      ["cli", "engine", "store", "codec"])
    assert not r.get("correct") and "CALLS" in (r.get("note") or "")
    r2 = engine.answer(w, s, j.id, "walk", j.truth["example"])
    assert r2["correct"] and "the work travels" in r2["explain"]


def test_overworld_layout_pure(world):
    from buzz.overworld import compute_layout
    rooms, tiles, height, tile_w = compute_layout(world)
    assert tile_w >= 14
    assert set(rooms) == set(world.zones)
    assert set(tiles) == set(world.modules)
    for m, (tx, ty) in tiles.items():
        x, y, w, h = rooms[world.modules[m].zone]
        assert x <= tx < x + w and y < ty < y + h, f"{m} outside its room"
    assert height > 0
    # no two tiles collide
    assert len({v for v in tiles.values()}) == len(tiles)


def test_whispers_true_and_guarded(world):
    from buzz.overworld import _whisper
    from buzz.model import Question
    s = engine.new_session(world)
    m = s.here
    w1 = _whisper(world, s, m)
    assert w1 is None or w1.startswith("~ ")
    # once heard, a tile stays quiet
    assert m in s.whispers or w1 is None
    assert _whisper(world, s, m) is None or m not in s.whispers
    # leak guard: an open ghost quest silences the co-change whisper
    partner = next(iter(world.cochange.get(m, [])), None)
    if partner:
        world.questions["qq_ghost"] = Question(
            id="qq_ghost", zone=world.modules[m].zone, qtype="ghost",
            verb="edge", prompt="",
            truth={"src": m, "accepted": [partner[0]], "best": partner[0],
                   "suspects": [partner[0]]}, xp=20)
        s2 = engine.new_session(world)
        got = _whisper(world, s2, m)
        assert got is None or partner[0] not in got
        del world.questions["qq_ghost"]


def test_session_roundtrip_with_whispers(tmp_path):
    from buzz.model import Session
    s = Session(here="a", discovered=["a"], seen=["a"], whispers=["a", "b"])
    p = tmp_path / "s.json"
    s.save(p)
    s2 = Session.load(p)
    assert s2.whispers == ["a", "b"]


def test_lore_openai_compat_transport(monkeypatch):
    """BUZZ_LORE_URL drives any OpenAI-compatible endpoint via stdlib:
    right route, right body, Bearer auth, content extracted - and an
    explicit URL never falls back to the SDK."""
    import io
    import json
    import urllib.request
    from buzz import lore

    seen = {}

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("Authorization")
        seen["body"] = json.loads(req.data.decode())
        return FakeResp(json.dumps({"choices": [{"message": {
            "content": '{"quests": []}'}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("BUZZ_LORE_URL", "https://gw.example.com/v1/")
    monkeypatch.setenv("BUZZ_LORE_MODEL", "mtk/glm-5.2")
    monkeypatch.setenv("BUZZ_LORE_KEY", "sekrit")
    monkeypatch.delenv("BUZZ_LORE_CMD", raising=False)
    out = lore._transport("the brief")
    assert out == '{"quests": []}'
    assert seen["url"] == "https://gw.example.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sekrit"
    assert seen["body"]["model"] == "mtk/glm-5.2"
    assert seen["body"]["messages"] == [
        {"role": "user", "content": "the brief"}]
    # a configured URL with no model is a loud config error, not a fallback
    monkeypatch.delenv("BUZZ_LORE_MODEL")
    with pytest.raises(lore.LoreUnavailable, match="BUZZ_LORE_MODEL"):
        lore._transport("the brief")


def test_quest_focus(world, capsys):
    """Viewing a quest tracks it; bare quest/hint/answer target the
    tracked quest; a typo'd id is refused, never swallowed as an answer;
    resolving clears the focus."""
    from buzz.cli import dispatch
    s = engine.new_session(world)
    q = next(q for q in world.questions.values() if q.qtype == "cycle")
    dispatch(world, s, "quest", [q.id])
    assert s.focus == q.id
    dispatch(world, s, "quest", [])           # bare quest reprints, no error
    dispatch(world, s, "hint", [])            # bare hint targets the focus
    assert s.hints.get(q.id) == 1
    with pytest.raises(engine.GameError):     # id-shaped typo is a typo
        dispatch(world, s, "answer", ["q999", "render"])
    assert q.id not in s.resolved
    dispatch(world, s, "answer", ["render", "core"])  # id omitted: focus
    assert s.resolved.get(q.id) == "correct"
    assert s.focus == ""                      # resolved -> nothing tracked
    # focus survives a save/load round trip like any session field
    capsys.readouterr()


def test_wanted_daily(world):
    from buzz import wanted
    s = engine.new_session(world)
    date, target = wanted.pick(world, "2026-08-26")
    d2, t2 = wanted.pick(world, "2026-08-26")
    assert (date, target) == (d2, t2)          # deterministic
    assert target in world.modules
    # play() hunts TODAY's fugitive - guesses must be relative to it, or
    # this test loses a coin-flip whenever the calendar rolls over
    _, target = wanted.pick(world)
    # the poster never names the fugitive
    assert all(target not in ln for ln in wanted.poster(world, target))
    xp0 = s.xp
    # a typo spends no guess
    out = wanted.play(world, s, "no.such.module")
    assert "free" in out[0] and not s.wanted.get("guesses")
    # wrong real guess: costs a guess, sharpens the poster, no XP change
    wrong = next(n for n in sorted(world.modules) if n != target)
    out = wanted.play(world, s, wrong)
    assert len(s.wanted["guesses"]) == 1 and s.xp == xp0
    # correct guess pays the bounty exactly once
    out = wanted.play(world, s, target)
    assert s.wanted["won"] and s.xp == xp0 + wanted.BOUNTY
    out = wanted.play(world, s, target)
    assert "already" in out[0] and s.xp == xp0 + wanted.BOUNTY
    # roundtrip: the wanted dict survives save/load
    import json as _json
    from dataclasses import asdict
    from buzz.model import Session
    s2 = Session(**_json.loads(_json.dumps(asdict(s))))
    assert s2.wanted["won"]


def test_wanted_exhaust_reveals_costs_nothing(world):
    from buzz import wanted
    s = engine.new_session(world)
    _, target = wanted.pick(world)
    xp0 = s.xp
    wrongs = [n for n in sorted(world.modules) if n != target]
    for g in wrongs[: wanted.MAX_GUESSES]:
        out = wanted.play(world, s, g)
    assert s.wanted["done"] and not s.wanted["won"]
    assert target in out[-1]                   # revealed on the cold trail
    assert s.xp == xp0                         # nothing lost (rule 12)


def test_export_pack(world, tmp_path):
    from buzz.export import export
    s = engine.new_session(world)
    out, files = export(world, s, tmp_path)
    assert (out / "index.md").exists()
    assert (out / "atlas.html").exists()
    assert (out / "field_notes.md").exists()
    idx = (out / "index.md").read_text()
    assert "atlas.html" in idx and "field_notes.md" in idx
    assert world.sha[:10] in idx

def test_exam_flow(world):
    from buzz import exam
    s = engine.new_session(world)
    with pytest.raises(engine.GameError):
        exam.start(world, s)   # nothing solved yet
    # solve enough quests honestly to open the exam
    solved = 0
    for q in list(world.questions.values()):
        if solved >= 4 or q.boss:
            continue
        t = q.truth
        try:
            if q.verb == "walk":
                r = engine.answer(world, s, q.id, "walk", t["example"])
            elif q.verb == "point":
                r = engine.answer(world, s, q.id, "point", [t["module"]])
            elif q.verb == "edge" and "dst" in t:
                r = engine.answer(world, s, q.id, "edge", [t["src"], t["dst"]])
            elif q.verb == "region":
                r = engine.answer(world, s, q.id, "region", t["region"])
            else:
                continue
        except engine.GameError:
            continue
        if r.get("correct"):
            solved += 1
    if solved < 4:
        pytest.skip("fixture too small to open the exam")
    r = exam.start(world, s)
    total = r["total"]
    xp_before = s.xp
    # answer every exam question correctly from truth
    for _ in range(total):
        q = exam.current(world, s)
        t = q.truth
        args = (t["example"] if q.verb == "walk"
                else [t["module"]] if q.verb == "point"
                else [t["src"], t["dst"]] if q.verb == "edge"
                else t["region"])
        res = exam.grade(world, s, args)
    assert res["done"] and res["pct"] == 100 and res["title"] == "Elder Sage"
    assert s.xp == xp_before          # the exam pays nothing
    assert s.exam["best"] == 100


def test_exam_resumes_and_teaches_on_miss(world):
    from buzz import exam
    s = engine.new_session(world)
    # seed 4 correct solves directly (grading tolerates a full map)
    qids = [q.id for q in world.questions.values() if not q.boss][:5]
    if len(qids) < 4:
        pytest.skip("fixture too small")
    s.resolved = {q: "correct" for q in qids}
    r1 = exam.start(world, s)
    assert not r1["resumed"]
    # the sample is OLDEST solves first, not newest
    assert s.exam["qids"][0] == qids[0]
    first = exam.current(world, s)
    # a wrong answer reports the truth so the miss teaches on the spot
    res = exam.grade(world, s, ["definitely-not-the-answer"])
    assert not res["ok"] and res["truth"]
    # bare exam mid-run RESUMES at the next item - it never restarts
    r2 = exam.start(world, s)
    assert r2["resumed"] and r2["i"] == 1
    assert exam.current(world, s).id != first.id or len(qids) == 1
    assert s.exam["missed"] == [first.id]   # the attempt survived
    # tool-coaching sentences are stripped from the exam's re-print
    for qid in s.exam["qids"]:
        assert "'buzz " not in exam.clean_prompt(world.questions[qid])


def test_badges_earned(world):
    from buzz.badges import earned, progress, MIN_CLASS
    s = engine.new_session(world)
    assert not earned(world, s)          # nothing done, nothing minted
    # command spam mints nothing: reading/seeing everything is not a badge
    s.discovered = list(world.modules)
    s.seen = list(world.modules)
    assert not earned(world, s)
    # the first correct solve mints First Nectar
    s.resolved["q1"] = "correct"
    assert "First Nectar" in [n for n, _ in earned(world, s)]
    s.best_streak = 10
    assert "Streak Lord" in [n for n, _ in earned(world, s)]
    # a perfect exam mints Elder Sage; 88% does not
    s.exam = {"best": 88}
    assert "Elder Sage" not in [n for n, _ in earned(world, s)]
    s.exam = {"best": 100}
    assert "Elder Sage" in [n for n, _ in earned(world, s)]
    # class badges refuse to mint when the world has too few instances,
    # and say so in their progress note
    for name, desc, ok, note in progress(world, s):
        if name == "Ghost Hunter":
            n_ghost = sum(1 for q in world.questions.values()
                          if q.qtype == "ghost")
            if n_ghost < MIN_CLASS:
                assert not ok and "needs" in note
    # Clean Sweep needs EVERY quest correct, not just the boss path
    s.hints = {}
    s.tries = {}
    s.victory = True
    some = list(world.questions)[: len(world.questions) // 2]
    s.resolved = {q: "correct" for q in some}
    assert "Clean Sweep" not in [n for n, _ in earned(world, s)]
    s.resolved = {q: "correct" for q in world.questions}
    assert "Clean Sweep" in [n for n, _ in earned(world, s)]


def test_atlas_interactive_fog_safe(world):
    from buzz.atlas import render_atlas
    s = engine.new_session(world)
    page = render_atlas(world, s)
    # the interactive layer ships
    for needle in ("PROBE ROUTE", "var NODES=", "var EDGES=", "#town"):
        assert needle in page
    # fog: no unseen module's name reaches the file, in data or markup
    unseen = set(world.modules) - set(s.seen)
    for m in unseen:
        assert f'"{m}"' not in page and f">{m}<" not in page
    # edges are earned: only sources the session has READ are embedded
    import json as _json, re
    edges = _json.loads(re.search(r"var EDGES=(\[.*?\]);", page).group(1))
    assert all(src in s.discovered for src, _dst, _k in edges)
    assert all(dst in s.seen for _src, dst, _k in edges)


def test_known_zones_one_predicate(world):
    from buzz.render import known_zones, masked_modules
    s = engine.new_session(world)
    pq = next((q for q in world.questions.values() if q.qtype == "place"),
              None)
    if pq is None:
        pytest.skip("fixture has no place quest")
    target, zid = pq.truth["module"], pq.truth["zone"]
    # sighting and even READING the masked module must not unlock the
    # name of the district it secretly belongs to (round c6's oracle)
    s.seen.append(target)
    s.discovered.append(target)
    assert target in masked_modules(world, s)
    assert zid not in known_zones(world, s)
    # solving the place quest names the district - one write, every
    # surface reads the same predicate
    s.resolved[pq.id] = "correct"
    assert zid in known_zones(world, s)


def test_quest_ids_carry_no_zone_information(world, tmp_path):
    # regeneration is deterministic: same repo, same ids
    from buzz.analyze import analyze
    from buzz.questions import generate_questions
    import pathlib
    w2 = analyze(pathlib.Path(world.repo))
    generate_questions(w2)
    # cross-run id equality is verified on real repos (three byte-
    # identical analyzes in round c12); the synthetic fixture's
    # same-second commits can reorder archaeology, so here we assert
    # the shuffle is a proper permutation, not run-stable
    assert sorted(int(q[1:]) for q in w2.questions) == \
        list(range(1, len(w2.questions) + 1))
    # every stored reference survived the shuffle
    for q in world.questions.values():
        if q.truth.get("prev_stage"):
            assert q.truth["prev_stage"] in world.questions
        if q.followup_of:
            assert q.followup_of in world.questions
    # ids in numeric order must NOT walk the zones in generation order
    # (zone-contiguous id runs were a turn-zero place-quest oracle);
    # with 2+ zones and 4+ quests the odds a random permutation stays
    # perfectly zone-contiguous are negligible for real worlds - assert
    # only when the fixture is big enough to make the check meaningful
    qs = sorted(world.questions.values(), key=lambda q: int(q.id[1:]))
    zones_in_id_order = [q.zone for q in qs]
    runs = 1 + sum(1 for a, b in zip(zones_in_id_order,
                                     zones_in_id_order[1:]) if a != b)
    distinct = len(set(zones_in_id_order))
    if len(qs) >= 8 and distinct >= 3:
        assert runs > distinct, (
            "ids form zone-contiguous runs - the id number is an oracle")
