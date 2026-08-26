---
name: panel
description: Run a playtest panel round - the repo's validation instrument for gameplay changes (CLAUDE.md rule 3). Spawns scout subagents against a real world, collects structured verdicts, and fixes what converges. Use before merging any gameplay change, or whenever feedback is wanted.
---

# /panel — run a playtest round

The roster lives in `.claude/agents/`: scout-staff (opus, transfer
skeptic), scout-junior (sonnet, learnability), scout-impatient (sonnet,
wordiness/pacing), scout-completionist (sonnet, re-skin detection),
scout-ux (sonnet, screens/feedback loops), scout-casual (haiku, cheap
first-contact signal). Pick 2-4 whose specialty matches what changed;
add scout-casual to almost any round - it is cheap.

## Steps

1. **Prepare a world** in a scratch directory: clone or reuse a target
   repo (a mid-size unfamiliar one beats a toy; a synthetic priors-free
   repo beats a famous one - see docs/FINDINGS.md on rater priors), then
   `buzz analyze <repo>` there with the code under test installed.
2. **Write a brief** file in the scratch dir. It MUST contain: the setup
   block (game dir, `export BUZZ_SESSION=<given in task>`, `buzz play`);
   the round's focus (what changed, what question the round answers);
   play expectations (command count, zones, what to exercise); the
   honesty calibration line (average prototype = 5-6, 8+ = would keep
   playing unprompted); and the exact JSON report contract - always
   include continue_score, learning_score, learned (checkable claims),
   best_moment, worst_moment, suggestions, bugs, plus round-specific
   fields. Agents cannot use interactive readline: tell them to pipe
   shell bursts (`printf 'quests\nquit\n' | buzz shell`) or use one-shot
   commands; for the tui, point them at a pty driver script.
3. **Launch** the chosen scouts concurrently via the Agent tool
   (subagent_type = the scout's name). Each prompt: the brief path + a
   unique session name (panelXNa, panelXNb, ...). Sessions share the
   world - that is a feature (standings, shared fog stay honest).
4. **Aggregate** when all verdicts land: average the scores, then list
   findings by CONVERGENCE (how many scouts hit the same thing),
   quoting their words. One scout's taste is an opinion; two scouts'
   agreement is a finding; a bug report is a finding at n=1.
5. **Fix what converges**, then confirm with a small follow-up round
   (1-2 scouts, fresh sessions) before merging. Record the round's
   scores and what changed in docs/FINDINGS.md.

## Rules

- Never skip the panel for a gameplay change because it is "just a
  view" or "optional" - that mistake shipped an aimless screen once.
- Scouts never read the game's implementation; they play it.
- Panel scores saturate: agents tolerate what humans will not (walls of
  text) and know what humans do not (architecture priors). The owner's
  own dogfood reports outrank any panel average - panels find the
  convergent fixable, humans find the truth.
