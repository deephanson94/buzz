"""New-game+: the hive moved while you were away.

Design doc decision #10: worlds are pinned to a commit SHA, and the diff
between the pinned SHA and the repo's new HEAD is a retention mechanic -
"this district changed since you cleared it" content. v1 keeps it light:
report the disturbance, and spawn AFTERSHOCK quests from real cross-module
commits that landed since the pin.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .model import World, Question

MAX_AFTERSHOCKS = 4
BORING = ("release", "bump", "update version", "prepare", "changelog")


def _log_since(repo: Path, old_sha: str):
    try:
        raw = subprocess.run(
            ["git", "log", "--no-merges", "--name-only",
             "--pretty=format:__C__%as|%s", f"{old_sha}..HEAD"],
            cwd=repo, capture_output=True, text=True, timeout=120,
        )
        if raw.returncode != 0:
            return None
    except Exception:
        return None
    commits, date, subject, files = [], "", "", []
    started = False
    for line in raw.stdout.splitlines():
        if line.startswith("__C__"):
            if started:
                commits.append({"date": date, "subject": subject, "files": files})
            started = True
            date, _, subject = line[5:].partition("|")
            files = []
        elif line.strip():
            files.append(line.strip())
    if started:
        commits.append({"date": date, "subject": subject, "files": files})
    return commits


def rescout(world: World, repo: Path) -> dict:
    repo = repo.resolve()
    new_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                             capture_output=True, text=True).stdout.strip()
    if not new_sha:
        return {"error": "not a git repository"}
    if new_sha == world.sha:
        return {"moved": False}
    commits = _log_since(repo, world.sha)
    if commits is None:
        return {"error": f"cannot diff {world.sha[:10]}..HEAD (shallow clone?)"}

    path_to_mod = {m.path: m.name for m in world.modules.values()}
    disturbed: dict[str, int] = {}
    aftershocks = []
    for c in commits:
        mods = sorted({path_to_mod[f] for f in c["files"] if f in path_to_mod})
        for m in mods:
            disturbed[m] = disturbed.get(m, 0) + 1
        if (len(mods) == 2 and len(c["subject"]) > 15
                and not c["subject"].lower().startswith(BORING)):
            a, b = mods
            subj = c["subject"].lower().replace("_", "")
            if any(m.split(".")[-1].strip("_").replace("_", "") in subj
                   for m in mods):
                continue  # subject names a module - answer would leak
            aftershocks.append((c, a, b))

    made = []
    for c, a, b in aftershocks[:MAX_AFTERSHOCKS]:
        qid = f"q{len(world.questions) + 1}"
        suspects = sorted({b} | set(
            sorted(world.modules, key=lambda x: -world.modules[x].commits)[:5]
        ) - {a})[:5]
        if b not in suspects:
            suspects = sorted(suspects[:4] + [b])
        world.questions[qid] = Question(
            id=qid, zone=world.modules[a].zone, qtype="patch", verb="point",
            prompt=(f"AFTERSHOCK - the hive moved while you were away. "
                    f"On {c['date']} a fresh change landed: "
                    f"\"{c['subject'][:110]}\". It touched {a} - and exactly "
                    f"one other module had to move with it. "
                    f"Suspects: {', '.join(suspects)}. "
                    f"Point at the companion: answer point <module>."),
            truth={"module": b, "anchor": a, "subject": c["subject"][:110],
                   "date": c["date"], "suspects": suspects},
            xp=25, distance=2)
        made.append(qid)

    zones_hit = sorted({world.zones[world.modules[m].zone].name
                        for m in disturbed if m in world.modules})
    world.sha = new_sha
    return {"moved": True, "commits": len(commits),
            "disturbed": dict(sorted(disturbed.items(), key=lambda kv: -kv[1])),
            "zones": zones_hit, "aftershocks": made, "new_sha": new_sha}
