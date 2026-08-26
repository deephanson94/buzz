---
name: kickoff
description: Orient a fresh session on this project - read the handoff doc, verify repo state, and resume the queued work. Use as the first command in a new session.
---

# /kickoff — resume from the last handoff

Bring yourself fully up to speed, verify the handoff is still true, and
start (or propose) the next queued task.

## Steps

1. Read `docs/HANDOFF.md`. If it does not exist, say so and fall back to
   `docs/FINDINGS.md`, `README.md`, and `git log --oneline -15`.
2. Verify the snapshot against reality — `git branch -a`, head SHAs,
   `python -m pytest tests/ -q`, CI status if reachable. Note any drift
   between the handoff and what you find (someone may have worked since).
3. Report a compact orientation to the user: current state in 3-5 lines,
   any drift found, and the top item from the handoff's "Next up" queue.
4. If the next task is unambiguous, start it. If the handoff lists open
   questions for the human, ask those first instead of guessing.

## Rules

- Trust the repo over the handoff wherever they disagree; say when they do.
- Do not redo completed work listed in "What just happened".
- Keep the orientation short - the point is to start working, not to
  re-summarize the whole project.
