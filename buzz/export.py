"""The onboarding pack: everything a run taught, bundled for handing on.

`buzz export` writes a directory a player can give to the NEXT person
who joins the codebase: the atlas (visual map), the field notes (every
evidence-backed lesson), and an index that explains what each file is.
Nothing here is new truth - it re-renders what the run already proved.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from .model import World, Session


def export(world: World, s: Session, out_dir: Path) -> tuple[Path, list[str]]:
    from .atlas import write_atlas
    from .recap import render_recap

    out = out_dir / "onboarding-pack"
    out.mkdir(parents=True, exist_ok=True)
    files: list[str] = []

    write_atlas(world, s, out / "atlas.html")
    files.append("atlas.html - the visual map: districts, fog state, "
                 "strata (dependency depth), and every journey you traced")

    (out / "field_notes.md").write_text(render_recap(world, s))
    files.append("field_notes.md - the run's evidence-backed notes: what "
                 "was learned, with the witnesses that prove it")

    solved = sum(1 for v in s.resolved.values() if v == "correct")
    lines = [
        f"# Onboarding pack - {Path(world.repo).name}",
        "",
        f"Built from a buzz run on {datetime.date.today().isoformat()}.",
        f"Source: `{world.repo}` at commit `{world.sha[:10]}` - point "
        f"your editor there.",
        f"The run covered {len(set(s.discovered))} of "
        f"{len(world.modules)} modules across {len(world.zones)} "
        f"district(s), and proved {solved} fact(s) about how this "
        f"codebase actually fits together.",
        "",
        "## What is in here",
        "",
    ]
    lines += [f"- **{f.split(' - ')[0]}** - {f.split(' - ', 1)[1]}"
              for f in files]
    lines += [
        "",
        "## How to use it",
        "",
        "1. Open `atlas.html` in a browser. Read the district layout "
        "first, then THE STRATA - the layer diagram is the 30-second "
        "version of the architecture.",
        "2. Read `field_notes.md` top to bottom. Every claim in it was "
        "verified against the import graph or the git history, not "
        "written from memory.",
        "3. Better still: run your own hunt. `pip install` buzz, then "
        f"`buzz analyze <path-to-{Path(world.repo).name}> && buzz play`.",
    ]
    # where this survey stopped - so the next scout continues instead of
    # restarting (wave-3 audit: a raw percentage is not a handover)
    from .render import zone_label
    unseen_zones = [zone_label(world, s, z.id)
                    for z in world.zones.values()
                    if not any(m in set(s.seen) for m in z.members)]
    open_q = sum(1 for q in world.questions.values()
                 if q.id not in s.resolved)
    if unseen_zones or open_q:
        lines += ["", "## Where this survey stopped", ""]
        if unseen_zones:
            lines.append("- Districts never reached: "
                         + ", ".join(sorted(unseen_zones)))
        if open_q:
            lines.append(f"- {open_q} quest(s) still open - `buzz play` "
                         f"in the same game directory picks them up.")
    lines += [
        "",
        "*Assembled by buzz - the map is not the territory, but this "
        "map was surveyed on foot.*",
    ]
    (out / "index.md").write_text("\n".join(lines) + "\n")
    files.insert(0, "index.md - start here")
    return out, files
