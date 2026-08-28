"""Data model for the Buzz world (analysis output) and player session."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Edge kinds. TOP is a plain module-level import; LAZY is a function-level
# import (a "sealed tunnel" until the ability unlocks); TYPE is a
# TYPE_CHECKING-only import (visible, dashed — it never runs).
TOP = "top"
LAZY = "lazy"
TYPE = "type"

ROLE_BOSS = "boss"
ROLE_BEDROCK = "bedrock"
ROLE_GATE = "gate"
ROLE_SWAMP = "swamp"
ROLE_LEAF = "leaf"
ROLE_NORMAL = "normal"

ROLE_GLYPH = {
    ROLE_BOSS: "[BOSS]",
    ROLE_BEDROCK: "[bedrock]",
    ROLE_GATE: "[gate]",
    ROLE_SWAMP: "[swamp]",
    ROLE_LEAF: "",
    ROLE_NORMAL: "",
}


@dataclass
class Module:
    name: str                 # short display name (unique)
    path: str                 # path relative to repo root
    zone: str                 # zone id
    role: str = ROLE_NORMAL
    loc: int = 0
    commits: int = 0
    authors: int = 0
    pagerank: float = 0.0
    betweenness: float = 0.0
    in_degree: int = 0
    out_degree: int = 0
    born: str = ""            # date of first commit touching this file
    doc: str = ""             # first line of the module docstring
    gloss: str = ""           # AI-authored one-liner (shown ONLY when the
                              # file has no docstring; flavor, never truth)


@dataclass
class Edge:
    src: str
    dst: str
    kind: str = TOP


@dataclass
class Zone:
    id: str
    name: str
    members: list[str] = field(default_factory=list)
    order: int = 0            # suggested play order, 0-based
    brief: str = ""           # AI-authored district one-liner (flavor)


@dataclass
class Question:
    id: str
    zone: str
    qtype: str                # walk | direction | region | place | cycle | ghost
    verb: str                 # walk | edge | region | place
    prompt: str
    truth: dict = field(default_factory=dict)
    xp: int = 10
    distance: int = 2         # distinct files needed to answer
    boss: bool = False
    followup_of: str | None = None
    lesson: str = ""          # overrides the generic per-qtype lesson line


@dataclass
class World:
    repo: str
    sha: str
    modules: dict[str, Module] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    zones: dict[str, Zone] = field(default_factory=dict)
    questions: dict[str, Question] = field(default_factory=dict)
    cochange: dict[str, list] = field(default_factory=dict)  # name -> [[other, shared], ...]
    events: list = field(default_factory=list)    # focused 2-module commits
    reverts: list = field(default_factory=list)   # reverted changes
    calls: list = field(default_factory=list)     # cross-module CALL edges
    entries: list = field(default_factory=list)   # likely run entry points
    start: str = ""

    def out_edges(self, name: str) -> list[Edge]:
        return [e for e in self.edges if e.src == name]

    def in_edges(self, name: str) -> list[Edge]:
        return [e for e in self.edges if e.dst == name]

    def has_edge(self, src: str, dst: str, kinds: tuple[str, ...] = (TOP, LAZY, TYPE)) -> bool:
        return any(e.src == src and e.dst == dst and e.kind in kinds for e in self.edges)

    def save(self, path: Path) -> None:
        data = {
            "repo": self.repo,
            "sha": self.sha,
            "start": self.start,
            "modules": {k: asdict(v) for k, v in self.modules.items()},
            "edges": [asdict(e) for e in self.edges],
            "zones": {k: asdict(v) for k, v in self.zones.items()},
            "questions": {k: asdict(v) for k, v in self.questions.items()},
            "cochange": self.cochange,
            "events": self.events,
            "reverts": self.reverts,
            "calls": self.calls,
            "entries": self.entries,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1))

    @classmethod
    def load(cls, path: Path) -> "World":
        d = json.loads(path.read_text())
        w = cls(repo=d["repo"], sha=d["sha"], start=d["start"])
        w.modules = {k: Module(**v) for k, v in d["modules"].items()}
        w.edges = [Edge(**e) for e in d["edges"]]
        w.zones = {k: Zone(**v) for k, v in d["zones"].items()}
        w.questions = {k: Question(**v) for k, v in d["questions"].items()}
        w.cochange = d["cochange"]
        w.events = d.get("events", [])
        w.reverts = d.get("reverts", [])
        w.calls = d.get("calls", [])
        w.entries = d.get("entries", [])
        return w


@dataclass
class Session:
    here: str = ""                         # current module
    discovered: list[str] = field(default_factory=list)   # visited modules
    seen: list[str] = field(default_factory=list)         # names visible on map
    xp: int = 0
    max_xp: int = 0                        # XP available so far (for rank)
    abilities: list[str] = field(default_factory=list)    # e.g. ["tunnel-vision"]
    resolved: dict[str, str] = field(default_factory=dict)  # qid -> correct|partial|revealed
    hints: dict[str, int] = field(default_factory=dict)     # qid -> highest hint level used
    tries: dict[str, int] = field(default_factory=dict)     # qid -> extra region attempts used
    followups: dict[str, dict] = field(default_factory=dict)  # dynamically spawned questions
    whispers: list = field(default_factory=list)  # overworld facts already heard
    best_streak: int = 0      # high-water mark, for the Streak Lord badge
    exam: dict = field(default_factory=dict)  # recall-run state + best score
    cleared: list[str] = field(default_factory=list)        # zone ids
    streak: int = 0             # consecutive first-try, hint-free solves
    boss_open: bool = False
    victory: bool = False
    log: list[str] = field(default_factory=list)
    wanted: dict = field(default_factory=dict)   # daily mystery: date/guesses/done/won
    focus: str = ""             # tracked quest id: bare hint/answer target it

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1))

    @classmethod
    def load(cls, path: Path) -> "Session":
        return cls(**json.loads(path.read_text()))
