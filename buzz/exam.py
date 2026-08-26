"""The exam: spaced-repetition proof that the learning stuck.

After a run, `buzz exam` re-asks a sample of quests you ALREADY solved -
from memory, no tools, no hints, one attempt each, worth zero XP. The
score is a retention percentage: buzz claims to teach; the exam is where
that claim gets audited. Design rule 12 holds - a failed exam takes
nothing away, it just tells the truth.

Round-W2 staff audit shaped this file: the sample is OLDEST solves
first (forgetting lives in what you learned longest ago, not in the
last ten minutes), a bare `exam` mid-run RESUMES instead of silently
restarting, grading carries your campaign progress so boss stages stay
gradeable, and a miss shows the truth on the spot - the material was
already yours once.
"""
from __future__ import annotations

import re

from .model import World, Session, Question
from . import engine

EXAM_SIZE = 8
# with a handful of items, 90% is unreachable except at perfection -
# so the top title honestly asks for perfection
TITLES = [(1.0, "Elder Sage"), (0.75, "Sage"), (0.5, "Journeybee"),
          (0.0, "Forgetful Forager")]

_TOOL_HINT = re.compile(
    r"(?<=[.!?)]) [^.!?]*'buzz [^.!?]*[.!?]|"
    r"(?<=[.!?)]) Evidence:[^.!?]*[.!?]", re.S)


def clean_prompt(q: Question) -> str:
    """The quest prompt without its tool-coaching sentences - an exam
    that says 'no tools' should not re-print 'probe each pair'."""
    return _TOOL_HINT.sub("", q.prompt).replace("  ", " ").strip()


def in_progress(s: Session) -> bool:
    e = s.exam
    return bool(e and "qids" in e and e["idx"] < len(e["qids"]))


def start(world: World, s: Session) -> dict:
    if in_progress(s):
        # resuming is the only safe meaning of a bare `exam` mid-run -
        # restarting silently made 'one attempt each' a lie
        e = s.exam
        return {"total": len(e["qids"]), "q": current(world, s),
                "i": e["idx"], "resumed": True}
    solved = [qid for qid, v in s.resolved.items()
              if v == "correct" and qid in world.questions]
    if len(solved) < 4:
        raise engine.GameError(
            "the exam opens after 4 correctly solved quests - go earn "
            "some knowledge worth testing first")
    # OLDEST solves first: that is where forgetting actually lives; a
    # newest-first sample is a recency quiz, not a retention audit.
    # Deterministic, so a re-run after finishing re-asks the same set.
    qids = solved[:EXAM_SIZE]
    s.exam = {"qids": qids, "idx": 0, "correct": [], "missed": [],
              "best": s.exam.get("best", 0)}
    return {"total": len(qids), "q": world.questions[qids[0]], "i": 0,
            "resumed": False}


def current(world: World, s: Session):
    e = s.exam
    if not e or "qids" not in e or e["idx"] >= len(e["qids"]):
        return None
    return world.questions[e["qids"][e["idx"]]]


def truth_line(q: Question) -> str:
    """The canonical answer, so a miss teaches on the spot - this is
    material the player already solved once, nothing new leaks."""
    t = q.truth
    if "example" in t:
        return " -> ".join(t["example"])
    for k in ("best", "module", "target", "order"):
        if k in t:
            v = t[k]
            return " ".join(v) if isinstance(v, list) else str(v)
    if "region" in t:
        return ", ".join(t["region"])
    if "src" in t and "dst" in t:
        return f"{t['src']} -> {t['dst']}"
    if "n" in t:
        return str(t["n"])
    return "(see 'buzz quest %s')" % q.id


def grade(world: World, s: Session, args: list[str]) -> dict:
    q = current(world, s)
    if q is None:
        raise engine.GameError("no exam in progress - 'buzz exam' starts one")
    # grade on a permissive scratch session: one strict attempt, no
    # retries, and the REAL session is never touched. It carries the
    # campaign's OTHER solves so stage-gated quests (the boss) grade
    # exactly as they did when first answered.
    scratch = Session(here=world.start, discovered=[world.start],
                      seen=list(world.modules),
                      abilities=[engine.TUNNEL], boss_open=True,
                      resolved={k: v for k, v in s.resolved.items()
                                if k != q.id})
    scratch.tries = {q.id: 99}
    verb = q.verb
    if args and args[0] in ("walk", "edge", "region", "place", "point",
                            "order"):
        args = args[1:]
    try:
        r = engine.answer(world, scratch, q.id, verb, args)
        ok = bool(r.get("correct") or r.get("partial"))
    except engine.GameError:
        ok = False
    e = s.exam
    (e["correct"] if ok else e["missed"]).append(q.id)
    e["idx"] += 1
    done = e["idx"] >= len(e["qids"])
    result = {"ok": ok, "q": q, "done": done,
              "next": current(world, s) if not done else None,
              "i": e["idx"], "total": len(e["qids"])}
    if not ok:
        result["truth"] = truth_line(q)
    if done:
        pct = int(round(100 * len(e["correct"]) / len(e["qids"])))
        e["best"] = max(e.get("best", 0), pct)
        result["pct"] = pct
        result["best"] = e["best"]
        result["title"] = next(t for cut, t in TITLES if pct >= cut * 100)
        result["missed"] = list(e["missed"])
    return result
