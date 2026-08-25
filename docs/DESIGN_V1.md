# Buzz — Design Doc v1

Game that teaches how a repo works, from architecture down to line-level detail. Motivation: coding agents write faster than developers read; make repo comprehension motivating and measurable.

## Settled decisions

1. **Scope of v1: whole-repo onboarding.** Point at any repo (GitHub URL or local clone). PR-review mode ("game around one diff + blast radius") is a later mode of the same pipeline, not v1.
2. **Answers are spatial, not multiple choice.** The answer to a question is a movement or arrangement: walk the execution path, place the module on the map, draw the dependency edge, select the blast-radius region. Multiple choice is the fallback for questions that can't be spatialized. If most content ends up as MC, the design has failed.
3. **The map IS the architecture diagram.** One artifact: fog-of-war graph map that fills in as the player explores. The completed map is the fast-travel screen and the player's externalized mental model. No separate "diagram collection" mode.
4. **Abstraction level is a zoom axis** (system → module → file → function → line), not a separate code panel.
5. **2D first.** Learning value wins over fidelity. Character/embodiment later if content proves out. 3D is v2+ at most; if built, terrain is generated from the graph (rooms=modules sized by LOC, corridors=imports weighted by coupling).
6. **Not a maze — fog-of-war coverage.** A repo has no exit. Goal is coverage of important nodes.
7. **Eager structure, lazy questions.** Full graph/metrics/zones computed up front (cheap, deterministic). LLM question generation streamed one zone ahead of the player (expensive).
8. **Difficulty = graph traversal distance**: number of distinct files needed to answer, weighted by edge type (direct import 1, dynamic/protocol/config wiring 3). Anything answerable from one file is auto-discarded as trivial.
9. **Indirection = locked abilities (Metroidvania).** Edges you can't follow by eye (protocol dispatch, event bus, DI, lazy imports) are impassable until the player proves understanding of the mechanism; then that edge type unlocks everywhere. This is the core progression mechanic.
10. **Pin to commit SHA.** Diff between SHAs → incremental zone invalidation → "this zone changed since you cleared it" quests = retention mechanic.
11. **LLM cheating → in-game oracle.** The model is a priced game resource giving Socratic hints, not an adversary outside the game. Detailed design deferred.
12. **Wrong answers reveal + spawn follow-up.** Never remove progress. No XP from walking; grinding must be impossible.
13. **Cross-language edge inference (shared strings: endpoints, topics, table names): v2.**
14. **Ground truth never comes from LLM prose.** LLM writes flavor, zone names, distractors. Answers come from the graph, git, or (when the repo runs) traces/mutation.

## Content pipeline (tiers)

- **Tier 0 (always works, no execution):** AST import graph; PageRank, betweenness, in/out-degree; Louvain zones; git churn, author counts, co-change coupling; lazy-import cycle detection; LOC.
- **Tier 1 (git semantics):** diff-comprehension questions from real PRs; revert/refix pairs; blame archaeology; co-change "hidden coupling" questions.
- **Tier 2 (only if repo runs — detect via CI config/Dockerfile):** execution traces from test suite (call-order questions), mutation testing (blast-radius ground truth).
- **Language scope v1:** Python/TypeScript/Go for call-graph-level analysis; Tier 0/1 git questions are language-agnostic fallback for everything else.

## Role assignment (level design from metrics)

| Signal | Role |
|---|---|
| churn × (pagerank+betweenness) max | **Boss** |
| high pagerank × low churn | Bedrock zone (early, mandatory) |
| high betweenness | Gate / locked door |
| authors × churn | Swamp ("why is it like this" quests) |
| low centrality leaf | Optional side content |

Each module gets ONE dominant role (boss precedence first) — god modules otherwise saturate every list (observed: rich's console.py was #1 boss, gate, and swamp simultaneously).

## Question quality gate (bracketing filter)

1. Weak pass: solver with only the local file in context answers correctly → too shallow, discard.
2. Strong pass: agentic solver with grep/read tools + call budget can't answer → ambiguous/wrong key, discard.
3. Keep the band between. Distractors separately verified false against the graph.
4. Solver tool-call count = empirical difficulty; log divergence from graph-distance difficulty (divergence marks misleading code — the most valuable questions).

## Validation run: Textualize/rich (4460 commits, 77 modules, 362 top-level edges)

Algorithm picks vs. human intuition — matched:

- **Boss: console.py** — in-degree 50/77, out-degree 36, 467 commits, 44 authors, 2698 LOC. The known god module. ✓
- **Bedrock: style, text, segment** — the render primitives everything rests on. ✓
- **Gates: console, text, table, color** (betweenness). ✓
- **Swamp: progress, pretty, traceback** (many authors × churn). ✓
- **Zones (Louvain, 6):** markup/emoji; color/style/palette; live/progress/spinner/prompt; console+platform internals; pretty/inspect/table/layout; segment/panel/markdown/syntax. Mostly thematic, some noise (text landed in the live zone).
- **Protocol layer invisible to imports:** 43 `__rich_console__` implementations across 30 files. Rich's real architecture is consumer-protocol (console consumes anything implementing the protocol) — the import graph can't see it. Confirms the "protocol edge = locked ability" mechanic is load-bearing, not decorative.
- **Lazy imports as design decisions:** 20 function-level-only internal imports; **13 would create import cycles if top-level** (e.g. color→style lazily while style→color top-level; console→pretty/traceback/rule lazily because they import console). Auto-generates verified "why is this import inside the function?" questions via graph reachability check.
- **Co-change coupling:** console+table (77 shared commits), table+text (43), syntax+text (37), markdown+text (35) — hidden-coupling question source. Skip mega-commits (>15 files) as formatting sweeps.

Caveats found: Louvain is noisy on small graphs (needs a "does this zone make sense" LLM sanity pass for naming/merging); god modules need role dedup; betweenness ≈ pagerank on this graph size (may not need both).

## Open questions for implementation session

- Map rendering: force-directed vs. generated tilemap; how fog-of-war reveals edges vs. nodes.
- Exact spatial-answer verbs and their verification against the graph (path-walk, node-place, edge-draw, region-select).
- Oracle pricing/economy; hint ladder design.
- Session shape: meaningful loop must fit in 15 minutes.
- Zone ordering: topological over the condensed zone graph, bedrock first.

Analysis code from the validation run: single-file Python (ast + networkx + git log parsing), ~150 lines, seconds to run on rich. Reproduce: parse imports (track function-level separately), pagerank/betweenness/louvain, `git log --name-only` for churn/authors/co-change.
