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
    # the root package is the SHALLOWEST __init__.py, not the shortest
    # name - 'cli' outscored 'waggle' and put the CLI's docstring under
    # the repo's headline (caught by the wave-3 export audit)
    root = min(world.modules.values(),
               key=lambda m: (m.path.count("/")
                              if m.path.endswith("__init__.py") else 99,
                              len(m.name)))
    if root.name in disc and root.doc:
        doc = root.doc
        if doc.lower().startswith(name.lower() + ":"):
            doc = doc[len(name) + 1:].strip()  # no 'waggle: waggle: ...'
        lines += [f"{name}: {doc}", ""]
    # one line per district actually reached - built from the docstrings and
    # roles this run surfaced, so a newcomer gets the shape, not a quest log
    from .render import known_zones, masked_modules
    known = known_zones(world, s)
    masked = masked_modules(world, s)
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        # ONE naming predicate everywhere (round c7: recap was a
        # one-command answer key for both place quests), and a module
        # whose placement is an open mystery belongs to no roster
        hit = [m for m in sorted(z.members)
               if m in seen and m not in masked]
        if not hit:
            continue  # still under fog - the notes only report what was seen
        zname = z.name if z.id in known else f"an unnamed district ({z.id})"
        notable = sorted(hit, key=lambda m: (-world.modules[m].in_degree,
                                             -world.modules[m].commits))[:4]
        bits = []
        for m in notable:
            mod = world.modules[m]
            tag = f" [{mod.role}]" if mod.role else ""
            doc = f' "{mod.doc}"' if m in disc and mod.doc else ""
            bits.append(f"{m}{tag}{doc}")
        impression = (f" _{z.brief}_ (scout's impression, AI-written)."
                      if z.brief and z.id in known else "")
        lines.append(f"- **{zname}** -{impression} {len(hit)}/"
                     f"{len(z.members)} modules surveyed. "
                     f"Key parts: {'; '.join(bits)}.")
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
    care = []
    if boss:
        b = world.modules[boss]
        care.append(f"- {boss}: this repo's center of gravity "
                    f"({b.commits} commits, {b.authors} authors, "
                    f"{b.in_degree} direct importers). Review changes to "
                    f"it hardest.")
    # every other surveyed hotspot the run already knows about - a real
    # handover names all the stoves that are hot, not just the hottest
    hot = sorted((m for m in seen if m != boss
                  and world.modules[m].commits >= 10),
                 key=lambda m: -world.modules[m].commits)[:5]
    care += [f"- {m}: high churn ({world.modules[m].commits} commits, "
             f"{world.modules[m].authors} author(s))" for m in hot]
    if care:
        lines += ["", "## Handle with care", ""] + care
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
    from .badges import earned
    got = earned(world, s)
    if got or s.exam.get("best"):
        lines += ["", "## Honors", ""]
        for name, desc in got:
            lines.append(f"- {name}: {desc}")
        if s.exam.get("best"):
            lines.append(f"- Exam retention (best): {s.exam['best']}% - "
                         f"recall proven without tools")
    lines += ["", f"(regenerate anytime: buzz recap)"]
    return "\n".join(lines)
