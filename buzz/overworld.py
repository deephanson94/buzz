"""The overworld: a top-down map screen for the terminal (curses).

Districts are rooms, modules are tiles, and your bee walks the grid with
the arrow keys - fog-of-war means tiles literally appear as you play.
Optional and never load-bearing: every action calls the exact engine the
shell uses (go/peek/quests), agents and pipes keep the one-shot
interface, and quitting drops you back where you were.

Keys: arrows/wasd hop module to module · Enter travel to the tile under
you · l look · e quests here · ? help · Q or ESC leave
"""
from __future__ import annotations

import curses

from . import engine, render
from .engine import GameError
from .model import World, Session, ROLE_BOSS, ROLE_BEDROCK, ROLE_GATE, \
    ROLE_SWAMP

TILE_W = 14          # minimum character cells per module tile
ROOM_PAD = 2


def _tile_w(world: World) -> int:
    """Tile width adapts to the hive: small worlds have screen to spare,
    so no name gets cut to 'neuron_to...' when 'neuron_tools' would fit.
    Big worlds keep the compact minimum so rooms still tile the screen."""
    longest = max((len(m.split(".")[-1]) for m in world.modules), default=8)
    if len(world.modules) > 30:
        return TILE_W
    return max(TILE_W, min(26, longest + 4))


def compute_layout(world: World, width: int = 110):
    """Pure layout (unit-testable without curses): rooms as character-cell
    boxes {zid: (x, y, w, h)}, module tiles {name: (x, y)}, total height,
    and the tile width used."""
    tile_w = _tile_w(world)
    rooms, tiles = {}, {}
    x, y, row_h = 2, 2, 0
    # no room may be wider than the wrap width - a fat district must grow
    # DOWN, not off the screen (owner's big-repo dogfood: borders wider
    # than the terminal render as a wall of disconnected dashes)
    max_cols = max(1, (width - ROOM_PAD * 2 - 2) // tile_w)
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        n = max(1, len(z.members))
        cols = min(max(2, int(n ** 0.5 * 1.4 + 0.99)), max_cols)
        rows = -(-n // cols)
        w = cols * tile_w + ROOM_PAD * 2
        h = rows * 2 + 3
        if x + w > width and x > 2:
            x = 2
            y += row_h + 2
            row_h = 0
        rooms[z.id] = (x, y, w, h)
        for i, m in enumerate(sorted(z.members)):
            tiles[m] = (x + ROOM_PAD + (i % cols) * tile_w,
                        y + 2 + (i // cols) * 2)
        row_h = max(row_h, h)
        x += w + 3
    return rooms, tiles, y + row_h + 3, tile_w


ROLE_GLYPH = {ROLE_BOSS: "B", ROLE_BEDROCK: "#", ROLE_GATE: "%",
              ROLE_SWAMP: "~"}

HELP_LINES = [
    "THE OVERWORLD - how it works",
    "",
    "the loop: hop to a ! tile, press e to read its quest,",
    "then answer in the shell ('buzz answer <id> ...') -",
    "the overworld is for roaming and finding things out.",
    "",
    "arrows / wasd   hop module to module (rooms = districts;",
    "                the hop drifts to the NEAREST tile when",
    "                none sits straight ahead)",
    "Enter           formally travel here - fog and seals can",
    "                refuse you; that is the game, not an error",
    "l               spyglass the module under you (look)",
    "e               quests of this district",
    "Q or ESC        back to the shell",
    "",
    "tiles: ! quest starts here · B boss · # bedrock · % gate",
    "       ~ swamp · o worker · ·· fog · b a fellow scout",
    "walking whispers one true fact per tile per session.",
]


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
        if q.qtype != "place":
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


def _draw_map(pad, world: World, s: Session, rooms, tiles, tile_w=TILE_W):
    pad.erase()
    seen, disc = set(s.seen), set(s.discovered)
    masked = render.masked_modules(world, s)
    marks, zone_open = _quest_marks(world, s)
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        x, y, w, h = rooms[z.id]
        known = z.id in render.known_zones(world, s)
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
                label = (tail if len(tail) <= tile_w - 4
                         else tail[: tile_w - 5] + "…")
                pad.addstr(ty, tx, f"{glyph} {label}", attr)
            except curses.error:
                pass


def _drain(scr):
    """Eat buffered input. Keys typed before a screen existed - during
    launch, or while an overlay was up - must never replay into the map
    (flushinp alone races a fast typist; settle, then drain)."""
    scr.nodelay(True)
    curses.napms(80)
    while scr.getch() != -1:
        pass
    scr.nodelay(False)


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
            # keys queued while the overlay was up must NOT replay into
            # the map (round SNAP: 'one press moved 3 tiles')
            _drain(scr)
            # Q/ESC means QUIT THE OVERWORLD, even from an overlay - both
            # round-18 scouts hung when an overlay swallowed their quit
            return k in (ord("Q"), 27)


def _main(scr, world: World, s: Session, save, sessions_dir=None):
    curses.curs_set(0)
    _maxy, _maxx = scr.getmaxyx()
    curses.use_default_colors()
    for i, c in [(1, curses.COLOR_YELLOW), (2, curses.COLOR_BLUE),
                 (3, curses.COLOR_MAGENTA), (4, curses.COLOR_GREEN),
                 (5, curses.COLOR_CYAN), (6, curses.COLOR_BLACK)]:
        try:
            curses.init_pair(i, c, -1)
        except curses.error:
            pass
    # the map wraps to THIS terminal, and the pad is as wide as the map
    # actually is - fixed 110/130 constants broke every repo whose rooms
    # outgrew them (silent addstr failures ate whole border rows)
    rooms, tiles, height, tile_w = compute_layout(
        world, width=max(60, _maxx - 2))
    map_w = max(x + w for x, y, w, h in rooms.values()) + 3
    pad = curses.newpad(height + 4, max(map_w, _maxx + 1))
    # tile-snap movement (owner's call after rounds 18-W1 converged on
    # "navigation is tedious"): the bee is always ON a module tile, and
    # one keypress hops to the nearest tile in that direction - across
    # rooms too, so districts are grouping, not obstacle course
    cur = s.here if s.here in tiles else next(iter(tiles), None)
    msg = "arrows hop module to module · Enter travels · l look · e quests · ? help · Q quits"
    # a whisper stays on the status line while the bee STANDS on its
    # tile (round W1: a one-frame flash was lost to a blink), and the
    # spawn tile whispers on first paint - starting somewhere is
    # arriving there
    whisper_line, whisper_tile = "", None
    _first = _whisper(world, s, s.here) if s.here else None
    if _first:
        whisper_line, whisper_tile = _first, s.here
        save(s)
    # the owner's dogfood verdict on rounds 18-W1: 'I still don't know
    # how the TUI works.' First visit opens the how-it-works card - once
    # per session, any key dismisses it
    if "overworld-visited" not in s.log:
        s.log.append("overworld-visited")
        save(s)
        if _overlay(scr, HELP_LINES, title="welcome to the overworld"):
            return
    _drain(scr)  # input from before this screen existed is not input

    def hop(frm, dx, dy):
        """The next tile in a direction, or None at the map's edge.
        Horizontal: the neighbor in the same row (rooms included - the
        corridor is one hop). Vertical: the nearest row beyond, then
        the tile in it nearest in x."""
        tx, ty = tiles[frm]
        if dx:
            row = sorted((x, m) for m, (x, y2) in tiles.items() if y2 == ty)
            i = [m for _, m in row].index(frm) + (1 if dx > 0 else -1)
            return row[i][1] if 0 <= i < len(row) else None
        rows = sorted({y2 for _, y2 in tiles.values()
                       if (y2 > ty if dy > 0 else y2 < ty)},
                      reverse=dy < 0)
        if not rows:
            return None
        # weigh row distance against horizontal drift: a tile roughly
        # above/below two rows away beats the far end of the next row
        # (round SNAP: a vertical key must not yank the bee sideways)
        best = None
        for depth, ny in enumerate(rows[:3]):
            for m, (x, y2) in tiles.items():
                if y2 != ny:
                    continue
                # ties break toward column alignment: straight above
                # beats equally-costed sideways
                key = (depth * 2 + abs(x - tx) / max(1, tile_w),
                       abs(x - tx))
                if best is None or key < best[0]:
                    best = (key, m)
        return best[1]

    while True:
        _draw_map(pad, world, s, rooms, tiles, tile_w)
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
        here_m = cur
        # the bee perches BESIDE a tile's label, never on it (a panel saw
        # '@ire' where 'wire' should be - sprite and text fighting a cell)
        bx, by = max(0, tiles[cur][0] - 1), tiles[cur][1]
        try:
            pad.addstr(by, bx, "@",
                       curses.A_BOLD | curses.color_pair(1))
        except curses.error:
            pass
        scr.erase()
        hud = (f" xp {s.xp} · streak {s.streak} · facts {len(s.resolved)}/"
               f"{len(world.questions)} · at {s.here}")
        if here_m and here_m != s.here:
            hud += f" · bee over {here_m}"
        scr.addstr(0, 0, hud[: maxx - 1], curses.A_REVERSE)
        scr.refresh()
        # viewport follows the bee
        vy = max(0, min(by - (maxy - 4) // 2, height - (maxy - 3)))
        vx = max(0, min(bx - maxx // 2, map_w - maxx))
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
            n = zone_open.get(world.modules[here_m].zone, 0)
            info = ("an unseen tile - Enter tries to travel, or scout "
                    "in the shell"
                    + (f" · {n} open quest{'s' if n != 1 else ''} in "
                       f"this district" if n else ""))
        line = msg or whisper_line or info
        attr = (curses.color_pair(5) | curses.A_BOLD
                if line.startswith("~") else curses.A_DIM)
        scr.addstr(maxy - 1, 0, line[: maxx - 1], attr)
        msg = ""  # events flash once; ambient info returns next frame
        scr.refresh()

        k = scr.getch()
        if k == curses.KEY_RESIZE:
            _maxy, _maxx = scr.getmaxyx()
            rooms, tiles, height, tile_w = compute_layout(
                world, width=max(60, _maxx - 2))
            map_w = max(x + w for x, y, w, h in rooms.values()) + 3
            pad = curses.newpad(height + 4, max(map_w, _maxx + 1))
            continue  # cur is a module name, so the bee survives reflow
        if k in (ord("Q"), 27):
            return
        elif k in (curses.KEY_LEFT, ord("a"), curses.KEY_RIGHT, ord("d"),
                   curses.KEY_UP, ord("w"), curses.KEY_DOWN, ord("s")):
            dx = (-1 if k in (curses.KEY_LEFT, ord("a"))
                  else 1 if k in (curses.KEY_RIGHT, ord("d")) else 0)
            dy = (-1 if k in (curses.KEY_UP, ord("w"))
                  else 1 if k in (curses.KEY_DOWN, ord("s")) else 0)
            nxt = hop(cur, dx, dy)
            if nxt:
                cur = nxt
                # the tall-grass encounter: every hop lands on a module,
                # and a new one whispers (round W1)
                if cur != whisper_tile:
                    whisper_line, whisper_tile = "", None
                whisper = _whisper(world, s, cur)
                if whisper:
                    whisper_line, whisper_tile = whisper, cur
                    save(s)
            else:
                msg = "the map ends here"
        elif k in (curses.KEY_ENTER, 10, 13) and here_m:
            try:
                how = engine.go(world, s, here_m)
                save(s)
                whisper = _whisper(world, s, s.here)
                msg = f"[{how}] arrived at {s.here}"
                if whisper:
                    whisper_line, whisper_tile = whisper, here_m
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
            # standing on a tile that starts exactly one open quest: track
            # it, so the shell you answer in already has the id in its
            # prompt (the loop the first-visit card teaches)
            if here_m:
                mine = [q.id for q in world.questions.values()
                        if q.id not in s.resolved
                        and here_m == (q.truth.get("src")
                                       or q.truth.get("target")
                                       or q.truth.get("anchor")
                                       or q.truth.get("a"))]
                if len(mine) == 1:
                    s.focus = mine[0]
                    save(s)
            if _overlay(scr,
                        render.render_quests(world, s, zid).splitlines(),
                        title="quests here (answer them in the shell)"):
                return
        elif k == ord("?"):
            if _overlay(scr, HELP_LINES, title="help"):
                return


def run_overworld(world: World, s: Session, save, sessions_dir=None) -> None:
    import sys
    if not sys.stdout.isatty():
        raise GameError("the overworld needs a real terminal - it is a "
                        "screen, not a stream (agents and pipes keep the "
                        "one-shot commands)")
    curses.wrapper(_main, world, s, save, sessions_dir)
