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
buzz help                           # everything else
```

The game is a stateful CLI: every command prints the current view and a
contextual "try next". State lives in `./.buzz/` (`BUZZ_SESSION=<name>` for
parallel sessions over one world, `BUZZ_DIR` to relocate).

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
- **The oracle.** A 3-level hint ladder priced in XP; the third hint reveals
  the answer for zero XP.
- **Two-stage ending.** The boss fight is hive-scale (import-time footprint,
  the longest march, the strongest ghost coupling) and felling the boss is a
  big moment — but victory means clearing every district.

## Ground truth

Every answer is verified against the AST import graph or git history —
never against generated prose. The analyzer (`buzz/analyze.py`) computes:
AST import graph (top-level / function-level / TYPE_CHECKING edges,
`__main__`-block imports excluded), PageRank, betweenness, Louvain zones,
git churn / author counts / co-change coupling (mega-commits skipped).
Anything answerable from a single file is never asked.

## Design doc

See `docs/DESIGN_V1.md` for the full design. v1 deviations from it:

- **Text-first**: the 2D map is rendered as text; a graphical renderer is a
  later layer on the same world model. Chosen so both humans (terminal) and
  agents can play the identical game.
- **No LLM in the pipeline**: v1 question *text* is templated, not generated;
  the LLM bracketing filter is replaced by the graph-distance floor. Hints
  are deterministic. This keeps `analyze` at ~10s for a 4.5k-commit repo.
- **Languages**: Python analysis only in v1 (git questions are
  language-agnostic by construction, wired to Python worlds for now).

## Development

```bash
pip install -e . pytest
python -m pytest tests/
```
