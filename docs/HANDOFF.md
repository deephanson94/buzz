# Handoff

## Snapshot (2026-08-26)

- Working branch: `claude/sonnet-subagents-game-lbvql5`, mirrored to
  `main` (repo default) at every green milestone - both at the
  small-hive-fixes commit. CI (`.github/workflows/ci.yml`: pytest 3.10/3.12
  + clean-install smoke) is green on both; it does NOT run on `feature/**`.
- `feature/decision-quests` holds the decision-quest tier (cut / refactor /
  order / via), validated by panel rounds 15-16, NOT yet merged - the
  owner wants to feel it in a dogfood before merging.
- Owner's dogfood target: a private 9-module scripts repo ("pixie");
  replica of its shape lives in the session scratchpad as `pixieish/`.

## What just happened

- Small-hive support: generator thresholds scale down under 15 modules /
  12 edges, new `direction` quest type, honest "small hive" notice at
  analyze, place quests never target the start module.
- First-contact fixes from the owner's dogfood: shell forgives a leading
  `buzz `, the answer verb is optional (the quest knows its own).
- Panel rounds 15-16 on `feature/decision-quests`: refactor tier validated
  (three-way council), order got branching + a red-herring second instance,
  via forces real detours.

## In flight

- `buzz analyze --lore`: automate the existing author pipeline
  (`buzz/author.py` export_brief/apply_authored) so analyze can call an
  LLM to (a) author semantic "which module owns X?" quests and (b) write
  short district briefs / module glosses, displayed as clearly-marked
  "scout's impressions". Design rule stands: LLM prose is never XP ground
  truth - authored answers must resolve to real modules and pass
  validation; prose briefs are flavor, not answers.

## Next up

1. Finish `analyze --lore` (owner approved; answers "I don't know what
   neuron_tools does" from the dogfood).
2. Merge `feature/decision-quests` into main once the owner has dogfooded
   it (or on their say-so).
3. Flow tier (v2 research): static call-graph quests over entry points -
   "order the modules a task passes through at runtime". The owner's core
   critique: imports/commits teach change-safety, not system
   comprehension; responsibility (lore) and flow are the missing layers.
4. Optional `buzz tui` (textual, as `pip install "buzz[tui]"` extra) -
   approved as long as it is never load-bearing.

## Test / validation state

- `python -m pytest tests/` - 39 passed / 3 skipped on the working branch,
  43/3 on `feature/decision-quests`. `bash scripts/smoke.sh` is the
  clean-install end-to-end check (CI runs it too).
- Playtest methodology: panels of Sonnet subagents play via one-shot
  commands / piped shell against a world in the session scratchpad, then
  return structured JSON verdicts (continue_score / learning_score / per-
  feature feedback). Fix what converges across scouts, re-run a small
  confirmation panel. History and scores: `docs/FINDINGS.md`. Bar: 8/10
  on continue + learning; learning has hit it, continue peaked at 7.33.

## Open questions for the human

- Merge `feature/decision-quests` now or after dogfooding it?
- For `--lore`: is shelling out to the `claude` CLI acceptable as the
  default LLM transport (with ANTHROPIC_API_KEY HTTP fallback)?
