# Session handoff

Start a fresh session with `/kickoff`; end one with `/handoff`.

## Where things stand (2026-08-26, end of the "long job" session)

Twelve PRs merged to main; main is green (pytest 56 passed + smoke) and
carries the full stack:

1. Plain-language pass, shell, HUD (#1) - round 14, best continue 7.33
2. Decision tier: cut / refactor / order / via (#2) - rounds 15-16
3. Flow tier: journeys over the conservative call graph (#3) - round 17
4. Atlas diagrams: THE STRATA + THE JOURNEYS (#4)
5. Overworld TUI (#5) + purpose fixes (#9) - rounds 18-18c
6. help/tui + bare-buzz entry guidance (#6, #7) - owner dogfood fixes
7. Standing scout roster + /panel skill (#8)
8. Exam + badges (#10) - rounds W2/W2c, confirmation 8/8
9. Wanted poster + onboarding export (#11) - round W3
10. Overworld whispers + fellow scouts (#12) - rounds W1/W1c, purpose 9

## The game surface now

`analyze [--lore]` -> `play` (shell) / `tui` (overworld). In-game:
map/look/edges/go/quests/quest/answer/hint/scout/probe/trace/chronicle/
who/flow/notes/atlas/recap/standings/rescout/status/words + `exam`
(retention run, oldest-first, 0 XP), `badges` (earned honors),
`wanted` (daily mystery), `export` (onboarding pack). 15+ quest types
across three tiers (structure / decision / flow) + lore layer.

## Methodology state

- Panels run on the roster in `.claude/agents/` via `/panel`. The pin
  rule was broken TWICE this session (round 18, round W1) - both times
  produced contamination that had to be discounted; use worktrees and
  do not touch the code under test until every scout reports.
- Confirmation rounds after fixes are cheap and decisive (W1c, W2c,
  18c all resolved keep-or-kill cleanly).
- GitHub Actions webhooks dropped once mid-session and recovered;
  the CLAUDE.md stuck-CI playbook (workflow_dispatch) worked as
  written.

## Since the last handoff (the second long job)

PRs #14-#16 merged earlier (adaptive tile width, tile-snap TUI
movement with first-visit card, terminal-fit layout). Then the WEB
chain: the atlas became an interactive instrument (pan/zoom, search,
grounded route probe, journey playback) and its fourteen-round staff
audit hardened the whole game's information economy - one naming
predicate (render.known_zones), one label chokepoint
(render.zone_label), one prose masker (render.mask_prose), one fog
gate for name resolution (engine.resolve_visible), sha-permuted quest
ids, place quests district-independent everywhere. Full story in
FINDINGS ('The WEB audit chain, closed').

## Known open items (small, recorded in FINDINGS)

- Exam "no tools" is an honor system (single process cannot enforce).
- `wanted` day-2 difficulty collapses once fog is fully lifted -
  a v2 question (fog-independent clue ladders?).
- F18a deferred: draw import-edge connectors between overworld tiles.
- Journey/flow quests in the exam accept only the canonical example
  path shape the engine verifies; fine today, worth watching.

## Owner's dogfood loop

```bash
cd <game-dir> && git -C <buzz-checkout> pull
buzz analyze /ssd2/deep/pixie --lore
buzz play        # or: buzz tui
```
