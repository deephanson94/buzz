# Handoff

## Snapshot (2026-08-26, end of day)

- `main` (default) holds EVERYTHING: shell + overworld, lore, small-hive
  support, decision tier, flow tier, atlas diagrams. PRs #1-#5 all
  merged, CI green (via workflow_dispatch where webhooks dropped - see
  CLAUDE.md's stuck-CI playbook). Feature branches may be deleted.
- Branch model: main stays stable; feature branches merge via PR.

## What just happened

- PR #5 overworld: buzz tui, a curses map screen - bee walks districts
  with arrow keys, fog lifts tile by tile; never load-bearing.
- PR #4 atlas diagrams: THE STRATA (layers) + THE JOURNEYS (sequence
  strips for solved journeys) - both earned, fog-respecting.
- PR #3 flow tier: conservative call graph (buzz/flow.py), JOURNEY
  quests, buzz flow tool. Panel round 17: junior 7/8, staff 7/7.
- PR #2 decision tier: cut/refactor/order/via. Panel rounds 15-16.
- analyze --lore: automated semantic layer (owner-validated on their
  private repo, voice-tuned to the hive register).

## In flight

- Nothing mid-edit. All work is merged and tested (48 passed, 3 skipped).

## Next up

1. Owner dogfoods the full stack on their private repo ("pixie"):
   git pull && buzz analyze <repo> --lore && buzz play / buzz tui.
   Their verdict decides the next lever - they are the instrument now.
2. Possible next levers, unranked until that verdict: overworld polish
   (quest markers on tiles?), journey branching at dynamic-dispatch
   seams (round-17 staff ask), multi-language analysis, a combined-
   stack panel round on waggle.

## Test / validation state

- python -m pytest tests/ (48/3 on main), bash scripts/smoke.sh.
- Panel methodology + 17 rounds of history: docs/FINDINGS.md.
- CI: pushes to main/claude/**/feature/** + PRs + workflow_dispatch.
  If runs do not materialize or stick in queued: CLAUDE.md playbook.

## Open questions for the human

- None blocking. Overworld verdict (walking vs typing go) most wanted.
