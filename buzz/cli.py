"""buzz CLI: stateful commands, JSON persistence under .buzz/.

Every command prints the relevant view plus a contextual 'try next' line, so
the game is discoverable move by move (humans and agents alike).
"""
from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

# players pipe output through head/less constantly; a closed pipe is not an
# error worth a traceback
try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass

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
        name = os.environ.get("BUZZ_SESSION", "default")
        raise SystemExit(
            f"no session named '{name}' in {p.parent} - run 'buzz play' to "
            f"start one, and check you are in the game directory with the "
            f"same BUZZ_SESSION exported as before")
    return Session.load(p)


def cmd_analyze(args: list[str]) -> None:
    from .analyze import analyze
    from .questions import generate_questions
    lore = "--lore" in args
    args = [a for a in args if a != "--lore"]
    if not args:
        raise SystemExit("usage: buzz analyze <repo-path> [--lore]")
    world = analyze(Path(args[0]))
    generate_questions(world)
    world.save(game_dir() / "world.json")
    if lore:
        from .lore import run_lore
        print("authoring the lore layer (an LLM reads the map + source "
              "heads; answers stay mechanically verified)...")
        try:
            r = run_lore(world)
            world.save(game_dir() / "world.json")
            print(f"lore: {len(r['added'])} semantic quest(s) added "
                  f"({len(r['rejected'])} rejected by validation), "
                  f"{r['zone_briefs']} district brief(s), "
                  f"{r['glosses']} module gloss(es)")
        except Exception as e:  # --lore must never break analyze
            print(f"lore skipped: {e}")
    nq = len(world.questions)
    print(f"world built: {len(world.modules)} modules, {len(world.edges)} edges, "
          f"{len(world.zones)} zones, {nq} quests  (pinned to {world.sha[:10]})")
    if len(world.modules) < 15 or len(world.edges) < 12:
        print("(a small hive: few modules, a flat import graph - expect a "
              "short campaign. buzz bites hardest on big, messy repos you "
              "don't already know)")
    print("start playing: buzz play")


def cmd_play() -> None:
    world = load_world()
    s = engine.new_session(world)
    s.save(session_path())
    name = world.repo.rsplit("/", 1)[-1]
    from .ui import paint
    print(paint(f"THE HIVE: {name}", "gold"))
    print(f"""You are a scout bee in a dark codebase. Explore freely (always
safe, always free); answer quests to earn XP and light up the map.
Wrong answers cost nothing - they reveal the truth.

You wake up at {world.start}.
""")
    print(render.render_map(world, s))
    print("\ntry next: buzz look   (then: buzz quests · 'tui' opens the "
          "walkable map screen)")


def _try_next(world: World, s: Session) -> str:
    zone = world.modules[s.here].zone
    open_q = [q for q in world.questions.values()
              if q.zone == zone and q.id not in s.resolved
              and (not q.boss or s.boss_open)]
    if open_q:
        q = sorted(open_q, key=lambda q: q.xp)[0]
        return f"try next: buzz quest {q.id}"
    nxt = [z for z in sorted(world.zones.values(), key=lambda z: z.order)
           if z.id not in s.cleared
           and any(q.zone == z.id and q.id not in s.resolved
                   for q in world.questions.values())]
    if nxt:
        from .render import known_zones
        nname = (nxt[0].name if nxt[0].id in known_zones(world, s)
                 else f"an unexplored district ({nxt[0].id})")
        target = max(nxt[0].members, key=lambda m: world.modules[m].pagerank)
        if target not in s.seen:
            # never suggest a command that will bounce off the fog
            s.seen.append(target)
            return (f"this zone is done - your scouts point the way to "
                    f"{nname}: buzz go {target}")
        return (f"this zone is done - head for {nname} "
                f"(e.g. buzz go {target}, or explore with buzz map)")
    return "all zones cleared - buzz status"


def _enter_shell(world: World, s: Session) -> None:
    from .shell import run_shell
    run_shell(world, s, lambda sess: sess.save(session_path()))


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        # bare `buzz` on a real terminal: drop straight into the game -
        # and when the game isn't set up yet, say the ONE next step
        # instead of a wall of help (a dogfooder asked "analyze, play,
        # or tui?" - the entry point should answer that itself)
        if sys.stdin.isatty():
            if not (game_dir() / "world.json").exists():
                print("no world in this directory yet.\n"
                      "  step 1:  buzz analyze <repo-path>   (once per "
                      "repo; add --lore for the semantic layer)\n"
                      "  step 2:  buzz play                  (starts your "
                      "run)\n"
                      "full reference: buzz help")
                return
            if not session_path().exists():
                print("world found, but no session yet - start one:\n"
                      "  buzz play\n"
                      "(then everything happens at the buzz> prompt; "
                      "'tui' there opens the map screen)")
                return
            world = load_world()
            s = load_session(world)
            _enter_shell(world, s)
            return
        print(render.HELP)
        return
    if args[0] in ("-h", "--help", "help"):
        print(render.HELP)
        return
    cmd, rest = args[0], args[1:]

    if cmd == "analyze":
        cmd_analyze(rest)
        return
    if cmd == "play":
        cmd_play()
        if sys.stdin.isatty():
            world = load_world()
            s = load_session(world)
            _enter_shell(world, s)
        return
    if cmd == "shell":
        world = load_world()
        s = load_session(world)
        _enter_shell(world, s)
        return
    if cmd in ("tui", "overworld"):
        world = load_world()
        s = load_session(world)
        from .overworld import run_overworld
        try:
            run_overworld(world, s, lambda sess: sess.save(session_path()),
                          sessions_dir=game_dir() / "sessions")
        except GameError as e:
            raise SystemExit(f"! {e}")
        return
    if cmd == "calibrate":
        from . import calibrate
        world = load_world()
        if rest and rest[0] == "export":
            p = game_dir() / "calibration.jsonl"
            rows = calibrate.export(world)
            p.write_text("\n".join(json.dumps(r) for r in rows))
            print(f"{len(rows)} questions exported to {p}")
        elif rest and rest[0] == "apply" and len(rest) == 2:
            results = json.loads(Path(rest[1]).read_text())
            summary = calibrate.apply_verdicts(world, results)
            world.save(game_dir() / "world.json")
            print(json.dumps(summary, indent=1))
        else:
            raise SystemExit("usage: buzz calibrate export | apply <results.json>")
        return
    if cmd == "author":
        from . import author
        world = load_world()
        if rest and rest[0] == "export":
            p = game_dir() / "author_brief.json"
            p.write_text(json.dumps(author.export_brief(world), indent=1))
            print(f"authoring brief written to {p}")
        elif rest and rest[0] == "apply" and len(rest) == 2:
            items = json.loads(Path(rest[1]).read_text())
            summary = author.apply_authored(world, items)
            world.save(game_dir() / "world.json")
            print(json.dumps(summary, indent=1))
        else:
            raise SystemExit("usage: buzz author export | apply <items.json>")
        return
    if cmd == "check":
        # calibration grader: no session, no XP, no side effects
        from . import calibrate
        world = load_world()
        if len(rest) < 3:
            raise SystemExit("usage: buzz check <qid> <verb> <args...>")
        ok = calibrate.check(world, rest[0], rest[1], rest[2:])
        print("CORRECT" if ok else "WRONG")
        return

    world = load_world()
    s = load_session(world)
    try:
        dispatch(world, s, cmd, rest)
    except GameError as e:
        print(f"! {e}")
        sys.exit(1)
    finally:
        s.save(session_path())


def dispatch(world: World, s: Session, cmd: str, rest: list[str]) -> None:
    """One game command against a live world+session. Shared by the one-shot
    CLI and the interactive shell; raises GameError, never exits."""
    if cmd == "map":
        print(render.render_map(world, s))
    elif cmd == "look":
        at = engine.peek(world, s, rest[0]) if rest else None
        print(render.render_look(world, s, at))
        print("\n" + _try_next(world, s))
    elif cmd == "edges":
        zid = (engine.resolve_zone(world, " ".join(rest)) if rest
               else world.modules[s.here].zone)
        print("\n".join(engine.zone_edges(world, zid, s)))
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
            print("every quest in the hive (id / type / XP / zone / status):")
            from .render import known_zones as _kz
            _known = _kz(world, s)
            for z in sorted(world.zones.values(), key=lambda z: z.order):
                zname = z.name if z.id in _known else "???"
                for q in sorted((q for q in world.questions.values()
                                 if q.zone == z.id),
                                key=lambda q: (q.boss, q.id)):
                    st = s.resolved.get(q.id, "open")
                    boss = " [BOSS]" if q.boss else ""
                    # an OPEN place quest filed under its district hands
                    # over its own answer - it lists as unplaced instead
                    shown = ("(unplaced - its district IS the answer)"
                             if q.qtype == "place" and st == "open"
                             else zname)
                    print(f"  {q.id:5} {q.qtype:8} {q.xp:>3}xp  "
                          f"{shown}{boss}  [{st}]")
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
            raise GameError("usage: buzz scout <district>  (z1, z2, or a "
                            "district name - 'map' lists them)")
        try:
            zid = engine.resolve_zone(world, " ".join(rest))
        except GameError:
            # they probably named a MODULE - do what they meant when the
            # map already shows where it lives (fog rules permitting)
            try:
                m = engine.resolve_module(world, rest[0])
            except GameError:
                raise GameError(f"no district called '{' '.join(rest)}' - "
                                f"scout takes a district (z1, z2...); "
                                f"'map' lists them")
            if m not in s.seen or m in render.masked_modules(world, s):
                raise GameError(f"{m} is a module, and its district is "
                                f"still unknown to you - scout takes a "
                                f"district id like z1")
            zid = world.modules[m].zone
            print(f"({m} is a module - scouting its district, "
                  f"{world.zones[zid].name})")
        gained = engine.scout(world, s, zid)
        masked = render.masked_modules(world, s)
        hidden_here = [m for m in world.zones[zid].members if m in masked]
        # name what was gained - EXCEPT place-quest targets: tying their
        # name to the district just scouted would hand over that answer
        namable = sorted(m for m in gained if m not in masked)
        # report ONLY the namable count: '3 new names' listing 2 would
        # betray that an unplaced module lives in this district, and a
        # per-zone 'sightings stay unplaced here' note narrowed every
        # place quest to one district for free (round WEBATLASc3)
        if namable:
            print(f"your scouts report back: {len(namable)} new name(s) "
                  f"on the map: {', '.join(namable)}"
                  f"  (names only - fly there to read their imports)")
        else:
            print("your scouts report back: nothing new to NAME in this "
                  "district (unplaced sightings, if any, appear on the "
                  "map without a district)")
    elif cmd == "answer":
        if len(rest) < 2:
            raise GameError("usage: buzz answer <id> [verb] <answer...> - "
                            "the verb (walk/edge/region/place/point) is "
                            "optional; the quest already knows its own")
        qid = rest[0]
        VERBS = ("walk", "edge", "region", "place", "point", "order")
        if rest[1] in VERBS:
            verb, params = rest[1], rest[2:]
        else:
            # first dogfooder's question: "what does point even mean?" -
            # they shouldn't have to know. The quest knows its verb.
            verb, params = engine.get_question(world, s, qid).verb, rest[1:]
        if not params:
            raise GameError("usage: buzz answer <id> [verb] <answer...>")
        pre_log = len(s.log)
        pre_victory = s.victory
        from .badges import earned as _earned
        pre_badges = {n for n, _ in _earned(world, s)}
        r = engine.answer(world, s, qid, verb, params)
        for bn, bd in _earned(world, s):
            if bn not in pre_badges:
                s.log.append(f"badge earned: {bn} - {bd}")
        lesson = r["q"].lesson or engine.LESSONS.get(r["q"].qtype)
        prior_lessons = set()
        for q2 in s.resolved:
            if q2 == qid:
                continue
            try:
                qq = engine.get_question(world, s, q2)
            except GameError:
                continue  # a calibration pass may have pruned it
            prior_lessons.add(qq.lesson or engine.LESSONS.get(qq.qtype))
        from .ui import paint
        if r.get("retry"):
            print(f"{paint('NEARLY.', 'yellow')} {r['note']}")
        elif r["correct"]:
            streak_note = f"  [streak x{s.streak}]" if s.streak >= 2 else ""
            print(f"{paint('CORRECT!', 'green')} +{r['gained']} XP"
                  f"{streak_note}  ({r['explain']})")
            if r["note"]:
                print(r["note"])
        elif r["partial"]:
            print(f"{paint('CLOSE', 'yellow')} - partial credit, "
                  f"+{r['gained']} XP. {r['note']}")
            print(f"the truth: {r['explain']}")
        else:
            print(f"{paint('WRONG', 'red')} - but knowledge is never "
                  f"wasted. {r['note']}")
            print(f"the truth: {r['explain']}")
            if r["followup"]:
                print(f"a follow-up quest appeared: buzz quest {r['followup']}")
        if not r.get("retry"):
            # make the learning visible: every resolved quest is a fact
            # banked, win or lose - the recap is built from exactly these.
            # A repeated lesson is honest about being reinforcement, so the
            # fanfare stays reserved for genuinely new insight
            if lesson and lesson in prior_lessons:
                print(paint(f"* field note #{len(s.resolved)} recorded "
                            f"(reinforces an earlier lesson)", "cyan"))
            else:
                print(paint(f"* field note #{len(s.resolved)} recorded"
                            + (f" - {lesson}" if lesson else ""), "cyan"))
        for ev in s.log[pre_log:]:
            print(paint(f">>> {ev.upper()} <<<", "magenta"))
        # the full status block prints ONCE, at the moment of victory -
        # re-dumping it after every later answer buried the feedback that
        # actually changed (a panel's unanimous worst-moment)
        if s.victory and not pre_victory:
            print("\n" + render.render_status(world, s))
        else:
            print("\n" + _try_next(world, s))
    elif cmd == "standings":
        rows = []
        for p in sorted((game_dir() / "sessions").glob("*.json")):
            try:
                other = Session.load(p)
            except Exception:
                continue
            solved = sum(1 for v in other.resolved.values() if v == "correct")
            here = other.here
            # the district name is masked by what the VIEWING session
            # has earned - a shared leaderboard was a turn-zero reveal
            # of five district names (round c7)
            from .render import known_zones as _kz2
            _viewer_known = _kz2(world, s)
            if here in world.modules:
                _hz = world.modules[here].zone
                at = (world.zones[_hz].name if _hz in _viewer_known
                      else f"??? ({_hz})")
            else:
                at = "?"
            rows.append((other.xp, p.stem, engine.rank(world, other),
                         solved, len(other.resolved),
                         len(other.discovered), other.streak,
                         other.victory, at))
        rows.sort(reverse=True)
        print("standings for this hive (all scouts, shared world):")
        print(f"  {'scout':16} {'XP':>5}  {'rank':12} {'solved':>9} "
              f"{'visited':>8} {'streak':>7}  now in")
        for xp, name, rk, solved, att, disc, streak, vic, at in rows:
            flag = " *CLEAR*" if vic else ""
            print(f"  {name:16} {xp:>5}  {rk:12} {solved:>4}/{att:<4} "
                  f"{disc:>8} {streak:>7}  {at}{flag}")
    elif cmd == "rescout":
        from .rescout import rescout as _rescout
        target = Path(rest[0]) if rest else Path(world.repo)
        r = _rescout(world, target)
        if r.get("error"):
            raise GameError(r["error"])
        if not r.get("moved"):
            print("the ground is quiet - no new commits since the "
                  f"world was last pinned ({world.sha[:10]})")
            mine = [qid for qid in r.get("standing", [])
                    if qid not in s.resolved]
            if mine:
                print(f"but the last tremor's AFTERSHOCK quest(s) still "
                      f"stand for you: {', '.join(mine)} - "
                      f"'buzz quest <id>' to take them on")
            elif r.get("standing"):
                print("(you already settled every aftershock on record)")
        else:
            world.save(game_dir() / "world.json")
            print(f"the hive MOVED: {r['commits']} new commit(s) since "
                  f"your pin (now re-pinned to {r['new_sha'][:10]})")
            if r["zones"]:
                print("disturbed districts: " + ", ".join(r["zones"]))
            top = list(r["disturbed"].items())[:6]
            if top:
                print("most-shaken modules: "
                      + ", ".join(f"{m} ({n})" for m, n in top))
            if r["aftershocks"]:
                print(f"AFTERSHOCK quest(s) spawned: "
                      f"{', '.join(r['aftershocks'])} - "
                      f"'buzz quest <id>' to take them on")
    elif cmd == "atlas":
        from .atlas import write_atlas
        # session-scoped file: two scouts sharing one hive must not
        # clobber each other's render (a full-clear atlas was destroyed
        # by a throwaway session's regenerate in round WEBATLAS)
        sname = os.environ.get("BUZZ_SESSION", "default")
        fname = "atlas.html" if sname == "default" else f"atlas-{sname}.html"
        p = write_atlas(world, s, game_dir() / fname)
        print(f"atlas rendered: {p.resolve()}")
        print("open it in a browser; regenerate after moving")
    elif cmd == "recap":
        from .recap import render_recap
        text = render_recap(world, s)
        sname = os.environ.get("BUZZ_SESSION", "default")
        fname = ("field_notes.md" if sname == "default"
                 else f"field_notes-{sname}.md")
        p = game_dir() / fname
        p.write_text(text)
        print(text)
        print(f"\n(saved to {p.resolve()})")
    elif cmd == "trace":
        if len(rest) < 2:
            raise GameError("usage: buzz trace <module> <module> [module ...]")
        mods = [engine.resolve_module(world, x) for x in rest]
        print("\n".join(engine.trace(world, s, mods)))
    elif cmd == "chronicle":
        if not rest:
            raise GameError("usage: buzz chronicle <module>")
        print("\n".join(engine.chronicle(world, s, rest[0])))
    elif cmd == "flow":
        if not rest:
            raise GameError("usage: buzz flow <module>  (a module you have "
                            "already read)")
        print("\n".join(engine.flow(world, s, rest[0])))
    elif cmd == "who":
        if not rest:
            raise GameError("usage: buzz who <module>")
        print("\n".join(engine.who(world, rest[0], s)))
    elif cmd == "probe":
        if len(rest) < 2:
            raise GameError("usage: buzz probe <module> <suspect> [suspect ...]")
        a = engine.resolve_module(world, rest[0])
        for other in rest[1:]:
            b = engine.resolve_module(world, other)
            engine._name_seen(s, a, b)
            print(f"[{a} x {b}]")
            print(engine.probe(world, a, b))
    elif cmd == "exam":
        from . import exam as _exam
        if not rest:
            r = _exam.start(world, s)
            q = r["q"]
            if r.get("resumed"):
                print(f"exam in progress - picking up where you were "
                      f"(answers already given stand):")
            else:
                print(f"THE EXAM - recall, no tools, no hints, one "
                      f"attempt each, 0 XP. {r['total']} questions from "
                      f"your OLDEST solves - that is where forgetting "
                      f"lives. Retention is the score.")
            print(f"\n[{r['i'] + 1}/{r['total']}] {_exam.clean_prompt(q)}")
            print("answer with: buzz exam <your answer...>")
        else:
            from .badges import earned as _earned
            pre_badges = {n for n, _ in _earned(world, s)}
            r = _exam.grade(world, s, rest)
            from .ui import paint
            print(paint("RECALLED." if r["ok"] else "slipped away.",
                        "green" if r["ok"] else "yellow"))
            if not r["ok"]:
                # 'you proved this once' asserted a canonical chain as
                # the player's own - several chains can be equally true
                print(f"  one correct answer: {r['truth']}  (yours may "
                      f"have been another - 'buzz quest {r['q'].id}' "
                      f"re-reads it)")
            if r["done"]:
                print(f"\nexam over: {r['pct']}% retention "
                      f"({len(s.exam['correct'])}/{r['total']}) - "
                      f"title: {r['title']}"
                      + (f" · personal best {r['best']}%"
                         if r["best"] != r["pct"] else ""))
                for bn, bd in _earned(world, s):
                    if bn not in pre_badges:
                        print(paint(f">>> BADGE EARNED: {bn.upper()} - "
                                    f"{bd} <<<", "magenta"))
                        s.log.append(f"badge earned: {bn} - {bd}")
                print("(retention fades - re-examine after your next "
                      "session away)")
            else:
                q = r["next"]
                print(f"\n[{r['i'] + 1}/{r['total']}] "
                      f"{_exam.clean_prompt(q)}")
                print("answer with: buzz exam <your answer...>")
    elif cmd == "badges":
        from .badges import progress
        print("badges of this hive:")
        for name, desc, ok, note in progress(world, s):
            mark = "*" if ok else " "
            tail = f" {note}" if note else ""
            print(f"  [{mark}] {name:12} - {desc}{tail}")
    elif cmd in ("notes", "facts"):
        # the mid-run glance every panel asked for: just the lessons, no
        # wall of recap - keeps 'I am learning' alive between beats
        seen_lessons: list[str] = []
        for qid2 in s.resolved:
            try:
                q2 = engine.get_question(world, s, qid2)
            except GameError:
                continue
            les = q2.lesson or engine.LESSONS.get(q2.qtype)
            if les and les not in seen_lessons:
                seen_lessons.append(les)
        print(f"field notes so far: {len(s.resolved)} fact(s) banked, "
              f"{len(seen_lessons)} transferable lesson(s):")
        for i, les in enumerate(seen_lessons, 1):
            print(f"  {i}. {les}")
        if not seen_lessons:
            print("  (none yet - answer a quest, right or wrong, and the "
                  "lesson lands here)")
        print("(full evidence-backed notes: buzz recap)")
    elif cmd == "hint":
        if not rest:
            raise GameError("usage: buzz hint <id>")
        lvl, text = engine.hint(world, s, rest[0])
        print(f"oracle hint {lvl}: {text}")
    elif cmd == "wanted":
        from .wanted import play as wanted_play
        for line in wanted_play(world, s, rest[0] if rest else None):
            print(line)
    elif cmd == "export":
        from .export import export as export_pack
        out, files = export_pack(world, s, Path("."))
        print(f"onboarding pack written to {out.resolve()}:")
        for f in files:
            print(f"  {f.split(' - ')[0]}")
        print("hand the directory to the next scout - or read index.md")
    elif cmd == "status":
        print(render.render_status(world, s))
    elif cmd in ("words", "glossary", "jargon"):
        print(render.GLOSSARY)
    else:
        import difflib
        from .shell import COMMANDS
        close = difflib.get_close_matches(cmd, COMMANDS, n=1, cutoff=0.6)
        hint = f" - did you mean '{close[0]}'?" if close else ""
        raise GameError(f"unknown command '{cmd}'{hint} ('help' lists "
                        f"the moves, 'words' explains the vocabulary)")


if __name__ == "__main__":
    main()
