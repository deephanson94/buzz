"""Badges: earned titles computed from what a session actually did.

Pure functions of (world, session) - never stored, never revocable by a
data migration, and never worth XP (rule 12: progress is presentation,
the learning is the loot)."""
from __future__ import annotations

from .model import World, Session


def _all_of(world, s, qtypes) -> bool:
    qs = [q for q in world.questions.values() if q.qtype in qtypes]
    return bool(qs) and all(s.resolved.get(q.id) == "correct" for q in qs)


BADGES = [
    ("Cartographer", "read every module in the hive",
     lambda w, s: len(set(s.discovered)) == len(w.modules)),
    ("Surveyor", "put every module on the map",
     lambda w, s: len(set(s.seen)) == len(w.modules)),
    ("Ghost Hunter", "solved every ghost-edge quest",
     lambda w, s: _all_of(w, s, ("ghost",))),
    ("Archivist", "solved every git-history quest",
     lambda w, s: _all_of(w, s, ("ghost", "patch", "scar", "elder"))),
    ("Wayfarer", "solved every chain quest",
     lambda w, s: _all_of(w, s, ("walk", "cycle", "detour", "via",
                                 "journey"))),
    ("Clean Sweep", "campaign clear with no hints and no retries",
     lambda w, s: s.victory and not s.hints and not s.tries),
    ("Streak Lord", "ten clean solves in a row",
     lambda w, s: s.best_streak >= 10),
    ("Elder Sage", "90%+ retention on the exam",
     lambda w, s: s.exam.get("best", 0) >= 90),
]


def earned(world: World, s: Session) -> list[tuple[str, str]]:
    out = []
    for name, desc, fn in BADGES:
        try:
            if fn(world, s):
                out.append((name, desc))
        except Exception:
            continue
    return out
