"""The wanted poster: one mystery module a day, guessed from its shape.

Every fact on the poster is mechanical - degrees, zone, age, size, git
co-change - assembled without naming the module (rule: ground truth
never comes from LLM prose). Three guesses; each miss buys a sharper
clue. First solve of the day pays a small bounty; running out of
guesses reveals the answer and costs nothing (rule: wrong answers never
subtract). The pick is deterministic in (date, world sha), so everyone
hunting the same hive hunts the same fugitive.
"""
from __future__ import annotations

import datetime
import hashlib

from .model import World, Session
from . import engine

BOUNTY = 15
MAX_GUESSES = 3


def _today() -> str:
    return datetime.date.today().isoformat()


def pick(world: World, date: str | None = None) -> tuple[str, str]:
    date = date or _today()
    names = sorted(world.modules)
    linked = [n for n in names
              if world.modules[n].in_degree + world.modules[n].out_degree > 0]
    pool = linked or names
    h = int(hashlib.sha256(f"{date}:{world.sha}".encode()).hexdigest(), 16)
    return date, pool[h % len(pool)]


def _size_band(loc: int) -> str:
    if loc < 60:
        return "a small cell"
    if loc < 250:
        return "a mid-sized chamber"
    return "one of the hive's great halls"


def poster(world: World, name: str, s: Session = None) -> list[str]:
    m = world.modules[name]
    from .render import zone_label
    zone = (zone_label(world, s, m.zone) if s is not None
            else world.zones[m.zone].name)
    lines = [
        "WANTED - a fugitive module, description posted by the elders:",
        f"  last seen in {zone}.",
        f"  {m.in_degree} module(s) lean on it; it leans on "
        f"{m.out_degree}.",
        f"  {_size_band(m.loc)}, about {m.loc} lines.",
    ]
    return lines


def clue(world: World, name: str, miss: int) -> str:
    """One sharper fact per miss - mechanical, never the name itself."""
    m = world.modules[name]
    if miss == 1:
        partner = next((o for o, _n in world.cochange.get(name, [])), None)
        if partner:
            n_shared = world.cochange[name][0][1]
            return (f"clue: the chronicle files it alongside {partner} - "
                    f"{n_shared} shared patch(es)")
        neigh = ([e.dst for e in world.out_edges(name)]
                 or [e.src for e in world.in_edges(name)])
        if neigh:
            return f"clue: it is one hop from {sorted(neigh)[0]}"
        return "clue: it keeps to itself - no imports either way"
    born = m.born or "before the chronicle begins"
    return (f"clue: born {born}, {m.commits} patch(es) to its name, and "
            f"its name starts with '{name[0]}'")


def play(world: World, s: Session, guess: str | None) -> list[str]:
    date, target = pick(world)
    w = s.wanted
    if w.get("date") != date:
        w = s.wanted = {"date": date, "guesses": [], "done": False,
                        "won": False}
    out: list[str] = []
    if w["done"]:
        verdict = ("captured" if w["won"] else "escaped")
        out.append(f"today's fugitive already {verdict}: it was {target}. "
                   f"A new poster goes up tomorrow.")
        return out
    if guess is None:
        out += poster(world, target, s)
        for i in range(len(w["guesses"])):
            out.append("  " + clue(world, target, i + 1))
        left = MAX_GUESSES - len(w["guesses"])
        out.append(f"{left} guess(es) left - 'buzz wanted <module>' to "
                   f"accuse. Wrong guesses cost nothing but sharpen "
                   f"the poster.")
        return out
    try:
        g = engine.resolve_module(world, guess)
    except engine.GameError:
        out.append(f"no module called '{guess}' in this hive - that one "
                   f"is free (guesses spend only on real names)")
        return out
    if g == target:
        w["done"] = True
        w["won"] = True
        s.xp += BOUNTY
        s.max_xp += BOUNTY
        s.log.append(f"wanted-day {date}: captured {target} in "
                     f"{len(w['guesses']) + 1} guess(es)")
        engine._name_seen(s, target)
        out.append(f"CAPTURED. The fugitive was {target} - identified in "
                   f"{len(w['guesses']) + 1} guess(es). +{BOUNTY} XP "
                   f"bounty. Next poster goes up tomorrow.")
        return out
    w["guesses"].append(g)
    misses = len(w["guesses"])
    if misses >= MAX_GUESSES:
        w["done"] = True
        out.append(f"the trail goes cold - it was {target}. No bounty, "
                   f"nothing lost; study it with 'buzz look {target}'. "
                   f"A new poster goes up tomorrow.")
        return out
    out.append(f"not {g} - the poster sharpens:")
    out.append("  " + clue(world, target, misses))
    out.append(f"{MAX_GUESSES - misses} guess(es) left")
    return out
