"""Tier 0/1 analysis: AST import graph + graph metrics + git history.

Everything here is deterministic and cheap (seconds on a 5k-commit repo).
Ground truth for every question comes from this module's output — never
from generated prose.
"""
from __future__ import annotations

import ast
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx

from .model import (
    Edge, Module, World, Zone,
    TOP, LAZY, TYPE,
    ROLE_BOSS, ROLE_BEDROCK, ROLE_GATE, ROLE_SWAMP, ROLE_LEAF, ROLE_NORMAL,
)

SKIP_DIRS = {
    "tests", "test", "docs", "examples", "benchmarks", "tools", "scripts",
    ".git", ".tox", ".venv", "venv", "node_modules", "build", "dist",
    "__pycache__",
}
MEGA_COMMIT = 15          # commits touching more files are formatting sweeps
MIN_ZONE = 3              # smaller Louvain communities merge into the outskirts


def find_py_files(root: Path) -> dict[str, Path]:
    """Map dotted module name (relative to repo root) -> file path."""
    out = {}
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        parts = rel.parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in parts[:-1]):
            continue
        if parts[-1] in ("setup.py", "conftest.py"):
            continue
        dotted = ".".join(parts)[:-3]  # strip .py
        if dotted.endswith(".__init__"):
            dotted = dotted[: -len(".__init__")]
        if not dotted:
            continue
        out[dotted] = p
    return out


class _ImportVisitor(ast.NodeVisitor):
    """Collect imports with laziness classification."""

    def __init__(self, self_dotted: str, is_pkg_init: bool):
        self.self_dotted = self_dotted
        self.is_pkg_init = is_pkg_init
        # each entry: (candidate dotted targets, most-specific first, kind)
        self.found: list[tuple[list[str], str]] = []
        self._depth = 0        # >0 inside function/method
        self._type_block = 0   # >0 inside `if TYPE_CHECKING:`

    def _kind(self) -> str:
        if self._type_block:
            return TYPE
        return LAZY if self._depth else TOP

    def visit_FunctionDef(self, node):
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node):
        # `if __name__ == "__main__":` demo blocks never run on import —
        # their imports are not architecture, skip them entirely
        t = node.test
        if (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name)
                and t.left.id == "__name__"):
            for n in node.orelse:
                self.visit(n)
            return
        is_tc = (
            (isinstance(t, ast.Name) and t.id == "TYPE_CHECKING")
            or (isinstance(t, ast.Attribute) and t.attr == "TYPE_CHECKING")
        )
        if is_tc:
            self._type_block += 1
            for n in node.body:
                self.visit(n)
            self._type_block -= 1
            for n in node.orelse:
                self.visit(n)
        else:
            self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            self.found.append(([alias.name], self._kind()))

    def visit_ImportFrom(self, node):
        base = node.module or ""
        if node.level:  # relative import: resolve against our own package
            pkg_parts = self.self_dotted.split(".")
            # for a module, level 1 == its own package; for a package
            # __init__, level 1 == itself
            up = node.level - (1 if self.is_pkg_init else 0)
            anchor = pkg_parts[: len(pkg_parts) - up] if up else pkg_parts
            base = ".".join(anchor + ([base] if base else []))
        for alias in node.names:
            # `from x import y`: y may be a submodule or a symbol. Prefer the
            # submodule; fall back to the package itself only if y isn't one.
            if base:
                self.found.append(([f"{base}.{alias.name}", base], self._kind()))


def parse_imports(path: Path, self_dotted: str, is_pkg_init: bool) -> list[tuple[str, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    v = _ImportVisitor(self_dotted, is_pkg_init)
    v.visit(tree)
    return v.found


def short_names(dotted: list[str]) -> dict[str, str]:
    """Unique short display names: strip the longest common package prefix.
    A module that IS the stripped prefix (the package __init__) keeps its
    own last segment. Residual collisions are disambiguated with parents."""
    if not dotted:
        return {}
    split = [d.split(".") for d in dotted]
    prefix = 0
    while True:
        deeper = [s for s in split if len(s) > prefix + 1]
        heads = {s[prefix] for s in deeper}
        # strip another level when every name deeper than the prefix agrees
        # on the next segment and shallower names are ancestors of it
        ancestors_ok = bool(deeper) and all(
            len(s) > prefix + 1 or s == deeper[0][: len(s)] for s in split
        )
        if len(heads) == 1 and len(deeper) >= 2 and ancestors_ok:
            prefix += 1
        else:
            break
    names = {}
    for d, s in zip(dotted, split):
        tail = s[prefix:]
        names[d] = ".".join(tail) if tail else s[-1]
    counts = Counter(names.values())
    for d, n in list(names.items()):
        if counts[n] > 1:
            names[d] = ".".join(d.split(".")[-2:])
    return names


def git_history(root: Path, path_to_name: dict[str, str]):
    """churn, authors, co-change from `git log --name-only`."""
    churn: Counter = Counter()
    authors: defaultdict[str, set] = defaultdict(set)
    cochange: Counter = Counter()
    try:
        raw = subprocess.run(
            ["git", "log", "--no-merges", "--name-only", "--pretty=format:__C__%an"],
            cwd=root, capture_output=True, text=True, timeout=300,
        ).stdout
    except Exception:
        return churn, authors, cochange
    author = None
    files: list[str] = []

    def flush():
        mods = sorted({path_to_name[f] for f in files if f in path_to_name})
        for m in mods:
            churn[m] += 1
            authors[m].add(author)
        if 2 <= len(mods) <= MEGA_COMMIT:
            for i, a in enumerate(mods):
                for b in mods[i + 1:]:
                    cochange[(a, b)] += 1

    for line in raw.splitlines():
        if line.startswith("__C__"):
            if author is not None:
                flush()
            author = line[5:]
            files = []
        elif line.strip():
            files.append(line.strip())
    if author is not None:
        flush()
    return churn, authors, cochange


def _norm(d: dict[str, float]) -> dict[str, float]:
    m = max(d.values(), default=0) or 1
    return {k: v / m for k, v in d.items()}


def assign_roles(world: World, G: nx.DiGraph) -> None:
    """One dominant role per module, boss precedence first (god modules
    otherwise saturate every list)."""
    mods = world.modules
    pr = _norm({m: mods[m].pagerank for m in mods})
    btw = _norm({m: mods[m].betweenness for m in mods})
    ch = _norm({m: mods[m].commits for m in mods})
    au = _norm({m: mods[m].authors for m in mods})

    taken: set[str] = set()

    def take_top(score: dict[str, float], n: int, role: str, floor: float = 0.05):
        ranked = sorted(
            (m for m in score if m not in taken and score[m] > floor),
            key=lambda m: -score[m],
        )
        for m in ranked[:n]:
            mods[m].role = role
            taken.add(m)

    take_top({m: ch[m] * (pr[m] + btw[m]) for m in mods}, 1, ROLE_BOSS)
    # bedrock must be genuinely widely imported: deep data-file sinks
    # accumulate pagerank but have in-degree 1 — exclude them
    take_top({m: pr[m] * (1 - ch[m]) for m in mods if mods[m].in_degree >= 3},
             3, ROLE_BEDROCK)
    take_top(btw, 3, ROLE_GATE)
    take_top({m: au[m] * ch[m] for m in mods}, 3, ROLE_SWAMP)
    for m in mods:
        if m in taken:
            continue
        deg = G.in_degree(m) + G.out_degree(m)
        mods[m].role = ROLE_LEAF if deg <= 1 else ROLE_NORMAL


ZONE_SUFFIXES = ["Chamber", "Gallery", "Vault", "Atrium", "Cells", "Annex", "Combs", "Apiary"]


def build_zones(world: World, G: nx.DiGraph) -> None:
    communities = nx.community.louvain_communities(G.to_undirected(), seed=42)
    big = [sorted(c) for c in communities if len(c) >= MIN_ZONE]
    small = [m for c in communities if len(c) < MIN_ZONE for m in c]
    big.sort(key=lambda c: -sum(world.modules[m].pagerank for m in c))
    zones = []
    for i, members in enumerate(big):
        top = max(members, key=lambda m: world.modules[m].pagerank)
        name = f"The {top.split('.')[-1].strip('_').title()} {ZONE_SUFFIXES[i % len(ZONE_SUFFIXES)]}"
        zones.append(Zone(id=f"z{i+1}", name=name, members=members))
    if small:
        zones.append(Zone(id=f"z{len(zones)+1}", name="The Outskirts", members=sorted(small)))
    # play order: bedrock-heaviest zone first, then by how much the REST of
    # the hive imports this zone (external in-edges; a self-contained data
    # blob has none and belongs late, however big it is)
    member_zone = {m: z.id for z in zones for m in z.members}

    def zkey(z: Zone):
        bedrock = sum(1 for m in z.members if world.modules[m].role == ROLE_BEDROCK)
        ext = sum(1 for e in world.edges
                  if member_zone.get(e.dst) == z.id and member_zone.get(e.src) != z.id)
        return -(ext + 15 * bedrock)

    for order, z in enumerate(sorted(zones, key=zkey)):
        z.order = order
    for z in zones:
        world.zones[z.id] = z
        for m in z.members:
            world.modules[m].zone = z.id


def analyze(repo: Path) -> World:
    repo = repo.resolve()
    files = find_py_files(repo)
    if len(files) < 5:
        raise SystemExit(f"only {len(files)} python modules found under {repo} - not enough to play")
    names = short_names(list(files))
    dotted_to_short = names
    # candidate resolution table: every dotted name and its ancestors
    resolve: dict[str, str] = {}
    for d in files:
        resolve[d] = d

    edges: dict[tuple[str, str], str] = {}  # (src, dst) -> kind (TOP wins)
    kind_rank = {TOP: 0, TYPE: 1, LAZY: 2}
    for d, p in files.items():
        is_pkg_init = p.name == "__init__.py"
        for candidates, kind in parse_imports(p, d, is_pkg_init):
            t = next((resolve[c] for c in candidates if c in resolve), None)
            if t is None or t == d:
                continue
            key = (dotted_to_short[d], dotted_to_short[t])
            if key not in edges or kind_rank[kind] < kind_rank[edges[key]]:
                edges[key] = kind

    G = nx.DiGraph()
    G.add_nodes_from(names.values())
    G.add_edges_from((s, t, {"kind": k}) for (s, t), k in edges.items())

    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
        ).stdout.strip() or "unknown"
    except Exception:
        sha = "unknown"

    world = World(repo=str(repo), sha=sha)
    pr = nx.pagerank(G) if G.number_of_edges() else {n: 0.0 for n in G}
    btw = nx.betweenness_centrality(G)

    path_to_name = {str(p.relative_to(repo)): names[d] for d, p in files.items()}
    churn, authors, cochange = git_history(repo, path_to_name)

    for d, p in files.items():
        n = names[d]
        try:
            loc = sum(1 for _ in p.open(encoding="utf-8", errors="replace"))
        except OSError:
            loc = 0
        world.modules[n] = Module(
            name=n, path=str(p.relative_to(repo)), zone="",
            loc=loc, commits=churn.get(n, 0), authors=len(authors.get(n, ())),
            pagerank=round(pr.get(n, 0.0), 6), betweenness=round(btw.get(n, 0.0), 6),
            in_degree=G.in_degree(n), out_degree=G.out_degree(n),
        )
    world.edges = [Edge(s, t, k) for (s, t), k in sorted(edges.items())]

    assign_roles(world, G)
    build_zones(world, G)

    cc: defaultdict[str, list] = defaultdict(list)
    for (a, b), n in cochange.items():
        cc[a].append([b, n])
        cc[b].append([a, n])
    world.cochange = {m: sorted(v, key=lambda x: -x[1])[:10] for m, v in cc.items()}

    # start: most out-degree in the first zone (the file that reads the most
    # of the hive — best vantage point)
    first = min(world.zones.values(), key=lambda z: z.order)
    world.start = max(first.members, key=lambda m: world.modules[m].out_degree)
    return world


def top_graph(world: World) -> nx.DiGraph:
    """Graph of top-level (always-runs) import edges only."""
    G = nx.DiGraph()
    G.add_nodes_from(world.modules)
    G.add_edges_from((e.src, e.dst) for e in world.edges if e.kind == TOP)
    return G


def full_graph(world: World) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_nodes_from(world.modules)
    G.add_edges_from((e.src, e.dst) for e in world.edges)
    return G
