"""The atlas: a self-contained HTML/SVG rendering of the fog-of-war map.

The most-requested feature across every playtest round: the map metaphor,
actually drawn. Districts are boxes, modules are dots, edges are lines -
and the fog is real: undiscovered modules render as anonymous specks,
sealed tunnels as dashed stubs, and the picture fills in as you play.
Deterministic layout, no external assets, works from file://.
"""
from __future__ import annotations

import html
import math
from pathlib import Path

from .model import World, Session, TOP, LAZY, TYPE, ROLE_BOSS, ROLE_BEDROCK, \
    ROLE_GATE, ROLE_SWAMP
from .engine import TUNNEL, coverage, rank

ROLE_COLOR = {ROLE_BOSS: "#d4a017", ROLE_BEDROCK: "#4a90d9",
              ROLE_GATE: "#b0568f", ROLE_SWAMP: "#5f9e6e"}


def _zone_boxes(world: World, width: int = 1500):
    """Grid of district boxes sized to member count; returns
    zone_id -> (x, y, w, h) plus per-module positions."""
    zones = sorted(world.zones.values(), key=lambda z: z.order)
    boxes, positions = {}, {}
    x, y, row_h = 30, 60, 0
    for z in zones:
        n = len(z.members)
        cols = max(2, math.ceil(math.sqrt(n * 1.6)))
        rows = math.ceil(n / cols)
        w = cols * 46 + 40
        h = rows * 42 + 64
        if x + w > width - 20:
            x = 30
            y += row_h + 40
            row_h = 0
        boxes[z.id] = (x, y, w, h)
        row_h = max(row_h, h)
        for i, m in enumerate(sorted(z.members)):
            cx = x + 30 + (i % cols) * 46
            cy = y + 52 + (i // cols) * 42
            positions[m] = (cx, cy)
        x += w + 36
    height = y + row_h + 60
    return boxes, positions, height


def _layers(world: World) -> dict[str, int]:
    """Dependency depth over top-level imports: layer 0 imports nothing
    internal (the foundation); higher layers sit on everything below.
    Cycles collapse to the same layer."""
    deps: dict[str, set] = {m: set() for m in world.modules}
    for e in world.edges:
        if e.kind == TOP:
            deps[e.src].add(e.dst)
    layer: dict[str, int] = {}

    def depth(m, stack):
        if m in layer:
            return layer[m]
        if m in stack:
            return 0  # cycle: flatten
        stack.add(m)
        d = 1 + max((depth(x, stack) for x in deps[m]), default=-1)
        stack.discard(m)
        layer[m] = d
        return d

    for m in world.modules:
        depth(m, set())
    return layer


def _strata_svg(world: World, s: Session) -> str:
    """THE STRATA: the classic layered-architecture diagram, earned - only
    modules you have seen appear; fog stays specks."""
    seen, disc = set(s.seen), set(s.discovered)
    layers = _layers(world)
    by_layer: dict[int, list] = {}
    for m, l in layers.items():
        by_layer.setdefault(l, []).append(m)
    rows = sorted(by_layer.items(), key=lambda kv: -kv[0])  # surface on top
    parts, y = [], 30
    width = 1500
    for l, mods in rows:
        parts.append(f'<rect x="20" y="{y}" width="{width - 40}" height="46" '
                     f'rx="8" class="zone"/>')
        label = ("foundation - imports nothing internal" if l == 0 else
                 f"layer {l}")
        parts.append(f'<text x="32" y="{y + 27}" class="ztitle">{label}</text>')
        x = 260
        for m in sorted(mods, key=lambda m: -world.modules[m].pagerank):
            if x > width - 120:
                break
            mod = world.modules[m]
            if m not in seen:
                parts.append(f'<circle cx="{x}" cy="{y + 23}" r="4" class="fog"/>')
                x += 18
                continue
            color = ROLE_COLOR.get(mod.role, "#8a8a8a")
            fill = color if m in disc else "none"
            parts.append(
                f'<circle class="node" data-m="{html.escape(m)}" cx="{x}" '
                f'cy="{y + 18}" r="6" fill="{fill}" stroke="{color}"/>')
            parts.append(f'<text x="{x}" y="{y + 38}" class="mlabel">'
                         f'{html.escape(m.split(".")[-1][:11])}</text>')
            x += max(26, 9 * min(11, len(m.split(".")[-1])))
        y += 56
    return (f'<h1>THE STRATA - who rests on whom</h1>'
            f'<div class="legend">the classic layers diagram, computed from '
            f'always-run imports: everything in a layer can only lean on '
            f'layers below it. Fog rules apply - keep exploring to fill it '
            f'in.</div>'
            f'<svg viewBox="0 0 1500 {y + 10}" '
            f'xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>')


def _journeys_svg(world: World, s: Session) -> str:
    """Solved journeys render as sequence strips - stations joined by
    arrows labeled with the functions that carry the work. Unsolved ones
    stay a teaser: diagrams are earned, not given."""
    js = [q for q in world.questions.values() if q.qtype == "journey"]
    if not js:
        return ""
    parts, y = [], 26
    for q in sorted(js, key=lambda q: q.id):
        t = q.truth
        if q.id not in s.resolved:
            parts.append(f'<text x="24" y="{y}" class="ztitle">??? an '
                         f'untraced journey ({q.id}) - solve it to draw '
                         f'this diagram</text>')
            y += 34
            continue
        path = t["example"]
        x = 30
        for i, m in enumerate(path):
            w = max(84, 9 * len(m.split(".")[-1]) + 26)
            parts.append(f'<rect x="{x}" y="{y - 16}" width="{w}" '
                         f'height="30" rx="7" class="zone"/>')
            parts.append(f'<text x="{x + w / 2}" y="{y + 4}" class="mlabel" '
                         f'style="font-size:11px">'
                         f'{html.escape(m.split(".")[-1][:14])}</text>')
            if i < len(path) - 1:
                rec = next((c for c in world.calls if c["src"] == m
                            and c["dst"] == path[i + 1]), None)
                fns = "/".join((rec.get("via") or ["?"])[:2]) if rec else "?"
                parts.append(f'<line x1="{x + w}" y1="{y}" x2="{x + w + 44}" '
                             f'y2="{y}" class="top" marker-end="url(#arr)"/>')
                parts.append(f'<text x="{x + w + 22}" y="{y - 8}" '
                             f'class="mlabel" style="font-size:9px">'
                             f'{html.escape(fns[:18])}()</text>')
            x += w + 48
        y += 52
    return (f'<h1>THE JOURNEYS - how a run actually flows</h1>'
            f'<div class="legend">each solved journey becomes a sequence '
            f'diagram: every arrow is a real function call. This is the '
            f'runtime story the import map cannot tell.</div>'
            f'<svg viewBox="0 0 1500 {y}" xmlns="http://www.w3.org/2000/svg">'
            f'<defs><marker id="arr" markerWidth="8" markerHeight="8" '
            f'refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6" '
            f'fill="none" stroke="#6f8f6a"/></marker></defs>'
            f'{"".join(parts)}</svg>')


def render_atlas(world: World, s: Session) -> str:
    boxes, pos, height = _zone_boxes(world)
    d, total = coverage(world, s)
    seen, disc = set(s.seen), set(s.discovered)
    tunnel = TUNNEL in s.abilities
    parts = []

    # edges first (under nodes); fog rule: draw only when the SOURCE is
    # discovered (you have read that file) and the target is at least seen
    for e in world.edges:
        if e.src not in disc:
            continue
        if e.kind == LAZY and not tunnel:
            # a sealed stub: short dashed line toward a mystery
            x1, y1 = pos[e.src]
            parts.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x1 + 14}" y2="{y1 + 14}" '
                f'class="sealed"/>')
            continue
        if e.dst not in seen:
            continue
        x1, y1 = pos[e.src]
        x2, y2 = pos[e.dst]
        cls = {TOP: "top", LAZY: "tunnel", TYPE: "typeonly"}[e.kind]
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="{cls}"/>')

    for z in sorted(world.zones.values(), key=lambda z: z.order):
        x, y, w, h = boxes[z.id]
        # sighting ONE member names the district (panels found '???' over a
        # half-scouted zone read as a bug, not fog)
        known = any(m in seen for m in z.members)
        title = z.name if known else "??? unexplored district"
        zq = [q for q in world.questions.values() if q.zone == z.id and not q.boss]
        done = sum(1 for q in zq if q.id in s.resolved)
        badge = " ✦ CLEARED" if z.id in s.cleared else (
            f"  {done}/{len(zq)} quests" if zq else "")
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" '
            f'class="zone{" cleared" if z.id in s.cleared else ""}"/>')
        parts.append(
            f'<text x="{x + 12}" y="{y + 24}" class="ztitle">'
            f'{html.escape(title)}{html.escape(badge)}</text>')
        for m in z.members:
            cx, cy = pos[m]
            mod = world.modules[m]
            color = ROLE_COLOR.get(mod.role, "#8a8a8a")
            if m not in seen:
                parts.append(f'<circle cx="{cx}" cy="{cy}" r="4" class="fog"/>')
                continue
            fill = color if m in disc else "none"
            here = ' stroke-width="3.5"' if m == s.here else ""
            parts.append(
                f'<circle class="node" data-m="{html.escape(m)}" '
                f'cx="{cx}" cy="{cy}" r="{9 if mod.role == ROLE_BOSS else 7}" '
                f'fill="{fill}" stroke="{color}"{here}>'
                f'<title>{html.escape(m)} ({mod.role}, {mod.commits} commits)</title></circle>')
            label = m.split(".")[-1][:12]
            parts.append(
                f'<text x="{cx}" y="{cy + 20}" class="mlabel">'
                f'{html.escape(label)}</text>')
            if m == s.here:
                parts.append(f'<text x="{cx}" y="{cy - 13}" class="you">YOU</text>')

    # per-node dossier for the click panel - fog-respecting: discovered
    # modules carry full detail, merely-seen ones only their name and zone
    import json as _json
    info = {}
    for m in seen:
        if m not in world.modules:
            continue
        mod = world.modules[m]
        zname = world.zones[mod.zone].name
        if m in disc:
            outs = [f"{e.dst} [{e.kind}]" for e in world.out_edges(m)
                    if e.kind != LAZY or tunnel]
            sealed_n = sum(1 for e in world.out_edges(m)
                           if e.kind == LAZY and not tunnel)
            if sealed_n:
                outs.append(f"+{sealed_n} sealed tunnel(s)")
            info[m] = {"t": f"{m} — {mod.role}, {zname}",
                       "d": mod.doc or (f"~ {mod.gloss} (AI impression)"
                                        if mod.gloss else mod.path),
                       "s": (f"{mod.loc} lines · {mod.commits} commits · "
                             f"{mod.authors} authors"
                             + (f" · born {mod.born}" if mod.born else "")),
                       "i": "imports: " + (", ".join(outs) or "nothing internal")}
        else:
            # a sighted-but-unread module still has public facts: its role
            # and churn are on the map and in every edges/status readout -
            # only its file contents (docstring, imports) stay behind a read
            info[m] = {"t": f"{m} — {mod.role or 'worker'}, seen, not yet read",
                       "d": zname,
                       "s": (f"{mod.commits} commits · {mod.authors} authors"
                             + (f" · born {mod.born}" if mod.born else "")),
                       "i": "spyglass it (buzz look) or fly there (buzz go) "
                            "to read its imports"}
    info_json = _json.dumps(info)
    name = world.repo.rsplit("/", 1)[-1]
    header = (f"THE HIVE · {html.escape(name)} · quests "
              f"{len(s.resolved)}/{len(world.questions)} · modules visited "
              f"{d}/{total} · XP {s.xp} · rank {html.escape(rank(world, s))}")
    return f"""<meta charset="utf-8">
<title>buzz atlas — {html.escape(name)}</title>
<style>
  body {{ background:#151310; color:#e8e0d0; font:14px/1.4 ui-monospace,monospace;
         margin:0; padding:16px; }}
  h1 {{ font-size:15px; letter-spacing:.06em; color:#e9c46a; }}
  svg {{ width:100%; height:auto; }}
  .zone {{ fill:#1f1b16; stroke:#4d4436; stroke-width:1.4; }}
  .zone.cleared {{ stroke:#e9c46a; }}
  .ztitle {{ fill:#cdbfa3; font-size:13px; font-weight:bold; }}
  .mlabel {{ fill:#9a8f7a; font-size:9px; text-anchor:middle; }}
  .you {{ fill:#e9c46a; font-size:9px; font-weight:bold; text-anchor:middle; }}
  .fog {{ fill:#33302a; }}
  line.top {{ stroke:#6f8f6a; stroke-width:1.1; opacity:.6; }}
  line.tunnel {{ stroke:#c77b3f; stroke-width:1.1; stroke-dasharray:5 3; opacity:.8; }}
  line.typeonly {{ stroke:#666; stroke-width:1; stroke-dasharray:1 3; opacity:.5; }}
  line.sealed {{ stroke:#8a3b2f; stroke-width:2; stroke-dasharray:3 3; }}
  .legend {{ color:#9a8f7a; font-size:12px; margin-top:10px; }}
</style>
<h1>{header}</h1>
<svg viewBox="0 0 1500 {height}" xmlns="http://www.w3.org/2000/svg">
{chr(10).join(parts)}
</svg>
<div class="legend">
filled dot = visited · hollow dot = seen · speck = fog · gold ring = boss ·
blue = bedrock · purple = gate · green = swamp ·
solid line = top-level import · orange dash = tunnel (unlocked) ·
red stub = sealed tunnel · faint dots = types-only ·
edges appear once you have read the importing file
</div>
<div class="legend">click any visible node for its dossier · regenerate after
moving: <b>buzz atlas</b></div>
{_journeys_svg(world, s)}
{_strata_svg(world, s)}
<div id="panel" style="display:none"></div>
<style>
  #panel {{ position:fixed; right:16px; top:16px; max-width:340px;
    background:#241f18; border:1px solid #e9c46a; border-radius:10px;
    padding:12px 14px; font-size:12.5px; box-shadow:0 6px 24px #000a; }}
  #panel .t {{ color:#e9c46a; font-weight:bold; margin-bottom:6px; }}
  #panel .d {{ color:#cdbfa3; font-style:italic; margin-bottom:6px; }}
  #panel .s, #panel .i {{ color:#9a8f7a; margin-bottom:4px; }}
  .node {{ cursor:pointer; }}
</style>
<script>
var INFO = {info_json};
var panel = document.getElementById('panel');
document.querySelectorAll('.node').forEach(function(n) {{
  n.addEventListener('click', function(ev) {{
    var d = INFO[n.getAttribute('data-m')];
    if (!d) return;
    panel.innerHTML = '<div class="t"></div><div class="d"></div>'
      + '<div class="s"></div><div class="i"></div>';
    panel.querySelector('.t').textContent = d.t;
    panel.querySelector('.d').textContent = d.d;
    panel.querySelector('.s').textContent = d.s;
    panel.querySelector('.i').textContent = d.i;
    panel.style.display = 'block';
    ev.stopPropagation();
  }});
}});
document.body.addEventListener('click', function() {{
  panel.style.display = 'none';
}});
</script>
"""


def write_atlas(world: World, s: Session, out: Path) -> Path:
    out.write_text(render_atlas(world, s))
    return out
