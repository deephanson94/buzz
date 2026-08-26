# Playtest program findings (v1, 10 rounds, 60+ agent sessions)

Method: panels of six Sonnet agents with fixed personas (methodical,
speedrunner, junior dev, game critic, completionist, staff engineer) play a
full session and return structured verdicts: `continue_score` (want to keep
playing, 1-10) and `learning_score` (learned real, checkable things, 1-10),
plus learned-claims, best/worst moments, frictions, and bugs. Fixes are
applied between rounds. Passing bar: 8/10 on both.

## Scores

| Round | Build | Continue | Learning |
|---|---|---|---|
| 1 | rich, first playable | 5.83 | 7.50 |
| 2 | + real boss, witness chains, probe | 6.50 | 7.83 |
| 3 | + retries, masking, scout | 6.83 | 7.67 |
| 4 | + flavor variants, detour, spyglass | 6.83 | 7.83 |
| 5 | + Tier-1 git quests (regression: pipe crash) | 6.17 | 7.67 |
| 6 | + crash fix, caps, campaign arc | 6.67 | 8.00 |
| 7 | peft, solver-calibrated | 6.33 | 8.00 |
| 8 | + streaks, patch quests | 6.83 | 8.00 |
| 9 | + wide generation (regression: gate funnel) | 6.00 | 7.67 |
| 10 | + lore tier, all fixes | (in flight) | (in flight) |

**Learning met the bar** (8.00 across three separate rounds, both repos;
every claim graph- or git-checkable). **Continue plateaued at 6-7** with
round-to-round noise of about +/-0.4.

## What reliably delighted (panel best-moments, recurring)

- Ghost edges: co-change coupling with zero imports (console/default_styles
  41 commits; utils.other/peft __init__ 35 commits) - "the import graph said
  unrelated, git said inseparable".
- The tunnel-vision unlock teaching lazy-import cycle-breaking across zones.
- Boss import-time footprint: modules that load transitively despite the
  boss's own edges being sealed.
- Patch quests: a real commit's hidden companion file ("genuine detective
  work with a verifiable payoff").

## What capped continue

1. **Priors dominate on public repos.** The bracketing gate (weak solver =
   prompt + anchor file only; strong solver = agentic with budget) discarded
   46-76% of generated questions per round as guessable-without-reading -
   including 9 of 10 LLM-authored semantic questions. Sonnet already knows
   rich and peft. The corollary is the project's real positioning: **buzz's
   discriminating power is on codebases outside the model's training data -
   private repos, i.e. the actual onboarding use case.** Public-repo panels
   systematically understate the game.
2. Deterministic quest recipes become mechanical lookups once learned;
   variety additions (10 quest types, flavor rotation, arc changes) each
   bought ~+0.3-0.5 continue, then a new degeneracy appeared (gate quests
   collapsing onto registry funnels, walk superhighways).
3. Rater ceiling: the game-critic persona never scored continue above 7 in
   ten rounds. A control arm (rating plain repo-reading the same way) would
   measure lift instead of absolute enthusiasm.

## Pipeline learnings (now encoded in the code)

- Phantom edges are trust-killers: `__main__`-guarded and BoolOp-guarded
  demo imports must be excluded; absolute-vs-relative resolution must match
  the repo layout (src/ transparency doubled peft's edge count).
- Louvain explodes on plugin registries (peft: 35 zones -> 10 after folding
  low-external-degree communities); god modules need one role each.
- Every ruling must carry its witness (chains in region/gate reveals);
  every tool output that names a module must un-fog it.
- Wrong answers need retries at a discount, not one-shot reveals; stakes
  work as streak bonuses, never XP loss (design rule 12 holds).
- Overgenerate, then let the solver gate prune (the gate is the quality
  mechanism the design doc promised, and it works - including on
  LLM-authored questions, where it caught 9 shallow keys out of 10).

## Recommended next steps

1. Playtest on a repo outside the raters' priors (private or post-cutoff)
   - the single most informative unrun experiment.
2. Control arm for the bar: pass = buzz beats plain-reading by 2+ points.
3. Boss as a composite encounter (ghost + gate + walk chained on one
   module) - requested in five separate rounds.
4. Tier-2 (execution traces, mutation) when a repo's test suite runs.
