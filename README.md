# Buzz

A fog-of-war game that teaches how a repo works — from architecture down to
import-level detail. Coding agents write faster than developers read; Buzz
makes repo comprehension motivating and measurable.

The codebase is a hive. You are a scout bee. The map starts dark: walk the
import edges, light up the districts, and prove you understand how the code
fits together. The completed map IS the architecture diagram.

## Quickstart

```bash
pip install -e .
mkdir game && cd game
buzz analyze /path/to/some/repo     # build the world (seconds; Python repos)
buzz play                           # wake up in the hive
```

On a real terminal, `buzz play` drops you into an interactive shell: no
`buzz` prefix, tab-completion over commands and every module name you have
sighted (the completer respects the fog), a persistent one-line HUD
(xp / streak / facts learned / where you are), and a colored verdict on
every answer. Re-enter anytime with bare `buzz`. `buzz tui` opens the
OVERWORLD: a top-down map screen where your bee walks the districts with
the arrow keys and the fog lifts tile by tile (Enter travels, l looks,
e lists quests - answers stay in the shell). Every command also works
one-shot (`buzz map`, `buzz answer q3 ...`) for pipes, agents, and CI.
`buzz wanted` posts a daily mystery module - three guesses from its
mechanical silhouette. `buzz export` bundles the atlas and field notes
into an onboarding pack you can hand to the next person.

State lives in `./.buzz/` (`BUZZ_SESSION=<name>` for parallel sessions
sharing one world - `buzz standings` is the leaderboard across them -
`BUZZ_DIR` to relocate).

## How it plays

- **Explore free, earn by proving.** Walking reveals the map but pays no XP.
  XP comes only from quests, so grinding is impossible.
- **Answers are spatial, not multiple choice.** You answer by moving or
  arranging: `answer q3 walk console segment syntax` traces an import chain;
  `answer q7 region a b c` selects a blast radius; `answer q2 edge x y`
  draws a dependency edge; `answer q9 place z2` places a module in its
  district.
- **Wrong answers reveal the truth** and spawn a smaller follow-up quest.
  Progress is never removed.
- **Sealed tunnels (Metroidvania).** Function-level imports hide their
  destination (`# ???`) and are impassable until you solve a cycle quest —
  walking the import cycle that *forces* the import to be lazy — which
  unlocks tunnel-vision everywhere, retroactively revealing every sealed
  destination you walked past.
- **Roles from metrics.** The module where churn × centrality peaks is the
  BOSS (its quests unlock after clearing 2 zones). High pagerank + low churn
  is bedrock; high betweenness is a gate; many authors × churn is a swamp.
- **Ghost edges.** Files with zero imports between them that git says change
  together constantly — hidden coupling the import graph cannot see.
  `buzz probe <a> <b>` is the in-game instrument: it reports import edges
  (and their kind) plus the co-change count between any two modules.
- **Git archaeology quests.** Patch quests hand you a real commit subject
  and ask which second module had to move with it (`buzz probe` supplies
  the pair evidence); scar quests dig up reverts; elder quests date the
  architecture. `buzz rescout` diffs the repo against the world's pinned
  commit and spawns AFTERSHOCK quests from commits that landed since.
- **The oracle.** A 3-level hint ladder priced in XP; the third hint reveals
  the answer for zero XP. Clean first-try solves build a streak bonus; a
  miss halves the streak (XP is never subtracted).
- **Campaign arc.** The boss is a STAGED, hive-scale encounter (blast
  radius, the longest march, the strongest ghost coupling - stages unseal
  in order). Boss + 3 cleared districts is CAMPAIGN CLEAR — the win, landed
  while the game is fresh. Everything beyond is optional endgame; clearing
  it all earns FULL CLEAR.
- **The learning is the loot.** Every resolved quest - win or lose - banks
  a field note. `buzz notes` is the mid-run glance; `buzz recap` compiles
  the run into evidence-backed onboarding notes for the repo; `buzz atlas`
  renders the fog-of-war map as an interactive HTML file with per-module
  dossiers.

## Ground truth

Every answer is verified against the AST import graph or git history —
never against generated prose. The analyzer (`buzz/analyze.py`) computes:
AST import graph (top-level / function-level / TYPE_CHECKING edges,
`__main__`-block imports excluded), PageRank, betweenness, Louvain zones,
git churn / author counts / co-change coupling (mega-commits skipped).
Anything answerable from a single file is never asked.

## Design doc

See `docs/DESIGN_V1.md` for the full design and `docs/FINDINGS.md` for the
14-round playtest program that shaped it. v1 notes:

- **Text-first**: the terminal is the primary surface (`buzz atlas` renders
  the same world model as HTML). Chosen so both humans and agents can play
  the identical game.
- **LLM optional, never trusted for truth**: quest *text* is templated by
  default. The solver-bracketing quality gate is real (`buzz calibrate
  export/apply`: questions a shallow solver cracks or a strong solver
  cannot are pruned), and an optional authored tier exists (`buzz author
  export/apply`: LLM-written semantic questions, validated so the answer
  resolves and never leaks). Ground truth always comes from the graph or
  git.
- **Languages**: Python analysis only in v1 (git questions are
  language-agnostic by construction, wired to Python worlds for now).

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/
```
