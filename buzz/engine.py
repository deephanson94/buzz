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
    # reading a file shows you what it imports: out-edge targets become
    # seen - except sealed tunnels, whose destination stays ??? until the
    # tunnel-vision ability is unlocked
    for e in world.out_edges(node):
        if e.kind == LAZY and TUNNEL not in s.abilities:
            continue
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
        # seen on the map but never visited and not adjacent: a scout can
        # still fly there - the fog only hides what no one has named yet
        return True, "scout-flight"
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
        return False, f"boss quests unlock after clearing {boss_needed(world)} zones"
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
        why = t.get("why")
        if why:  # show the witness chain behind every ruling
            parts = [f"{m} ({' -> '.join(why[m])})" for m in t["region"]]
            return f"the blast radius of {t['target']}: " + "; ".join(parts)
        return f"the blast radius of {t['target']} is: {', '.join(t['region'])}"
    if q.qtype == "hub":
        return (f"{t['module']} is the load-bearing wall - imported top-level "
                f"by {t['count']} modules of its own district")
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
    elif q.verb == "point":
        if len(args) != 1:
            raise GameError("answer point <module>")
        m = resolve_module(world, args[0])
        correct = m == t["module"]
        if not correct:
            note = f"{m} is not the one"
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


def boss_needed(world: World) -> int:
    """Zones to clear before the boss opens - capped by how many zones can
    actually be cleared (small repos may have quest-less zones)."""
    clearable = sum(
        1 for z in world.zones
        if any(q.zone == z and not q.boss for q in world.questions.values())
    )
    return min(BOSS_ZONES_NEEDED, clearable)


def _post_answer(world: World, s: Session, q: Question) -> None:
    if q.qtype == "cycle" and TUNNEL not in s.abilities:
        s.abilities.append(TUNNEL)
        s.log.append("ability unlocked: tunnel-vision")
        # retroactively reveal every sealed destination already walked past
        for node in s.discovered:
            for e in world.out_edges(node):
                if e.dst not in s.seen:
                    s.seen.append(e.dst)
    # zone clearing: every non-boss static quest in the zone resolved
    for z in world.zones.values():
        if z.id in s.cleared:
            continue
        zq = [x for x in world.questions.values() if x.zone == z.id and not x.boss]
        if zq and all(x.id in s.resolved for x in zq):
            s.cleared.append(z.id)
            s.log.append(f"zone cleared: {z.name}")
    if not s.boss_open and len(s.cleared) >= boss_needed(world):
        s.boss_open = True
        s.log.append("the boss lair is open")
    # Two-stage ending: felling the boss is a big moment, not the end.
    # Victory = boss down AND every clearable zone cleared (the hive mapped).
    boss_qs = [x for x in world.questions.values() if x.boss]
    boss_down = bool(boss_qs) and all(x.id in s.resolved for x in boss_qs)
    if boss_down and "boss defeated" not in s.log:
        remaining = [z for z in world.zones
                     if z not in s.cleared
                     and any(x.zone == z and not x.boss
                             for x in world.questions.values())]
        s.log.append("boss defeated")
        if remaining:
            s.log.append(f"the hive's heart is yours, but {len(remaining)} "
                         f"district(s) remain unmapped - the campaign continues")
    clearable = {z for z in world.zones
                 if any(x.zone == z and not x.boss
                        for x in world.questions.values())}
    all_cleared = clearable <= set(s.cleared)
    if (boss_down or not boss_qs) and all_cleared and world.questions and not s.victory:
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
        elif q.qtype == "hub":
            text = f"it is imported by {t['count']} of its own district"
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
            text = ("it is one of: " + ", ".join(_ghost_candidates(world, t))
                    + f"  (probe them: buzz probe {t['src']} <candidate>)")
        elif q.qtype == "place":
            text = f"its highest-pagerank neighbor sits in {world.zones[t['zone']].name}"
        elif q.qtype == "hub":
            zid = world.modules[t["module"]].zone
            top = sorted(world.zones[zid].members,
                         key=lambda m: -world.modules[m].in_degree)
            cands = [m for m in top if m != t["module"]][:2] + [t["module"]]
            text = "it is one of: " + ", ".join(sorted(cands))
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


def _ghost_candidates(world: World, t: dict) -> list[str]:
    """Answer + two look-alike decoys (same-zone, high churn, no edge)."""
    x, best = t["src"], t["best"]
    zid = world.modules[best].zone
    decoys = [m for m in sorted(world.zones[zid].members,
                                key=lambda m: -world.modules[m].commits)
              if m not in (x, best) and m not in t["accepted"]][:2]
    return sorted([best] + decoys)


def probe(world: World, a: str, b: str) -> str:
    """Free investigative tool: how are two modules actually related?
    Shows import edges (with kind) and the co-change count the game itself
    uses (focused commits only: no merges, no >15-file sweeps)."""
    lines = []
    kinds = {TOP: "top-level import", LAZY: "function-level import (sealed tunnel)",
             TYPE: "TYPE_CHECKING-only import (never runs)"}
    found = False
    for e in world.edges:
        if (e.src, e.dst) in ((a, b), (b, a)):
            lines.append(f"import edge: {e.src} -> {e.dst}  [{kinds[e.kind]}]")
            found = True
    if not found:
        lines.append(f"no import statement of any kind connects {a} and {b}")
    shared = next((n for o, n in world.cochange.get(a, []) if o == b), None)
    if shared is None:
        shared = next((n for o, n in world.cochange.get(b, []) if o == a), None)
    if shared:
        lines.append(f"co-change: {shared} shared focused commits "
                     f"(merges and >15-file sweeps excluded)")
    else:
        lines.append("co-change: nothing notable on record (not in either "
                     "module's top-10 co-change partners)")
    return "\n".join(lines)


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
