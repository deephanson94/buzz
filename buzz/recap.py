"""Field notes: everything a run taught, compiled into an architecture
summary you keep. On a real onboarding this IS the deliverable - the game
was the pen."""
from __future__ import annotations

from .model import World, Session
from .engine import _explain, get_question, rank, coverage, LESSONS


def render_recap(world: World, s: Session) -> str:
    d, total = coverage(world, s)
    name = world.repo.rsplit("/", 1)[-1]
    disc, seen = set(s.discovered), set(s.seen)
    lines = [
        f"# Field notes: {name}",
        "",
        f"Scouted by a {rank(world, s)} - {len(s.resolved)}/"
        f"{len(world.questions)} quests resolved, {d}/{total} modules read, "
        f"{len(seen)}/{total} surveyed (scouted, probed, or named by quest "
        f"work), {s.xp} XP. Pinned to commit {world.sha[:10]}.",
        "",
        "## The hive at a glance",
        "",
    ]
    # the repo's own one-liner, when its root package was read
    root = min(world.modules.values(), key=lambda m: len(m.name))
    if root.name in disc and root.doc:
        lines += [f"{name}: {root.doc}", ""]
    # one line per district actually reached - built from the docstrings and
    # roles this run surfaced, so a newcomer gets the shape, not a quest log
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        hit = [m for m in sorted(z.members) if m in seen]
        if not hit:
            continue  # still under fog - the notes only report what was seen
        notable = sorted(hit, key=lambda m: (-world.modules[m].in_degree,
                                             -world.modules[m].commits))[:4]
        bits = []
        for m in notable:
            mod = world.modules[m]
            tag = f" [{mod.role}]" if mod.role else ""
            doc = f' "{mod.doc}"' if m in disc and mod.doc else ""
            bits.append(f"{m}{tag}{doc}")
        lines.append(f"- **{z.name}** - {len(hit)}/{len(z.members)} modules "
                     f"surveyed. Key parts: {'; '.join(bits)}.")
    lines += [
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
    directory = [m for m in sorted(world.modules) if m in seen]
    if directory:
        lines += ["", "## Directory of everything surveyed", ""]
        unread = 0
        for m in directory:
            if m not in disc:
                unread += 1  # a list of "not yet read" was pure padding
                continue
            mod = world.modules[m]
            tag = f" [{mod.role}]" if mod.role else ""
            lines.append(f"- {m}{tag} - {mod.doc or '(no docstring)'}")
        if unread:
            lines.append(f"- ...plus {unread} module(s) sighted but not "
                         f"yet read")
    lines += ["", f"(regenerate anytime: buzz recap)"]
    return "\n".join(lines)
