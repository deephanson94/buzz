"""Deterministic question generation from graph + git ground truth.

Every question stores its truth as graph facts. Anything answerable from a
single file is not generated (design rule: distance >= 2). Difficulty = the
number of distinct files the answer spans; XP scales with it.
"""
from __future__ import annotations

import networkx as nx

from .analyze import top_graph, full_graph
from .model import World, Question, TOP, LAZY, TYPE, ROLE_BOSS

MAX_PER_ZONE = 6
BOSS_XP_MULT = 2

# stated in every prompt that depends on it: what counts as a real edge
EDGE_RULE = ("Count only top-level imports that always run - function-level "
             "(sealed tunnel) and TYPE_CHECKING-only imports do NOT count.")


def _sig(qtype: str, *parts) -> tuple:
    return (qtype, *parts)


def _small(world: World) -> bool:
    """A small hive: scripts-repo scale, where the big-repo thresholds
    starve every generator (first private-repo dogfood: 9 modules, 5
    edges -> exactly one quest and an instant FULL CLEAR)."""
    return len(world.modules) < 15 or len(world.edges) < 12


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
        # would otherwise stamp out near-identical walks with new endpoints:
        # dedup identical interiors AND allow at most ONE mostly-funnel walk
        # per world (playtesters called the rest recycled)
        interior = example[1:-1]
        via = _sig("walkvia", tuple(interior))
        if len(example) > 2 and via in used:
            continue
        max_btw = max((m.betweenness for m in world.modules.values()),
                      default=0) or 1
        funnel = {n for n, m in world.modules.items()
                  if m.betweenness >= 0.1 * max_btw}
        if interior and sum(1 for n in interior if n in funnel) / len(interior) > 0.5:
            if _sig("walk-funnel-used") in used:
                continue
            used.add(_sig("walk-funnel-used"))
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
        floor = 4 if _small(world) else 12
        partners = [(o, n) for o, n in world.cochange.get(x, []) if n >= floor
                    and not world.has_edge(x, o) and not world.has_edge(o, x)]
        # the same hidden coupling must never be asked twice from opposite
        # sides (a panel found the boss fight re-asked as a zone quest)
        partners = [(o, n) for o, n in partners
                    if _sig("ghostpair", *sorted((x, o))) not in used]
        if not partners:
            continue
        used.add(_sig("ghost", x))
        used.add(_sig("ghostpair", *sorted((x, partners[0][0]))))
        accepted = [o for o, _ in partners[:3]]
        topn = partners[0][1]
        mult = BOSS_XP_MULT if boss else 1
        # a bounded suspect list turns this into hypothesis-testing with
        # probe, not blind enumeration of the whole hive. Decoys that also
        # co-change with x (just less) make the probe readings a contest,
        # not a lone nonzero number in a row of zeros
        near = [o for o, n in world.cochange.get(x, [])
                if o not in accepted and o != x
                and not world.has_edge(x, o) and not world.has_edge(o, x)]
        cold = [m for m in sorted(
            world.modules, key=lambda m: -world.modules[m].commits)
            if m != x and m not in accepted and m not in near
            and not world.has_edge(x, m) and not world.has_edge(m, x)]
        decoys = (near + cold)[:4]
        suspects = sorted([accepted[0]] + decoys)
        # deliberately no exact commit count in the prompt - playtesters
        # string-matched it against probe output instead of reasoning
        lead = _flavor(world, [
            f"Ghost edge. No import statement of ANY kind (top-level, "
            f"function-level, or type-hint) connects {x} to it in either "
            f"direction, yet git says they change together constantly - "
            f"hidden coupling the import graph cannot see.",
            f"The old bees whisper that {x} has a secret companion: a module "
            f"it never imports and is never imported by, yet the two have "
            f"moved in lockstep through years of history.",
            f"Someone keeps editing two files in the same breath: {x}, and a "
            f"module git says it has never once imported. Find the silent "
            f"partner.",
        ])
        _q(world, zone_id, "ghost", "edge",
           f"{lead} Suspects: {', '.join(suspects)}. Investigate with "
           f"'buzz probe {x} <suspect>' and reason about which one would HAVE "
           f"to move when {x} moves, then draw the ghost edge: "
           f"answer {x} <your-guess>.",
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
    min_members, min_deg = (3, 2) if _small(world) else (4, 3)
    if _sig("hub", zone_id) in used or len(zone.members) < min_members:
        return 0
    counts = {m: sum(1 for p in G.predecessors(m) if p in zone.members)
              for m in zone.members}
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    if ranked[0][1] < min_deg or ranked[0][1] == ranked[1][1]:
        return 0
    hub, n = ranked[0]
    used.add(_sig("hub", zone_id))
    _q(world, zone_id, "hub", "point",
       f"Every district rests on one load-bearing wall. Which module in "
       f"{zone.name} is imported (top-level) by more of its own district "
       f"than any other? Point at it: answer <module>.",
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
        if _sig("place", x) in used or x == world.start:
            # never mask the module the player WAKES UP in (a dogfooder
            # stood in '??? (unplaced)' on turn one)
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
             if world.modules[m].born
             and world.modules[m].commits >= (2 if _small(world) else 5)]
    dated.sort(key=lambda m: world.modules[m].born)
    if len(dated) < 2:
        return 0
    old, new = dated[0], dated[-1]
    # gap must be wide enough to be fair: a year normally; a month on a
    # young small hive (where a year gap cannot exist yet)
    cut = 7 if _small(world) else 4
    if world.modules[old].born[:cut] == world.modules[new].born[:cut]:
        return 0
    used.add(_sig("elder", zone_id))
    _q(world, zone_id, "elder", "edge",
       f"The elders' dispute. Two residents of {zone.name} both claim to be "
       f"the district's founder: {min(old, new)} and {max(old, new)}. Git "
       f"remembers. Draw time's arrow from the elder to the newcomer: "
       f"answer <older> <newer>.",
       {"src": old, "dst": new,
        "born_src": world.modules[old].born, "born_dst": world.modules[new].born},
       xp=15, distance=2)
    return 1


def gen_hotspot(world: World, zone_id: str, used: set | None = None) -> int:
    """Point at the district's most-reworked module (churn hotspot)."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    min_members = 3 if _small(world) else 4
    if _sig("hotspot", zone_id) in used or len(zone.members) < min_members:
        return 0
    ranked = sorted(zone.members, key=lambda m: -world.modules[m].commits)
    top, second = ranked[0], ranked[1]
    c1, c2 = world.modules[top].commits, world.modules[second].commits
    if c1 < (5 if _small(world) else 10) or c1 < c2 * 1.3:
        return 0  # no clear hotspot
    used.add(_sig("hotspot", zone_id))
    _q(world, zone_id, "hotspot", "point",
       f"Storm damage survey. One building in {zone.name} has been rebuilt "
       f"far more often than any other - the district's churn hotspot, where "
       f"bugs and features keep landing. Point at it: answer <module>.",
       {"module": top, "commits": c1},
       xp=15, distance=len(zone.members) // 2 + 1)
    return 1


def gen_patch(world: World, zone_id: str, used: set | None = None) -> int:
    """Tier-1 diff comprehension: a real historical commit touched exactly
    two modules. Given the commit subject and one of them, point at the
    module that had to move with it. Prefers surprising companions - pairs
    with no import edge - so the answer teaches change-coupling, not
    import-following."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    if _sig("patch", zone_id) in used:
        return 0
    BORING = ("release", "bump", "update version", "prepare", "post release",
              "changelog", "v0.", "v1.", "v2.")
    scored = []
    for ev in world.events:
        a, b = ev["mods"]
        if a not in world.modules or b not in world.modules:
            continue
        if ev["subject"].lower().startswith(BORING):
            continue  # version-bump ceremony teaches nothing
        subj = ev["subject"].lower().replace("_", "")
        if any(mod.split(".")[-1].strip("_").replace("_", "") in subj
               for mod in (a, b)):
            continue  # the subject names a module - the answer would leak
        # anchor the quest in this zone via either module
        for m, other in ((a, b), (b, a)):
            if world.modules[m].zone != zone_id or m == other:
                continue
            if _sig("patch", *sorted((m, other))) in used:
                continue
            surprising = not (world.has_edge(m, other) or world.has_edge(other, m))
            cross_zone = world.modules[other].zone != zone_id
            scored.append((surprising, cross_zone, ev, m, other))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    if not scored:
        return 0
    surprising, _, ev, m, other = scored[0]
    # decoys that ALSO share focused history with the anchor keep the quest
    # a puzzle now that probe reports pair evidence: several suspects read
    # nonzero, and only the DATE settles which patch the chronicle means
    hist = sorted({x for e2 in world.events + world.reverts
                   if m in e2["mods"] for x in e2["mods"]} - {m, other})
    cold = [d for d in sorted(world.modules,
                              key=lambda x: -world.modules[x].commits)
            if d not in (m, other) and d not in hist]
    decoys = (hist + cold)[:4]
    suspects = sorted([other] + decoys)
    used.add(_sig("patch", zone_id))
    used.add(_sig("patch", *sorted((m, other))))
    _q(world, zone_id, "patch", "point",
       f"A page from the hive's chronicle, {ev['date']}: "
       f"\"{ev['subject']}\". That patch touched {m} - and exactly ONE "
       f"other module in the whole hive had to move in the very same "
       f"commit. Suspects: {', '.join(suspects)}. Unfamiliar names? "
       f"'buzz look <suspect>' tells you what each one is. Then probe each "
       f"pair for shared patches ('buzz probe {m} <suspect>') and match "
       f"the DATE. Point at the companion: answer <module>.",
       {"module": other, "anchor": m, "subject": ev["subject"],
        "date": ev["date"], "suspects": suspects, "surprising": surprising},
       xp=25, distance=2)
    return 1


def gen_scar(world: World, zone_id: str, used: set | None = None) -> int:
    """Revert archaeology: a change here was rolled back. Point at the
    module that bears the scar."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    if _sig("scar", zone_id) in used:
        return 0
    for ev in world.reverts:
        mods = [m for m in ev["mods"] if m in world.modules]
        if not mods:
            continue
        m = max(mods, key=lambda x: world.modules[x].commits)
        if world.modules[m].zone != zone_id or _sig("scar", m) in used:
            continue
        used.add(_sig("scar", zone_id))
        used.add(_sig("scar", m))
        _q(world, zone_id, "scar", "point",
           f"The hive remembers a wound. On {ev['date']} a change was "
           f"ROLLED BACK: \"{ev['subject']}\". Somewhere in "
           f"{zone.name} stands the module that bears that scar. Dig "
           f"through the history (git is fair game) and point at it: "
           f"answer <module>.",
           {"module": m, "subject": ev["subject"], "date": ev["date"]},
           xp=20, distance=2)
        return 1
    return 0


def gen_gate(world: World, G: nx.DiGraph, zone_id: str,
             used: set | None = None) -> int:
    """Chokepoint: a pair (a, b) whose every top-level import route runs
    through one module. Point at the gate. Any module whose removal cuts
    a off from b is accepted."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    if _sig("gate", zone_id) in used:
        return 0
    # a repo-wide funnel (registry __init__, core config) is a cut vertex
    # for nearly every pair - gates through it are pattern-matchable and
    # one answer solves them all; require a locally-interesting chokepoint
    max_btw = max((m.betweenness for m in world.modules.values()), default=0) or 1
    funnel = {name for name, m in world.modules.items()
              if m.betweenness >= 0.1 * max_btw}
    cands = sorted(zone.members, key=lambda m: -world.modules[m].betweenness)
    for g in cands[:5]:
        if not G.has_node(g) or world.modules[g].betweenness == 0:
            continue
        if g in funnel:
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
                # accept any cut vertex - but only district-local ones, so
                # the repo-wide funnel can't be a universal skeleton key
                accepted = []
                for c in nx.shortest_path(G, a, b)[1:-1]:
                    if c in funnel:
                        continue
                    H2 = G.copy()
                    H2.remove_node(c)
                    if not nx.has_path(H2, a, b):
                        accepted.append(c)
                if not accepted or g not in accepted:
                    continue
                used.add(_sig("gate", zone_id))
                shown_funnel = sorted(funnel & set(nx.shortest_path(G, a, b)))
                excl = (f" (Repo-wide funnels do not count - here that "
                        f"means: {', '.join(shown_funnel)}.)"
                        if shown_funnel else "")
                _q(world, zone_id, "gate", "point",
                   f"The gate. Every top-level import route from {a} to {b} "
                   f"squeezes through a single LOCAL chokepoint - remove "
                   f"that one module and {a} loses {b} entirely.{excl} "
                   f"Point at the chokepoint: answer <module>.",
                   {"a": a, "b": b, "module": g,
                    "accepted": sorted(set(accepted)),
                    "witness": nx.shortest_path(G, a, b)},
                   xp=10 * (dist + 1), distance=dist + 1)
                return 1
    return 0


# --- the decision tier ---------------------------------------------------
# Rounds 13/14, every panel: by the third district the measurement
# templates (count, select, trace) stop teaching. These quests ask for a
# JUDGEMENT - safest deletion, best refactor, valid migration order - and
# the ground truth is still computed, never opined.

def gen_cut(world: World, G: nx.DiGraph, zone_id: str,
            used: set | None = None) -> int:
    """Decision: one of these modules must be torn down - which demolition
    strands the FEWEST others? (safe removal = smallest reverse reach)"""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    if _sig("cut", zone_id) in used:
        return 0
    sized = sorted(
        (len(nx.ancestors(G, m)), m) for m in zone.members
        if G.has_node(m) and len(nx.ancestors(G, m)) >= 1)
    if len(sized) < 4:
        return 0
    low_n = sized[0][0]
    lows = [m for n, m in sized if n == low_n][:2]  # ties are both right
    bigger = [m for n, m in sized if n >= low_n + 2][-4:]
    if len(bigger) < 3:
        return 0
    cands = sorted(lows + bigger)
    sizes = {m: n for n, m in sized if m in cands}
    used.add(_sig("cut", zone_id))
    tie = (" (Candidates may tie for fewest - any pick at the minimum "
           "counts.)" if len(lows) > 1 else "")
    _q(world, zone_id, "cut", "point",
       f"The demolition order. Budget cuts: exactly one of these modules "
       f"will be deleted outright - {', '.join(cands)}. Every module that "
       f"transitively imports the victim (top-level chains) is stranded "
       f"with it. Which deletion strands the FEWEST other modules?{tie} "
       f"{EDGE_RULE} Point at the safe demolition: answer <module>.",
       {"module": lows[0], "accepted": lows, "candidates": cands,
        "sizes": sizes},
       xp=25, distance=3)
    return 1


def gen_refactor(world: World, G: nx.DiGraph, zone_id: str,
                 used: set | None = None) -> int:
    """Decision: two importers of x each propose dropping their import -
    which severed edge actually shrinks x's blast radius?"""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    if _sig("refactor", zone_id) in used:
        return 0
    for x in sorted(zone.members, key=lambda m: -world.modules[m].in_degree):
        if not G.has_node(x):
            continue
        ins = [e.src for e in world.in_edges(x)
               if e.kind == TOP and G.has_node(e.src)][:5]
        if len(ins) < 2:
            continue
        base = len(nx.ancestors(G, x))
        outcome = []
        for a in ins:
            G2 = G.copy()
            G2.remove_edge(a, x)
            outcome.append((len(nx.ancestors(G2, x)), a))
        outcome.sort()
        (n_win, winner), (n_lose, loser) = outcome[0], outcome[-1]
        if n_lose - n_win < 2:
            continue  # both cuts land alike - no real decision to teach
        # the SECOND refactor in a world changes shape (a panel solved the
        # repeat by rote): a three-way council where every cut helps, just
        # unevenly - comparison of magnitudes, not spot-the-decoy
        second = any(q.qtype == "refactor" for q in world.questions.values())
        distinct = []
        for n, a in outcome:
            if not distinct or n > distinct[-1][0]:
                distinct.append((n, a))
        if second and len(distinct) >= 3:
            (n1, w1), (n2, w2), (n3, w3) = distinct[0], distinct[1], distinct[2]
            used.add(_sig("refactor", zone_id))
            _q(world, zone_id, "refactor", "edge",
               f"The refactor council reconvenes - three proposals this "
               f"time. {w1}, {w2} and {w3} each import {x} top-level, and "
               f"each owner proposes severing THEIR import to shrink {x}'s "
               f"blast radius (today: {base} modules reach {x} through "
               f"always-run chains). All three cuts change something - but "
               f"not equally. Which single severed import shrinks the "
               f"radius MOST? {EDGE_RULE} Answer with that edge: "
               f"answer <importer> {x}.",
               {"src": w1, "dst": x, "loser": w3, "base": base,
                "n_win": n1, "n_lose": n3,
                "others": [[w2, n2], [w3, n3]]},
               xp=35, distance=3)
            return 1
        used.add(_sig("refactor", zone_id))
        _q(world, zone_id, "refactor", "edge",
           f"The refactor council. {x} is imported top-level by both "
           f"{winner} and {loser}, and each owner proposes severing THEIR "
           f"import to shrink {x}'s blast radius (today: {base} modules "
           f"can reach {x} through always-run chains). Redundant routes "
           f"make some cuts pointless - the reach just flows around them. "
           f"Which single severed import shrinks the radius more? "
           f"{EDGE_RULE} Answer with that edge: answer <importer> {x}.",
           {"src": winner, "dst": x, "loser": loser, "base": base,
            "n_win": n_win, "n_lose": n_lose},
           xp=30, distance=3)
        return 1
    return 0


def gen_via(world: World, G: nx.DiGraph, zone_id: str,
            used: set | None = None) -> int:
    """Escalated walk: the inspection tour must pass THROUGH a waypoint."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    if _sig("via", zone_id) in used:
        return 0
    # a panel caught the second via coming out EASIER than the first -
    # repeats must escalate, so later instances demand a longer tour
    min_len = 3 + sum(1 for q in world.questions.values()
                      if q.qtype == "via")
    for via in sorted(zone.members,
                      key=lambda m: -world.modules[m].betweenness):
        if not G.has_node(via):
            continue
        for src in sorted(nx.ancestors(G, via)):
            d1 = nx.shortest_path_length(G, src, via)
            if not 1 <= d1 <= 2:
                continue
            for dst in sorted(nx.descendants(G, via)):
                if dst == src:
                    continue
                d2 = nx.shortest_path_length(G, via, dst)
                if not 1 <= d2 <= 2 or d1 + d2 < min_len:
                    continue
                if _sig("walk", src, dst) in used or \
                        _sig("via", src, via, dst) in used:
                    continue
                # the waypoint must force a real reroute: if every natural
                # (shortest) route already passes through it, the
                # constraint is a checkbox, not a decision
                if via in nx.shortest_path(G, src, dst):
                    continue
                example = (nx.shortest_path(G, src, via)
                           + nx.shortest_path(G, via, dst)[1:])
                used.add(_sig("via", zone_id))
                used.add(_sig("via", src, via, dst))
                used.add(_sig("walk", src, dst))  # no duplicate plain walk
                _q(world, zone_id, "via", "walk",
                   f"The inspection tour. Walk a top-level import chain "
                   f"from {src} all the way to {dst} - but protocol says "
                   f"the tour MUST pass through {via} on the way. "
                   f"answer <module> <module> ... (start at {src}, "
                   f"end at {dst}, {via} somewhere between).",
                   {"src": src, "dst": dst, "via": via, "example": example},
                   xp=10 * (len(example)), distance=len(example))
                return 1
    return 0


def gen_order(world: World, G: nx.DiGraph, zone_id: str,
              used: set | None = None) -> int:
    """Migration order: rewrite bottom-up - any valid dependency-respecting
    order is accepted, verified topologically."""
    from itertools import combinations
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    if _sig("order", zone_id) in used:
        return 0
    members = [m for m in zone.members if G.has_node(m)]
    if len(members) > 10:
        members = sorted(members,
                         key=lambda m: -world.modules[m].pagerank)[:10]
    # prefer 5-module instances (harder to eyeball off one edges dump);
    # fall back to 4. A full chain on k nodes has k*(k-1)/2 transitive
    # pairs and exactly ONE valid order - copy-the-arrows, no decision -
    # so the pair count is capped strictly below that. The SECOND order
    # quest in a world must carry a red herring: a function-level or
    # type-only import between two of the modules that constrains NOTHING
    # (a panel solved the repeat by rote; this punishes careless reading).
    second = any(q.qtype == "order" for q in world.questions.values())
    for need_herring in ([True, False] if second else [False]):
        for k, lo, hi in ((5, 4, 8), (4, 3, 5)):
            for combo in combinations(sorted(members), k):
                pairs = []
                mutual = False
                for u in combo:
                    for v in combo:
                        if u == v:
                            continue
                        if nx.has_path(G, u, v):
                            if nx.has_path(G, v, u):
                                mutual = True
                            pairs.append((u, v))  # u transitively imports v
                if mutual or not lo <= len(pairs) <= hi:
                    continue
                herring = None
                if need_herring:
                    cset = set(combo)
                    for e in world.edges:
                        # a lazy/type-only edge u->v whose REAL top-level
                        # dependency runs the other way: counting the fake
                        # edge as a constraint yields an INVALID order
                        if (e.kind != TOP and e.src in cset
                                and e.dst in cset
                                and (e.dst, e.src) in pairs):
                            herring = [e.src, e.dst]
                            break
                    if not herring:
                        continue
                H = nx.DiGraph()
                H.add_nodes_from(combo)
                H.add_edges_from((v, u) for u, v in pairs)  # deps first
                example = list(nx.topological_sort(H))
                used.add(_sig("order", zone_id))
                truth = {"set": sorted(combo),
                         "pairs": [[u, v] for u, v in pairs],
                         "example": example}
                if herring:
                    truth["herring"] = herring
                _q(world, zone_id, "order", "order",
                   f"The migration plan. These {k} modules are being "
                   f"rewritten: {', '.join(combo)}. Rule: a module may "
                   f"only be rewritten AFTER everything it imports "
                   f"(directly or through top-level chains) is already "
                   f"done. {EDGE_RULE} Several valid orders exist - give "
                   f"ANY one, dependencies first: answer "
                   f"{' '.join('<' + str(i + 1) + '>' for i in range(k))}.",
                   truth, xp=35 if herring else 30, distance=k)
                return 1
    return 0

def gen_direction(world: World, zone_id: str, count: int = 2,
                  used: set | None = None) -> int:
    """Small-hive filler: who imports whom? On a scripts-scale repo there
    are no multi-hop chains to walk, but edge DIRECTION is still the first
    thing a newcomer gets wrong - and the game can ask it honestly."""
    zone = world.zones[zone_id]
    used = used if used is not None else set()
    made = 0
    for e in sorted(world.edges, key=lambda e: (e.src, e.dst)):
        if made >= count:
            break
        if e.kind != TOP or e.src not in zone.members:
            continue
        pair = _sig("direction", *sorted((e.src, e.dst)))
        if pair in used or world.has_edge(e.dst, e.src):
            continue
        used.add(pair)
        a, b = sorted((e.src, e.dst))
        _q(world, zone_id, "direction", "edge",
           f"Two residents, one dependency: {a} and {b}. Exactly one of "
           f"them imports the other (top-level). Getting this backwards is "
           f"how newcomers break builds - draw the edge the right way: "
           f"answer <importer> <imported>.",
           {"src": e.src, "dst": e.dst},
           xp=10, distance=2)
        made += 1
    return made


def gen_journey(world: World, count: int = 3,
                used: set | None = None) -> int:
    """The flow tier: follow the WORK from a run's entry point. Every hop
    must be a real cross-module function call - imports alone don't count.
    This is the 'how does it actually work' layer: the journey a task
    takes at runtime IS the architecture story."""
    used = used if used is not None else set()
    CG = nx.DiGraph()
    for c in world.calls:
        CG.add_edge(c["src"], c["dst"])
    if not CG.number_of_edges():
        return 0
    entries = [e for e in world.entries if CG.has_node(e)]
    if not entries:  # fall back to call-graph roots that start real work
        entries = sorted((n for n in CG.nodes if CG.in_degree(n) == 0
                          and CG.out_degree(n) >= 1), key=str)[:3]
    # a panel's only complaint: ONE journey in a 22-quest campaign - the
    # skill never got practiced. Mid-tier journeys start from busy hubs
    # deeper in the system, not just the front door
    interior = sorted((n for n in CG.nodes
                       if n not in entries and CG.out_degree(n) >= 2),
                      key=lambda n: (-CG.out_degree(n), str(n)))[:4]
    made = 0
    for e in entries + interior:
        if made >= count:
            break
        lengths = nx.single_source_shortest_path_length(CG, e)
        far = sorted(((d, n) for n, d in lengths.items() if 2 <= d <= 4),
                     key=lambda t: (-t[0], t[1]))
        if not far:
            continue
        # one journey per destination, and never a sub-path of an
        # existing journey - three quests sharing one call spine is the
        # walk-superhighway mistake all over again
        seen_nodes = {n for k, *rest in used if k == "journey-nodes"
                      for n in rest}
        best = None
        for d, dst in far:
            if _sig("journey-dst", dst) in used:
                continue
            path = nx.shortest_path(CG, e, dst)
            fresh = sum(1 for n in path if n not in seen_nodes)
            if fresh < 2:  # a rerun of known ground teaches nothing new
                continue
            score = (fresh, d)
            if best is None or score > best[0]:
                best = (score, d, dst, path)
        if not best:
            continue
        _, d, dst, path = best
        used.add(_sig("journey-dst", dst))
        used.add(_sig("journey-nodes", *path))
        _q(world, world.modules[e].zone, "journey", "walk",
           f"THE JOURNEY. A run begins at {e} - and by the time the work "
           f"is done, code in {dst} has executed. Follow the WORK, not the "
           f"imports: name the stations in order from {e} to {dst}, where "
           f"every hop is a real function CALL from one module into the "
           f"next. Evidence: 'buzz flow <module>' shows who a file you "
           f"have read calls into. answer <module> <module> ...",
           {"src": e, "dst": dst, "example": path, "flow": True},
           xp=15 * d, distance=d + 1)
        made += 1
    return made


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
        # the boss is a staged encounter, not three tagged quests: each
        # stage opens only after the previous one resolves (six rounds of
        # playtesters asked for a climax that escalates)
        boss_qs = [q for q in world.questions.values() if q.boss]
        for i, q in enumerate(boss_qs, 1):
            q.truth["stage"] = i
            if i > 1:
                q.truth["prev_stage"] = boss_qs[i - 2].id
            q.prompt = (f"[BOSS - stage {i}/{len(boss_qs)}] " + q.prompt)

    # the flow tier: 1-2 runtime journeys from real entry points
    gen_journey(world, count=3, used=used)

    # rotate the quest mix so districts play differently, and cap the
    # most repetition-prone types GLOBALLY - a recipe learned once should
    # not be re-run in every district (top playtest complaint)
    def count(qt: str) -> int:
        return sum(1 for q in world.questions.values() if q.qtype == qt)

    # generous caps: the bracketing gate (buzz calibrate) prunes shallow
    # and broken questions afterward, so generation runs wide - scaled so a
    # big repo's post-calibration world isn't clearable at 5% coverage
    # measurement templates tightened round over round: by the fourth
    # blast radius / second hub, panels report re-running a worksheet
    CAPS = {"cycle": 2, "region": 3, "hub": 2, "ghost": 8, "gate": 6,
            "place": 5, "elder": 5, "hotspot": 5, "patch": 6, "scar": 3}

    def capped(qt: str) -> bool:
        return count(qt) >= CAPS.get(qt, 99)

    # non-boss walks are budgeted per WORLD, not per zone: three panels
    # running found a walk (and often two) in literally every district
    WALK_BUDGET = 6

    def walk_left(want: int) -> int:
        return max(0, min(want, WALK_BUDGET - count("walk")))

    for z in sorted(world.zones.values(), key=lambda z: z.order):
        n = 0
        if not capped("cycle"):  # carries the ability unlock, so tried first
            n += gen_cycle(world, Gtop, z.id, used=used)
        mix = z.order % 3
        if mix == 0:
            # git-history quests lead: ghost and patch were the panels'
            # best-moment winners in nearly every round
            if not capped("ghost"):
                n += gen_ghost(world, z.id, used=used)
            if not capped("patch"):
                n += gen_patch(world, z.id, used=used)
            if walk_left(3):
                n += gen_walk(world, Gtop, z.id, count=walk_left(3), used=used)
            if not capped("region"):
                n += gen_region(world, Gtop, z.id, used=used)
            if not capped("hub"):
                n += gen_hub(world, Gtop, z.id, used=used)
        elif mix == 1:
            if walk_left(2):
                n += gen_walk(world, Gtop, z.id, count=walk_left(2), used=used)
            n += gen_detour(world, Gtop, z.id, used=used)
            if not capped("gate"):
                n += gen_gate(world, Gtop, z.id, used=used)
            if not capped("ghost"):
                n += gen_ghost(world, z.id, used=used)
            if not capped("scar"):
                n += gen_scar(world, z.id, used=used)
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
            if not capped("patch"):
                n += gen_patch(world, z.id, used=used)
            if not capped("hub"):
                n += gen_hub(world, Gtop, z.id, used=used)
            if n < 3 and walk_left(1):
                n += gen_walk(world, Gtop, z.id, count=1, used=used)
        # the decision tier: later districts escalate to judgement calls
        # (safest deletion, best refactor, migration order, routed walks)
        # instead of re-running the measurement templates - the panels'
        # top structural ask two rounds running
        if z.order >= 2:
            DCAPS = {"cut": 3, "refactor": 3, "via": 3, "order": 3}
            dgens = [
                ("refactor", lambda: gen_refactor(world, Gtop, z.id, used=used)),
                ("cut", lambda: gen_cut(world, Gtop, z.id, used=used)),
                ("order", lambda: gen_order(world, Gtop, z.id, used=used)),
                ("via", lambda: gen_via(world, Gtop, z.id, used=used)),
            ]
            # fill whichever decision type is globally scarcest first, so
            # every type shows up across a world instead of the rotation
            # starving one of them
            ranked = sorted(enumerate(dgens),
                            key=lambda iv: (count(iv[1][0]),
                                            (iv[0] - z.order) % 4))
            made_d = 0
            for _, (qt, fn) in ranked:
                if made_d >= 2:
                    break
                if count(qt) < DCAPS[qt]:
                    made_d += fn()
            n += made_d
        # top up thin zones only
        if n < 4 and not capped("elder"):
            n += gen_elder(world, z.id, used=used)
        if n < 4 and not capped("hotspot"):
            n += gen_hotspot(world, z.id, used=used)
        if n < 3 and _small(world):
            # a small hive has no chains to walk: git-history and edge-
            # direction quests keep its districts clearable and honest
            if not capped("patch"):
                n += gen_patch(world, z.id, used=used)
            if n < 3:
                n += gen_direction(world, z.id, count=3 - n, used=used)
        if n < 3:  # thin zone: top up so it stays clearable and worthwhile
            if walk_left(1):
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
                  f"answer <importer> <imported>.")
        truth = {"src": a, "dst": b}
    elif q.qtype == "region":
        x = t["target"]
        member = t["region"][0]
        prompt = (f"Follow-up: {member} was in {x}'s blast radius. Draw the first "
                  f"dependency step: between {member} and {x}, who imports whom? "
                  f"answer <importer> <imported>.")
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
                  f"{x} and {top}, who imports whom? answer <importer> <imported>.")
        src, dst = (x, top) if world.has_edge(x, top) else (top, x)
        truth = {"src": src, "dst": dst}
    else:
        return None
    return {"id": fid, "zone": q.zone, "qtype": "direction", "verb": "edge",
            "prompt": prompt, "truth": truth, "xp": max(5, q.xp // 4),
            "distance": 2, "boss": False, "followup_of": q.id}
