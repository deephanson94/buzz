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
| 14 | + interactive shell, HUD, learning beats (UX round, n=3) | **7.33** | 8.00 |
| 15 | + decision tier v1: cut/refactor/order/via (n=3) | 7.00 | 7.67 |
| 16 | decision tier reshaped (confirmation, n=2) | 6.50 | 7.50 |
| 17 | + flow tier: journeys over the call graph (n=2) | 7.00 | 7.50 |
| 18 | overworld map screen (keep-or-kill, n=2+1) | - | - |
| W1 | overworld whispers + fellow scouts (purpose scoring, n=2+1) | - | - |
| W2 | exam + badges (n=2, +confirmation) | 7.00 | 7.00 |
| W2c | exam + badges confirmation (junior) | **8.00** | **8.00** |
| W3 | wanted poster + onboarding export (completionist, n=1) | 7.00 | 8.00 |
| SNAP | tile-snap overworld movement (purpose scoring, n=2+2) | - | - |
| WEB | interactive atlas (purpose scoring, n=2+3) | - | - |

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

Round 14 note: the interactive shell - built from the OWNER's dogfood
feedback, not panel asks - produced the program's best continue score,
and the round-17 flow tier its strongest single quotes ("the first time
the game showed me a request's real path end to end"; the import-vs-call
rejection was "the single best teaching moment in the whole session").
Round 18 used purpose/keep-or-kill scoring instead of continue/learning:
verdict keep-with-changes from both scouts (purpose 4 then 7 as fixes
landed mid-round - which also produced the methodology's contamination
lesson, now a /panel rule: pin the code under test for the whole round).
From round 18c onward, rounds run on the standing roster in
.claude/agents/ via the /panel skill. Round 18c (scout-ux confirmation
burst, 16 driver bursts): markers, overlay-quit, and bee/label fixes all
confirmed clean; one NEW bug - the right wall had no collision because
the 2-column step could hop over a wall whose column parity differed
from the tiles (left wall was parity-aligned, masking the class of bug).
Fixed by testing every swept column, verified against the scout's exact
tmux repro (bee halts at the wall; doorway still passes). 18c also
noted marker count is deliberately not a proxy for quest count (shared
targets collapse onto one '!'; district-wide searches get none).

### The W-rounds (the "long job": three feature waves, each paneled)

**W1 - whispers + fellow scouts** (scout-ux + scout-casual, purpose
scoring). Both scouts caught the launch build's whispers never firing -
verified real: the whisper hung off a successful Enter-travel, which
obeys graph adjacency, so plain walking (the whole point) stayed
silent. Fixed to fire on the walk itself, plus the ux round's asks:
whispers stay on the status line while standing (a one-frame flash
lost to a blink), the spawn tile whispers on first paint, wall bumps
announce themselves, and the HUD names the tile under the bee. Fellow
scouts verified end to end (live positions across concurrent sessions,
shared-tile naming). Confirmation W1c: ship, all five behaviors pass,
purpose 9 (from 4 pre-fix). Methodology note: the whisper fix landed
while scout-ux was mid-round - the pin rule broken a second time; its
pre-fix observations were discounted as contamination and the clean
confirmation run re-established every claim.

**W2 - exam + badges** (scout-staff + scout-junior). The staff audit
was the program's best single report: 93 tool calls, four real bugs,
two hard. (1) Boss stages 2/3 ungradeable in the exam - the scratch
grading session carried no resolved quests, so stage-gating rejected
answers the campaign had accepted; the exam told players they had
forgotten things they had not. (2) Bare `exam` mid-run silently
restarted the attempt, making "one attempt each" unenforceable. Both
convergent critiques shipped: sampling flipped from newest-first (a
recency quiz) to OLDEST solves; badges purged of command-spam mints
(Cartographer/Surveyor cut, First Nectar added, denominators shown,
class badges refuse to mint under 3 instances, Clean Sweep = full
clear, Elder Sage = perfect exam). Confirmation W2c: ship, 8/8 checks,
continue 8 / learning 8. Standing limitation, recorded not fixed:
"no tools" during the exam is an honor system - one process cannot
stop a player running `edges` in another shell.

**W3 - wanted poster + onboarding export** (scout-completionist).
`wanted` earned a clean keep - "a genuine remix of existing evidence
types into one risk-free escalating-clue puzzle, not a re-skin" - won
by real deduction (16 investigation commands, 1 accusation). Honest
structural note: day-2 difficulty collapses once a session's fog is
fully lifted; inherent to per-session fog, recorded as a v2 question.
The export audit caught the recap headline quoting the WRONG file's
docstring (root package picked by shortest name: `cli` beat `waggle`)
- fixed by path depth, plus repo pointer, full hotspot list, and a
"where this survey stopped" handover section.

**SNAP - tile-snap movement** (owner-directed after the dogfood
verdict "I still don't know how the TUI works"). Movement rebuilt: the
bee is always ON a module and one keypress hops to the nearest tile in
that direction, rooms included; a first-visit card teaches the loop.
Round: casual 8/ship ("feels like a game", cold open ~5s), ux hold on
apparent hop non-determinism. The convergent real fixes: overlay close
drains queued input (buffered arrows replayed into the map), vertical
hops weigh row distance against horizontal drift and tie-break toward
column alignment. The ux re-confirmation then re-held on a burst test
- which forensics showed was run on a session whose ONE-TIME card was
already consumed: the keys hit a live map and were ordinary input; the
"replayed" end state was byte-identical to legitimate hop-by-hop
movement. A protocol-tightened final round (card presence PROVEN on
screen before bursting, 3 fresh sessions) verified the drain absorbs
the full burst every time: ship, purpose 7. Methodology lessons: (a) a
scout's bug report needs the same adversarial verification as a
scout's pass; (b) one-shot state (a once-per-session card) silently
invalidates repeat tests - protocols must assert the precondition on
screen, not assume it. Remaining known quirk, now explained on the
card: on sparse rows a vertical hop drifts to the nearest tile, which
can read as sideways movement.

**WEB - the interactive atlas** (inspired by studying archify; ux +
staff, then three staff audit rounds). The atlas grew pan/zoom, search,
a route probe, journey playback, and quest markers - every interaction
computed from the earned graph, verified by driving the page in
headless Chromium. The staff audits were the program's deepest work:
round 1 caught THE STRATA publishing the complete dependency-depth
histogram at turn 0 and district names using 'seen' where the CLI uses
'read'; round 2 confirmed those fixes airtight, then answered q13 by
copying an unplaced module's district off its dossier - unplaced
modules now live in a limbo strip whose coordinates feed every
consumer (edges, search, probe); round 3 confirmed limbo end-to-end
and caught journey labels FABRICATING function names by truncating
identifiers before '()' - and, best of all, that the CLI itself leaks
place answers: 'buzz who' and 'buzz edges' printed '[z4]' for unplaced
modules (now masked to '[???]'). OPEN DESIGN ITEMS: (a) FIXED in round c4's wake -
place quests are now district-independent: they list in 'quests all'
as '(unplaced - its district IS the answer)', never in a district's
own listing, and never gate a zone's clear; 'quests all' also masks
the names of districts with no read member (a virgin session's first
command had been solving both place quests and reading five district
names off one listing); (b) round c3's deepest finding - 'buzz edges <zone>' plus
'buzz who' supply enough free graph that a full clear needed only
9/44 files read: the fog never bound the player. Deciding how much
graph those tools give away for free is a difficulty-model question,
not a bug fix; (c) a district can be *CLEARED* while still named
'??? unexplored' (all its quests solved without a visit) - decide
whether clearing should name it; (d) the post-answer nudge reasons
from the standing zone, not the solved quest's zone; (e1, from round c11, FIXED) quest ids were zone-contiguous
generation ordinals - the id NUMBER alone identified a place quest's
hidden district (18/19 blind placements across six worlds). Ids are
now a deterministic sha-seeded permutation assigned at world-pin
time, references remapped, locked by a regression test. NOTE: worlds
must be re-analyzed to get shuffled ids; old world.json files keep
the oracle. (e2, NEW from round c10) an intermittent LOST WRITE: one correct
answer printed its full CORRECT banner and zone-clear yet nothing
persisted - re-running the identical command banked it. Not
reproduced in three targeted attempts; suspect concurrent one-shot
invocations racing the session file (last-writer-wins). Needs file
locking or write-then-rename with a version check - this silently
deletes a solve, the inverse of rule 4. Also recorded from c10:
FULL CLEAR banner overclaims ('every district mapped' with two
districts unentered), the boss-lair map nudge outlives the boss, and
the streak display is illegible after a hinted solve. (e) round c6's
design critique of the place quest TYPE: its answer is a majority
vote over buzz's own Louvain partition ('which cluster did the
partitioner assign this to'), and hint 1 says as much - unlike gate or
walk quests it may not teach judgement that transfers. Candidate v2:
retire place as a quest type or re-ground it in something the repo
itself asserts (package paths, imports-majority stated as such). Probe verdicts also verified: an earned-sight route that
`buzz trace` confirms hop-for-hop, edge kinds carried into the chain
text with a CAUTION on types-only hops. Methodology: the audit-fix-
confirm loop ran three times because each confirmation found a NEW
true bug - a sign the instrument works, and that visual surfaces need
the same adversarial budget as mechanics.

**The WEB audit chain, closed** (rounds c1-c14, one scout persona,
fourteen rounds, ten oracles found and ten sealed against the
finder's own repros). What began as an interactive-atlas review
became the program's deepest security audit of the game's own
information economy. The arc: per-surface leaks (strata histogram,
district naming, dossiers) -> derived-count oracles (denominators,
fog deltas) -> the naming predicate (known_zones), the label
chokepoint (zone_label), prose masking (mask_prose) -> the primary
key itself (zone-ordinal quest ids, now sha-permuted) -> the
resolution layer (resolve_visible: seven verbs, one refusal
sentence). Closing verdict (c14): 'ship - the audited fixes hold
exactly as claimed... log the edges-driven full-map surveyed reveal
to FINDINGS as the fog model's real remaining soft spot rather than
blocking.' That soft spot is open item (b) with numbers: seven free
`edges` calls take surveyed 6/44 -> 44/44 pre-quest, unlocking
look/go/who/chronicle on the whole board; only flow's read-gate and
the place-quest masks resist. The chain's meta-lesson for the
methodology: an invariant is not a set of patched surfaces - it
needs one enforcement point per CLASS of output (names, prose,
counts, resolution), and a confirmation round that keeps finding new
true bugs is the instrument working, not failing.

**Round PROSE + round FOCUS** (2026-08-28, owner-dogfood-driven, one
scout each). PROSE: the owner read the big-repo quests as "a bit AI
(eg. load-bearing)". Diagnosis: the epigram opener - a portentous
fragment before every question ("The gate.", "Storm warning.", "The
hive remembers a wound.") - plus purple idioms; and the lore voice
contract was literally instructing the author model into the tic
("open each prompt with one flavorful beat"). A scout-impatient
review of the rewrite held round 1 by catching four relapses under
new masks ("Git remembers." = the killed fragment-sting relocated);
round 2 shipped. Lesson: banning a style by example is weaker than
banning the pattern - the tic re-emerges anywhere it isn't named.
FOCUS: "after my buzz edges, i forgot the quest id that im on" -
the game had no current-quest concept. Viewing a quest now tracks
it (prompt becomes `buzz [q6]>`; bare quest/hint/answer target it;
explicit id wins; id-shaped typos refused; resolve clears). Scout
verdict ship, purpose 8, zero bugs. The round's real find: `buzz
play` had ALWAYS silently reset the session (new_session
unconditionally) - re-entering via play wiped a run's XP; likely
behind earlier "state loss" reports. play now resumes (the exam's
W2 fix pattern); fresh runs are explicit (new BUZZ_SESSION).

**Round BIGEDGE / c / c2** (2026-08-29, the first big-repo round:
django, 899 modules, 3115 edges - built because the owner's private
big repo hit walls the pixie-scale panels never could). The wall:
`edges z1` was 768 one-arrow lines and the hub quest asked for
hand-counting across them; the withheld tally was also theater (one
shell pipe reconstructs it), so the misery landed only on eyeball
players. Three rounds: (1) group by import target - 768->193, but
both scouts then solved hubs from ROW LENGTH alone (hiding the
number while printing all 58 names is not withholding); (2) cap
rows at six names + a numberless '...' while the hub quest is open
(never '+N more' - N is the tally), add the `edges <zone> <module>`
lens (uncapped, counted, both directions - also the forward-hop
tool walks lacked); (3) the comparison lens `edges <zone> <m1> <m2>
...` (11 single lenses per hub was ceremony), (leaf) tags on
forward imports (a lens-only walk burned ~19 calls on dead
branches; leafness is graph truth), cross block capped like the
rest, lens lists wrapped (a hub's 89 importers came out as one
2852-char line). Final: 119 lines, hub loop timed at ~24s,
verdict ship at purpose 7. Meta-lesson: a fog rule is only as
honest as its least-equipped bypass - withholding a number while
printing the list it counts is a rule the shell never enforced.
Open residue (owner's call): leaf tags close dead branches but do
not rank live ones - multi-district walk quests (q39-shaped, 4+
hops across 3 districts) still cost 15+ lens calls and walk hints
give only hop count, not direction.
Coda - an instrument limitation made explicit: the owner's next
dogfood called the shipped screen "hard to read, wordy, no colors"
- and no panel could ever have caught that, because scouts drive
the game through pipes, where output is plain BY DESIGN (rule 2),
and text-reading agents have no perception of density or type
anyway. The panel validates information design, loops, and
honesty; color and typography are validated by human eyes and tmux
captures. A restrained paint() pass (gold section headers, cyan
scan anchors, dim meta/tips/tags, yellow leaf tags) went onto
edges and the quest card, with footers deduped; piped output
verified byte-plain, TTY render verified via tmux -e capture.

**Round CARD** (2026-08-31, quest-card redesign on the django world).
Owner, in one sitting: "I see a lot of things, my eyes are painful
and im lost", then the correction that shaped the fix - "instead of
purely cutting, think of what a user will want to continue to play
and learn". Cutting alone makes a spec sheet. What shipped: the
per-type rule sentences demoted to one dim footnote, candidate sets
as a width-aware grid (14 candidates: 14 lines -> 5; on a big repo
near-twins like qwen2_5_vl_pre_encoder / qwen2_vl_pre_encoder had
been hiding inside one wrapped paragraph, and picking the wrong twin
fails the quest), and the pull put back into lines the card already
spent - district progress and the live streak bonus in the header.
Scout verdict: set out to do 3-4 quests, chained SEVEN, naming the
rising streak bonus, the try-next line and unlock moments as what
pulled; field notes it would "bring to a code review". Held the PR
on two dud recipe steps, both fixed: the hub step dumped ~70 lines
to scan for the '...' rows (now the shortlist prints as a
copy-pasteable compare command - which rows are capped is already on
screen, so naming them leaks nothing), and the walk step advertised
`trace`, which only CHECKS a chain you already have; walks now lead
with `who <destination>` because a destination's fan-in is far
narrower than a source's fan-out (the scout had burned ~8 blind
forward calls). It also caught an honesty bug the fog audit missed:
`look` called a function-level edge an "unsealed tunnel" while
`trace` called the identical edge a "sealed tunnel" - the kind never
changes, tunnel-vision only makes it PASSABLE; both now say so, and
trace adds that such an edge never counts as top-level. Cut on the
same evidence: the "solving banks field note #N" footer, which the
scout stopped reading after two quests. Methodology note, against
the color coda above: the panel cannot see typography, but it CAN
answer "do I want to open the next one" - motivation is panel-
testable, density is not.

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
