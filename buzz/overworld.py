"""The overworld: a top-down map screen for the terminal (curses).

Districts are rooms, modules are tiles, and your bee walks the grid with
the arrow keys - fog-of-war means tiles literally appear as you play.
Optional and never load-bearing: every action calls the exact engine the
shell uses (go/peek/quests), agents and pipes keep the one-shot
interface, and quitting drops you back where you were.

Keys: arrows/wasd move · Enter travel to the tile under you · l look ·
e quests here · ? help · Q or ESC leave
"""
from __future__ import annotations

import curses

from . import engine, render
from .engine import GameError
from .model import World, Session, ROLE_BOSS, ROLE_BEDROCK, ROLE_GATE, \
    ROLE_SWAMP

TILE_W = 14          # character cells per module tile
ROOM_PAD = 2


def compute_layout(world: World, width: int = 110):
    """Pure layout (unit-testable without curses): rooms as character-cell
    boxes {zid: (x, y, w, h)}, module tiles {name: (x, y)}."""
    rooms, tiles = {}, {}
    x, y, row_h = 2, 2, 0
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        n = max(1, len(z.members))
        cols = max(2, int(n ** 0.5 * 1.4 + 0.99))
        rows = -(-n // cols)
        w = cols * TILE_W + ROOM_PAD * 2
        h = rows * 2 + 3
        if x + w > width and x > 2:
            x = 2
            y += row_h + 2
            row_h = 0
        rooms[z.id] = (x, y, w, h)
        for i, m in enumerate(sorted(z.members)):
            tiles[m] = (x + ROOM_PAD + (i % cols) * TILE_W,
                        y + 2 + (i // cols) * 2)
        row_h = max(row_h, h)
        x += w + 3
    return rooms, tiles, y + row_h + 3


ROLE_GLYPH = {ROLE_BOSS: "B", ROLE_BEDROCK: "#", ROLE_GATE: "%",
              ROLE_SWAMP: "~"}


def _whisper(world: World, s: Session, m: str) -> str | None:
    """One TRUE fact about the tile the bee stands on - the tall-grass
    encounter. Every fact mirrors something look/probe/chronicle already
    expose freely; anything an OPEN quest hangs on stays withheld."""
    if m in s.whispers or m not in s.seen:
        return None
    mod = world.modules[m]
    zid = mod.zone

    def quest_open(pred):
        return any(pred(q) for q in world.questions.values()
                   if q.id not in s.resolved)

    facts = []
    if mod.born:
        facts.append(f"the old bees say {m} was built {mod.born} - "
                     + ("an elder of this district"
                        if mod.commits >= 10 else "still young timber"))
    if mod.in_degree >= 3:
        facts.append(f"{mod.in_degree} modules lean on this wall - "
                     f"tread carefully when it moves")
    if mod.commits >= 8:
        facts.append(f"storm-worn: {mod.commits} commits by "
                     f"{mod.authors} author(s) have reshaped this place")
    top = next(iter(world.cochange.get(m, [])), None)
    ghost_or_patch_open = quest_open(
        lambda q: (q.qtype == "ghost" and (q.truth.get("src") == m
                   or m in (q.truth.get("accepted") or [])))
        or (q.qtype == "patch" and m in (q.truth.get("anchor"),
                                         q.truth.get("module"))))
    if top and not ghost_or_patch_open:
        facts.append(f"git whispers: {m} and {top[0]} moved together "
                     f"{top[1]} times")
    scar_open = quest_open(lambda q: q.qtype == "scar"
                           and q.truth.get("module") == m)
    if any(m in ev.get("mods", []) for ev in world.reverts) and not scar_open:
        facts.append(f"a scar: something here was once rolled back - "
                     f"the chronicle remembers")
    if mod.doc:
        facts.append(f'the residents describe it: "{mod.doc}"')
    if not facts:
        return None
    s.whispers.append(m)
    return "~ " + facts[len(s.whispers) % len(facts)]


def _other_scouts(world: World, s: Session, sessions_dir):
    """Fellow bees: other sessions' positions on the shared world."""
    out = {}
    if not sessions_dir:
        return out
    from .model import Session as _S
    try:
        for p in sorted(sessions_dir.glob("*.json")):
            try:
                other = _S.load(p)
            except Exception:
                continue
            if other.here != s.here and other.here in world.modules:
                out.setdefault(other.here, []).append(p.stem)
    except OSError:
        pass
    return out


def _quest_marks(world: World, s: Session):
    """Tiles worth walking to: modules OPEN quests name in their prompts
    (sources, anchors, targets - never hidden answers), plus per-zone open
    counts. The panel-less first cut had no goals on screen at all."""
    marks, zone_open = set(), {}
    for q in world.questions.values():
        if q.id in s.resolved:
            continue
        zone_open[q.zone] = zone_open.get(q.zone, 0) + 1
        t = q.truth
        # ONE marker per quest - its starting point - so '!' keeps meaning
        # "begin here" (a scout found four marked tiles in one small room:
        # density defeats the signal)
        primary = (t.get("src") or t.get("target") or t.get("anchor")
                   or t.get("a"))
        if primary:
            marks.add(primary)
    marks.discard(None)
    return marks, zone_open


def _draw_map(pad, world: World, s: Session, rooms, tiles):
    pad.erase()
    seen, disc = set(s.seen), set(s.discovered)
    masked = render.masked_modules(world, s)
    marks, zone_open = _quest_marks(world, s)
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        x, y, w, h = rooms[z.id]
        known = any(m in seen for m in z.members)
        title = z.name if known else "??? unexplored"
        n_open = zone_open.get(z.id, 0)
        if n_open and known:
            title += f" · {n_open} quest{'s' if n_open > 1 else ''}"
        try:
            pad.addstr(y, x, "+" + "-" * (w - 2) + "+")
            bottom = list("+" + "-" * (w - 2) + "+")
            door = w // 2
            bottom[door - 1: door + 1] = "  "  # the doorway
            pad.addstr(y + h - 1, x, "".join(bottom))
            for yy in range(y + 1, y + h - 1):
                pad.addstr(yy, x, "|")
                pad.addstr(yy, x + w - 1, "|")
            pad.addstr(y, x + 2, f" {title[:w - 6]} ",
                       curses.A_BOLD | curses.color_pair(5))
        except curses.error:
            pass
        for m in z.members:
            tx, ty = tiles[m]
            mod = world.modules[m]
            try:
                if m not in seen:
                    pad.addstr(ty, tx, "··", curses.color_pair(6))
                    continue
                glyph = ROLE_GLYPH.get(mod.role, "o")
                if m in marks:
                    glyph = "!"  # an open quest names this tile - go there
                pair = {ROLE_BOSS: 1, ROLE_BEDROCK: 2, ROLE_GATE: 3,
                        ROLE_SWAMP: 4}.get(mod.role, 0)
                if m in marks:
                    pair = 1
                attr = curses.color_pair(pair) | (
                    curses.A_BOLD if m in disc or m in marks
                    else curses.A_DIM)
                tail = "???" if m in masked and m not in disc \
                    else m.split(".")[-1]
                label = (tail if len(tail) <= TILE_W - 4
                         else tail[: TILE_W - 5] + "…")
                pad.addstr(ty, tx, f"{glyph} {label}", attr)
            except curses.error:
                pass


def _overlay(scr, lines, title=""):
    """Full-screen text overlay. Returns True if the player pressed
    Q/ESC (quit the whole overworld), False for a plain dismiss."""
    maxy, maxx = scr.getmaxyx()
    top = 0
    while True:
        scr.erase()
        if title:
            scr.addstr(0, 2, title[: maxx - 4], curses.A_BOLD)
        for i, ln in enumerate(lines[top: top + maxy - 3]):
            try:
                scr.addstr(i + 1, 2, ln[: maxx - 4])
            except curses.error:
                pass
        scr.addstr(maxy - 1, 2,
                   "j/k or arrows scroll · any other key closes"[: maxx - 4],
                   curses.A_DIM)
        scr.refresh()
        k = scr.getch()
        if k in (curses.KEY_DOWN, ord("j")) and top + maxy - 3 < len(lines):
            top += 3
        elif k in (curses.KEY_UP, ord("k")) and top > 0:
            top = max(0, top - 3)
        else:
            # Q/ESC means QUIT THE OVERWORLD, even from an overlay - both
            # round-18 scouts hung when an overlay swallowed their quit
            return k in (ord("Q"), 27)


def _main(scr, world: World, s: Session, save, sessions_dir=None):
    curses.curs_set(0)
    curses.use_default_colors()
    for i, c in [(1, curses.COLOR_YELLOW), (2, curses.COLOR_BLUE),
                 (3, curses.COLOR_MAGENTA), (4, curses.COLOR_GREEN),
                 (5, curses.COLOR_CYAN), (6, curses.COLOR_BLACK)]:
        try:
            curses.init_pair(i, c, -1)
        except curses.error:
            pass
    rooms, tiles, height = compute_layout(world)
    pad = curses.newpad(height + 4, 130)
    bee = list(tiles.get(s.here, (4, 4)))
    msg = "arrows move · Enter travels · l look · e quests · ? help · Q quits"

    def tile_at(bx, by):
        for m, (tx, ty) in tiles.items():
            if ty == by and tx <= bx < tx + TILE_W - 2:
                return m
        return None

    while True:
        _draw_map(pad, world, s, rooms, tiles)
        maxy, maxx = scr.getmaxyx()
        others = _other_scouts(world, s, sessions_dir)
        for om, names in others.items():
            if om in tiles and om in s.seen:
                ox, oy = tiles[om]
                try:
                    pad.addstr(oy, max(0, ox - 1), "b",
                               curses.A_DIM | curses.color_pair(4))
                except curses.error:
                    pass
        here_m = tile_at(*bee)
        # the bee perches BESIDE a tile's label, never on it (a panel saw
        # '@ire' where 'wire' should be - sprite and text fighting a cell)
        bx, by = bee
        if here_m:
            bx = max(0, tiles[here_m][0] - 1)
        try:
            pad.addstr(by, bx, "@",
                       curses.A_BOLD | curses.color_pair(1))
        except curses.error:
            pass
        scr.erase()
        hud = (f" xp {s.xp} · streak {s.streak} · facts {len(s.resolved)}/"
               f"{len(world.questions)} · at {s.here}")
        scr.addstr(0, 0, hud[: maxx - 1], curses.A_REVERSE)
        scr.refresh()
        # viewport follows the bee
        vy = max(0, min(bee[1] - (maxy - 4) // 2, height - (maxy - 3)))
        vx = max(0, min(bee[0] - maxx // 2, 130 - maxx))
        pad.refresh(max(0, vy), max(0, vx), 1, 0, maxy - 2, maxx - 1)
        marks, zone_open = _quest_marks(world, s)
        info = ""
        if here_m and here_m in s.seen:
            mod = world.modules[here_m]
            info = f"{here_m} [{mod.role}]"
            if here_m in marks:
                info += " · an open quest names this module ('e' to read)"
            if here_m in others:
                info += f" · scout {others[here_m][0]} is here too"
            info += (" - Enter travels, l looks" if here_m != s.here
                     else " - you are here (l looks)")
        elif here_m:
            info = "an unseen tile - walk elsewhere or scout in the shell"
        else:
            room = next((z for z, (x, y, w, h) in rooms.items()
                         if x <= bee[0] < x + w and y <= bee[1] < y + h),
                        None)
            n = zone_open.get(room, 0) if room else 0
            info = (f"{n} open quest{'s' if n != 1 else ''} in this "
                    f"district - 'e' lists them, ! tiles are named by them"
                    if n else "")
        line = msg or info
        attr = (curses.color_pair(5) | curses.A_BOLD
                if msg.startswith("~") else curses.A_DIM)
        scr.addstr(maxy - 1, 0, line[: maxx - 1], attr)
        msg = ""  # events flash once; ambient info returns next frame
        scr.refresh()

        k = scr.getch()
        if k in (ord("Q"), 27):
            return
        elif k in (curses.KEY_LEFT, ord("a"), curses.KEY_RIGHT, ord("d"),
                   curses.KEY_UP, ord("w"), curses.KEY_DOWN, ord("s")):
            dx = (-2 if k in (curses.KEY_LEFT, ord("a"))
                  else 2 if k in (curses.KEY_RIGHT, ord("d")) else 0)
            dy = (-1 if k in (curses.KEY_UP, ord("w"))
                  else 1 if k in (curses.KEY_DOWN, ord("s")) else 0)
            nx = max(1, min(127, bee[0] + dx))
            ny = max(1, min(height, bee[1] + dy))
            # walls block; doorways (the gap in each bottom wall) pass
            blocked = False
            for zid, (x, y, w, h) in rooms.items():
                on_v = ny in (y, y + h - 1) and x <= nx <= x + w - 1
                on_h = nx in (x, x + w - 1) and y <= ny <= y + h - 1
                if on_v or on_h:
                    door = x + w // 2
                    if ny == y + h - 1 and door - 1 <= nx <= door:
                        continue  # through the doorway
                    blocked = True
                    break
            if not blocked:
                bee[0], bee[1] = nx, ny
        elif k in (curses.KEY_ENTER, 10, 13) and here_m:
            try:
                how = engine.go(world, s, here_m)
                save(s)
                whisper = _whisper(world, s, s.here)
                msg = (whisper if whisper
                       else f"[{how}] arrived at {s.here}")
                if whisper:
                    save(s)
            except GameError as e:
                msg = f"! {e}"
        elif k == ord("l") and here_m:
            try:
                at = engine.peek(world, s, here_m)
                save(s)
                if _overlay(scr,
                            render.render_look(world, s, at).splitlines(),
                            title=f"spyglass: {at}"):
                    return
            except GameError as e:
                msg = f"! {e}"
        elif k == ord("e"):
            zid = (world.modules[here_m].zone if here_m
                   else world.modules[s.here].zone)
            if _overlay(scr,
                        render.render_quests(world, s, zid).splitlines(),
                        title="quests here (answer them in the shell)"):
                return
        elif k == ord("?"):
            if _overlay(scr, [
                "THE OVERWORLD - keys",
                "",
                "arrows / wasd   walk the bee across the hive",
                "Enter           travel to the module tile under you",
                "                (same rules as 'go': fog and seals apply)",
                "l               spyglass the tile under you (look)",
                "e               quests of the district you stand in",
                "Q or ESC        back to the shell",
                "",
                "tiles: B boss · # bedrock · % gate · ~ swamp · o worker",
                "bright = read · dim = seen · ·· = still under fog",
                "",
                "answers stay in the shell - the overworld is for roaming.",
            ], title="help"):
                return


def run_overworld(world: World, s: Session, save, sessions_dir=None) -> None:
    import sys
    if not sys.stdout.isatty():
        raise GameError("the overworld needs a real terminal - it is a "
                        "screen, not a stream (agents and pipes keep the "
                        "one-shot commands)")
    curses.wrapper(_main, world, s, save, sessions_dir)
