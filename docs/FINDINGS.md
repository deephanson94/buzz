# Playtest program findings (v1, 12 rounds, 78 playtest sessions)

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
| 10 | + lore tier, all fixes | **7.17** | 8.00 |
| 11 | + trace/chronicle, consistency fixes | 6.83 | 7.83 |
| 12 | synthetic priors-free repo ("waggle") | 6.33 | 7.83* |
| 13 | + atlas/recap/standings/aftershock/staged boss (feature round, n=4) | 6.25 | 7.75 |

*Round 12 produced the program's deepest individual verdicts (an 8/9 and
the first 9-learning score) alongside its lowest (4-continue from the
completionist, who full-cleared with zero mistakes).

Round 13 was a feature-validation round: every new feature was confirmed
working and worth keeping (the standings' shared-world liveness and the
staged boss's stage-3 ghost drew the round's best-moments), and its
convergent asks were shipped immediately after: rescout reporting standing
aftershocks (a confirmed bug), a live "now in" column on standings, a
repo-overview + surveyed-directory recap, probe-based pre-guess evidence
for patch quests, soft streak decay (halve, not reset), atlas zone-name
reveal on first sighting, and a tighter region cap.

**Learning met the bar** (8.00 across four separate rounds, both repos;
every claim graph-, git-, or source-checkable). **Continue peaked at 7.17
(round 10) and plateaued in the 6-7.2 band** with round-to-round noise of
about +/-0.4; individual 8-continue verdicts appeared in rounds 8, 10, 11
and 12, but no panel averaged 8.

## The three-factor difficulty model (the program's core result)

Solver calibration across three repos shows question survivability - and
play difficulty - is governed by:

1. **Rater priors**: on famous public repos (rich, peft) the weak solver
   answers 46-76% of questions from memory + one file.
2. **Conventionality**: on a fictional repo no model has seen (waggle,
   built for round 12 with designed teaching moments), the weak solver
   STILL answered 69% - a strong model infers a cleanly-structured,
   well-documented codebase from names and docstrings alone. Synthetic
   repos are legible by design.
3. **Messiness x unfamiliarity** is therefore where buzz discriminates:
   real, accumulated, undocumented weirdness in codebases outside training
   data - i.e. actual private repos, the product's target. A Sonnet panel
   structurally cannot simulate that player experience: it defeats famous
   repos by memory and clean repos by convention.

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

1. **Human playtesting on a real private repo** - the panel instrument is
   saturated; the remaining signal lives exactly where agents can't rate.
2. The visual map layer (asked for in 6+ rounds): the fog-of-war metaphor
   deserves a rendered graph, per the original design doc's v2 plan.
3. Boss as a composite encounter (ghost + gate + walk chained on one
   module) - requested in six separate rounds.
4. End-of-run consolidated recap of every earned lesson line as the run's
   architecture summary (round 12 suggestion; cheap, high payoff).
5. Lore authoring rule: answers must live in code bodies, never in a
   docstring that states them (round 12: self-documenting repos leak).
6. Control arm for the bar: pass = buzz beats plain-reading by 2+ points.
7. Tier-2 (execution traces, mutation) when a repo's test suite runs.
