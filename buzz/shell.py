"""The interactive shell: buzz as a game you sit inside, not a command you
retype. One process, readline tab-completion over everything you can
currently see (the completer respects the fog), a persistent HUD line, and
no 'buzz ' prefix. One-shot commands keep working for pipes and agents.
"""
from __future__ import annotations

from .engine import GameError
from .model import World, Session
from .ui import paint

COMMANDS = [
    "map", "look", "edges", "go", "quests", "quest", "scout", "answer",
    "hint", "probe", "trace", "chronicle", "who", "flow", "notes", "atlas",
    "recap", "standings", "rescout", "status", "words", "wanted",
    "export", "exam", "badges", "tui", "help", "quit",
]
VERBS = ["walk", "edge", "region", "place", "point", "order"]

SHORT_HELP = """the moves (tab completes everything; no 'buzz' prefix needed):
  map / look [m] / go <m>      the map; read one file; move to it
  quests / quest <id>          this district's challenges; read one in full
  answer <id> <answer...>      submit an answer - the ONLY source of XP
  hint <id>                    3 levels of help (costs XP; 3rd gives it away)
  scout <district>             reveal which files a district holds (z1, z2...)
  probe <a> <b>                how are two files related? imports + shared commits
  trace <m1> <m2> ...          test a chain of imports BEFORE you answer
  who <m>                      which files import this one\n  flow <m>                     where a file's work GOES at runtime (calls)
  chronicle <m>                this file's commit history
  edges [district]             every import inside a district, counted up
  notes                        the lessons you have learned so far\n  exam                         recall run: re-answer solved quests from\n                               memory - retention is the score\n  badges                       the titles this run has earned
  atlas / recap / standings    visual HTML map / your field notes / leaderboard
  status / rescout             your progress / check whether the repo changed
  wanted [guess]               today's mystery module - 3 guesses, small bounty
  export                       bundle atlas + notes into an onboarding pack
  words                        the game's vocabulary in plain language\n  tui                          the OVERWORLD: walk the map with arrow keys
  quit                         leave (progress saves after every move)
names are forgiving: any unique tail works ('backend' finds
transports.trunkline.backend). Confused by a term? try: words
"""


def _hud(world: World, s: Session) -> str:
    from .render import masked_modules
    zid = world.modules[s.here].zone
    # the HUD must not leak a zone the fog still masks (its place quest
    # is literally the question "which district is this?")
    zone = ("???" if s.here in masked_modules(world, s)
            else world.zones[zid].name)
    facts = len(s.resolved)
    total = len(world.questions)
    parts = [
        f"xp {s.xp}",
        f"streak {s.streak}",
        f"facts {facts}/{total}",
        f"{zone} @ {s.here}",
    ]
    return paint("  ".join(f"[{p}]" for p in parts), "dim")


def _completer_factory(world: World, s: Session):
    def complete(text: str, state: int):
        try:
            import readline
            buf = readline.get_line_buffer()
        except Exception:
            buf = text
        words = buf.split()
        at_first = not words or (len(words) == 1 and not buf.endswith(" "))
        cands: list[str] = []
        if at_first:
            cands = COMMANDS
        else:
            cmd = words[0]
            argn = len(words) - (0 if buf.endswith(" ") else 1)
            if cmd == "answer" and argn == 1:
                cands = [q.id for q in world.questions.values()
                         if q.id not in s.resolved] + list(s.followups)
            elif cmd == "answer" and argn == 2:
                cands = VERBS
            elif cmd in ("quest", "hint") and argn == 1:
                cands = list(world.questions) + list(s.followups)
            elif cmd in ("scout", "edges", "quests"):
                cands = list(world.zones) + [z.name for z in
                                             world.zones.values()]
            else:
                # module names - only what the fog has already yielded
                cands = sorted(s.seen)
        hits = [c for c in cands if c.startswith(text)]
        # a dotted name completes segment-wise too: 'back' -> ...backend
        if not hits and text:
            hits = [c for c in cands
                    if any(seg.startswith(text) for seg in c.split("."))]
        return hits[state] if state < len(hits) else None
    return complete


def run_shell(world: World, s: Session, save) -> None:
    try:
        import readline
        readline.set_completer_delims(" ")
        readline.set_completer(_completer_factory(world, s))
        readline.parse_and_bind("tab: complete")
    except Exception:
        pass
    print(paint("(interactive - type a command, tab completes, "
                "'?' for moves, 'quit' to leave)", "dim"))
    last_hud = None
    while True:
        # reprint the HUD only when something on it changed - six identical
        # HUD lines in a scrollback bury the output that mattered
        cur = _hud(world, s)
        if cur != last_hud:
            print(cur)
            last_hud = cur
        try:
            line = input(paint("buzz> ", "gold"))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        parts = line.split()
        if not parts:
            from .cli import _try_next
            print(_try_next(world, s))
            continue
        if parts[0] == "buzz" and len(parts) > 1:
            parts = parts[1:]  # 'buzz look' inside the shell means 'look'
        cmd, rest = parts[0], parts[1:]
        if cmd in ("quit", "exit", "q"):
            break
        if cmd in ("help", "?"):
            print(SHORT_HELP)
            continue
        if cmd in ("tui", "overworld"):
            try:
                from .overworld import run_overworld
                from .cli import game_dir
                run_overworld(world, s, save,
                              sessions_dir=game_dir() / "sessions")
                print(paint("(back from the overworld - the shell "
                            "continues)", "dim"))
            except GameError as e:
                print(paint(f"! {e}", "red"))
            except Exception as e:
                print(paint(f"! overworld error: {e}", "red"))
            continue
        if cmd in ("analyze", "play", "calibrate", "author", "check"):
            print("! that's a setup command - run it outside the shell "
                  "(quit first)")
            continue
        try:
            from .cli import dispatch
            dispatch(world, s, cmd, rest)
        except GameError as e:
            print(paint(f"! {e}", "red"))
        except Exception as e:  # a crash should never eat the session
            print(paint(f"! unexpected error: {e}", "red"))
        save(s)
        if s.victory:
            pass  # the victory banner already printed; keep playing or quit
    facts = len(s.resolved)
    print(paint(f"session saved - {facts} fact(s) about this repo are yours "
                f"now. 'buzz recap' compiles them into field notes.", "cyan"))
