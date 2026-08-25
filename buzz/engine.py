"""Game engine: fog-of-war, movement, answer verification, economy.

Rules it enforces (from the design doc):
- XP only from answers; walking reveals but never pays (grinding impossible).
- Wrong answers reveal the truth and spawn a follow-up; progress is never lost.
- Lazy-import edges are sealed until the tunnel-vision ability unlocks.
- Boss questions open after clearing 2 zones.
"""
from __future__ import annotations

from .model import World, Session, Question, TOP, LAZY, TYPE
from .questions import make_followup

TUNNEL = "tunnel-vision"
BOSS_ZONES_NEEDED = 2
HINT_COST = {1: 0.2, 2: 0.5}   # fraction of question XP forfeited


class GameError(Exception):
    """Player mistake that should NOT consume an attempt (typo, bad syntax)."""


def new_session(world: World) -> Session:
    s = Session(here=world.start)
    _arrive(world, s, world.start)
    return s


def _arrive(world: World, s: Session, node: str) -> None:
    s.here = node
    if node not in s.discovered:
        s.discovered.append(node)
    if node not in s.seen:
        s.seen.append(node)
    # reading a file shows you what it imports: out-edge targets become seen
    for e in world.out_edges(node):
        if e.dst not in s.seen:
            s.seen.append(e.dst)


def resolve_module(world: World, name: str) -> str:
    """Accept exact short names, case-insensitive, or unique suffix."""
    if name in world.modules:
        return name
    low = name.lower().lstrip("_")
    exact = [m for m in world.modules if m.lower().lstrip("_") == low]
    if len(exact) == 1:
        return exact[0]
    sufx = [m for m in world.modules
            if m.lower().split(".")[-1].lstrip("_") == low]
    if len(sufx) == 1:
        return sufx[0]
    if len(exact) > 1 or len(sufx) > 1:
        raise GameError(f"'{name}' is ambiguous: {', '.join(exact or sufx)}")
    raise GameError(f"no module called '{name}' in this hive")


def resolve_zone(world: World, name: str) -> str:
    if name in world.zones:
        return name
    low = name.lower()
    hits = [z.id for z in world.zones.values()
            if z.name.lower() == low or low in z.name.lower()]
    if len(hits) == 1:
        return hits[0]
    raise GameError(f"no zone called '{name}'")


def can_travel(world: World, s: Session, dst: str) -> tuple[bool, str]:
    if dst == s.here:
        return False, "you are already there"
    if dst in s.discovered:
        return True, "fast-travel"
    edge = next((e for e in world.out_edges(s.here) if e.dst == dst), None)
    if edge:
        if edge.kind == LAZY and TUNNEL not in s.abilities:
            return False, (f"the tunnel from {s.here} to {dst} is SEALED - a "
                           f"function-level import. Solve a cycle quest to unlock "
                           f"tunnel-vision.")
        return True, "walk"
    if dst in s.seen:
        # seen on the map but not adjacent and not yet visited
        return False, (f"you can see {dst} on the map but there is no import "
                       f"edge from {s.here} to it. Travel via a module that "
                       f"imports it, or fast-travel once you have visited it.")
    return False, f"{dst} is still under fog - you have not seen it yet"


def go(world: World, s: Session, name: str) -> str:
    dst = resolve_module(world, name)
    ok, how = can_travel(world, s, dst)
    if not ok:
        raise GameError(how)
    _arrive(world, s, dst)
    return how


def get_question(world: World, s: Session, qid: str) -> Question:
    if qid in world.questions:
        return world.questions[qid]
    if qid in s.followups:
        return Question(**s.followups[qid])
    raise GameError(f"no quest '{qid}'")


def question_open(world: World, s: Session, q: Question) -> tuple[bool, str]:
    if q.id in s.resolved:
        return False, "already resolved"
    if q.boss and not s.boss_open:
        return False, f"boss quests unlock after clearing {BOSS_ZONES_NEEDED} zones"
    return True, ""


def _award(s: Session, q: Question, frac: float) -> int:
    hint_frac = HINT_COST.get(s.hints.get(q.id, 0), 0.0)
    gained = max(0, int(round(q.xp * frac * (1 - hint_frac))))
    s.xp += gained
    s.max_xp += q.xp
    return gained


def _explain(world: World, q: Question) -> str:
    t = q.truth
    if q.qtype in ("walk", "cycle"):
        return f"one real chain: {' -> '.join(t['example'])}"
    if q.qtype == "region":
        return f"the blast radius of {t['target']} is: {', '.join(t['region'])}"
    if q.qtype == "ghost":
        return (f"{t['src']} secretly co-changes with {t['best']} "
                f"({t['shared']} shared commits, zero imports between them)")
    if q.qtype == "place":
        return f"{t['module']} belongs to {world.zones[t['zone']].name} ({t['zone']})"
    if q.qtype == "direction":
        return f"{t['src']} imports {t['dst']}"
    return ""


def _check_walk(world: World, s: Session, q: Question, path: list[str]) -> tuple[bool, str]:
    t = q.truth
    if len(path) < 2:
        raise GameError("a walk needs at least two modules")
    if path[0] != t["src"] or path[-1] != t["dst"]:
        return False, f"the walk must start at {t['src']} and end at {t['dst']}"
    allowed = (TOP, TYPE) if TUNNEL not in s.abilities else (TOP, TYPE, LAZY)
    if q.qtype == "cycle":
        allowed = (TOP,)  # the cycle proof is about always-run imports
    for a, b in zip(path, path[1:]):
        if not world.has_edge(a, b, kinds=allowed):
            return False, f"there is no import from {a} to {b} at that step"
    return True, ""


def answer(world: World, s: Session, qid: str, verb: str, args: list[str]) -> dict:
    """Returns {correct, partial, gained, explain, followup}."""
    q = get_question(world, s, qid)
    ok, why = question_open(world, s, q)
    if not ok:
        raise GameError(why)
    if verb != q.verb:
        raise GameError(f"quest {q.id} expects 'answer {q.id} {q.verb} ...'")

    t = q.truth
    correct, partial, note = False, False, ""

    if q.verb == "walk":
        path = [resolve_module(world, a) for a in args]
        correct, note = _check_walk(world, s, q, path)
    elif q.verb == "edge":
        if len(args) != 2:
            raise GameError("answer edge <importer> <imported>")
        a, b = (resolve_module(world, x) for x in args)
        if q.qtype == "ghost":
            pair_ok = (a == t["src"] and b in t["accepted"]) or \
                      (b == t["src"] and a in t["accepted"])
            correct = pair_ok
            if not correct:
                note = "that pair does not co-change unusually often"
        else:
            correct = (a == t["src"] and b == t["dst"])
            if not correct and (a == t["dst"] and b == t["src"]):
                note = "right pair, wrong direction!"
            elif not correct:
                note = "no such import edge"
    elif q.verb == "region":
        picks = {resolve_module(world, x) for x in args}
        truth_set = set(t["region"])
        if picks == truth_set:
            correct = True
        else:
            inter = picks & truth_set
            union = picks | truth_set
            jac = len(inter) / len(union) if union else 0
            missed = sorted(truth_set - picks)
            extra = sorted(picks - truth_set)
            bits = []
            if missed:
                bits.append(f"missed: {', '.join(missed)}")
            if extra:
                bits.append(f"safe (not affected): {', '.join(extra)}")
            note = "; ".join(bits)
            if jac >= 0.5:
                partial = True
    elif q.verb == "place":
        z = resolve_zone(world, " ".join(args))
        correct = z == t["zone"]
        if not correct:
            note = f"{world.zones[z].name} is not where it lives"
    else:
        raise GameError(f"unknown verb {q.verb}")

    result = {"q": q, "correct": correct, "partial": partial, "note": note,
              "explain": _explain(world, q), "gained": 0, "followup": None}

    if correct:
        s.resolved[q.id] = "correct"
        result["gained"] = _award(s, q, 1.0)
    elif partial:
        s.resolved[q.id] = "partial"
        result["gained"] = _award(s, q, 0.5)
    else:
        s.resolved[q.id] = "revealed"
        s.max_xp += q.xp
        if q.followup_of is None and q.id not in s.followups:
            fu = make_followup(world, q, len(s.followups))
            if fu:
                s.followups[fu["id"]] = fu
                result["followup"] = fu["id"]

    # reveal what the question was about (answers teach the map)
    for m in _modules_in_truth(q):
        if m in world.modules and m not in s.seen:
            s.seen.append(m)

    _post_answer(world, s, q)
    return result


def _modules_in_truth(q: Question) -> list[str]:
    t = q.truth
    out = []
    for key in ("src", "dst", "target", "module", "best"):
        if key in t:
            out.append(t[key])
    out.extend(t.get("example", []))
    out.extend(t.get("region", []))
    return out


def _post_answer(world: World, s: Session, q: Question) -> None:
    if q.qtype == "cycle" and TUNNEL not in s.abilities:
        s.abilities.append(TUNNEL)
        s.log.append("ability unlocked: tunnel-vision")
    # zone clearing: every non-boss static quest in the zone resolved
    for z in world.zones.values():
        if z.id in s.cleared:
            continue
        zq = [x for x in world.questions.values() if x.zone == z.id and not x.boss]
        if zq and all(x.id in s.resolved for x in zq):
            s.cleared.append(z.id)
            s.log.append(f"zone cleared: {z.name}")
    if not s.boss_open and len(s.cleared) >= BOSS_ZONES_NEEDED:
        s.boss_open = True
        s.log.append("the boss lair is open")
    boss_qs = [x for x in world.questions.values() if x.boss]
    if boss_qs and all(x.id in s.resolved for x in boss_qs) and not s.victory:
        s.victory = True
        s.log.append("victory: the hive is mapped")


def hint(world: World, s: Session, qid: str) -> tuple[int, str]:
    """Oracle hint ladder. Level 1 (-20% XP): orientation fact.
    Level 2 (-50%): one concrete element. Level 3: full reveal, 0 XP."""
    q = get_question(world, s, qid)
    ok, why = question_open(world, s, q)
    if not ok:
        raise GameError(why)
    level = s.hints.get(q.id, 0) + 1
    t = q.truth
    if level == 1:
        if q.qtype in ("walk", "cycle"):
            text = f"the shortest chain has {len(t['example']) - 1} hops"
        elif q.qtype == "region":
            text = f"the blast radius contains {len(t['region'])} modules"
        elif q.qtype == "ghost":
            text = f"the partner lives in {world.zones[world.modules[t['best']].zone].name}"
        elif q.qtype == "place":
            nb = t["module"]
            text = f"look at which zone most of {nb}'s neighbors are in"
        else:
            text = f"read {t['src']}'s imports"
        s.hints[q.id] = 1
        return 1, text + "  (XP for this quest now -20%)"
    if level == 2:
        if q.qtype in ("walk", "cycle"):
            text = f"the second module in one valid chain is {t['example'][1]}"
        elif q.qtype == "region":
            text = f"one member of the blast radius: {t['region'][0]}"
        elif q.qtype == "ghost":
            text = f"the partner's name starts with '{t['best'][0]}'"
        elif q.qtype == "place":
            text = f"its highest-pagerank neighbor sits in {world.zones[t['zone']].name}"
        else:
            text = f"{t['src']} is the importer"
        s.hints[q.id] = 2
        return 2, text + "  (XP for this quest now -50%)"
    # level 3: reveal, resolve for 0 XP, no followup (the oracle already taught it)
    s.hints[q.id] = 3
    s.resolved[q.id] = "revealed"
    s.max_xp += q.xp
    text = _explain(world, q)
    for m in _modules_in_truth(q):
        if m in world.modules and m not in s.seen:
            s.seen.append(m)
    _post_answer(world, s, q)
    return 3, "the oracle reveals everything: " + text


def coverage(world: World, s: Session) -> tuple[int, int]:
    return len(s.discovered), len(world.modules)


def rank(s: Session) -> str:
    if s.max_xp == 0:
        return "Egg"
    r = s.xp / s.max_xp
    for cut, name in [(0.9, "Queen Bee"), (0.75, "Royal Guard"), (0.5, "Forager"),
                      (0.25, "Worker"), (0.0, "Larva")]:
        if r >= cut:
            return name
    return "Larva"
