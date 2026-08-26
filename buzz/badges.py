"""Badges: earned titles computed from what a session actually did.

Pure functions of (world, session) - never stored, never revocable by a
data migration, and never worth XP (rule 12: progress is presentation,
the learning is the loot).

Round-W2 staff audit shaped the roster: no badge mintable by command
spam (a look-loop is not cartography), class badges (every-X-solved)
refuse to mint when the world holds fewer than MIN_CLASS instances and
always show their denominator, Clean Sweep means the FULL clear, and
Elder Sage asks for a perfect exam - with a handful of items, 90% was
reachable only at perfection anyway, so the badge now says so.
"""
from __future__ import annotations

from .model import World, Session

MIN_CLASS = 3   # a class badge over 1 quest is a participation trophy


def _class_progress(world, s, qtypes):
    qs = [q for q in world.questions.values() if q.qtype in qtypes]
    got = sum(1 for q in qs if s.resolved.get(q.id) == "correct")
    return got, len(qs)


def _full_clear(world, s) -> bool:
    return bool(world.questions) and all(
        s.resolved.get(q.id) == "correct"
        for q in world.questions.values())


# (name, description, check) - check returns (earned, progress_note)
BADGES = [
    ("First Nectar", "your first correct answer",
     lambda w, s: (any(v == "correct" for v in s.resolved.values()), "")),
    ("Ghost Hunter", "solved every ghost-edge quest",
     lambda w, s: _class(w, s, ("ghost",))),
    ("Archivist", "solved every git-history quest",
     lambda w, s: _class(w, s, ("ghost", "patch", "scar", "elder"))),
    ("Wayfarer", "solved every chain quest",
     lambda w, s: _class(w, s, ("walk", "cycle", "detour", "via",
                                "journey"))),
    ("Clean Sweep", "every quest solved, no hints, no retries",
     lambda w, s: (_full_clear(w, s) and not s.hints and not s.tries, "")),
    ("Streak Lord", "ten clean solves in a row",
     lambda w, s: (s.best_streak >= 10, "")),
    ("Elder Sage", "a perfect exam - every answer recalled",
     lambda w, s: (s.exam.get("best", 0) >= 100, "")),
]


def _class(world, s, qtypes):
    got, total = _class_progress(world, s, qtypes)
    if total < MIN_CLASS:
        return False, f"(needs {MIN_CLASS}+ such quests; this hive has "\
                      f"{total})"
    return got == total, f"({got}/{total})"


def progress(world: World, s: Session) -> list[tuple[str, str, bool, str]]:
    """Every badge with its earned state and denominator note."""
    out = []
    for name, desc, fn in BADGES:
        try:
            ok, note = fn(world, s)
        except Exception:
            ok, note = False, ""
        out.append((name, desc, ok, note))
    return out


def earned(world: World, s: Session) -> list[tuple[str, str]]:
    return [(n, d) for n, d, ok, _ in progress(world, s) if ok]
