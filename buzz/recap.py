"""Field notes: everything a run taught, compiled into an architecture
summary you keep. On a real onboarding this IS the deliverable - the game
was the pen."""
from __future__ import annotations

from .model import World, Session
from .engine import _explain, get_question, rank, coverage, LESSONS


def render_recap(world: World, s: Session) -> str:
    d, total = coverage(world, s)
    name = world.repo.rsplit("/", 1)[-1]
    lines = [
        f"# Field notes: {name}",
        "",
        f"Scouted by a {rank(world, s)} - {len(s.resolved)}/"
        f"{len(world.questions)} quests resolved, {d}/{total} modules "
        f"visited, {s.xp} XP. Pinned to commit {world.sha[:10]}.",
        "",
        "## What this run established (in the order it was learned)",
        "",
    ]
    seen_lessons = []
    for qid, status in s.resolved.items():
        try:
            q = get_question(world, s, qid)
        except Exception:
            continue
        fact = _explain(world, q)
        if not fact:
            continue
        mark = {"correct": "", "partial": " (partially worked out)",
                "revealed": " (revealed by the oracle)"}[status]
        zone = world.zones[q.zone].name if q.zone in world.zones else q.zone
        lines.append(f"- [{zone}] {fact}{mark}")
        lesson = q.lesson or LESSONS.get(q.qtype, "")
        if lesson and lesson not in seen_lessons:
            seen_lessons.append(lesson)
    if seen_lessons:
        lines += ["", "## Transferable lessons", ""]
        lines += [f"- {l}" for l in seen_lessons]
    boss = next((m for m, mod in world.modules.items()
                 if mod.role == "boss"), None)
    if boss:
        b = world.modules[boss]
        lines += ["", "## Handle with care", "",
                  f"- {boss}: this repo's center of gravity "
                  f"({b.commits} commits, {b.authors} authors, "
                  f"{b.in_degree} direct importers). Review changes to it "
                  f"hardest."]
    lines += ["", f"(regenerate anytime: buzz recap)"]
    return "\n".join(lines)
