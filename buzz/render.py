"""Text rendering: the fog-of-war map IS the architecture diagram."""
from __future__ import annotations

from .model import World, Session, ROLE_GLYPH, LAZY, TYPE
from .engine import coverage, rank, TUNNEL, BOSS_ZONES_NEEDED


def _mod_label(world: World, s: Session, m: str) -> str:
    glyph = ROLE_GLYPH.get(world.modules[m].role, "")
    here = " <YOU>" if m == s.here else ""
    tag = "" if m in s.discovered else "(seen)"
    return f"{m}{glyph and ' ' + glyph}{tag}{here}"


def render_map(world: World, s: Session) -> str:
    d, total = coverage(world, s)
    lines = [
        f"=== THE HIVE: {world.repo.rsplit('/', 1)[-1]} "
        f"| coverage {d}/{total} modules | XP {s.xp} | rank {rank(s)} ===",
        f"you are at: {s.here}  (zone {world.modules[s.here].zone}, "
        f"{world.zones[world.modules[s.here].zone].name})",
        "",
    ]
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        vis = [m for m in z.members if m in s.seen]
        zq = [q for q in world.questions.values() if q.zone == z.id and not q.boss]
        done = sum(1 for q in zq if q.id in s.resolved)
        status = " *CLEARED*" if z.id in s.cleared else f"  quests {done}/{len(zq)}"
        known = z.id in {world.modules[m].zone for m in s.discovered}
        title = z.name if known else "??? (unexplored district)"
        lines.append(f"[{z.id}] {title}{status}")
        if vis:
            row = []
            for m in sorted(vis, key=lambda m: -world.modules[m].pagerank):
                row.append("  " + _mod_label(world, s, m))
            lines.extend(row)
        hidden = len(z.members) - len(vis)
        if hidden:
            lines.append(f"  ... and {hidden} module(s) under fog")
        lines.append("")
    if not s.boss_open:
        lines.append(f"(boss quests are sealed until {BOSS_ZONES_NEEDED} zones are cleared)")
    else:
        lines.append("!! the BOSS LAIR is open - see 'buzz quests' in the boss zone")
    return "\n".join(lines)


def render_look(world: World, s: Session) -> str:
    m = world.modules[s.here]
    z = world.zones[m.zone]
    lines = [
        f"--- {s.here} ---",
        f"file: {m.path} | {m.loc} lines | {m.commits} commits by {m.authors} author(s)",
        f"zone: {z.name} ({z.id}) | role: {m.role}",
        f"imported by {m.in_degree} module(s)"
        + (": " + ", ".join(sorted(e.src for e in world.in_edges(s.here) if e.src in s.discovered))
           + (" +unknown others" if any(e.src not in s.discovered for e in world.in_edges(s.here)) else "")
           if m.in_degree else ""),
        "",
        "imports (its out-edges - you can walk these with 'buzz go <name>'):",
    ]
    outs = world.out_edges(s.here)
    if not outs:
        lines.append("  (imports nothing internal - a leaf)")
    for e in sorted(outs, key=lambda e: e.kind):
        if e.kind == LAZY:
            if TUNNEL in s.abilities:
                lines.append(f"  ~ {e.dst}  [tunnel: function-level import - passable]")
            else:
                lines.append(f"  # {e.dst}  [SEALED TUNNEL: function-level import]")
        elif e.kind == TYPE:
            lines.append(f"  - {e.dst}  [types-only: never runs]")
        else:
            lines.append(f"  > {e.dst}")
    return "\n".join(lines)


def _status_of(s: Session, qid: str) -> str:
    st = s.resolved.get(qid)
    return {"correct": "SOLVED", "partial": "partial", "revealed": "revealed"}.get(st, "open")


def render_quests(world: World, s: Session, zone_id: str) -> str:
    z = world.zones[zone_id]
    qs = [q for q in world.questions.values() if q.zone == zone_id]
    fus = [q for q in s.followups.values() if q["zone"] == zone_id]
    lines = [f"quests in {z.name} ({z.id}):"]
    for q in sorted(qs, key=lambda q: (q.boss, q.id)):
        lock = ""
        if q.boss and not s.boss_open:
            lock = " [LOCKED: clear more zones]"
        lines.append(f"  {q.id} [{_status_of(s, q.id)}] ({q.qtype}, {q.xp} XP){lock}")
    for f in fus:
        lines.append(f"  {f['id']} [{_status_of(s, f['id'])}] (follow-up, {f['xp']} XP)")
    lines.append("")
    lines.append("read one with 'buzz quest <id>', answer with 'buzz answer <id> ...'")
    return "\n".join(lines)


def render_question(world: World, s: Session, q) -> str:
    syntax = {
        "walk": f"buzz answer {q.id} walk <module> <module> ... <module>",
        "edge": f"buzz answer {q.id} edge <importer> <imported>",
        "region": f"buzz answer {q.id} region <module> <module> ...",
        "place": f"buzz answer {q.id} place <zone-id-or-name>",
    }[q.verb]
    st = _status_of(s, q.id)
    lines = [f"[{q.id}] ({q.qtype}, {q.xp} XP, status: {st})", "", q.prompt, "",
             f"answer syntax: {syntax}",
             f"stuck? 'buzz hint {q.id}' (level 1 free-ish, costs XP; level 3 reveals)"]
    return "\n".join(lines)


def render_status(world: World, s: Session) -> str:
    d, total = coverage(world, s)
    solved = sum(1 for v in s.resolved.values() if v == "correct")
    lines = [
        f"XP {s.xp}/{s.max_xp} attempted | rank: {rank(s)}",
        f"coverage: {d}/{total} modules discovered",
        f"zones cleared: {len(s.cleared)}/{len(world.zones)}"
        + (f" ({', '.join(world.zones[z].name for z in s.cleared)})" if s.cleared else ""),
        f"questions: {solved} solved, "
        f"{sum(1 for v in s.resolved.values() if v == 'partial')} partial, "
        f"{sum(1 for v in s.resolved.values() if v == 'revealed')} revealed",
        f"abilities: {', '.join(s.abilities) or 'none yet'}",
        f"boss lair: {'OPEN' if s.boss_open else 'sealed'}",
    ]
    if s.victory:
        lines.append("")
        lines.append("*** VICTORY - the hive is mapped. Final rank: " + rank(s) + " ***")
    if s.log:
        lines.append("")
        lines.append("recent events: " + "; ".join(s.log[-3:]))
    return "\n".join(lines)


HELP = """buzz - learn how a repo works by exploring it

setup:
  buzz analyze <repo-path>     build the world (run once, from the game dir)
  buzz play                    start (or restart) a session

exploring (free, no XP):
  buzz map                     the fog-of-war hive map
  buzz look                    inspect the module you are standing on
  buzz go <module>             walk an import edge, or fast-travel anywhere visited

quests (the only source of XP):
  buzz quests                  quests in your current zone
  buzz quest <id>              read one quest
  buzz answer <id> walk m1 m2 ...      trace an import chain
  buzz answer <id> edge <importer> <imported>   draw a dependency edge
  buzz answer <id> region m1 m2 ...    select a blast radius
  buzz answer <id> place <zone>        place a module in its district
  buzz hint <id>               oracle hint ladder (costs XP; 3rd hint reveals)

  buzz status                  XP, rank, abilities, victory progress

Wrong answers cost nothing but reveal the truth (and spawn a follow-up quest).
Sealed tunnels (#) are function-level imports - solve a cycle quest to unlock.
Clear 2 zones to open the boss lair. Beat the boss quests to win.
"""
