"""Deterministic question generation from graph + git ground truth.

Every question stores its truth as graph facts. Anything answerable from a
single file is not generated (design rule: distance >= 2). Difficulty = the
number of distinct files the answer spans; XP scales with it.
"""
from __future__ import annotations

import networkx as nx

from .analyze import top_graph, full_graph
from .model import World, Question, LAZY, ROLE_BOSS

MAX_PER_ZONE = 6
BOSS_XP_MULT = 2


def _q(world: World, zone: str, qtype: str, verb: str, prompt: str, truth: dict,
       xp: int, distance: int, boss: bool = False) -> Question:
    qid = f"q{len(world.questions) + 1}"
    q = Question(id=qid, zone=zone, qtype=qtype, verb=verb, prompt=prompt,
                 truth=truth, xp=xp, distance=distance, boss=boss)
    world.questions[qid] = q
    return q


def gen_walk(world: World, G: nx.DiGraph, zone_id: str, count: int = 2,
             boss: bool = False, dst_pool=None) -> int:
    """Trace an import chain src -> ... -> dst (any valid directed path)."""
    zone = world.zones[zone_id]
    targets = dst_pool or zone.members
    pairs = []
    for a in zone.members:
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
                # prefer paths that end somewhere important
                pairs.append((d, world.modules[b].pagerank, a, b))
    pairs.sort(key=lambda t: (-t[0], -t[1]))
    made = 0
    used: set[str] = set()
    for d, _, a, b in pairs:
        if made >= count or a in used or b in used:
            continue
        used.update((a, b))
        example = nx.shortest_path(G, a, b)
        mult = BOSS_XP_MULT if boss else 1
        _q(world, zone_id, "walk", "walk",
           f"{a} never imports {b} directly, yet changing {b} can break {a}. "
           f"Walk the import chain that connects them: start at {a}, end at {b}, "
           f"naming each module along the way. Any real chain of imports counts.",
           {"src": a, "dst": b, "example": example},
           xp=10 * d * mult, distance=d + 1, boss=boss)
        made += 1
    return made


def gen_region(world: World, G: nx.DiGraph, zone_id: str, boss: bool = False,
               target: str | None = None) -> int:
    """Blast radius: all zone members that transitively import x."""
    zone = world.zones[zone_id]
    best = None
    candidates = [target] if target else sorted(
        zone.members, key=lambda m: -world.modules[m].pagerank)
    for x in candidates:
        if not G.has_node(x):
            continue
        importers = {m for m in zone.members
                     if m != x and G.has_node(m) and nx.has_path(G, m, x)}
        if 2 <= len(importers) <= 8 and len(importers) < len(zone.members) - 1:
            best = (x, importers)
            break
    if not best:
        return 0
    x, importers = best
    depth = max(nx.shortest_path_length(G, m, x) for m in importers)
    mult = BOSS_XP_MULT if boss else 1
    _q(world, zone_id, "region", "region",
       f"Blast radius. You are changing {x}'s public API. Select every module in "
       f"{world.zones[zone_id].name} that could break - everything that imports {x} "
       f"directly or through a chain. Candidates: {', '.join(sorted(zone.members))}.",
       {"target": x, "region": sorted(importers)},
       xp=(10 + 5 * len(importers)) * mult, distance=1 + depth, boss=boss)
    return 1


def gen_cycle(world: World, Gtop: nx.DiGraph, zone_id: str) -> int:
    """Why is this import inside a function? Because top-level would cycle.
    Walk the return path that proves it. Resolving any cycle question
    unlocks the tunnel-vision ability."""
    made = 0
    lazy_edges = [e for e in world.edges if e.kind == LAZY and
                  world.modules[e.src].zone == zone_id]
    for e in lazy_edges:
        if made:
            break
        if not (Gtop.has_node(e.dst) and Gtop.has_node(e.src)):
            continue
        try:
            back = nx.shortest_path(Gtop, e.dst, e.src)
        except nx.NetworkXNoPath:
            continue
        if len(back) < 2 or len(back) > 5:
            continue
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
              target: str | None = None) -> int:
    """Hidden coupling: files that change together with no import edge."""
    zone = world.zones[zone_id]
    pool = [target] if target else sorted(
        zone.members, key=lambda m: -world.modules[m].commits)
    for x in pool:
        partners = [(o, n) for o, n in world.cochange.get(x, []) if n >= 12
                    and not world.has_edge(x, o) and not world.has_edge(o, x)]
        if not partners:
            continue
        accepted = [o for o, _ in partners[:3]]
        topn = partners[0][1]
        mult = BOSS_XP_MULT if boss else 1
        _q(world, zone_id, "ghost", "edge",
           f"Ghost edge. No import connects {x} to it in either direction, yet git "
           f"says they change together constantly ({topn}+ shared commits) - hidden "
           f"coupling the import graph cannot see. Name the module and draw the "
           f"ghost edge: answer edge {x} <your-guess>.",
           {"src": x, "accepted": accepted, "best": partners[0][0], "shared": topn},
           xp=20 * mult, distance=2, boss=boss)
        return 1
    return 0


def gen_place(world: World, G: nx.DiGraph, zone_id: str) -> int:
    """Given a module and its neighbors, place it in the right zone.
    Only high-confidence placements (Louvain is noisy)."""
    zone = world.zones[zone_id]
    for x in sorted(zone.members, key=lambda m: -world.modules[m].in_degree):
        nbrs = sorted(set(G.predecessors(x)) | set(G.successors(x)))
        if len(nbrs) < 3:
            continue
        inside = sum(1 for n in nbrs if world.modules[n].zone == zone_id)
        if inside / len(nbrs) < 0.6:
            continue
        shown = nbrs[:6]
        _q(world, zone_id, "place", "place",
           f"A scout reports a module named {x}. Its import neighbors are: "
           f"{', '.join(shown)}. Which district of the hive does {x} belong to? "
           f"Answer with the zone id or name.",
           {"module": x, "zone": zone_id},
           xp=15, distance=2)
        return 1
    return 0


def generate_questions(world: World) -> None:
    Gtop = top_graph(world)
    Gfull = full_graph(world)
    boss_mods = [m for m, mod in world.modules.items() if mod.role == ROLE_BOSS]
    boss = boss_mods[0] if boss_mods else None

    for z in sorted(world.zones.values(), key=lambda z: z.order):
        n = 0
        n += gen_cycle(world, Gtop, z.id)
        n += gen_walk(world, Gtop, z.id, count=2)
        n += gen_region(world, Gtop, z.id)
        n += gen_ghost(world, z.id)
        if n < MAX_PER_ZONE:
            gen_place(world, Gfull, z.id)

    # Boss fight: three staged questions in the boss's zone, unlocked after
    # clearing 2 zones. The boss is the module where churn x centrality peaks.
    if boss:
        bz = world.modules[boss].zone
        gen_region(world, Gtop, bz, boss=True, target=boss)
        if not gen_walk(world, Gtop, bz, count=1, boss=True, dst_pool=[boss]):
            gen_walk(world, Gtop, bz, count=1, boss=True)
        gen_ghost(world, bz, boss=True, target=boss)
        for q in world.questions.values():
            if q.boss:
                q.prompt = "[BOSS] " + q.prompt


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
