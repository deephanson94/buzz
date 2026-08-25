"""Bracketing quality gate (design doc: "question quality gate").

1. Weak pass: a solver given ONLY the question's anchor file(s) answers
   correctly -> the question is too shallow, discard it.
2. Strong pass: an agentic solver with read/grep tools and a call budget
   can't answer -> ambiguous or wrong key, discard it.
3. Keep the band between. The strong solver's tool-call count becomes the
   question's empirical difficulty; divergence from graph distance marks
   misleading code (the most valuable questions).

The solvers themselves are external LLM agents - this module only exports
the work orders, grades answers against ground truth, and applies verdicts.
"""
from __future__ import annotations

import json
from pathlib import Path

from .model import World, Session, Question
from . import engine


def anchor_files(world: World, q: Question) -> list[str]:
    """What the weak (local-context-only) solver is allowed to read."""
    t = q.truth
    mods: list[str] = []
    if q.qtype in ("walk", "detour", "ghost"):
        mods = [t["src"]]
    elif q.qtype == "cycle":
        mods = [t["lazy_src"]]
    elif q.qtype == "region":
        mods = [t["target"]]
    elif q.qtype == "place":
        mods = [t["module"]]
    elif q.qtype == "elder":
        mods = [t["src"], t["dst"]]
    # hub / gate / hotspot: prompt-only - no file answers them locally
    return [world.modules[m].path for m in mods if m in world.modules]


def export(world: World) -> list[dict]:
    out = []
    for q in world.questions.values():
        if q.qtype == "place":
            # place answers are zone ids - game vocabulary solvers don't
            # have; they can't be judged fairly, so they are auto-kept
            continue
        syntax = {
            "walk": f"walk <module> <module> ...",
            "edge": f"edge <importer-or-elder> <imported-or-newcomer>",
            "region": f"region <module> <module> ...",
            "place": f"place <zone-id>",
            "point": f"point <module>",
        }[q.verb]
        out.append({
            "id": q.id, "qtype": q.qtype, "verb": q.verb, "zone": q.zone,
            "prompt": q.prompt, "answer_syntax": syntax,
            "graph_distance": q.distance,
            "anchor_files": anchor_files(world, q),
        })
    return out


def check(world: World, qid: str, verb: str, args: list[str]) -> bool:
    """Grade an answer against ground truth with no session side effects.
    Permissive posture: abilities unlocked, boss open, no retries."""
    if qid not in world.questions:
        raise engine.GameError(f"no question {qid}")
    s = Session(here=world.start, discovered=[world.start],
                seen=list(world.modules), abilities=[engine.TUNNEL],
                boss_open=True)
    s.tries = {qid: 99}  # exhaust retries: one strict attempt
    try:
        r = engine.answer(world, s, qid, verb, args)
    except engine.GameError:
        return False
    return bool(r.get("correct") or r.get("partial"))


def apply_verdicts(world: World, results: dict) -> dict:
    """results: {qid: {"weak_solved": bool, "strong_solved": bool,
    "strong_tool_calls": int}} -> prune the question set in place and
    return a summary. Unlisted questions are kept untouched."""
    dropped_shallow, dropped_broken, divergent, kept = [], [], [], []
    for qid, r in results.items():
        q = world.questions.get(qid)
        if not q:
            continue
        if q.qtype == "cycle" and qid in world.questions:
            # never drop the last unlock quest of the world
            cycles = [x for x in world.questions.values() if x.qtype == "cycle"]
            if len(cycles) <= 1:
                kept.append(qid)
                continue
        if r.get("weak_solved"):
            dropped_shallow.append(qid)
            del world.questions[qid]
            continue
        if not r.get("strong_solved", True):
            dropped_broken.append(qid)
            del world.questions[qid]
            continue
        calls = int(r.get("strong_tool_calls", 0))
        if calls:
            q.truth["empirical_calls"] = calls
            # divergence between empirical and graph difficulty marks
            # misleading code - flag and reward it
            if calls >= 2 * q.distance:
                divergent.append(qid)
                q.xp = int(q.xp * 1.5)
                q.prompt += (" [The archives say this one misleads even "
                             "seasoned scouts - bonus XP.]")
        kept.append(qid)
    return {"dropped_shallow": dropped_shallow, "dropped_broken": dropped_broken,
            "divergent": divergent, "kept": kept}
