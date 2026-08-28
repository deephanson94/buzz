"""Semantic ("lore") quest authoring - the Tier-S content layer.

An external LLM author reads the actual source and proposes questions about
what the code DOES (behavior, responsibility, mechanism), each with a
designated answer module and a suspect list. This bends design rule #14
("ground truth never comes from LLM prose") into: LLM-PROPOSED truth,
SOLVER-VERIFIED - every authored question must still pass the bracketing
gate (buzz calibrate), where a wrong or ambiguous key fails the strong
solver and a priors-guessable one falls to the weak solver. Answers remain
mechanically checkable in play (point at a module).
"""
from __future__ import annotations

import json

from .model import World, Question


def export_brief(world: World, per_zone: int = 2) -> dict:
    """Everything an author agent needs: the map, module facts, and the
    contract for the questions it must return."""
    zones = []
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        mods = sorted(z.members,
                      key=lambda m: -world.modules[m].pagerank)[:12]
        zones.append({
            "id": z.id, "name": z.name, "order": z.order,
            "modules": [{
                "name": m, "path": world.modules[m].path,
                "doc": world.modules[m].doc, "loc": world.modules[m].loc,
                "commits": world.modules[m].commits,
                "role": world.modules[m].role,
            } for m in mods],
        })
    boss = next((m for m, mod in world.modules.items()
                 if mod.role == "boss"), None)
    return {
        "repo": world.repo,
        "questions_per_zone": per_zone,
        "boss_module": boss,
        "zones": zones,
        "contract": {
            "format": ("JSON list; each item: {zone: zone-id, prompt: str, "
                       "answer: module-name, suspects: [4-6 module names "
                       "including the answer], lesson: one-line transferable "
                       "takeaway, hint: one-line nudge that helps without "
                       "revealing}"),
            "voice": (
                "Write in the game's voice: the repo is a hive, districts "
                "are chambers, modules are residents, git history is the "
                "chronicle, long-lived modules are elders, the player is a "
                "scout bee. Lead with the concrete question; let the theme "
                "live in the nouns, not in scene-setting. Never open with a "
                "short dramatic fragment ('The gate.', 'Storm warning.') or "
                "an aphorism - that reads as generated text. Flavor must "
                "never blur the technical claim. Register examples from the "
                "game's own quests: 'A page from the hive's chronicle, "
                "2024-01-09: ...' / 'The old bees whisper that X has a "
                "secret companion...' / 'One building in this district has "
                "been rebuilt far more often than any other...'"),
            "rules": [
                "each question asks WHERE a specific behavior, mechanism, or "
                "responsibility lives - answerable by pointing at ONE module",
                "the answer must be verifiable by reading the answer module's "
                "source (name the function/class in the lesson)",
                "never put the answer module's name (or an obvious fragment "
                "of it) in the prompt",
                "suspects must be plausible - same district or same layer, "
                "not random names",
                "prefer questions whose answer surprises someone who only "
                "read the import graph",
                "lessons are ONE short sentence (under ~20 words) naming "
                "the function or class as evidence - not a paragraph",
            ],
        },
    }


def apply_authored(world: World, items: list[dict]) -> dict:
    """Validate and add authored lore questions. Returns a summary; invalid
    items are reported, not silently dropped."""
    added, rejected = [], []
    for i, it in enumerate(items):
        why = None
        zone = it.get("zone")
        ans = it.get("answer", "")
        suspects = it.get("suspects") or []
        prompt = it.get("prompt", "")
        if zone not in world.zones:
            why = f"unknown zone {zone!r}"
        elif ans not in world.modules:
            why = f"answer {ans!r} is not a module"
        elif ans not in suspects:
            why = "answer missing from suspects"
        elif not (4 <= len(suspects) <= 6):
            why = "need 4-6 suspects"
        elif any(sp not in world.modules for sp in suspects):
            why = "unknown suspect module"
        elif ans.split(".")[-1].strip("_").replace("_", "") in \
                prompt.lower().replace("_", ""):
            why = "prompt leaks the answer's name"
        elif len(prompt) < 60:
            why = "prompt too thin"
        if why:
            rejected.append({"index": i, "why": why})
            continue
        qid = f"q{len(world.questions) + 1}"
        world.questions[qid] = Question(
            id=qid, zone=zone, qtype="lore", verb="point",
            prompt=(f"{prompt.rstrip('.') }. Suspects: "
                    f"{', '.join(sorted(suspects))}. Read the code - the "
                    f"map alone cannot answer this. Point: "
                    f"answer <module>."),
            truth={"module": ans, "suspects": sorted(suspects),
                   "hint": it.get("hint", ""), "why": it.get("lesson", "")},
            xp=30, distance=len(suspects),
            lesson=it.get("lesson", ""))
        added.append(qid)
    return {"added": added, "rejected": rejected}
