"""Text rendering: the fog-of-war map IS the architecture diagram."""
from __future__ import annotations

from pathlib import Path

from .model import World, Session, ROLE_GLYPH, LAZY, TYPE
from .engine import coverage, rank, boss_needed, TUNNEL


def masked_modules(world: World, s: Session) -> set[str]:
    """Modules whose district must stay hidden: subject of an open place
    quest (otherwise walking there reads the answer off the map)."""
    return {q.truth["module"] for q in world.questions.values()
            if q.qtype == "place" and q.id not in s.resolved}


def _mod_label(world: World, s: Session, m: str) -> str:
    glyph = ROLE_GLYPH.get(world.modules[m].role, "")
    here = " <YOU>" if m == s.here else ""
    tag = "" if m in s.discovered else "(seen)"
    return f"{m}{glyph and ' ' + glyph}{tag}{here}"


def render_map(world: World, s: Session) -> str:
    d, total = coverage(world, s)
    masked = masked_modules(world, s)
    here_zone = ("??? (unplaced)" if s.here in masked
                 else f"zone {world.modules[s.here].zone}, "
                      f"{world.zones[world.modules[s.here].zone].name}")
    nq = len(world.questions)
    lines = [
        f"=== THE HIVE: {world.repo.rsplit('/', 1)[-1]} "
        f"| quests {len(s.resolved)}/{nq} | modules visited {d}/{total} "
        f"| XP {s.xp} | rank {rank(world, s)} ===",
        f"you are at: {s.here}  ({here_zone})",
        "",
    ]
    unplaced = sorted(m for m in masked if m in s.seen)
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        vis = [m for m in z.members if m in s.seen and m not in masked]
        zq = [q for q in world.questions.values() if q.zone == z.id and not q.boss]
        done = sum(1 for q in zq if q.id in s.resolved)
        n_boss = sum(1 for q in world.questions.values()
                     if q.zone == z.id and q.boss)
        status = (" *CLEARED*" if z.id in s.cleared
                  else " (side content - no quests)" if not zq
                  else f"  quests {done}/{len(zq)}"
                  + (f" +{n_boss} boss" if n_boss else ""))
        known = z.id in {world.modules[m].zone for m in s.discovered}
        title = z.name if known else "??? (unexplored district)"
        lines.append(f"[{z.id}] {title}{status}")
        if z.id in s.cleared and s.here not in z.members:
            # cleared districts collapse to keep the growing map legible
            lines.append(f"  ({len(vis)} module(s) mapped - 'buzz edges "
                         f"{z.id}' for detail)")
            lines.append("")
            continue
        if vis:
            row = []
            for m in sorted(vis, key=lambda m: -world.modules[m].pagerank):
                row.append("  " + _mod_label(world, s, m))
            lines.extend(row)
        hidden = len([m for m in z.members if m not in s.seen])
        if hidden:
            lines.append(f"  ... and {hidden} module(s) under fog")
        lines.append("")
    if unplaced:
        lines.append("unplaced sightings (district unknown until a scout "
                     "places them): " + ", ".join(unplaced))
        lines.append("")
    if not s.boss_open:
        lines.append(f"(boss quests are sealed until {boss_needed(world)} zones are cleared)")
    else:
        lines.append("!! the BOSS LAIR is open - see 'buzz quests' in the boss zone")
    return "\n".join(lines)


def _source_peek(world: World, m) -> list[str]:
    """A glimpse of the actual code: first docstring line + real import
    lines. The game should teach what the code does, not just its shape."""
    try:
        text = (Path(world.repo) / m.path).read_text(encoding="utf-8",
                                                     errors="replace")
    except OSError:
        return []
    lines = []
    for i, raw in enumerate(text.splitlines()[:3], 1):
        t = raw.strip()
        if t.startswith(('"""', "'''", '#')):
            first = t.strip(chr(34) + chr(39) + "# ")[:76]
            if first != (m.doc or ""):  # look already printed the docstring
                lines.append(f"  {first}")
            break
    # column-0 lines only: indented (function-level / TYPE_CHECKING) imports
    # stay hidden, same as the fog rules
    all_imports = [f"  {i}: {raw[:76]}{'...' if len(raw) > 76 else ''}"
                   for i, raw in enumerate(text.splitlines(), 1)
                   if raw.startswith(("import ", "from "))]
    if all_imports:
        lines.append("  top-of-file import lines (verbatim, relative and "
                     "absolute forms are the same edge):")
        lines.extend("  " + ln for ln in all_imports[:25])
        if len(all_imports) > 25:
            lines.append(f"    ... +{len(all_imports) - 25} more import lines")
    return lines


def render_look(world: World, s: Session, at: str | None = None) -> str:
    node = at or s.here
    m = world.modules[node]
    z = world.zones[m.zone]
    zone_line = ("zone: ??? - a scout must place this module (see its "
                 "place quest)" if node in masked_modules(world, s)
                 else f"zone: {z.name} ({z.id}) | role: {m.role}")
    lines = [
        f"--- {node}{'' if node == s.here else '  (spyglass view)'} ---",
        f"file: {m.path} | {m.loc} lines | {m.commits} commits by "
        f"{m.authors} author(s)"
        + (f" | first commit {m.born}" if m.born else ""),
        *([f'"{m.doc}"'] if m.doc else
          [f"~ scout's impression (AI-written, unverified): {m.gloss}"]
          if m.gloss else []),
        zone_line,
        f"imported by {m.in_degree} module(s)"
        + (": " + ", ".join(sorted(e.src for e in world.in_edges(node) if e.src in s.discovered))
           + (" +unknown others" if any(e.src not in s.discovered for e in world.in_edges(node)) else "")
           if m.in_degree else ""),
    ]
    peek = _source_peek(world, m)
    if peek:
        lines.append("")
        lines.extend(peek)
    lines += [
        "",
        "imports (its out-edges - you can walk these with 'buzz go <name>'):",
    ]
    outs = world.out_edges(node)
    if not outs:
        lines.append("  (imports nothing internal - a leaf)")
    for e in sorted(outs, key=lambda e: e.kind):
        if e.kind == LAZY:
            if TUNNEL in s.abilities:
                lines.append(f"  ~ {e.dst}  [tunnel: function-level import - passable]")
            else:
                lines.append("  # ???  [SEALED TUNNEL: a function-level import "
                             "hides its destination - solve a cycle quest]")
        elif e.kind == TYPE:
            lines.append(f"  - {e.dst}  [types-only: never runs]")
        else:
            lines.append(f"  > {e.dst}")
    lines.append("legend: > always-runs | # sealed tunnel | ~ unsealed tunnel "
                 "| - types-only (never runs)")
    return "\n".join(lines)


def _gist(prompt: str, width: int = 66) -> str:
    """One scannable line per open quest - the full text stays behind
    'buzz quest <id>' (wordiness was the first human dogfooder's top
    complaint)."""
    text = " ".join(prompt.split())
    if len(text) <= width:
        return text
    cut = text[:width].rsplit(" ", 1)[0]
    return cut + " ..."


def _status_of(s: Session, qid: str) -> str:
    st = s.resolved.get(qid)
    return {"correct": "SOLVED", "partial": "partial", "revealed": "revealed"}.get(st, "open")


def render_quests(world: World, s: Session, zone_id: str) -> str:
    z = world.zones[zone_id]
    qs = [q for q in world.questions.values() if q.zone == zone_id]
    fus = [q for q in s.followups.values() if q["zone"] == zone_id]
    nb = [q for q in qs if not q.boss]
    done = sum(1 for q in nb if q.id in s.resolved)
    n_boss = len(qs) - len(nb)
    lines = [f"quests in {z.name} ({z.id}) - {done}/{len(nb)} resolved"
             + (f" (+{n_boss} boss quest(s) listed below)" if n_boss else "")
             + (" *CLEARED*" if zone_id in s.cleared else "") + ":"]
    for q in sorted(qs, key=lambda q: (q.boss, q.truth.get("stage", 0), q.id)):
        lock = ""
        if q.boss and not s.boss_open:
            lock = " [LOCKED: clear more zones]"
        elif q.boss and q.truth.get("prev_stage") not in (None, *s.resolved):
            lock = f" [stage {q.truth['stage']}: sealed until the prior stage falls]"
        lines.append(f"  {q.id} [{_status_of(s, q.id)}] ({q.qtype}, {q.xp} XP){lock}")
        if not lock and q.id not in s.resolved:
            lines.append(f"        {_gist(q.prompt)}")
    for f in fus:
        lines.append(f"  {f['id']} [{_status_of(s, f['id'])}] (follow-up, {f['xp']} XP)")
    lines.append("")
    lines.append("read one with 'buzz quest <id>', answer with 'buzz answer <id> ...'")
    return "\n".join(lines)


def render_question(world: World, s: Session, q) -> str:
    # placeholders named for what THIS quest means, not the wire verb - a
    # dogfooder met 'edge <importer> <imported>' on an elder quest whose
    # two names mean <older> <newer>
    shapes = {
        "elder": "<older> <newer>",
        "direction": "<importer> <imported>",
        "ghost": "<one-of-the-pair> <the-other>",
        "refactor": "<importer> <imported>",
        "walk": "<module> <module> ... (a chain, one import per hop)",
        "journey": "<module> <module> ... (each hop a real function CALL)",
        "region": "<module> <module> ... (the whole affected set)",
        "place": "<district-id-or-name>",
        "order": "<first> <second> ... (dependencies first)",
    }
    by_verb = {"walk": "<module> <module> ...",
               "edge": "<importer> <imported>",
               "region": "<module> <module> ...",
               "place": "<district-id-or-name>",
               "point": "<module>", "order": "<first> <second> ..."}
    shape = shapes.get(q.qtype, by_verb[q.verb])
    syntax = f"buzz answer {q.id} {shape}"
    st = _status_of(s, q.id)
    rule = ""
    if q.verb == "walk":
        rule = ("edge rule: top-level (always-run) edges ONLY"
                if q.qtype in ("cycle", "detour") else
                "edge rule: any import edge you can traverse counts "
                "(sealed tunnels too, once tunnel-vision is unlocked)")
    evidence = ""
    if q.qtype in ("region", "hub", "gate", "hotspot"):
        # the tool that cracks these fastest, surfaced where it's needed
        # instead of buried in help (a panel found it too late)
        evidence = (f"evidence: 'buzz edges {q.zone}' dumps this district's "
                    f"import edges, tallied")
    lines = [f"[{q.id}] ({q.qtype}, {q.xp} XP, status: {st})", "", q.prompt,
             *([rule] if rule else []),
             *([evidence] if evidence else []), "",
             f"answer syntax: {syntax}",
             f"stuck? 'buzz hint {q.id}' (level 1 free-ish, costs XP; level 3 reveals)"]
    return "\n".join(lines)


def _badge_line(world: World, s: Session) -> str:
    from .badges import earned
    got = ", ".join(name for name, _ in earned(world, s))
    line = f"badges: {got or 'none yet'}"
    if s.exam.get("best"):
        line += f" | exam best: {s.exam['best']}% retention"
    from .exam import in_progress
    if in_progress(s):
        e = s.exam
        line += (f"\nEXAM IN PROGRESS [{e['idx'] + 1}"
                 f"/{len(e['qids'])}] - 'buzz exam' shows the question")
    return line


def render_status(world: World, s: Session) -> str:
    d, total = coverage(world, s)
    solved = sum(1 for v in s.resolved.values() if v == "correct")
    total_xp = sum(q.xp for q in world.questions.values())
    attempted = len(s.resolved)
    clean = sum(1 for qid, v in s.resolved.items()
                if v == "correct" and not s.hints.get(qid)
                and not s.tries.get(qid))
    lines = [
        f"XP {s.xp} (base pool {total_xp}; streak bonuses stack on top) "
        f"| rank: {rank(world, s)} (rank only ever climbs)"
        + (f" | solved: {solved}/{attempted} attempted"
           f" ({clean} clean - no hints, no retries)"
           if attempted else ""),
        f"coverage: {d}/{total} modules read, {len(s.seen)}/{total} surveyed "
        f"(read = visited/spyglassed; surveyed = named by scouting, probing, "
        f"or quest work - both are real reconnaissance)",
        f"zones cleared: {len(s.cleared)}/"
        f"{sum(1 for z in world.zones if any(q.zone == z and not q.boss for q in world.questions.values()))}"
        f" clearable"
        + (f" ({', '.join(world.zones[z].name for z in s.cleared)})" if s.cleared else ""),
        f"questions: {solved} solved, "
        f"{sum(1 for v in s.resolved.values() if v == 'partial')} partial, "
        f"{sum(1 for v in s.resolved.values() if v == 'revealed')} revealed",
        f"streak: {s.streak} clean solve(s) in a row"
        + (f" (+{min(50, 5 * s.streak)}% XP on the next clean solve)"
           if s.streak else " (first-try, hint-free solves build a bonus)"),
        f"abilities: {', '.join(s.abilities) or 'none yet'}",
        _badge_line(world, s),
        "boss lair: " + (
            "CLEARED" if (boss_qs := [q for q in world.questions.values() if q.boss])
            and all(q.id in s.resolved for q in boss_qs)
            else "OPEN" if s.boss_open else "sealed"),
    ]
    if s.victory:
        clearable = {z for z in world.zones
                     if any(q.zone == z and not q.boss
                            for q in world.questions.values())}
        left = len(clearable - set(s.cleared))
        lines.append("")
        if left:
            lines.append(f"*** CAMPAIGN CLEAR - the hive's heart is mapped. "
                         f"Rank: {rank(world, s)} ***")
            lines.append(f"({left} endgame district(s) stay open for 100% "
                         f"hunters - or point buzz at another repo)")
        else:
            lines.append(f"*** FULL CLEAR - the load-bearing core of this "
                         f"hive is mapped. Final rank: {rank(world, s)} ***")
            lines.append("(quests target the structure that matters, not "
                         "every file - most of the fog is side rooms)")
    if s.log:
        recent = s.log[-3:]
        if s.victory:
            # a stale "endgame districts stay open" line contradicts a
            # FULL CLEAR banner - drop superseded lines from the recap
            clearable = {z for z in world.zones
                         if any(q.zone == z and not q.boss
                                for q in world.questions.values())}
            if clearable <= set(s.cleared):
                recent = [l for l in recent if "endgame" not in l]
        if recent:
            lines.append("")
            lines.append("recent events: " + "; ".join(recent))
    return "\n".join(lines)


HELP = """buzz - learn how a repo works by exploring it

setup:
  buzz analyze <repo-path>     build the world (run once, from the game dir)
  buzz play                    start (or restart) a session - on a real
                               terminal this drops you into the interactive
                               shell (tab-completion, no 'buzz' prefix)
  buzz shell                   re-enter the shell for an existing session
                               (bare 'buzz' works too)

exploring (free, no XP):
  buzz map                     the fog-of-war hive map
  buzz look [module]           inspect where you stand - or spyglass any
                               module you can see on the map
  buzz edges [zone]            dump a district's internal top-level edges
                               (the audit trail behind hub/gate quests)
  buzz go <module>             walk an import edge, fast-travel anywhere
                               visited, or scout-fly to any module you can
                               see on the map
  buzz probe <a> <b> [c ...]   how are two modules related? shows import
                               edges (and their kind) + git co-change count;
                               extra names compare <a> against EACH of them
                               (fan-out, not a chain - for chains use trace)
  buzz trace <m1> <m2> ...     free dry-run of a proposed chain: reports
                               each hop's status and edge kind
  buzz chronicle <module>      the module's focused commits and reverts
                               from git history
  buzz who <module>            who imports it, across the whole hive
  buzz atlas                   render the hive as a visual map (HTML file
                               with real fog-of-war - open in a browser)
  buzz notes                   the transferable lessons banked so far,
                               one line each (the quick mid-run glance)
  buzz recap                   compile everything this run taught into
                               field notes (your keepable architecture
                               summary of the repo)
  buzz standings               leaderboard across every scout playing this
                               hive (sessions share one world)
  buzz tui                     the OVERWORLD: a walkable map screen - your
                               bee, the arrow keys, the fog lifting tile
                               by tile (Enter travels, l looks, Q leaves)
  buzz rescout [repo]          new-game+: see what changed since your
                               world was pinned - disturbed districts,
                               and fresh AFTERSHOCK quests from real new
                               commits
  buzz scout <zone>            reveal a district's module NAMES (not edges)
  buzz quests all              one-line progress for every district

quests (the only source of XP):
  buzz quests                  quests in your current zone
  buzz quest <id>              read one quest
  buzz answer <id> walk m1 m2 ...      trace an import chain
  buzz answer <id> edge <importer> <imported>   draw a dependency edge
  buzz answer <id> region m1 m2 ...    select a blast radius
  buzz answer <id> place <zone>        place a module in its district
  buzz answer <id> point <module>      point at the module a quest describes
  buzz hint <id>               oracle hint ladder (costs XP; 3rd hint reveals)

  buzz status                  XP, rank, abilities, victory progress
  buzz exam                    after 4+ solves: re-answer your oldest
                               solves from memory - no tools, 0 XP, a
                               retention score and a title
  buzz badges                  earned honors, computed from what you
                               actually did (never bought with XP)

Edge kinds matter: `>` top-level imports always run; `#` sealed tunnels are
function-level imports (walkable after a cycle quest unlocks tunnel-vision);
`-` TYPE_CHECKING imports never run. Blast-radius questions count ONLY
top-level chains.

The economy: a wrong answer never subtracts XP or removes progress - it
reveals the truth (and may spawn a follow-up quest). But it is not free
information either: walk/region quests burn a retry (-30% of that quest's
XP each), hints discount that quest, and any miss, hint, or retry HALVES
your streak - clean first-try solves stack a +5%-per-solve XP bonus.
Module names are forgiving: any unique tail works ('backend' or
'trunkline.backend' both name transports.trunkline.backend).
Clear 2 zones to open the boss lair. The boss plus 3 cleared districts is
CAMPAIGN CLEAR - the win. Districts beyond that are optional endgame; clear
them all for the FULL CLEAR title.
"""


GLOSSARY = """the hive's words, in plain language:

  module          one source file. The rooms of the game.
  district (zone) a cluster of modules that belong together, found by
                  community detection on the import graph. Ids: z1, z2...
                  Commands take either the id or the name.
  edge            one import: 'pixie -> adbc' means pixie imports adbc.
  top-level       an import at the top of a file. Always runs when the
                  file loads - these carry breakage.
  sealed tunnel   an import hidden INSIDE a function. Invisible (# ???)
                  until a cycle quest unlocks tunnel-vision.
  types-only      an import used only for type hints. Never runs.
  the fog         files you have not seen yet.
  scout           send scouts over a district: you learn the NAMES of its
                  files, nothing else.
  spyglass        'look <m>': read a file you can see without moving.
  probe           ask how two files are related: import edges between
                  them plus commits that touched both.
  trace           dry-run a chain of imports - free, no attempt spent.
  who             list every file that imports one.
  chronicle       one file's commit history, from git.
  blast radius    everything that (transitively) imports a file - what
                  could break when it changes.
  overworld       'buzz tui': the walkable map screen - your bee, the
                  arrow keys, and the fog lifting tile by tile. A skin
                  over the same engine; answers stay in the shell.
  flow / journey  where the WORK goes at runtime: real function calls
                  between modules. An import without a call carries no
                  work - 'buzz flow <m>' shows a read file's calls.
  ghost edge      two files with NO import between them that git shows
                  changing together constantly - hidden coupling.
  boss            the repo's center of gravity: highest churn x
                  centrality. Its quests are the endgame.
  bedrock/gate/   roles from metrics: bedrock = stable + widely imported;
  swamp           gate = a chokepoint on many paths; swamp = many authors
                  and heavy rework.
  streak          consecutive clean solves: +5% XP each, halves on a miss.
  scout's         a one-liner written by an AI, clearly marked, worth
  impression      0 XP - flavor, never ground truth.
  wanted poster   the daily mystery: one module described only by its
                  mechanical shape (degrees, size, age). 3 guesses,
                  misses sharpen the poster, a capture pays a bounty.
  onboarding      'buzz export' bundles the atlas + field notes into a
  pack            directory you can hand to the next person who joins
                  the codebase.
  exam            a recall run over quests you already solved - oldest
                  first, no tools, one attempt each, 0 XP. The score is
                  retention; only your best is kept.
  badge           an earned honor computed from what your session did.
                  Never worth XP, never mintable by command spam.

(back to the moves: help)"""
