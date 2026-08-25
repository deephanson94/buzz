"""Deterministic question generation from graph + git ground truth.

Every question stores its truth as graph facts. Anything answerable from a
single file is not generated (design rule: distance >= 2). Difficulty = the
number of distinct files the answer spans; XP scales with it.
"""
from __future__ import annotations

import networkx as nx

from .analyze import top_graph, full_graph
from .model import World, Question, LAZY, TYPE, ROLE_BOSS

MAX_PER_ZONE = 6
BOSS_XP_MULT = 2

# stated in every prompt that depends on it: what counts as a real edge
EDGE_RULE = ("Count only top-level imports that always run - function-level "
             "(sealed tunnel) and TYPE_CHECKING-only imports do NOT count.")


def _sig(qtype: str, *parts) -> tuple:
    return (qtype, *parts)


def _flavor(world: World, options: list[str]) -> str:
    """Deterministic phrasing rotation so quests don't read as one template
    with nouns swapped."""
    return options[len(world.questions) % len(options)]


def _q(world: World, zone: str, qtype: str, verb: str, prompt: str, truth: dict,
       xp: int, distance: int, boss: bool = False, lesson: str = "") -> Question:
    qid = f"q{len(world.questions) + 1}"
    q = Question(id=qid, zone=zone, qtype=qtype, verb=verb, prompt=prompt,
                 truth=truth, xp=xp, distance=distance, boss=boss, lesson=lesson)
    world.questions[qid] = q
    return q


def gen_walk(world: World, G: nx.DiGraph, zone_id: str, count: int = 2,
             boss: bool = False, dst_pool=None, src_pool=None,
             used: set | None = None) -> int:
    """Trace an import chain src -> ... -> dst (any valid directed path)."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    targets = dst_pool or zone.members
    sources = src_pool or zone.members
    pairs = []
    for a in sources:
        for b in targets:
            if a == b or not G.has_node(a) or not G.has_node(b):
                continue
            if world.has_edge(a, b):  # a lazy/type edge would falsify the prompt
                continue
            try:
                d = nx.shortest_path_length(G, a, b)
            except nx.NetworkXNoPath:
                continue
            if 2 <= d <= 4:
                # prefer paths that end somewhere important; deprioritize
                # dotted sub-package files (surprising as exact endpoints)
                pairs.append((d, "." in b, world.modules[b].pagerank, a, b))
    pairs.sort(key=lambda t: (-t[0], t[1], -t[2]))
    made = 0
    taken: set[str] = set()
    for d, _, _, a, b in pairs:
        if made >= count or a in taken or b in taken:
            continue
        if _sig("walk", a, b) in used:
            continue
        example = nx.shortest_path(G, a, b)
        # a repo-wide registry spine (X -> config -> pkg -> registry -> Y)
        # would otherwise stamp out near-identical walks with new endpoints
        via = _sig("walkvia", tuple(example[1:-1]))
        if len(example) > 2 and via in used:
            continue
        used.add(_sig("walk", a, b))
        used.add(via)
        taken.update((a, b))
        mult = BOSS_XP_MULT if boss else 1
        prompt = _flavor(world, [
            f"{a} never imports {b} directly, yet changing {b} can break {a}. "
            f"Walk the import chain that connects them: start at {a}, end at "
            f"{b}, naming each module along the way. Any real chain of "
            f"imports counts.",
            f"A wing-note from the archives: a bad release of {b} once took "
            f"{a} down with it - though {a} never names {b} anywhere in its "
            f"file. Retrace the supply line that made it possible: walk the "
            f"imports from {a} all the way to {b}.",
            f"Prove the rumor: {a} secretly rests on {b}. Show the evidence "
            f"as a walk - every hop a real import - from {a} down to {b}.",
        ])
        _q(world, zone_id, "walk", "walk", prompt,
           {"src": a, "dst": b, "example": example},
           xp=10 * d * mult, distance=d + 1, boss=boss)
        made += 1
    return made


def gen_detour(world: World, G: nx.DiGraph, zone_id: str,
               used: set | None = None) -> int:
    """Twist on the walk: the obvious route is closed. Reach b from a
    WITHOUT touching the collapsed module - proves the player knows more
    than one road."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    for a in sorted(zone.members, key=lambda m: -world.modules[m].out_degree):
        for b in sorted(zone.members, key=lambda m: -world.modules[m].in_degree):
            if a == b or world.has_edge(a, b):
                continue
            if _sig("walk", a, b) in used:
                continue
            if not (G.has_node(a) and G.has_node(b)):
                continue
            try:
                sp = nx.shortest_path(G, a, b)
            except nx.NetworkXNoPath:
                continue
            if not 3 <= len(sp) <= 5:
                continue
            interior = sorted(sp[1:-1],
                              key=lambda m: -world.modules[m].betweenness)
            for g in interior:
                H = G.copy()
                H.remove_node(g)
                if not nx.has_path(H, a, b):
                    continue
                alt = nx.shortest_path(H, a, b)
                if len(alt) > 6:
                    continue
                used.add(_sig("walk", a, b))
                _q(world, zone_id, "detour", "walk",
                   f"Cave-in! The tunnel hub {g} has collapsed. {a} still "
                   f"needs {b}. Walk an import chain from {a} to {b} that "
                   f"NEVER touches {g} - prove the district has a second "
                   f"road.",
                   {"src": a, "dst": b, "avoid": g, "example": alt},
                   xp=15 * (len(alt) - 1), distance=len(alt))
                return 1
    return 0


def gen_region(world: World, G: nx.DiGraph, zone_id: str, boss: bool = False,
               target: str | None = None, used: set | None = None) -> int:
    """Blast radius: all zone members that transitively import x."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    best = None
    candidates = [target] if target else sorted(
        zone.members, key=lambda m: -world.modules[m].pagerank)
    for x in candidates:
        if not G.has_node(x) or _sig("region", x) in used:
            continue
        importers = {m for m in zone.members
                     if m != x and G.has_node(m) and nx.has_path(G, m, x)}
        if 2 <= len(importers) <= 8 and len(importers) < len(zone.members) - 1:
            best = (x, importers)
            break
    if not best:
        return 0
    x, importers = best
    used.add(_sig("region", x))
    # witness chain per member, shown in the reveal so every ruling is taught
    why = {m: nx.shortest_path(G, m, x) for m in sorted(importers)}
    depth = max(len(p) - 1 for p in why.values())
    mult = BOSS_XP_MULT if boss else 1
    # a huge district would make an unreadable candidate wall: cap the list,
    # always containing the full truth plus the most plausible decoys
    if len(zone.members) > 14:
        decoys = [m for m in sorted(zone.members,
                                    key=lambda m: -world.modules[m].in_degree)
                  if m != x and m not in importers]
        cands = sorted(set(importers) | set(decoys[: 14 - len(importers)]))
    else:
        cands = sorted(m for m in zone.members if m != x)
    lead = _flavor(world, [
        f"Blast radius. You are changing {x}'s public API.",
        f"Storm warning. A breaking change is landing on {x} tonight.",
    ])
    _q(world, zone_id, "region", "region",
       f"{lead} Select every candidate that could break - everything that "
       f"imports {x} directly or through a chain. {EDGE_RULE} A chain may "
       f"pass through modules OUTSIDE the candidate list (even other zones) - "
       f"the candidates are only what you select from. "
       f"Candidates: {', '.join(cands)}.",
       {"target": x, "region": sorted(importers), "why": why,
        "candidates": cands},
       xp=(10 + 5 * len(importers)) * mult, distance=1 + depth, boss=boss)
    return 1


def gen_boss_reach(world: World, G: nx.DiGraph, boss: str, used: set) -> int:
    """Boss-scale region: the boss's import-time footprint. Which modules
    MUST load for `import boss` to succeed? Distractors are the boss's own
    sealed-tunnel / type-hint dependencies - modules it touches constantly
    that nevertheless don't load at import time."""
    if not G.has_node(boss):
        return 0
    reach = nx.descendants(G, boss)
    decoys = sorted(
        {e.dst for e in world.edges
         if e.src == boss and e.kind in (LAZY, TYPE) and e.dst not in reach},
        key=lambda m: -world.modules[m].pagerank)
    picks = sorted(reach, key=lambda m: -world.modules[m].in_degree)
    if len(picks) < 3 or len(decoys) < 3:
        return 0
    picks, decoys = picks[:5], decoys[:5]
    cands = sorted(picks + decoys)
    why = {m: nx.shortest_path(G, boss, m) for m in sorted(picks)}
    used.add(_sig("region", boss))
    _q(world, world.modules[boss].zone, "region", "region",
       f"The heart of the hive. Someone runs `import {boss}`. Which of these "
       f"modules MUST load successfully for that import to complete? "
       f"{boss} touches all of them - but modules it reaches only through "
       f"sealed tunnels (function-level imports) or type-hints do NOT load "
       f"at import time. Select the ones that do. A loading chain may pass "
       f"through modules outside this list - check every hop. "
       f"Candidates: {', '.join(cands)}.",
       {"target": boss, "region": sorted(picks), "why": why},
       xp=(10 + 5 * len(picks)) * BOSS_XP_MULT, distance=len(cands), boss=True,
       lesson=("import-time footprint = FORWARD reachability over always-run "
               "imports: everything that must load before your import returns"))
    return 1


def gen_cycle(world: World, Gtop: nx.DiGraph, zone_id: str,
              used: set | None = None) -> int:
    """Why is this import inside a function? Because top-level would cycle.
    Walk the return path that proves it. Resolving any cycle question
    unlocks the tunnel-vision ability."""
    made = 0
    used = used if used is not None else set()
    lazy_edges = [e for e in world.edges if e.kind == LAZY and
                  world.modules[e.src].zone == zone_id]
    for e in lazy_edges:
        if made:
            break
        if _sig("cycle", e.src, e.dst) in used:
            continue
        if not (Gtop.has_node(e.dst) and Gtop.has_node(e.src)):
            continue
        try:
            back = nx.shortest_path(Gtop, e.dst, e.src)
        except nx.NetworkXNoPath:
            continue
        if len(back) < 2 or len(back) > 5:
            continue
        used.add(_sig("cycle", e.src, e.dst))
        _q(world, zone_id, "cycle", "walk",
           f"A sealed tunnel: {e.src} imports {e.dst} only INSIDE a function, "
           f"not at the top of the file. That is a design decision, not an accident - "
           f"a top-level import would create an import cycle. Prove it: walk the "
           f"top-level import chain from {e.dst} back to {e.src}. "
           f"Solving this unlocks tunnel-vision (travel through all sealed tunnels).",
           {"src": e.dst, "dst": e.src, "example": back, "lazy_src": e.src, "lazy_dst": e.dst},
           xp=25, distance=len(back))
        made += 1
    return made


def gen_ghost(world: World, zone_id: str, boss: bool = False,
              target: str | None = None, used: set | None = None) -> int:
    """Hidden coupling: files that change together with no import edge."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    pool = [target] if target else sorted(
        zone.members, key=lambda m: -world.modules[m].commits)
    for x in pool:
        if _sig("ghost", x) in used:
            continue
        partners = [(o, n) for o, n in world.cochange.get(x, []) if n >= 12
                    and not world.has_edge(x, o) and not world.has_edge(o, x)]
        if not partners:
            continue
        used.add(_sig("ghost", x))
        accepted = [o for o, _ in partners[:3]]
        topn = partners[0][1]
        mult = BOSS_XP_MULT if boss else 1
        # a bounded suspect list turns this into hypothesis-testing with
        # probe, not blind enumeration of the whole hive
        decoys = [m for m in sorted(
            world.modules, key=lambda m: -world.modules[m].commits)
            if m != x and m not in accepted
            and not world.has_edge(x, m) and not world.has_edge(m, x)][:4]
        suspects = sorted([accepted[0]] + decoys)
        lead = _flavor(world, [
            f"Ghost edge. No import statement of ANY kind (top-level, "
            f"function-level, or type-hint) connects {x} to it in either "
            f"direction, yet git says they change together constantly ({topn}+ "
            f"shared focused commits) - hidden coupling the import graph "
            f"cannot see.",
            f"The old bees whisper that {x} has a secret companion: a module "
            f"it never imports and is never imported by, yet the two have "
            f"moved in lockstep through {topn}+ focused commits of history.",
        ])
        _q(world, zone_id, "ghost", "edge",
           f"{lead} Suspects: {', '.join(suspects)}. Investigate with "
           f"'buzz probe {x} <suspect>' and reason about which one would HAVE "
           f"to move when {x} moves, then draw the ghost edge: "
           f"answer edge {x} <your-guess>.",
           {"src": x, "accepted": accepted, "best": partners[0][0],
            "shared": topn, "suspects": suspects},
           xp=20 * mult, distance=2, boss=boss)
        return 1
    return 0


def gen_hub(world: World, G: nx.DiGraph, zone_id: str,
            used: set | None = None) -> int:
    """Point at the zone's load-bearing module: most imported-by within the
    zone. Pushes map-reading; only asked when the answer is unambiguous."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    if _sig("hub", zone_id) in used or len(zone.members) < 4:
        return 0
    counts = {m: sum(1 for p in G.predecessors(m) if p in zone.members)
              for m in zone.members}
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    if ranked[0][1] < 3 or ranked[0][1] == ranked[1][1]:
        return 0
    hub, n = ranked[0]
    used.add(_sig("hub", zone_id))
    _q(world, zone_id, "hub", "point",
       f"Every district rests on one load-bearing wall. Which module in "
       f"{zone.name} is imported (top-level) by more of its own district "
       f"than any other? Point at it: answer point <module>.",
       {"module": hub, "count": n},
       xp=15, distance=n + 1)
    return 1


def gen_place(world: World, G: nx.DiGraph, zone_id: str,
              used: set | None = None) -> int:
    """Given a module and its neighbors, place it in the right zone.
    Only high-confidence placements (Louvain is noisy)."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    for x in sorted(zone.members, key=lambda m: -world.modules[m].in_degree):
        if _sig("place", x) in used:
            continue
        nbrs = sorted(set(G.predecessors(x)) | set(G.successors(x)))
        if len(nbrs) < 3:
            continue
        inside = sum(1 for n in nbrs if world.modules[n].zone == zone_id)
        if inside / len(nbrs) < 0.6:
            continue
        used.add(_sig("place", x))
        shown = nbrs[:6]
        _q(world, zone_id, "place", "place",
           f"A scout reports a module named {x}. Its import neighbors are: "
           f"{', '.join(shown)}. Which district of the hive does {x} belong to? "
           f"Answer with the zone id or name.",
           {"module": x, "zone": zone_id},
           xp=15, distance=2)
        return 1
    return 0


def gen_elder(world: World, zone_id: str, used: set | None = None) -> int:
    """Time's arrow: which of two modules entered git history first?
    A Tier-1 (git-semantics) quest - the import graph knows nothing of it."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    if _sig("elder", zone_id) in used:
        return 0
    dated = [m for m in zone.members
             if world.modules[m].born and world.modules[m].commits >= 5]
    dated.sort(key=lambda m: world.modules[m].born)
    if len(dated) < 2:
        return 0
    old, new = dated[0], dated[-1]
    if world.modules[old].born[:4] == world.modules[new].born[:4]:
        return 0  # same year: too close to be interesting or fair
    used.add(_sig("elder", zone_id))
    _q(world, zone_id, "elder", "edge",
       f"The elders' dispute. Two residents of {zone.name} both claim to be "
       f"the district's founder: {min(old, new)} and {max(old, new)}. Git "
       f"remembers. Draw time's arrow from the elder to the newcomer: "
       f"answer edge <older> <newer>.",
       {"src": old, "dst": new,
        "born_src": world.modules[old].born, "born_dst": world.modules[new].born},
       xp=15, distance=2)
    return 1


def gen_hotspot(world: World, zone_id: str, used: set | None = None) -> int:
    """Point at the district's most-reworked module (churn hotspot)."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    if _sig("hotspot", zone_id) in used or len(zone.members) < 4:
        return 0
    ranked = sorted(zone.members, key=lambda m: -world.modules[m].commits)
    top, second = ranked[0], ranked[1]
    c1, c2 = world.modules[top].commits, world.modules[second].commits
    if c1 < 10 or c1 < c2 * 1.3:
        return 0  # no clear hotspot
    used.add(_sig("hotspot", zone_id))
    _q(world, zone_id, "hotspot", "point",
       f"Storm damage survey. One building in {zone.name} has been rebuilt "
       f"far more often than any other - the district's churn hotspot, where "
       f"bugs and features keep landing. Point at it: answer point <module>.",
       {"module": top, "commits": c1},
       xp=15, distance=len(zone.members) // 2 + 1)
    return 1


def gen_gate(world: World, G: nx.DiGraph, zone_id: str,
             used: set | None = None) -> int:
    """Chokepoint: a pair (a, b) whose every top-level import route runs
    through one module. Point at the gate. Any module whose removal cuts
    a off from b is accepted."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    if _sig("gate", zone_id) in used:
        return 0
    cands = sorted(zone.members, key=lambda m: -world.modules[m].betweenness)
    for g in cands[:5]:
        if not G.has_node(g) or world.modules[g].betweenness == 0:
            continue
        ups = [m for m in zone.members if m != g and nx.has_path(G, m, g)]
        downs = [m for m in zone.members if m != g and nx.has_path(G, g, m)]
        for a in sorted(ups, key=lambda m: -world.modules[m].commits):
            for b in sorted(downs, key=lambda m: -world.modules[m].in_degree):
                if a == b or not nx.has_path(G, a, b):
                    continue
                H = G.copy()
                H.remove_node(g)
                if nx.has_path(H, a, b):
                    continue  # g is not actually a chokepoint for this pair
                dist = nx.shortest_path_length(G, a, b)
                if dist < 2:
                    continue
                # accept ANY node whose removal cuts a off from b
                accepted = []
                for c in nx.shortest_path(G, a, b)[1:-1]:
                    H2 = G.copy()
                    H2.remove_node(c)
                    if not nx.has_path(H2, a, b):
                        accepted.append(c)
                if not accepted:
                    continue
                used.add(_sig("gate", zone_id))
                _q(world, zone_id, "gate", "point",
                   f"The gate. Every top-level import route from {a} to {b} "
                   f"squeezes through a single chokepoint - remove that one "
                   f"module and {a} loses {b} entirely. Point at the "
                   f"chokepoint: answer point <module>.",
                   {"a": a, "b": b, "module": g, "accepted": sorted(set(accepted))},
                   xp=10 * (dist + 1), distance=dist + 1)
                return 1
    return 0


def generate_questions(world: World) -> None:
    Gtop = top_graph(world)
    Gfull = full_graph(world)
    boss_mods = [m for m, mod in world.modules.items() if mod.role == ROLE_BOSS]
    boss = boss_mods[0] if boss_mods else None
    used: set = set()

    # Boss fight FIRST so zone generation can never duplicate it. Boss
    # questions are hive-scale: direct-vs-transitive importers across the
    # whole repo, the longest march into the boss from anywhere, and the
    # boss's strongest ghost coupling.
    if boss:
        bz = world.modules[boss].zone
        if not gen_boss_reach(world, Gtop, boss, used):
            gen_region(world, Gtop, bz, boss=True, target=boss, used=used)
        all_mods = sorted(world.modules)
        # longest march: into the boss from anywhere; if nothing sits above
        # the boss (a sink hub), march outward from it instead
        if not gen_walk(world, Gtop, bz, count=1, boss=True,
                        dst_pool=[boss], src_pool=all_mods, used=used):
            gen_walk(world, Gtop, bz, count=1, boss=True,
                     src_pool=[boss], dst_pool=all_mods, used=used)
        gen_ghost(world, bz, boss=True, target=boss, used=used)
        for q in world.questions.values():
            if q.boss:
                q.prompt = "[BOSS] " + q.prompt

    # rotate the quest mix so districts play differently, and cap the
    # most repetition-prone types GLOBALLY - a recipe learned once should
    # not be re-run in every district (top playtest complaint)
    def count(qt: str) -> int:
        return sum(1 for q in world.questions.values() if q.qtype == qt)

    # generous caps: the bracketing gate (buzz calibrate) prunes shallow
    # and broken questions afterward, so generation should run wide
    CAPS = {"cycle": 2, "region": 5, "hub": 2, "ghost": 6, "gate": 5,
            "place": 4, "elder": 4, "hotspot": 4}

    def capped(qt: str) -> bool:
        return count(qt) >= CAPS.get(qt, 99)

    for z in sorted(world.zones.values(), key=lambda z: z.order):
        n = 0
        if not capped("cycle"):  # carries the ability unlock, so tried first
            n += gen_cycle(world, Gtop, z.id, used=used)
        mix = z.order % 3
        if mix == 0:
            n += gen_walk(world, Gtop, z.id, count=3, used=used)
            if not capped("region"):
                n += gen_region(world, Gtop, z.id, used=used)
            if not capped("ghost"):
                n += gen_ghost(world, z.id, used=used)
            if not capped("hub"):
                n += gen_hub(world, Gtop, z.id, used=used)
        elif mix == 1:
            n += gen_walk(world, Gtop, z.id, count=1, used=used)
            if not capped("gate"):
                n += gen_gate(world, Gtop, z.id, used=used)
            if not capped("ghost"):
                n += gen_ghost(world, z.id, used=used)
            if not capped("elder"):
                n += gen_elder(world, z.id, used=used)
            if not capped("place"):
                n += gen_place(world, Gfull, z.id, used=used)
        else:
            n += gen_detour(world, Gtop, z.id, used=used)
            if not capped("region"):
                n += gen_region(world, Gtop, z.id, used=used)
            if not capped("gate"):
                n += gen_gate(world, Gtop, z.id, used=used)
            if not capped("hotspot"):
                n += gen_hotspot(world, z.id, used=used)
            if not capped("hub"):
                n += gen_hub(world, Gtop, z.id, used=used)
            if n < 3:
                n += gen_walk(world, Gtop, z.id, count=1, used=used)
        # top up thin zones only
        if n < 4 and not capped("elder"):
            n += gen_elder(world, z.id, used=used)
        if n < 4 and not capped("hotspot"):
            n += gen_hotspot(world, z.id, used=used)
        if n < 3:  # thin zone: top up so it stays clearable and worthwhile
            n += gen_walk(world, Gtop, z.id, count=1, used=used)
            if not capped("ghost"):
                gen_ghost(world, z.id, used=used)


def make_followup(world: World, q: Question, n_existing: int) -> dict | None:
    """A wrong answer reveals the truth and spawns a smaller, related
    question (never removes progress). Returns a session-local question dict."""
    fid = f"f{n_existing + 1}"
    t = q.truth
    if q.qtype in ("walk", "cycle"):
        path = t["example"]
        a, b = path[0], path[1]
        prompt = (f"Follow-up: you just saw the chain {' -> '.join(path)}. "
                  f"First hop check - between {a} and {b}, who imports whom? "
                  f"answer edge <importer> <imported>.")
        truth = {"src": a, "dst": b}
    elif q.qtype == "region":
        x = t["target"]
        member = t["region"][0]
        prompt = (f"Follow-up: {member} was in {x}'s blast radius. Draw the first "
                  f"dependency step: between {member} and {x}, who imports whom? "
                  f"answer edge <importer> <imported>.")
        truth = {"src": member, "dst": x}
    elif q.qtype == "place":
        x = t["module"]
        zid = t["zone"]
        zname = world.zones[zid].name
        top = max(world.zones[zid].members,
                  key=lambda m: world.modules[m].pagerank)
        if x == top or not (world.has_edge(x, top) or world.has_edge(top, x)):
            return None
        prompt = (f"Follow-up: {x} lives in {zname}. Its anchor is {top}. Between "
                  f"{x} and {top}, who imports whom? answer edge <importer> <imported>.")
        src, dst = (x, top) if world.has_edge(x, top) else (top, x)
        truth = {"src": src, "dst": dst}
    else:
        return None
    return {"id": fid, "zone": q.zone, "qtype": "direction", "verb": "edge",
            "prompt": prompt, "truth": truth, "xp": max(5, q.xp // 4),
            "distance": 2, "boss": False, "followup_of": q.id}
