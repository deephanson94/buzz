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
    if not (clearable <= set(s.cleared)):
        assert not s.victory, "boss down must not end the game while zones remain"
    for q in world.questions.values():
        s.resolved[q.id] = "correct"
    engine._post_answer(world, s, remaining[0])
    assert s.victory
