"""buzz CLI: stateful commands, JSON persistence under .buzz/.

Every command prints the relevant view plus a contextual 'try next' line, so
the game is discoverable move by move (humans and agents alike).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import engine, render
from .model import World, Session
from .engine import GameError


def game_dir() -> Path:
    return Path(os.environ.get("BUZZ_DIR", ".buzz"))


def session_path() -> Path:
    name = os.environ.get("BUZZ_SESSION", "default")
    return game_dir() / "sessions" / f"{name}.json"


def load_world() -> World:
    p = game_dir() / "world.json"
    if not p.exists():
        raise SystemExit("no world here. Run: buzz analyze <repo-path>")
    return World.load(p)


def load_session(world: World) -> Session:
    p = session_path()
    if not p.exists():
        raise SystemExit("no session. Run: buzz play")
    return Session.load(p)


def cmd_analyze(args: list[str]) -> None:
    from .analyze import analyze
    from .questions import generate_questions
    if not args:
        raise SystemExit("usage: buzz analyze <repo-path>")
    world = analyze(Path(args[0]))
    generate_questions(world)
    world.save(game_dir() / "world.json")
    nq = len(world.questions)
    print(f"world built: {len(world.modules)} modules, {len(world.edges)} edges, "
          f"{len(world.zones)} zones, {nq} quests  (pinned to {world.sha[:10]})")
    print("start playing: buzz play")


def cmd_play() -> None:
    world = load_world()
    s = engine.new_session(world)
    s.save(session_path())
    name = world.repo.rsplit("/", 1)[-1]
    print(f"""Welcome to the hive: {name}

This codebase is a hive and you are a scout bee. The map starts dark.
Walk the import edges, light up the districts, and answer quests to prove
you understand how the code fits together. XP comes ONLY from quests -
exploring is free and safe. Wrong answers just reveal the truth.

You wake up at {world.start} - the module with the widest view of the hive.
""")
    print(render.render_map(world, s))
    print("\ntry next: buzz look   (then: buzz quests)")


def _try_next(world: World, s: Session) -> str:
    zone = world.modules[s.here].zone
    open_q = [q for q in world.questions.values()
              if q.zone == zone and q.id not in s.resolved
              and (not q.boss or s.boss_open)]
    if open_q:
        q = sorted(open_q, key=lambda q: q.xp)[0]
        return f"try next: buzz quest {q.id}"
    nxt = [z for z in sorted(world.zones.values(), key=lambda z: z.order)
           if z.id not in s.cleared]
    if nxt:
        target = max(nxt[0].members, key=lambda m: world.modules[m].pagerank)
        return (f"this zone is done - head for {nxt[0].name} "
                f"(e.g. buzz go {target}, or explore with buzz map)")
    return "all zones cleared - buzz status"


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(render.HELP)
        return
    cmd, rest = args[0], args[1:]

    if cmd == "analyze":
        cmd_analyze(rest)
        return
    if cmd == "play":
        cmd_play()
        return

    world = load_world()
    s = load_session(world)
    try:
        if cmd == "map":
            print(render.render_map(world, s))
        elif cmd == "look":
            print(render.render_look(world, s))
            print("\n" + _try_next(world, s))
        elif cmd == "go":
            if not rest:
                raise GameError("usage: buzz go <module>")
            how = engine.go(world, s, rest[0])
            m = world.modules[s.here]
            outs = world.out_edges(s.here)
            sealed = sum(1 for e in outs if e.kind == "lazy")
            print(f"[{how}] you arrive at {s.here} "
                  f"({world.zones[m.zone].name}, role: {m.role}) - "
                  f"{len(outs)} out-edges"
                  + (f", {sealed} sealed" if sealed else "")
                  + ". 'buzz look' for detail.")
            print(_try_next(world, s))
        elif cmd == "quests":
            if rest and rest[0] == "all":
                for z in sorted(world.zones.values(), key=lambda z: z.order):
                    print(render.render_quests(world, s, z.id).split("\n")[0])
                print("\n('buzz quests' in a zone lists its quest ids)")
            elif rest:
                print(render.render_quests(world, s, engine.resolve_zone(world, rest[0])))
            else:
                print(render.render_quests(world, s, world.modules[s.here].zone))
        elif cmd == "quest":
            if not rest:
                raise GameError("usage: buzz quest <id>")
            q = engine.get_question(world, s, rest[0])
            engine.reveal_prompt_modules(world, s, q)
            print(render.render_question(world, s, q))
        elif cmd == "scout":
            if not rest:
                raise GameError("usage: buzz scout <zone-id-or-name>")
            n = engine.scout(world, s, " ".join(rest))
            print(f"your scouts report back: {n} new module name(s) on the map "
                  f"(names only - fly there to read their imports)")
        elif cmd == "answer":
            if len(rest) < 3:
                raise GameError("usage: buzz answer <id> <walk|edge|region|place> ...")
            qid, verb, params = rest[0], rest[1], rest[2:]
            pre_log = len(s.log)
            r = engine.answer(world, s, qid, verb, params)
            lesson = engine.LESSONS.get(r["q"].qtype)
            if r.get("retry"):
                print(f"NEARLY. {r['note']}")
            elif r["correct"]:
                print(f"CORRECT! +{r['gained']} XP  ({r['explain']})")
            elif r["partial"]:
                print(f"CLOSE - partial credit, +{r['gained']} XP. {r['note']}")
                print(f"the truth: {r['explain']}")
            else:
                print(f"WRONG - but knowledge is never wasted. {r['note']}")
                print(f"the truth: {r['explain']}")
                if r["followup"]:
                    print(f"a follow-up quest appeared: buzz quest {r['followup']}")
            if lesson and not r.get("retry"):
                print(f"(lesson: {lesson})")
            for ev in s.log[pre_log:]:
                print(f">>> {ev.upper()} <<<")
            if s.victory:
                print("\n" + render.render_status(world, s))
            else:
                print("\n" + _try_next(world, s))
        elif cmd == "probe":
            if len(rest) != 2:
                raise GameError("usage: buzz probe <module-a> <module-b>")
            a = engine.resolve_module(world, rest[0])
            b = engine.resolve_module(world, rest[1])
            print(engine.probe(world, a, b))
        elif cmd == "hint":
            if not rest:
                raise GameError("usage: buzz hint <id>")
            lvl, text = engine.hint(world, s, rest[0])
            print(f"oracle hint {lvl}: {text}")
        elif cmd == "status":
            print(render.render_status(world, s))
        else:
            raise GameError(f"unknown command '{cmd}' - try: buzz help")
    except GameError as e:
        print(f"! {e}")
        sys.exit(1)
    finally:
        s.save(session_path())


if __name__ == "__main__":
    main()
