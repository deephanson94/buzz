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


def known_zones(world: World, s: Session) -> set[str]:
    """The ONE predicate for 'may this district's name be printed'.
    Round c6's oracle: any per-surface variant of this test eventually
    disagrees with another and the disagreement is an answer. A zone's
    name is known iff a PLACED member has been read (a placement-masked
    module must not unlock its own hidden district - 'look' on it says
    '???' and used to flip the map), or its place quest is resolved
    (the player proved, or was shown, the placement)."""
    masked = masked_modules(world, s)
    known = {world.modules[m].zone for m in s.discovered
             if m in world.modules and m not in masked}
    for q in world.questions.values():
        if q.qtype == "place" and (q.id in s.resolved
                                   or s.hints.get(q.id, 0) >= 3):
            # resolved, or the oracle's level-3 hint said it out loud -
            # the map must not pretend otherwise (round c10)
            known.add(q.truth["zone"])
    # clearing a district is proof enough to learn its name
    known |= set(s.cleared)
    return known


def zone_label(world: World, s: Session, zid: str) -> str:
    """THE way to print a district's name. Every surface calls this or
    leaks (rounds c6-c8 found eight sites re-implementing the rule)."""
    if zid not in world.zones:
        return str(zid)
    if zid in known_zones(world, s):
        return world.zones[zid].name
    return f"an unexplored district ({zid})"


def mask_prose(world: World, s: Session, text: str) -> str:
    """Substitute unearned district names out of any prose (quest
    prompts and gists bake names in at generation time)."""
    known = known_zones(world, s)
    for z in world.zones.values():
        if z.id not in known and z.name:
            text = text.replace(z.name, f"district {z.id} (unexplored)")
    return text


def _mod_label(world: World, s: Session, m: str) -> str:
    from .ui import paint
    glyph = ROLE_GLYPH.get(world.modules[m].role, "")
    # read modules stand out from merely-sighted ones: the map's whole
    # job is showing what you have actually been to
    name = paint(m, "cyan") if m in s.discovered else m
    here = paint(" <YOU>", "gold") if m == s.here else ""
    tag = "" if m in s.discovered else paint(" (seen)", "dim")
    return f"{name}{glyph and ' ' + glyph}{tag}{here}"


def render_map(world: World, s: Session) -> str:
    d, total = coverage(world, s)
    masked = masked_modules(world, s)
    here_zone = ("??? (unplaced)" if s.here in masked
                 else f"zone {world.modules[s.here].zone}, "
                      f"{world.zones[world.modules[s.here].zone].name}")
    nq = len(world.questions)
    from .ui import paint
    lines = [
        paint(f"=== THE HIVE: {world.repo.rsplit('/', 1)[-1]} "
              f"| quests {len(s.resolved)}/{nq} | modules visited {d}/{total} "
              f"| XP {s.xp} | rank {rank(world, s)} ===", "gold"),
        f"you are at: {paint(s.here, 'cyan')}  {paint('(' + here_zone + ')', 'dim')}",
        "",
    ]
    unplaced = sorted(m for m in masked if m in s.seen)
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        vis = [m for m in z.members if m in s.seen and m not in masked]
        zq = [q for q in world.questions.values()
              if q.zone == z.id and not q.boss and q.qtype != "place"]
        done = sum(1 for q in zq if q.id in s.resolved)
        n_boss = sum(1 for q in world.questions.values()
                     if q.zone == z.id and q.boss)
        status = (paint(" *CLEARED*", "green") if z.id in s.cleared
                  else paint(" (side content - no quests)", "dim") if not zq
                  else f"  quests {done}/{len(zq)}"
                  + (paint(f" +{n_boss} boss", "magenta") if n_boss else ""))
        title = (z.name if z.id in known_zones(world, s)
                 else "??? (unexplored district)")
        lines.append(paint(f"[{z.id}] {title}", "gold") + status)
        if z.id in s.cleared and s.here not in z.members:
            # cleared districts collapse to keep the growing map legible
            lines.append(paint(f"  ({len(vis)} module(s) mapped - 'buzz "
                               f"edges {z.id}' for detail)", "dim"))
            lines.append("")
            continue
        if vis:
            row = []
            for m in sorted(vis, key=lambda m: -world.modules[m].pagerank):
                row.append("  " + _mod_label(world, s, m))
            lines.extend(row)
        hidden = len([m for m in z.members
                      if m not in s.seen and m not in masked])
        if hidden:
            lines.append(paint(f"  ... and {hidden} module(s) under fog",
                               "dim"))
        lines.append("")
    if unplaced:
        lines.append(paint("unplaced sightings (district unknown until a "
                           "scout places them): ", "dim")
                     + ", ".join(unplaced))
        lines.append("")
    if not s.boss_open:
        lines.append(paint(f"(boss quests are sealed until "
                           f"{boss_needed(world)} zones are cleared)", "dim"))
    else:
        _boss_qs = [q for q in world.questions.values() if q.boss]
        if _boss_qs and all(q.id in s.resolved for q in _boss_qs):
            pass  # the boss has fallen - status carries that story
        else:
            lines.append(paint("!! the BOSS LAIR is open - see 'buzz "
                               "quests' in the boss zone", "magenta"))
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
    # AST-verified: an unindented docstring line reading 'from the
    # actual socket...' scraped in as an import (round c12) - an
    # evidence panel must never render prose as a verified edge
    import ast as _ast
    try:
        _tree = _ast.parse(text)
        _import_lines = {n.lineno for n in _ast.walk(_tree)
                         if isinstance(n, (_ast.Import, _ast.ImportFrom))
                         and getattr(n, "col_offset", 1) == 0}
    except SyntaxError:
        _import_lines = set()
    all_imports = [f"  {i}: {raw[:76]}{'...' if len(raw) > 76 else ''}"
                   for i, raw in enumerate(text.splitlines(), 1)
                   if i in _import_lines]
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
    zname = (z.name if zone_id in known_zones(world, s)
             else "??? (unexplored district)")
    qs = [q for q in world.questions.values() if q.zone == zone_id
          # place quests are district-independent (filed under their
          # answer): they list in 'quests all', never here, and never
          # count toward this district's clear
          and q.qtype != "place"]
    fus = [q for q in s.followups.values() if q["zone"] == zone_id]
    nb = [q for q in qs if not q.boss]
    done = sum(1 for q in nb if q.id in s.resolved)
    n_boss = len(qs) - len(nb)
    from .ui import paint
    lines = [paint(f"quests in {zname} ({z.id}) - {done}/{len(nb)} resolved",
                   "gold")
             + (paint(f" (+{n_boss} boss quest(s) listed below)", "magenta")
                if n_boss else "")
             + (paint(" *CLEARED*", "green") if zone_id in s.cleared else "")
             + ":"]

    def _st(qid: str) -> str:
        st = _status_of(s, qid)
        return paint(f"[{st}]", "green" if st != "open" else "dim")

    for q in sorted(qs, key=lambda q: (q.boss, q.truth.get("stage", 0), q.id)):
        lock = ""
        if q.boss and not s.boss_open:
            lock = paint(" [LOCKED: clear more zones]", "yellow")
        elif q.boss and q.truth.get("prev_stage") not in (None, *s.resolved):
            lock = paint(f" [stage {q.truth['stage']}: sealed until the "
                         f"prior stage falls]", "yellow")
        lines.append(f"  {paint(q.id, 'cyan')} {_st(q.id)} "
                     + paint(f"({q.qtype}, {q.xp} XP)", "dim") + lock)
        if not lock and q.id not in s.resolved:
            lines.append(f"        {_gist(mask_prose(world, s, q.prompt))}")
    for f in fus:
        lines.append(f"  {paint(f['id'], 'cyan')} {_st(f['id'])} "
                     + paint(f"(follow-up, {f['xp']} XP)", "dim"))
    lines.append("")
    lines.append(paint("read one with 'buzz quest <id>', answer with "
                       "'buzz answer <id> ...'", "dim"))
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
        rule = ("edge rule: top-level (always-run) edges only"
                if q.qtype in ("cycle", "detour") else
                "edge rule: any import edge you can traverse counts, "
                "sealed tunnels included once tunnel-vision is unlocked")
    # A RECIPE, not a paragraph: each step is a command you can run plus
    # what it gets you. The owner asked twice how a hub quest is meant to
    # be solved while a prose 'evidence:' sentence sat on the card saying
    # exactly that - a run-on sentence is not an instruction. Steps never
    # promise what the game withholds (the in-degree tally during a hub
    # quest, the churn ranking during a hotspot quest ARE those answers).
    steps: list[tuple[str, str]] = []
    if q.qtype == "region":
        # NOT 'edges <zone>': a blast radius is TRANSITIVE and its chains
        # may leave the district (the prompt says so), while edges is
        # district-scoped and its tally is direct in-degree. 'who' is the
        # whole-hive fan-in, tagged by edge kind - the one tool that can
        # actually close this set (owner dogfood on a region quest).
        tgt = q.truth.get("target", "<module>")
        steps = [(f"buzz who {tgt}", "its direct importers"),
                 ("buzz who <each importer>", "repeat until no new names")]
    elif q.qtype == "gate":
        steps = [(f"buzz edges {q.zone}", "the district's imports"),
                 ("buzz trace <m1> <m2> ...", "does a route survive "
                  "without your suspect?")]
    elif q.qtype == "hub":
        steps = [
            (f"buzz edges {q.zone}", "rows ending '...' are your candidates"),
            (f"buzz edges {q.zone} <m1> <m2> ...", "compare their counts"),
        ]
    elif q.qtype == "hotspot":
        steps = [("buzz look <module>", "its commit count - compare the "
                  "busy-looking ones")]
    elif q.qtype in ("walk", "cycle", "detour", "via"):
        steps = [(f"buzz edges {q.zone} <module>",
                  "its imports; '(leaf)' = dead end"),
                 ("buzz trace <m1> <m2> ...", "check a chain")]
    elif q.qtype == "journey":
        steps = [("buzz flow <module>", "who it CALLS (not imports)")]
    elif q.qtype in ("ghost", "patch"):
        steps = [("buzz probe <a> <b>", "edges + how often they "
                  "changed together"),
                 ("buzz look <module>", "what a suspect is")]
    elif q.qtype == "elder":
        steps = [("buzz chronicle <module>", "its git history")]
    # generation bakes district names into quest prose; display is
    # where the fog lives (round c7: 'quest q26' named The Defaults
    # Atrium on a virgin session)
    prompt = mask_prose(world, s, q.prompt)
    from .ui import paint
    # A pick-from-this-set quest embeds its set as an inline comma run.
    # On a big repo that wraps into an unreadable wall where near-twins
    # hide side by side (owner dogfood: qwen2_5_vl_pre_encoder and
    # qwen2_vl_pre_encoder, four lines apart in one paragraph) - and
    # picking the wrong twin fails the quest. Lift it into a column at
    # DISPLAY time: existing worlds get it without re-analyzing, and an
    # exact-substring miss leaves the prompt untouched.
    # The same two rule-sentences ride on every quest of a type and cost
    # four dense lines each time. They are conditions, not narrative -
    # demote them to one short dim footnote (owner: "I see a lot of
    # things, my eyes are painful and im lost").
    notes: list[str] = []
    BOILER = [
        ("Count only top-level imports that always run - function-level "
         "(sealed tunnel) and TYPE_CHECKING-only imports do NOT count.",
         "top-level imports only - no sealed tunnels, no type-hints"),
        ("A chain may pass through modules OUTSIDE the candidate list "
         "(even other zones) - the candidates are only what you select "
         "from.", "chains may route through other districts"),
        ("A chain may pass through modules outside this list - check "
         "every hop.", "chains may route through other districts"),
        ("A loading chain may pass through modules outside this list - "
         "check every hop.", "chains may route through other districts"),
    ]
    for long, short in BOILER:
        if long in prompt:
            prompt = prompt.replace(long, "").replace("  ", " ").strip()
            notes.append(short)

    picks: list[str] = []
    label = ""
    for key, lbl in (("candidates", "pick from:"),
                     ("suspects", "suspects:"),
                     ("set", "put these in order:")):
        items = q.truth.get(key)
        if not isinstance(items, list) or len(items) < 4:
            continue
        items = [str(m) for m in items]
        inline = ", ".join(items)
        if inline not in prompt:
            continue
        tail = next((f"{w}: {inline}." for w in ("Candidates", "Suspects")
                     if f"{w}: {inline}." in prompt), None)
        prompt = (prompt.replace(tail, "").strip() if tail
                  else prompt.replace(inline, "(listed below)", 1))
        picks, label = items, lbl
        break
    column = []
    if picks:
        # grid, not a stack: fourteen candidates were fourteen lines
        import shutil
        term = max(60, min(shutil.get_terminal_size((100, 24)).columns, 160))
        w = max(len(m) for m in picks) + 2
        ncol = max(1, min(4, (term - 2) // w))
        rows_n = -(-len(picks) // ncol)
        column = [paint(label, "cyan")]
        for r in range(rows_n):
            cells = [picks[r + c * rows_n] for c in range(ncol)
                     if r + c * rows_n < len(picks)]
            column.append("  " + "".join(c.ljust(w) for c in cells).rstrip())
    # the recipe's last step IS the answer syntax - printing both said
    # the same thing twice on an already-wordy card
    recipe: list[str] = []
    if steps:
        rows = [*steps, (syntax, "")]
        width = max(len(cmd) for cmd, _ in rows)
        recipe.append(paint("how to solve:", "cyan"))
        for cmd, why in rows:
            recipe.append((f"  {paint(cmd.ljust(width), 'cyan')}"
                           + (f"  {paint(why, 'dim')}" if why else ""))
                          .rstrip())
    else:
        recipe.append(f"answer: {paint(syntax, 'cyan')}")
    if rule:
        notes.insert(0, rule.replace("edge rule: ", ""))
    # Cutting alone makes a spec sheet. What makes someone play the NEXT
    # one is seeing the run move: where this quest sits in its district,
    # what a clean solve is worth right now, and that solving banks a
    # field note (the learning IS the loot). All of it rides in the two
    # lines the card already spends on framing - no new lines.
    head = paint(f"[{q.id}]", "gold") + paint(f" {q.qtype} · ", "dim")
    bonus = min(50, 5 * s.streak)
    head += paint(f"{q.xp} XP", "gold" if q.boss else "cyan")
    if bonus and st == "open":
        head += paint(f" +{bonus}% streak", "green")
    if q.qtype != "place":  # a place quest's district IS its answer
        zq = [x for x in world.questions.values()
              if x.zone == q.zone and not x.boss and x.qtype != "place"]
        if zq and q.zone in known_zones(world, s):
            done = sum(1 for x in zq if x.id in s.resolved)
            head += paint(f" · {world.zones[q.zone].name} "
                          f"{done}/{len(zq)}", "dim")
    head += paint(f" · {st}", "dim") if st != "open" else ""
    reward = (paint(f"  solving banks field note #{len(s.resolved) + 1}",
                    "dim") + paint("  ·  ", "dim")
              + paint(f"stuck? buzz hint {q.id}", "dim"))
    lines = [head,
             "", prompt,
             *(["", *column] if column else []),
             *([paint("  (" + " · ".join(notes) + ")", "dim")]
               if notes else []),
             "", *recipe, reward]
    return "\n".join(lines)


def _badge_line(world: World, s: Session) -> str:
    from .badges import earned
    from .ui import paint
    got = ", ".join(name for name, _ in earned(world, s))
    line = paint("badges: ", "cyan") + (paint(got, "green") if got
                                        else "none yet")
    if s.exam.get("best"):
        line += f" | exam best: {s.exam['best']}% retention"
    from .exam import in_progress
    if in_progress(s):
        e = s.exam
        line += "\n" + paint(f"EXAM IN PROGRESS [{e['idx'] + 1}"
                             f"/{len(e['qids'])}] - 'buzz exam' shows the "
                             f"question", "magenta")
    return line


def render_status(world: World, s: Session) -> str:
    d, total = coverage(world, s)
    solved = sum(1 for v in s.resolved.values() if v == "correct")
    total_xp = sum(q.xp for q in world.questions.values())
    attempted = len(s.resolved)
    clean = sum(1 for qid, v in s.resolved.items()
                if v == "correct" and not s.hints.get(qid)
                and not s.tries.get(qid))
    from .ui import paint

    def lbl(text: str) -> str:
        return paint(text, "cyan")

    lines = []
    if s.focus and s.focus not in s.resolved:
        lines.append(lbl(f"tracking: {s.focus}")
                     + paint(" - 'quest' reprints it, bare 'hint'/'answer "
                             "<...>' target it", "dim"))
    lines += [
        lbl(f"XP {s.xp}")
        + paint(f" (base pool {total_xp}; streak bonuses stack on top)", "dim")
        + f" | rank: {rank(world, s)}"
        + paint(" (rank only ever climbs)", "dim")
        + (f" | solved: {solved}/{attempted} attempted"
           + paint(f" ({clean} clean - no hints, no retries)", "dim")
           if attempted else ""),
        lbl(f"coverage: {d}/{total} modules read, "
            f"{len(s.seen)}/{total} surveyed")
        + paint(" (read = visited/spyglassed; surveyed = named by scouting, "
                "probing, or quest work - both are real reconnaissance)",
                "dim"),
        lbl(f"zones cleared: {len(s.cleared)}/"
            f"{sum(1 for z in world.zones if any(q.zone == z and not q.boss for q in world.questions.values()))}"
            f" clearable")
        + (paint(f" ({', '.join(world.zones[z].name for z in s.cleared)})",
                 "green") if s.cleared else ""),
        lbl(f"questions: {solved} solved, "
            f"{sum(1 for v in s.resolved.values() if v == 'partial')} partial, "
            f"{sum(1 for v in s.resolved.values() if v == 'revealed')} revealed"),
        lbl(f"streak: {s.streak} clean solve(s) in a row")
        + (paint(f" (+{min(50, 5 * s.streak)}% XP on the next clean solve)",
                 "green")
           if s.streak else paint(" (first-try, hint-free solves build a "
                                  "bonus)", "dim")),
        lbl(f"abilities: {', '.join(s.abilities) or 'none yet'}"),
        _badge_line(world, s),
        lbl("boss lair: ") + (
            paint("CLEARED", "green")
            if (boss_qs := [q for q in world.questions.values() if q.boss])
            and all(q.id in s.resolved for q in boss_qs)
            else paint("OPEN", "magenta") if s.boss_open
            else paint("sealed", "dim")),
    ]
    if s.victory:
        clearable = {z for z in world.zones
                     if any(q.zone == z and not q.boss
                            for q in world.questions.values())}
        left = len(clearable - set(s.cleared))
        lines.append("")
        if left:
            lines.append(paint(f"*** CAMPAIGN CLEAR - the hive's heart is "
                               f"mapped. Rank: {rank(world, s)} ***", "gold"))
            lines.append(paint(f"({left} endgame district(s) stay open for "
                               f"100% hunters - or point buzz at another "
                               f"repo)", "dim"))
        else:
            lines.append(paint(f"*** FULL CLEAR - the core of this hive is "
                               f"mapped. Final rank: {rank(world, s)} ***",
                               "gold"))
            lines.append(paint("(quests target the structure that matters, "
                               "not every file - most of the fog is side "
                               "rooms)", "dim"))
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
  buzz flow <module>           where a read file's work GOES at runtime
                               (real calls - the evidence for journeys)
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
  buzz quest <id>              read one quest (and track it: the shell
                               prompt shows the id; bare 'quest', 'hint'
                               and 'answer <...>' then mean that quest)
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
