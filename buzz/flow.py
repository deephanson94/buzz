"""The flow tier's ground truth: a conservative cross-module CALL graph.

Imports say what a module COULD reach; calls say where the work actually
goes when the program runs. Python is dynamic, so only high-confidence
edges are kept - a wrong edge would poison quest ground truth:

  - ``from mod import f`` ... later ``f(...)``       -> self calls mod.f
  - ``import mod [as m]`` ... later ``m.f(...)``     -> self calls mod.f
  - ``import pkg.sub`` ... later ``pkg.sub.f(...)``  -> self calls pkg.sub.f

Method calls on objects, callbacks, and dynamic dispatch are deliberately
ignored. Calls inside ``if __name__ == "__main__":`` blocks COUNT here
(unlike import edges): they are exactly how a run begins.
"""
from __future__ import annotations

import ast
from pathlib import Path

ENTRY_NAMES = ("cli", "main", "__main__", "app", "run")


class _CallVisitor(ast.NodeVisitor):
    def __init__(self, self_dotted: str, is_pkg_init: bool):
        self.self_dotted = self_dotted
        self.is_pkg_init = is_pkg_init
        self.symbols: dict[str, list[str]] = {}   # local name -> candidates
        self.aliases: dict[str, list[str]] = {}   # module alias -> candidates
        self.calls: list[tuple[list[str], str]] = []  # (candidates, symbol)
        self.has_main_guard = False

    # -- imports build the resolution tables ------------------------------
    def visit_Import(self, node):
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            # `import a.b` binds `a`; `import a.b as m` binds the whole path
            self.aliases[local] = ([alias.name] if alias.asname
                                   else [alias.name.split(".")[0]])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        base = node.module or ""
        if node.level:  # relative: resolve against our own package
            pkg_parts = self.self_dotted.split(".")
            up = node.level - (1 if self.is_pkg_init else 0)
            anchor = pkg_parts[: len(pkg_parts) - up] if up else pkg_parts
            base = ".".join(anchor + ([base] if base else []))
        if not base:
            return
        for alias in node.names:
            local = alias.asname or alias.name
            # y may be a submodule (calls look like y.f()) or a symbol
            # (calls look like y()) - record both interpretations
            self.symbols[local] = [f"{base}.{alias.name}", base]
            self.aliases.setdefault(local, [f"{base}.{alias.name}"])
        self.generic_visit(node)

    def visit_If(self, node):
        if any(isinstance(n, ast.Name) and n.id == "__name__"
               for n in ast.walk(node.test)):
            self.has_main_guard = True
        self.generic_visit(node)  # __main__ calls count: a run starts there

    # -- calls resolve against the tables ---------------------------------
    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Name) and f.id in self.symbols:
            self.calls.append((self.symbols[f.id], f.id))
        elif isinstance(f, ast.Attribute):
            chain = []
            cur = f
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and cur.id in self.aliases:
                chain.reverse()          # [attr1, ..., symbol]
                bases = self.aliases[cur.id]
                mid, symbol = chain[:-1], chain[-1]
                cands = ([b + "." + ".".join(mid) for b in bases]
                         if mid else []) + list(bases)
                self.calls.append((cands, symbol))
        self.generic_visit(node)


def extract_calls(files: dict[str, Path], resolve: dict[str, str],
                  names: dict[str, str]):
    """Returns (calls, entries): calls as a list of
    {"src", "dst", "via": [symbols]} in SHORT names, cross-module only;
    entries as the short names of likely run entry points."""
    edges: dict[tuple[str, str], set] = {}
    entries: list[str] = []
    for d, p in files.items():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        v = _CallVisitor(d, p.name == "__init__.py")
        v.visit(tree)
        short = names[d]
        if v.has_main_guard or short.split(".")[-1] in ENTRY_NAMES:
            entries.append(short)
        for cands, symbol in v.calls:
            t = next((resolve[c] for c in cands if c in resolve), None)
            if t is None or t == d:
                continue
            edges.setdefault((short, names[t]), set()).add(symbol)
    calls = [{"src": s, "dst": t, "via": sorted(syms)[:4]}
             for (s, t), syms in sorted(edges.items())]
    return calls, sorted(set(entries))
