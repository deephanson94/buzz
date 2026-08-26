---
name: handoff
description: Write the current session's working state into docs/HANDOFF.md and push it, so any future session (any machine, any agent) can resume with /kickoff. Use at the end of a work session or before a risky/long break.
---

# /handoff — bank the session state

Produce `docs/HANDOFF.md` capturing everything a fresh session needs to
resume this project without the current conversation. Then commit and push
it to the working branch (and mirror to `main` if that is the current
convention).

## What to write (all sections required)

1. **Snapshot** — date, branch(es) and their head SHAs, CI state, which
   branch is deployed/stable vs. in-progress.
2. **What just happened** — the last 2-3 completed pieces of work, one
   line each, newest first.
3. **In flight** — anything started but unfinished: the exact file/function,
   what remains, and any gotcha discovered along the way.
4. **Next up** — the agreed queue, in priority order, with a one-line
   rationale each ("who asked / which playtest round demanded it").
5. **Test/validation state** — how to run tests, current pass counts,
   where the playtest worlds and briefs live (scratchpad paths if any),
   and how the panel methodology works in one paragraph.
6. **Open questions for the human** — decisions waiting on the owner.

## Rules

- Write for a reader with ZERO context: no session shorthand, no
  "as discussed". Spell out paths, commands, and reasons.
- Facts only from the repo and this session's actual work — never guess
  states you can verify with `git log`, `git status`, or the test suite.
  Run them if unsure.
- Keep it under ~120 lines: a handoff is a briefing, not a transcript.
- Overwrite the previous HANDOFF.md entirely (git history keeps old ones).
- Commit with message "handoff: <one-line state summary>" and push to the
  designated working branch.
