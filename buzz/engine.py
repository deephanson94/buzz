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


def scout(world: World, s: Session, zone_name: str) -> int:
    """Send a scout over a district: reveals the NAMES of its modules (they
    become seen/travelable) but none of their edges - you still have to fly
    there and read the files. Free, like all exploration."""
    zid = resolve_zone(world, zone_name)
    added = 0
    for m in world.zones[zid].members:
        if m not in s.seen:
            s.seen.append(m)
            added += 1
    return added


def peek(world: World, s: Session, name: str) -> str:
    """Remote look: read a module you can see on the map without flying
    there. Reading is discovering - it counts, it just doesn't move you."""
    m = resolve_module(world, name)
    if m != s.here and m not in s.seen:
        raise GameError(f"{m} is still under fog - you have not seen it yet")
    prev = s.here
    _arrive(world, s, m)
    s.here = prev
    return m


def zone_edges(world: World, zid: str) -> list[str]:
    """The induced top-level import subgraph of one district, with in-district
    in-degree tallies - the audit trail behind hub/region/gate quests."""
    members = set(world.zones[zid].members)
    edges = [e for e in world.edges
             if e.kind == TOP and e.src in members and e.dst in members]
    lines = [f"top-level import edges inside {world.zones[zid].name} ({zid}):"]
    for e in sorted(edges, key=lambda e: (e.src, e.dst)):
        lines.append(f"  {e.src} -> {e.dst}")
    if not edges:
        lines.append("  (none - this district is held together by git "
                     "history and convention, not imports)")
    cross = [e for e in world.edges
             if e.kind == TOP and (e.src in members) != (e.dst in members)]
    if cross:
        lines.append("cross-district edges touching it (answers often route "
                     "through these):")
        zone_of = {m: world.modules[m].zone for m in world.modules}
        for e in sorted(cross, key=lambda e: (e.src, e.dst)):
            if e.src in members:
                lines.append(f"  {e.src} -> {e.dst} [{zone_of.get(e.dst, '?')}]")
            else:
                lines.append(f"  {e.src} [{zone_of.get(e.src, '?')}] -> {e.dst}")
    lines.append("(the tallying is on you)")
    return lines


def who(world: World, name: str) -> list[str]:
    """Reverse imports of one module across the WHOLE hive, by edge kind -
    the fan-in view that per-module look can't give you."""
    m = resolve_module(world, name)
    kinds = {TOP: "top-level", LAZY: "function-level (sealed)",
             TYPE: "TYPE_CHECKING-only"}
    ins = world.in_edges(m)
    lines = [f"who imports {m} (whole hive, direct edges only):"]
    for e in sorted(ins, key=lambda e: (e.kind, e.src)):
        z = world.modules[e.src].zone
        lines.append(f"  {e.src} [{z}]  ({kinds[e.kind]})")
    if not ins:
        lines.append("  nobody - it is a root or an entry point")
    lines.append("(transitive importers are not listed - chains are yours to walk)")
    return lines


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


RETRY_COST = 0.3      # XP fraction forfeited per extra region attempt
MAX_RETRIES = 2


def _award(s: Session, q: Question, frac: float) -> int:
    hint_frac = HINT_COST.get(s.hints.get(q.id, 0), 0.0)
    retry_frac = min(1.0, RETRY_COST * s.tries.get(q.id, 0))
    gained = max(0, int(round(q.xp * frac * (1 - hint_frac) * (1 - retry_frac))))
    s.xp += gained
    s.max_xp += q.xp
    return gained


def _explain(world: World, q: Question) -> str:
    t = q.truth
    if q.qtype in ("walk", "cycle", "detour"):
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
    if q.qtype == "gate":
        return (f"{t['module']} is the gate: every top-level route from "
                f"{t['a']} to {t['b']} passes through it")
    if q.qtype == "ghost":
        return (f"{t['src']} secretly co-changes with {t['best']} "
                f"({t['shared']} shared commits, zero imports between them)")
    if q.qtype == "place":
        return f"{t['module']} belongs to {world.zones[t['zone']].name} ({t['zone']})"
    if q.qtype == "direction":
        return f"{t['src']} imports {t['dst']}"
    if q.qtype == "elder":
        return (f"{t['src']} entered history {t['born_src']}, long before "
                f"{t['dst']} ({t['born_dst']})")
    if q.qtype == "hotspot":
        return (f"{t['module']} is the hotspot: {t['commits']} commits of "
                f"rework, more than anything else in the district")
    return ""


def _check_walk(world: World, s: Session, q: Question, path: list[str]) -> tuple[bool, str]:
    t = q.truth
    if len(path) < 2:
        raise GameError("a walk needs at least two modules")
    if path[0] != t["src"] or path[-1] != t["dst"]:
        dst = t["dst"]
        if "." in dst and path[-1] == dst.rsplit(".", 1)[0]:
            return False, (f"so close - you reached {path[-1]}, but the quest "
                           f"asks for its submodule {dst}: one more hop")
        return False, f"the walk must start at {t['src']} and end at {t['dst']}"
    allowed = (TOP, TYPE) if TUNNEL not in s.abilities else (TOP, TYPE, LAZY)
    if q.qtype in ("cycle", "detour"):
        allowed = (TOP,)  # these proofs are about always-run imports
    avoid = t.get("avoid")
    if avoid and avoid in path:
        return False, f"your route touches {avoid} - the whole point is to go around it"

    def hop_ok(a: str, b: str) -> bool:
        if world.has_edge(a, b, kinds=allowed):
            return True
        # forgive a skipped parent-package hop: a -> pkg -> pkg.sub counts
        # as a -> pkg.sub (the __init__ hop is implicit when importing)
        parent = b.rsplit(".", 1)[0] if "." in b else None
        return bool(parent and parent != b
                    and world.has_edge(a, parent, kinds=allowed)
                    and world.has_edge(parent, b, kinds=allowed))

    for a, b in zip(path, path[1:]):
        if not hop_ok(a, b):
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
        if correct:
            pass
        elif s.tries.get(q.id, 0) < MAX_RETRIES:
            # a bad hop is feedback, not a verdict: patch the chain and
            # resubmit at a discount (typos shouldn't cost like ignorance)
            s.tries[q.id] = s.tries.get(q.id, 0) + 1
            left = MAX_RETRIES - s.tries[q.id]
            return {"q": q, "correct": False, "partial": False, "retry": True,
                    "gained": 0, "followup": None, "explain": "",
                    "note": (f"{note}. Fix your route and resubmit "
                             f"(-{int(RETRY_COST*100)}% XP per retry, "
                             f"{left} left after this one)")}
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
        jac = 1.0
        if picks == truth_set:
            correct = True
        else:
            inter = picks & truth_set
            union = picks | truth_set
            jac = len(inter) / len(union) if union else 0
            # near miss + retries left: counts-only feedback, patch and
            # resubmit at an XP discount - one missed hop should not erase
            # an otherwise-correct reading of the graph
            if jac >= 0.4 and s.tries.get(q.id, 0) < MAX_RETRIES:
                s.tries[q.id] = s.tries.get(q.id, 0) + 1
                zone_members = set(world.zones[q.zone].members)
                crosses = any(
                    any(step not in zone_members for step in t.get("why", {}).get(m, []))
                    for m in (truth_set - picks))
                dir_hint = (" Hint: at least one missing module only connects "
                            "through another district." if crosses else "")
                return {"q": q, "correct": False, "partial": False,
                        "retry": True, "gained": 0, "followup": None,
                        "explain": "",
                        "note": (f"{len(inter)} of your picks are right, "
                                 f"{len(picks - truth_set)} are wrong, and "
                                 f"{len(truth_set - picks)} module(s) are "
                                 f"missing. Patch your selection and resubmit "
                                 f"(-{int(RETRY_COST*100)}% XP per retry, "
                                 f"{MAX_RETRIES - s.tries[q.id]} retr"
                                 f"{'y' if MAX_RETRIES - s.tries[q.id] == 1 else 'ies'}"
                                 f" left after this one).{dir_hint}")}
            missed = sorted(truth_set - picks)
            extra = sorted(picks - truth_set)
            bits = []
            if missed:
                bits.append(f"missed: {', '.join(missed)}")
            if extra:
                bits.append(f"safe (not affected): {', '.join(extra)}")
            note = "; ".join(bits)
            if jac >= 0.4:
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
        ok_set = set(t.get("accepted") or [t["module"]])
        correct = m in ok_set
        if not correct:
            note = f"{m} is not the one"
    else:
        raise GameError(f"unknown verb {q.verb}")

    result = {"q": q, "correct": correct, "partial": partial, "note": note,
              "explain": _explain(world, q), "gained": 0, "followup": None}
    if correct and q.verb == "walk":
        # confirm THEIR chain, not a different valid one - the game agreeing
        # with you should never read like a correction
        result["explain"] = "your chain checks out: " + " -> ".join(
            resolve_module(world, a) for a in args)

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
    for key in ("src", "dst", "target", "module", "best", "a", "b"):
        if key in t:
            out.append(t[key])
    out.extend(t.get("example", []))
    out.extend(t.get("region", []))
    out.extend(t.get("accepted", []) if isinstance(t.get("accepted"), list) else [])
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
    if boss_down and not any(l.startswith("boss ") for l in s.log):
        remaining = [z for z in world.zones
                     if z not in s.cleared
                     and any(x.zone == z and not x.boss
                             for x in world.questions.values())]
        beaten = all(s.resolved.get(x.id) == "correct" for x in boss_qs)
        s.log.append("boss defeated" if beaten else
                     "boss lair emptied - but the boss eluded a true defeat "
                     "(some answers had to be revealed)")
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
        if q.qtype in ("walk", "cycle", "detour"):
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
        elif q.qtype == "gate":
            text = (f"walk from {t['a']} toward {t['b']} and watch which "
                    f"module every route funnels through")
        elif q.qtype == "elder":
            text = f"one of the two predates {t['born_dst'][:4]}"
        elif q.qtype == "hotspot":
            text = f"it has taken {t['commits']} commits of rework"
        else:
            text = f"read {t['src']}'s imports"
        s.hints[q.id] = 1
        return 1, text + "  (XP for this quest now -20%)"
    if level == 2:
        if q.qtype in ("walk", "cycle", "detour"):
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
        elif q.qtype == "gate":
            zid = world.modules[t["module"]].zone
            top = sorted(world.zones[zid].members,
                         key=lambda m: -world.modules[m].betweenness)
            cands = [m for m in top
                     if m not in t.get("accepted", []) and m != t["module"]][:2]
            text = "it is one of: " + ", ".join(sorted(cands + [t["module"]]))
        elif q.qtype == "elder":
            text = (f"for the record, one of them entered history "
                    f"{t['born_src']} - decide who that sounds like")
        elif q.qtype == "hotspot":
            zid = world.modules[t["module"]].zone
            top = sorted(world.zones[zid].members,
                         key=lambda m: -world.modules[m].commits)
            cands = [m for m in top if m != t["module"]][:2]
            text = "it is one of: " + ", ".join(sorted(cands + [t["module"]]))
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


def rank(world: World, s: Session) -> str:
    """Monotonic: fraction of the world's TOTAL quest XP earned. Earning
    more can never demote you (accuracy is shown separately in status)."""
    total = sum(q.xp for q in world.questions.values()) or 1
    r = s.xp / total
    for cut, name in [(0.8, "Queen Bee"), (0.6, "Royal Guard"), (0.4, "Forager"),
                      (0.2, "Worker"), (0.0001, "Larva")]:
        if r >= cut:
            return name
    return "Egg"


LESSONS = {
    "walk": "transitive top-level chains carry breakage across modules that never name each other",
    "cycle": "a function-level import is often a deliberate cycle-breaker, not sloppiness",
    "region": "blast radius = reverse reachability over always-run imports only; chains ignore zone boundaries",
    "ghost": "git co-change reveals coupling the import graph cannot see",
    "place": "a module's district is defined by where its import neighbors live",
    "hub": "in-degree inside a cluster tells you which wall is load-bearing",
    "gate": "high-betweenness modules are chokepoints: sever one and whole regions go dark",
    "detour": "redundant import paths are resilience - know the second road before you close the first",
    "elder": "file age explains architecture: the oldest modules shaped every API that came after",
    "hotspot": "churn concentrates: the file that changed most will change next - review it hardest",
    "direction": "always check which side of an import edge a module is on before touching it",
}


def reveal_prompt_modules(world: World, s: Session, q: Question) -> None:
    """Reading a quest marks the modules its text NAMES as seen (scout
    reports) - never the answer set itself."""
    t = q.truth
    named: list = []
    if q.qtype in ("walk", "cycle", "direction", "detour"):
        named = [t.get("src"), t.get("dst"), t.get("avoid")]
    elif q.qtype == "region":
        named = [t.get("target")] + world.zones[q.zone].members
    elif q.qtype == "ghost":
        named = [t.get("src")] + t.get("suspects", [])
    elif q.qtype == "place":
        named = [t.get("module")]
    elif q.qtype == "gate":
        named = [t.get("a"), t.get("b")]
    # hub names nothing - pointing at it IS the quest
    for m in named:
        if m in world.modules and m not in s.seen:
            s.seen.append(m)
