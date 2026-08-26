"""The exam: spaced-repetition proof that the learning stuck.

After a run, `buzz exam` re-asks a sample of quests you ALREADY solved -
from memory, no tools, no hints, one attempt each, worth zero XP. The
score is a retention percentage: buzz claims to teach; the exam is where
that claim gets audited. Design rule 12 holds - a failed exam takes
nothing away, it just tells the truth.
"""
from __future__ import annotations

from .model import World, Session
from . import engine

EXAM_SIZE = 8
TITLES = [(0.9, "Elder Sage"), (0.75, "Sage"), (0.5, "Journeybee"),
          (0.0, "Forgetful Forager")]


def start(world: World, s: Session) -> dict:
    solved = [qid for qid, v in s.resolved.items()
              if v == "correct" and qid in world.questions]
    if len(solved) < 4:
        raise engine.GameError(
            "the exam opens after 4 correctly solved quests - go earn "
            "some knowledge worth testing first")
    # newest solves first: recall is hardest-fair on recent learning;
    # deterministic so a re-run re-asks the same set
    qids = list(reversed(solved))[:EXAM_SIZE]
    s.exam = {"qids": qids, "idx": 0, "correct": [], "missed": [],
              "best": s.exam.get("best", 0)}
    return {"total": len(qids), "q": world.questions[qids[0]]}


def current(world: World, s: Session):
    e = s.exam
    if not e or "qids" not in e or e["idx"] >= len(e["qids"]):
        return None
    return world.questions[e["qids"][e["idx"]]]


def grade(world: World, s: Session, args: list[str]) -> dict:
    q = current(world, s)
    if q is None:
        raise engine.GameError("no exam in progress - 'buzz exam' starts one")
    # grade on a permissive scratch session: one strict attempt, no
    # retries, and the REAL session is never touched
    scratch = Session(here=world.start, discovered=[world.start],
                      seen=list(world.modules),
                      abilities=[engine.TUNNEL], boss_open=True)
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
    if done:
        pct = int(round(100 * len(e["correct"]) / len(e["qids"])))
        e["best"] = max(e.get("best", 0), pct)
        result["pct"] = pct
        result["best"] = e["best"]
        result["title"] = next(t for cut, t in TITLES if pct >= cut * 100)
        result["missed"] = list(e["missed"])
    return result
