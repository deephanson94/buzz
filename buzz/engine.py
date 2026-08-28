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
HINT_COST = {1: 0.2, 2: 0.5, 3: 1.0}   # fraction of question XP forfeited


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
    """Accept exact short names, case-insensitive, unique suffix, or the
    fully-qualified form (leading package segments the map strips)."""
    if name in world.modules:
        return name
    # peel leading qualifiers: `peft.tuners.lora.config` -> `tuners.lora.config`
    probe = name
    while "." in probe:
        probe = probe.split(".", 1)[1]
        if probe in world.modules:
            return probe
    low = name.lower().lstrip("_")
    exact = [m for m in world.modules if m.lower().lstrip("_") == low]
    if len(exact) == 1:
        return exact[0]
    sufx = [m for m in world.modules
            if m.lower().split(".")[-1].lstrip("_") == low]
    if len(sufx) == 1:
        return sufx[0]
    if not sufx:  # dotted tail: 'trunkline.backend' names transports.trunkline.backend
        sufx = [m for m in world.modules if m.lower().endswith("." + low)]
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
    if edge and not (edge.kind == LAZY and TUNNEL not in s.abilities):
        return True, "walk"
    if dst in s.seen:
        # seen on the map: a scout can always fly there, even when the
        # direct edge from here happens to be a sealed tunnel - the fog
        # only blocks what no one has named yet
        return True, "scout-flight"
    if edge:
        return False, (f"the tunnel from {s.here} to {dst} is SEALED - a "
                       f"function-level import hiding its destination. Solve "
                       f"a cycle quest to unlock tunnel-vision.")
    return False, f"{dst} is still under fog - you have not seen it yet"


def go(world: World, s: Session, name: str) -> str:
    dst = resolve_module(world, name)
    ok, how = can_travel(world, s, dst)
    if not ok:
        raise GameError(how)
    _arrive(world, s, dst)
    return how


def scout(world: World, s: Session, zone_name: str) -> list[str]:
    """Send a scout over a district: reveals the NAMES of its modules (they
    become seen/travelable) but none of their edges - you still have to fly
    there and read the files. Free, like all exploration. Returns the
    newly-revealed names so the caller can say what was gained."""
    zid = resolve_zone(world, zone_name)
    added = []
    for m in world.zones[zid].members:
        if m not in s.seen:
            s.seen.append(m)
            added.append(m)
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


def _name_seen(s: Session | None, *mods: str) -> None:
    """A module named by a tool's output is no longer fog: the player has
    been told it exists (playtesters rightly called the mismatch a bug)."""
    if s is None:
        return
    for m in mods:
        if m not in s.seen:
            s.seen.append(m)


def zone_edges(world: World, zid: str, s: Session | None = None) -> list[str]:
    """The induced top-level import subgraph of one district, with in-district
    in-degree tallies - the audit trail behind hub/region/gate quests. The
    tally is withheld while the district's own hub quest is open (it would
    BE the answer); everywhere else the game does the counting for you."""
    members = set(world.zones[zid].members)
    # a module under an OPEN place quest must not appear in a titled
    # district's member list - membership IS that quest's answer (round
    # WEBATLASc3 solved both place quests straight off this listing)
    from .render import masked_modules
    _masked = masked_modules(world, s) if s is not None else set()
    withheld = members & _masked
    members = members - withheld
    edges = [e for e in world.edges
             if e.kind == TOP and e.src in members and e.dst in members]
    zname = world.zones[zid].name
    if s is not None and not any(world.modules[m].zone == zid
                                 for m in s.discovered):
        zname = "??? (unexplored district)"
    lines = [f"top-level import edges inside {zname} ({zid}):"]
    for e in sorted(edges, key=lambda e: (e.src, e.dst)):
        _name_seen(s, e.src, e.dst)
        lines.append(f"  {e.src} -> {e.dst}")
    # NB: withheld edges get no note here - "N unplaced modules in THIS
    # district" is the same leak in a different coat
    if not edges:
        lines.append("  (none - this district is held together by git "
                     "history and convention, not imports)")
    cross = [e for e in world.edges
             if e.kind == TOP and (e.src in members) != (e.dst in members)]
    if cross:
        lines.append("cross-district edges touching it (all top-level; "
                     "answers often route through these):")
        from .render import masked_modules
        masked = masked_modules(world, s) if s is not None else set()
        zone_of = {m: ("???" if m in masked else world.modules[m].zone)
                   for m in world.modules}
        for e in sorted(cross, key=lambda e: (e.src, e.dst)):
            if e.src in members:
                lines.append(f"  {e.src} -> {e.dst} [{zone_of.get(e.dst, '?')}]")
            else:
                lines.append(f"  {e.src} [{zone_of.get(e.src, '?')}] -> {e.dst}")
    def quest_open(qt: str) -> bool:
        return s is not None and any(
            q.qtype == qt and q.zone == zid and q.id not in s.resolved
            for q in world.questions.values())

    if quest_open("hub"):
        lines.append("(in-degree tally withheld: this district's hub quest "
                     "is still open - that count IS the answer)")
    elif edges:
        indeg: dict[str, int] = {}
        for e in edges:
            indeg[e.dst] = indeg.get(e.dst, 0) + 1
        top = sorted(indeg.items(), key=lambda kv: (-kv[1], kv[0]))
        lines.append("in-district in-degree tally (placed modules only): "
                     + ", ".join(f"{m} ({n})" for m, n in top))
    if quest_open("hotspot"):
        lines.append("(churn ranking withheld: this district's hotspot quest "
                     "is still open - that ranking IS the answer)")
    else:
        churn = sorted(members, key=lambda m: -world.modules[m].commits)[:8]
        lines.append("churn ranking (commits): "
                     + ", ".join(f"{m} ({world.modules[m].commits})"
                                 for m in churn))
    return lines


def who(world: World, name: str, s: Session | None = None) -> list[str]:
    """Reverse imports of one module across the WHOLE hive, by edge kind -
    the fan-in view that per-module look can't give you."""
    m = resolve_module(world, name)
    kinds = {TOP: "top-level", LAZY: "function-level (sealed)",
             TYPE: "TYPE_CHECKING-only"}
    ins = world.in_edges(m)
    from .render import masked_modules
    masked = masked_modules(world, s) if s is not None else set()
    lines = [f"who imports {m} (whole hive, direct edges only):"]
    for e in sorted(ins, key=lambda e: (e.kind, e.src)):
        _name_seen(s, e.src)
        # the zone tag of a module under an open place quest IS that
        # quest's answer (round WEBATLAS: a scout solved q27 by copying
        # it out of this very listing)
        z = "???" if e.src in masked else world.modules[e.src].zone
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
    raise GameError(f"no quest '{qid}' - 'quests' lists this district's "
                    f"ids, 'quests all' the whole hive's")


def question_open(world: World, s: Session, q: Question) -> tuple[bool, str]:
    if q.id in s.resolved:
        return False, "already resolved"
    if q.boss and not s.boss_open:
        return False, f"boss quests unlock after clearing {boss_needed(world)} zones"
    prev = q.truth.get("prev_stage")
    if q.boss and prev and prev not in s.resolved:
        return False, (f"the boss reveals this stage only after {prev} "
                       f"falls - fight in order")
    return True, ""


RETRY_COST = 0.3      # XP fraction forfeited per extra region attempt
MAX_RETRIES = 2


STREAK_STEP = 0.05    # bonus per consecutive clean solve
STREAK_MAX = 0.50


def _award(s: Session, q: Question, frac: float) -> int:
    hint_frac = HINT_COST.get(s.hints.get(q.id, 0), 0.0)
    retry_frac = min(1.0, RETRY_COST * s.tries.get(q.id, 0))
    clean = frac >= 1.0 and hint_frac == 0 and not s.tries.get(q.id)
    # stakes without loss (design rule: progress is never removed): a clean
    # first-try solve extends a bonus streak; guessing merely breaks it
    streak_bonus = min(STREAK_MAX, STREAK_STEP * s.streak) if clean else 0.0
    gained = max(0, int(round(q.xp * frac * (1 - hint_frac) * (1 - retry_frac)
                              * (1 + streak_bonus))))
    s.xp += gained
    s.max_xp += q.xp
    # soft decay, not a hard reset: one slip halves the streak instead of
    # erasing it (a panel found hard resets punished guess-heavy quest
    # types out of proportion)
    s.streak = s.streak + 1 if clean else s.streak // 2
    s.best_streak = max(s.best_streak, s.streak)
    return gained


def _explain(world: World, q: Question) -> str:
    t = q.truth
    if q.qtype in ("walk", "cycle", "detour", "via"):
        return f"one real chain: {' -> '.join(t['example'])}"
    if q.qtype == "cut":
        sizes = ", ".join(f"{m} strands {n}" for m, n in
                          sorted(t["sizes"].items(), key=lambda kv: kv[1]))
        return (f"{t['module']} is the safe demolition - the reverse "
                f"reach of each candidate: {sizes}")
    if q.qtype == "refactor":
        if t.get("others"):
            rivals = "; ".join(f"cutting {a}'s leaves {n}"
                               for a, n in t["others"])
            return (f"severing {t['src']} -> {t['dst']} drops the radius "
                    f"from {t['base']} to {t['n_win']} - the biggest win "
                    f"({rivals})")
        return (f"severing {t['src']} -> {t['dst']} drops the radius from "
                f"{t['base']} to {t['n_win']}; cutting {t['loser']}'s import "
                f"leaves {t['n_lose']} - redundant routes keep carrying "
                f"the reach")
    if q.qtype == "order":
        her = t.get("herring")
        return (f"one valid order: {' -> '.join(t['example'])} - every "
                f"module lands after everything it imports"
                + (f" (and the {her[0]} -> {her[1]} import is "
                   f"function-level/type-only: it never runs, so it "
                   f"constrained nothing - the real dependency points the "
                   f"other way)" if her else ""))
    if q.qtype == "region":
        why = t.get("why")
        if why:  # show the witness chain behind every ruling
            parts = [f"{m} ({' -> '.join(why[m])})" for m in t["region"]]
            return f"the blast radius of {t['target']}: " + "; ".join(parts)
        return f"the blast radius of {t['target']} is: {', '.join(t['region'])}"
    if q.qtype == "hub":
        doc = world.modules[t["module"]].doc
        return (f"{t['module']} is the load-bearing wall - imported top-level "
                f"by {t['count']} modules of its own district"
                + (f' ("{doc}")' if doc else ""))
    if q.qtype == "gate":
        doc = world.modules[t["module"]].doc
        wit = t.get("witness")
        return (f"{t['module']} is the gate: every top-level route from "
                f"{t['a']} to {t['b']} passes through it"
                + (f" (one route: {' -> '.join(wit)})" if wit else "")
                + (f' ("{doc}")' if doc else ""))
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
    if q.qtype == "patch":
        return (f"the chronicle confirms: \"{t['subject']}\" ({t['date']}) "
                f"moved {t['anchor']} and {t['module']} in one commit"
                + (" - fresh history your pinned world never saw"
                   if t.get("aftershock") else ""))
    if q.qtype == "scar":
        return (f"{t['module']} bears the scar: \"{t['subject']}\" "
                f"({t['date']}) was rolled back")
    if q.qtype == "lore":
        doc = world.modules[t["module"]].doc
        return (f"{t['module']} is where it lives"
                + (f": {t['why']}" if t.get("why") else "")
                + (f' ("{doc}")' if doc else ""))
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
    via = t.get("via")
    if via and via not in path:
        return False, (f"a real chain, but the tour must pass THROUGH "
                       f"{via} - reroute")
    if t.get("flow"):  # journey: hops are function CALLS, not imports
        callset = {(c["src"], c["dst"]) for c in world.calls}
        for a, b in zip(path, path[1:]):
            if (a, b) not in callset:
                if world.has_edge(a, b):
                    return False, (f"{a} imports {b}, but no work flows "
                                   f"there - this journey needs hops where "
                                   f"{a} actually CALLS into {b}")
                return False, (f"no call from {a} into {b} at that step - "
                               f"you may be following IMPORT reachability, "
                               f"but a journey follows CALLS: 'buzz flow "
                               f"{a}' shows where its work actually goes")
        return True, ""

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
            if world.has_edge(a, b, kinds=(LAZY,)) and TUNNEL not in s.abilities:
                return False, (f"the import from {a} to {b} EXISTS but is a "
                               f"sealed tunnel - unlock tunnel-vision (a "
                               f"cycle quest) before that hop counts")
            if q.qtype in ("cycle", "detour") and world.has_edge(a, b):
                return False, (f"{a} -> {b} exists but not as an always-run "
                               f"top-level import - this proof needs "
                               f"top-level edges only")
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
        if not correct and "sealed tunnel - unlock" in note:
            # their code-reading was right; only the unlock mechanic was
            # unknown. Free do-over, not a penalized retry.
            return {"q": q, "correct": False, "partial": False, "retry": True,
                    "gained": 0, "followup": None, "explain": "",
                    "note": note + " (this attempt is free)"}
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
            raise GameError("answer <importer> <imported>")
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
                            "through another district - re-check the edges "
                            "of zones you have already left." if crosses
                            else "")
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
            raise GameError("answer <module>")
        m = resolve_module(world, args[0])
        ok_set = set(t.get("accepted") or [t["module"]])
        correct = m in ok_set
        if correct and m != t["module"]:
            # praise what they actually typed, never a different module
            note = (f"your pick {m} works too - the canonical answer is "
                    f"{t['module']}")
        if not correct:
            note = f"{m} is not the one"
    elif q.verb == "order":
        seq = [resolve_module(world, a) for a in args]
        need = list(t["set"])
        if sorted(seq) != sorted(need):
            raise GameError("list each of these exactly once: "
                            + ", ".join(need))
        posn = {m: i for i, m in enumerate(seq)}
        # (u, v) = u transitively imports v, so v must land before u
        bad = [(u, v) for u, v in t["pairs"] if posn[u] < posn[v]]
        if not bad:
            correct = True
        elif s.tries.get(q.id, 0) < MAX_RETRIES:
            s.tries[q.id] = s.tries.get(q.id, 0) + 1
            left = MAX_RETRIES - s.tries[q.id]
            return {"q": q, "correct": False, "partial": False, "retry": True,
                    "gained": 0, "followup": None, "explain": "",
                    "note": (f"{len(bad)} module(s) sit before something "
                             f"they (transitively) import. Reorder and "
                             f"resubmit (-{int(RETRY_COST*100)}% XP per "
                             f"retry, {left} left after this one)")}
        else:
            note = (f"{len(bad)} placement(s) rewrite a module before "
                    f"its dependency")
    else:
        raise GameError(f"unknown verb {q.verb}")

    result = {"q": q, "correct": correct, "partial": partial, "note": note,
              "explain": _explain(world, q), "gained": 0, "followup": None}
    if correct and q.verb == "walk":
        # confirm THEIR chain, not a different valid one - the game agreeing
        # with you should never read like a correction
        theirs = [resolve_module(world, a) for a in args]
        if q.truth.get("flow"):
            # a journey's reveal names the functions that carry the work
            legs = []
            for a, b in zip(theirs, theirs[1:]):
                rec = next((c for c in world.calls
                            if c["src"] == a and c["dst"] == b), None)
                fns = "/".join(rec["via"][:2]) if rec and rec.get("via") else "?"
                legs.append(f"{a} -({fns})->")
            result["explain"] = ("the work travels: " + " ".join(legs)
                                 + " " + theirs[-1])
        else:
            result["explain"] = "your chain checks out: " + " -> ".join(theirs)

    if correct:
        s.resolved[q.id] = "correct"
        result["gained"] = _award(s, q, 1.0)
    elif partial:
        s.resolved[q.id] = "partial"
        result["gained"] = _award(s, q, 0.5)
    else:
        s.resolved[q.id] = "revealed"
        s.max_xp += q.xp
        s.streak //= 2
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
    # a staged boss needs a beat between stages, not a silent unlock
    if q.boss and q.truth.get("stage"):
        nxt = next((x for x in world.questions.values()
                    if x.boss and x.truth.get("prev_stage") == q.id
                    and x.id not in s.resolved), None)
        if nxt:
            s.log.append(f"boss stage {q.truth['stage']} falls - stage "
                         f"{nxt.truth['stage']} unseals: buzz quest {nxt.id}")
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
        # place quests are district-independent: filed under their
        # answer, so they neither list in a district nor gate its clear
        zq = [x for x in world.questions.values()
              if x.zone == z.id and not x.boss and x.qtype != "place"]
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
    # Campaign arc: victory lands while the game is still fresh - the boss
    # plus a meaningful share of districts, not a full-clear grind. What
    # remains is explicit endgame, open for anyone who wants 100%.
    clearable = {z for z in world.zones
                 if any(x.zone == z and not x.boss
                        for x in world.questions.values())}
    need = min(3, len(clearable))
    if ((boss_down or not boss_qs) and len(s.cleared) >= need
            and world.questions and not s.victory):
        s.victory = True
        left = len(clearable) - len([z for z in s.cleared if z in clearable])
        if left > 0:
            s.log.append("campaign clear - the hive's heart is mapped")
            s.log.append(f"{left} endgame district(s) stay open - the hive "
                         f"remains yours, or take your wings to another repo")
        else:
            s.log.append("full clear - every district mapped")


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
        if q.qtype in ("walk", "cycle", "detour", "via", "journey"):
            text = f"one known chain has {len(t['example']) - 1} hops (shorter ones may exist)"
        elif q.qtype == "cut":
            text = (f"the safe pick strands only "
                    f"{min(t['sizes'].values())} module(s) - 'buzz who' "
                    f"each candidate and follow the fan-in upward")
        elif q.qtype == "refactor":
            text = (f"a cut only counts if no OTHER route re-creates the "
                    f"reach - trace which chains into {t['dst']} NEED "
                    f"their candidate edge")
        elif q.qtype == "order":
            text = ("start with the module that imports nothing else on "
                    "the list - 'buzz trace' pairs to test dependencies")
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
        elif q.qtype == "patch":
            text = (f"the companion lives in "
                    f"{world.zones[world.modules[t['module']].zone].name}")
        elif q.qtype == "scar":
            text = "git log is your shovel: search the subjects for 'Revert'"
        elif q.qtype == "lore":
            text = t.get("hint") or "open the suspects' files - skim their classes"
        else:
            text = f"read {t['src']}'s imports"
        s.hints[q.id] = 1
        return 1, text + "  (XP for this quest now -20%)"
    if level == 2:
        if q.qtype in ("walk", "cycle", "detour", "via", "journey"):
            text = f"the second module in one valid chain is {t['example'][1]}"
        elif q.qtype == "cut":
            worst = max(t["sizes"], key=lambda m: t["sizes"][m])
            text = (f"it is NOT {worst} - deleting that one strands "
                    f"{t['sizes'][worst]} modules")
        elif q.qtype == "refactor":
            text = (f"one candidate's removal leaves the radius at "
                    f"{t['n_lose']} of {t['base']} - barely a dent")
        elif q.qtype == "order":
            text = f"one valid order begins with {t['example'][0]}"
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
        elif q.qtype in ("patch", "scar", "lore"):
            text = f"the module's name starts with '{t['module'][0]}'"
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
    # level 3: the oracle tells all, but YOU still close the quest - submit
    # the answer with buzz answer (0 XP at this hint level; streak halves)
    s.hints[q.id] = 3
    s.streak //= 2
    text = _explain(world, q)
    for m in _modules_in_truth(q):
        if m in world.modules and m not in s.seen:
            s.seen.append(m)
    return 3, ("the oracle reveals everything: " + text
               + "  (now submit it with buzz answer - the closing move is yours)")


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
    # the pre-guess signal patch quests were missing: the chronicle withholds
    # WHO moved with a module, but probing a specific pair is a hypothesis
    # test - it earns the date evidence for that pair and nothing more
    pair = [ev for ev in world.events + world.reverts
            if a in ev["mods"] and b in ev["mods"]]
    if pair:
        dates = ", ".join(ev["date"] for ev in pair[:4])
        lines.append(f"focused commits moving BOTH in one patch: {len(pair)}"
                     f"  (dates: {dates}{', …' if len(pair) > 4 else ''})")
    return "\n".join(lines)


def flow(world: World, s: Session, name: str) -> list[str]:
    """Who does this module CALL into at runtime, and who calls into it?
    Reading calls means reading the file, so it requires a module you have
    already read (visited or spyglassed)."""
    m = resolve_module(world, name)
    if m not in s.discovered:
        raise GameError(f"you have not read {m} yet - 'buzz look {m}' "
                        f"(if you can see it) or fly there first")
    outs = [c for c in world.calls if c["src"] == m]
    ins = [c for c in world.calls if c["dst"] == m]
    lines = [f"where {m}'s work goes (function calls, not just imports):"]
    import re as _re
    for c in sorted(outs, key=lambda c: c["dst"]):
        _name_seen(s, c["dst"])
        seam = any(_re.match(r"(get_|lookup|resolve|make_|create_|factory)",
                             v) for v in c["via"]) or "registry" in c["dst"]
        lines.append(f"  calls into {c['dst']}  ({', '.join(c['via'])})"
                     + ("  <- a lookup seam: the concrete callee is chosen "
                        "at RUNTIME - static analysis stops here"
                        if seam else ""))
    if not outs:
        lines.append("  (no cross-module calls detected - work stays home)")
    called = {c["dst"] for c in outs}
    idle = sorted(e.dst for e in world.out_edges(m) if e.dst not in called)
    if idle:
        lines.append(f"  imported but never called: {', '.join(idle)}  "
                     f"(referenced only as values, or dispatched "
                     f"dynamically - no direct call found)")
    if ins:
        lines.append(f"who sends work INTO {m}:")
        for c in sorted(ins, key=lambda c: c["src"]):
            _name_seen(s, c["src"])
            lines.append(f"  {c['src']} calls  ({', '.join(c['via'])})")
    lines.append("(conservative static analysis: only unambiguous direct "
                 "calls are recorded - dynamic dispatch stays invisible)")
    return lines


def trace(world: World, s: Session, path: list[str]) -> list[str]:
    """Free dry-run of a proposed chain: reports each hop's status without
    spending an answer attempt. The player supplies the chain, so this
    reveals nothing they could not get from N probes - it just kills the
    tool-call grind around walk quests."""
    if len(path) < 2:
        raise GameError("buzz trace <module> <module> [module ...]")
    kinds = {TOP: "top-level", LAZY: "sealed tunnel (function-level)",
             TYPE: "TYPE_CHECKING-only (never runs)"}
    lines = []
    ok = True
    for a, b in zip(path, path[1:]):
        e = next((e for e in world.edges if e.src == a and e.dst == b), None)
        if e:
            lines.append(f"  {a} -> {b}  OK [{kinds[e.kind]}]")
        else:
            ok = False
            lines.append(f"  {a} -> {b}  NO EDGE")
    lines.append("chain " + ("holds (edge kinds above decide whether a "
                             "given quest accepts it)" if ok
                             else "breaks at the hop(s) marked NO EDGE"))
    return lines


def chronicle(world: World, s: Session, name: str) -> list[str]:
    """The hive's records for one module: focused commits and reverts that
    touched it. Companion names are withheld while an open patch quest in
    that module's zone depends on them - the record IS that answer."""
    m = resolve_module(world, name)
    zid = world.modules[m].zone
    patch_open = any(q.qtype == "patch" and q.zone == zid
                     and q.id not in s.resolved
                     for q in world.questions.values())
    lines = [f"chronicle of {m} (focused commits on record):"]
    found = 0
    for ev in world.events + world.reverts:
        if m not in ev["mods"]:
            continue
        found += 1
        others = [x for x in ev["mods"] if x != m]
        if patch_open:
            others = ["<withheld: an open patch quest in this district "
                      "hangs on it>"] if others else []
        lines.append(f"  {ev['date']}  \"{ev['subject']}\""
                     + (f"  (moved with: {', '.join(others)})" if others else ""))
        _name_seen(s, *(x for x in ev["mods"] if not patch_open))
    if not found:
        lines.append("  nothing notable on record (only focused 2-module "
                     "commits and reverts are kept)")
    return lines


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
    "patch": "one commit, two files: change-coupling is the review checklist the import graph never shows",
    "scar": "a revert marks risk - the module that was rolled back once deserves the hardest review next time",
    "hotspot": "churn concentrates: the file that changed most will change next - review it hardest",
    "direction": "always check which side of an import edge a module is on before touching it",
    "cut": "safe deletion = nothing upstream: reverse reachability tells you exactly what a removal strands",
    "refactor": "severing an import only helps when no redundant route re-creates the reach - measure the radius, never guess",
    "via": "knowing HOW breakage travels matters as much as whether it does - chokepoints are routes, not trivia",
    "order": "migration order is topological: rewrite a module only after everything it imports is already done",
}


def reveal_prompt_modules(world: World, s: Session, q: Question) -> None:
    """Reading a quest marks the modules its text NAMES as seen (scout
    reports) - never the answer set itself."""
    t = q.truth
    named: list = []
    if q.qtype in ("walk", "cycle", "direction", "detour", "via"):
        named = [t.get("src"), t.get("dst"), t.get("avoid"), t.get("via")]
    elif q.qtype == "cut":
        named = t.get("candidates", [])
    elif q.qtype == "refactor":
        named = [t.get("src"), t.get("dst"), t.get("loser")]
    elif q.qtype == "order":
        named = t.get("set", [])
    elif q.qtype == "region":
        named = [t.get("target")] + world.zones[q.zone].members
    elif q.qtype == "ghost":
        named = [t.get("src")] + t.get("suspects", [])
    elif q.qtype == "place":
        named = [t.get("module")]
    elif q.qtype == "gate":
        named = [t.get("a"), t.get("b")]
    elif q.qtype in ("lore", "patch"):
        named = t.get("suspects", []) + [t.get("anchor")]
    # hub names nothing - pointing at it IS the quest
    for m in named:
        if m in world.modules and m not in s.seen:
            s.seen.append(m)
