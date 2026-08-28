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
from . import render

def _disp_names(world: World) -> dict:
    """Short display names, with the parent segment restored whenever a
    bare tail collides ('backend' three ways) - shared by every diagram
    so the town and the strata stop disagreeing. Truncation is honest:
    a cut name carries an ellipsis."""
    from collections import Counter
    tails = Counter(m.split(".")[-1] for m in world.modules)
    out = {}
    for m in world.modules:
        tail = m.split(".")[-1]
        if tails[tail] > 1 and "." in m:
            tail = ".".join(m.split(".")[-2:])
        out[m] = tail if len(tail) <= 16 else tail[:15] + "…"
    return out


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
        # a staff audit caught the original leaking the complete depth
        # histogram at turn 0 via fog specks: only SEEN modules may
        # exist on this page, and a layer nobody has seen is not drawn
        vis = [m for m in mods if m in seen]
        if not vis:
            continue
        parts.append(f'<rect x="20" y="{y}" width="{width - 40}" height="46" '
                     f'rx="8" class="zone"/>')
        label = ("foundation - imports nothing internal" if l == 0 else
                 f"layer {l}")
        parts.append(f'<text x="32" y="{y + 27}" class="ztitle">{label}</text>')
        names = _disp_names(world)
        x = 330
        for m in sorted(vis, key=lambda m: -world.modules[m].pagerank):
            if x > width - 140:
                break
            mod = world.modules[m]
            color = ROLE_COLOR.get(mod.role, "#8a8a8a")
            fill = color if m in disc else "none"
            parts.append(
                f'<circle class="node" data-m="{html.escape(m)}" cx="{x}" '
                f'cy="{y + 18}" r="6" fill="{fill}" stroke="{color}"/>')
            parts.append(f'<text x="{x}" y="{y + 38}" class="mlabel">'
                         f'{html.escape(names[m])}</text>')
            x += max(34, 8 * min(16, len(names[m])) + 14)
        y += 56
    return (f'<h1>THE STRATA - who rests on whom</h1>'
            f'<div class="legend">the classic layers diagram, computed from '
            f'always-run imports: everything in a layer can only lean on '
            f'layers below it. Only what you have SEEN appears - the fog '
            f'may hold layers this page does not admit to.</div>'
            f'<svg viewBox="0 0 1500 {y + 10}" '
            f'xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>')


def _journeys_svg(world: World, s: Session) -> str:
    """Solved journeys render as sequence strips - stations joined by
    arrows labeled with the functions that carry the work. Unsolved ones
    stay a teaser: diagrams are earned, not given."""
    js = [q for q in world.questions.values() if q.qtype == "journey"]
    if not js:
        return ""
    parts, y = [], 44
    # solved strips first: an untraced placeholder sitting directly
    # above another journey's drawn diagram read as its answer
    for q in sorted(js, key=lambda q: (q.id not in s.resolved, q.id)):
        t = q.truth
        if q.id not in s.resolved:
            parts.append(f'<text x="24" y="{y}" class="ztitle">??? an '
                         f'untraced journey ({q.id}) - solve it to draw '
                         f'this diagram</text>')
            y += 34
            continue
        path = t["example"]
        x = 30
        stations = []
        for i, m in enumerate(path):
            w = max(84, 9 * len(m.split(".")[-1]) + 26)
            stations.append((x + w / 2, y - 1))
            parts.append(f'<rect x="{x}" y="{y - 16}" width="{w}" '
                         f'height="30" rx="7" class="zone"/>')
            parts.append(f'<text x="{x + w / 2}" y="{y + 4}" class="mlabel" '
                         f'style="font-size:11px">'
                         f'{html.escape(m.split(".")[-1][:14])}</text>')
            if i < len(path) - 1:
                rec = next((c for c in world.calls if c["src"] == m
                            and c["dst"] == path[i + 1]), None)
                via = (rec.get("via") or ["?"]) if rec else ["?"]
                # ONE whole symbol - truncating an identifier and
                # appending '()' fabricates a function that does not
                # exist (round WEBATLAS: 'generate_task_()')
                fn = via[0]
                label = (fn if len(fn) <= 18 else fn[:17] + "…") + "()"
                if len(via) > 1:
                    label += " +" + str(len(via) - 1)
                parts.append(f'<line x1="{x + w}" y1="{y}" x2="{x + w + 58}" '
                             f'y2="{y}" class="top" marker-end="url(#arr)"/>')
                parts.append(f'<text x="{x + w + 29}" y="{y - 22}" '
                             f'class="mlabel" style="font-size:9px" '
                             f'text-anchor="middle">'
                             f'{html.escape(label)}</text>')
            x += w + 62
        coords = ";".join(f"{cx:.0f},{cy:.0f}" for cx, cy in stations)
        parts.append(f'<text x="{x + 6}" y="{y + 4}" class="play" '
                     f'data-stations="{coords}" style="cursor:pointer">'
                     f'&#9654; play</text>')
        y += 52
    return (f'<h1>THE JOURNEYS - how a run actually flows</h1>'
            f'<div class="legend">each solved journey becomes a sequence '
            f'diagram: every arrow is a real function call. Shown is ONE '
            f'verified route per journey - the chain you answered with '
            f'may be another equally real one. This is the runtime story '
            f'the import map cannot tell.</div>'
            f'<svg viewBox="0 0 1500 {y}" xmlns="http://www.w3.org/2000/svg">'
            f'<defs><marker id="arr" markerWidth="8" markerHeight="8" '
            f'refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6" '
            f'fill="none" stroke="#6f8f6a"/></marker></defs>'
            f'{"".join(parts)}</svg>')



_ATLAS_JS = """
var town = document.getElementById('town');
var vb0 = town.getAttribute('viewBox').split(' ').map(Number);
var vb = vb0.slice();
function setVB() { town.setAttribute('viewBox', vb.join(' ')); }
var msg = document.getElementById('probemsg');
var HINT = msg.textContent;

// --- pan (drag) + zoom (wheel, about the cursor)
var drag = null, dragged = false;
town.addEventListener('mousedown', function (e) {
  drag = {x: e.clientX, y: e.clientY, vb: vb.slice()};
  dragged = false;
});
window.addEventListener('mousemove', function (e) {
  if (!drag) return;
  if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 3)
    dragged = true;
  var k = vb[2] / town.clientWidth;
  vb[0] = drag.vb[0] - (e.clientX - drag.x) * k;
  vb[1] = drag.vb[1] - (e.clientY - drag.y) * k;
  setVB();
});
window.addEventListener('mouseup', function () { drag = null; });
town.addEventListener('wheel', function (e) {
  e.preventDefault();
  var k = e.deltaY > 0 ? 1.25 : 0.8;
  var r = town.getBoundingClientRect();
  var mx = vb[0] + (e.clientX - r.left) / r.width * vb[2];
  var my = vb[1] + (e.clientY - r.top) / r.height * vb[3];
  var w = Math.min(vb0[2] * 4, Math.max(vb0[2] / 12, vb[2] * k));
  var h = w * vb[3] / vb[2];
  vb = [mx - (mx - vb[0]) * w / vb[2], my - (my - vb[1]) * h / vb[3], w, h];
  setVB();
}, {passive: false});
document.getElementById('reset').addEventListener('click', function () {
  vb = vb0.slice(); setVB(); clearRoute(); clearHit();
  probing = false; probeBtn.classList.remove('on');
  document.getElementById('q').value = '';
  msg.textContent = HINT;
});

// --- search: seen modules only (NODES is fog-filtered at generation)
var hit = null;
function clearHit() { if (hit) { hit.remove(); hit = null; } }
function centerOn(m) {
  var p = NODES[m]; if (!p) return;
  var w = Math.max(vb0[2] / 3, 420), h = w * vb0[3] / vb0[2];
  vb = [p[0] - w / 2, p[1] - h / 2, w, h]; setVB();
  clearHit();
  hit = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  hit.setAttribute('cx', p[0]); hit.setAttribute('cy', p[1]);
  hit.setAttribute('r', 16); hit.setAttribute('class', 'hit');
  town.appendChild(hit);
}
document.getElementById('q').addEventListener('keydown', function (e) {
  if (e.key !== 'Enter') return;
  var q = this.value.trim().toLowerCase(); if (!q) return;
  var names = Object.keys(NODES);
  var exact = names.filter(function (n) {
    return n.toLowerCase() === q || n.toLowerCase().endsWith('.' + q)
        || n.split('.').pop().toLowerCase() === q; });
  var subs = names.filter(function (n) {
    return n.toLowerCase().includes(q); });
  var cands = exact.length ? exact : subs;
  if (!cands.length) {
    msg.textContent = 'no seen module matches "' + q +
      '" - the fog may still hold it';
    return;
  }
  centerOn(cands[0]);
  msg.textContent = (cands.length === 1 ? 'found: ' + cands[0]
    : cands.length + ' match: ' + cands.slice(0, 3).join(', ')
      + (cands.length > 3 ? ', ...' : '') + ' (showing the first)');
});

// --- route probe: BFS over the EARNED edge list only, KINDS kept -
// a TYPE_CHECKING or tunnel hop must never pass as an always-run one
// (five quests teach exactly that distinction)
var adj = {};
EDGES.forEach(function (e) {
  (adj[e[0]] = adj[e[0]] || []).push({to: e[1], kind: e[2]});
});
function bfs(a, b) {
  var prev = {}, seenQ = {}, q = [a]; seenQ[a] = true;
  while (q.length) {
    var u = q.shift();
    if (u === b) {
      var path = [{m: b}];
      while (path[0].m !== a) {
        var pr = prev[path[0].m];
        path[0].kind = pr.kind;
        path.unshift({m: pr.m});
      }
      return path;
    }
    (adj[u] || []).forEach(function (e) {
      if (!seenQ[e.to]) { seenQ[e.to] = true;
        prev[e.to] = {m: u, kind: e.kind}; q.push(e.to); }
    });
  }
  return null;
}
var probing = false, probeA = null;
var probeBtn = document.getElementById('probe');
var routeG = document.getElementById('route');
function clearRoute() {
  while (routeG.firstChild) routeG.removeChild(routeG.firstChild);
  probeA = null;
}
probeBtn.addEventListener('click', function () {
  probing = !probing; clearRoute();
  probeBtn.classList.toggle('on', probing);
  msg.textContent = probing
    ? 'probe armed: click the FIRST module, then the second'
    : HINT;
});
var KIND_MARK = {top: '->', lazy: '-[tunnel]->', type: '-[types-only]->'};
function drawRoute(path) {
  clearRoute();
  var NS = 'http://www.w3.org/2000/svg';
  for (var i = 1; i < path.length; i++) {
    var a = NODES[path[i - 1].m], b = NODES[path[i].m];
    var ln = document.createElementNS(NS, 'line');
    ln.setAttribute('x1', a[0]); ln.setAttribute('y1', a[1]);
    ln.setAttribute('x2', b[0]); ln.setAttribute('y2', b[1]);
    ln.setAttribute('class', 'rseg ' + (path[i].kind || 'top'));
    ln.setAttribute('marker-end', 'url(#rarr)');
    routeG.appendChild(ln);
  }
  path.forEach(function (st) {
    var c = document.createElementNS(NS, 'circle');
    var pnt = NODES[st.m];
    c.setAttribute('cx', pnt[0]); c.setAttribute('cy', pnt[1]);
    c.setAttribute('r', 11); c.setAttribute('class', 'rstop');
    routeG.appendChild(c);
  });
}
function probeClick(m) {
  if (!probeA) { probeA = m;
    msg.textContent = 'from ' + m + ' - now click the destination'; return; }
  if (probeA === m) {
    msg.textContent = m + ' is both ends - click a DIFFERENT second module '
      + '(still from ' + m + ')';
    return;
  }
  var a = probeA, b = m; probeA = null;
  var path = bfs(a, b), flipped = false;
  if (!path) { path = bfs(b, a); flipped = true; }
  if (!path) {
    msg.textContent = 'no earned route between ' + a + ' and ' + b +
      ' - read more files (edges appear when their importer is read)';
    return;
  }
  drawRoute(path);
  var chain = path[0].m;
  for (var i = 1; i < path.length; i++)
    chain += ' ' + (KIND_MARK[path[i].kind] || '->') + ' ' + path[i].m;
  var names = path.map(function (st) { return st.m; });
  var warn = path.some(function (st) { return st.kind === 'type'; })
    ? '  CAUTION: a types-only hop never runs - this is NOT a blast-radius chain.'
    : '';
  msg.textContent = (flipped
    ? ('no earned route ' + a + ' -> ' + b + '; the REVERSE exists: ')
    : '') + chain + '  (verify: buzz trace ' + names.join(' ') +
    ')' + warn + '  [probe still armed - PROBE ROUTE disarms]';
}

// --- dossier panel (click), shared with the probe's node clicks
var panel = document.getElementById('panel');
document.querySelectorAll('.node').forEach(function (n) {
  n.addEventListener('click', function (ev) {
    ev.stopPropagation();
    var m = n.getAttribute('data-m');
    if (probing) { probeClick(m); return; }
    var d = INFO[m]; if (!d) return;
    panel.innerHTML = '<div class="t"></div><div class="d"></div>'
      + '<div class="s"></div><div class="i"></div>';
    panel.querySelector('.t').textContent = d.t;
    panel.querySelector('.d').textContent = d.d;
    panel.querySelector('.s').textContent = d.s;
    panel.querySelector('.i').textContent = d.i;
    panel.style.display = 'block';
  });
});
document.body.addEventListener('click', function () {
  if (dragged) { dragged = false; return; }  // a pan is not a dismiss
  panel.style.display = 'none';
});
window.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') panel.style.display = 'none';
});

// --- journey playback: each strip rides its own dot
document.querySelectorAll('.play').forEach(function (btn, bi) {
  btn.addEventListener('click', function (ev) {
    ev.stopPropagation();
    var pts = btn.getAttribute('data-stations').split(';').map(function (s) {
      return s.split(',').map(Number); });
    var svg = btn.ownerSVGElement;
    var old = svg.querySelector('.jdot[data-j="' + bi + '"]');
    if (old) old.remove();
    var dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    dot.setAttribute('class', 'jdot'); dot.setAttribute('data-j', bi);
    dot.setAttribute('r', 6);
    svg.appendChild(dot);
    var seg = 0, t0 = null, SEG_MS = 600;
    function step(ts) {
      if (!dot.isConnected) return;
      if (t0 === null) t0 = ts;
      var f = Math.min(1, (ts - t0) / SEG_MS);
      var a = pts[seg], b = pts[seg + 1];
      dot.setAttribute('cx', a[0] + (b[0] - a[0]) * f);
      dot.setAttribute('cy', a[1] + (b[1] - a[1]) * f);
      if (f >= 1) { seg += 1; t0 = null; }
      if (seg < pts.length - 1) requestAnimationFrame(step);
      else setTimeout(function () { dot.remove(); }, 700);
    }
    if (pts.length > 1) requestAnimationFrame(step);
  });
});
"""


def render_atlas(world: World, s: Session) -> str:
    boxes, pos, height = _zone_boxes(world)
    d, total = coverage(world, s)
    seen, disc = set(s.seen), set(s.discovered)
    tunnel = TUNNEL in s.abilities

    # an OPEN place quest means this module's district is the answer -
    # so nothing on the page may place it: not its node, not an edge
    # endpoint, not its dossier (the staff audit answered q13 straight
    # off the page). Masked modules live in a limbo strip; overwriting
    # pos here moves EVERY consumer - edges, nodes, search, probe.
    masked = render.masked_modules(world, s) & seen
    limbo_y = height - 4
    limbo_pos = {}
    for i, m in enumerate(sorted(masked)):
        limbo_pos[m] = (140 + i * 150, limbo_y + 36)
        pos[m] = (limbo_pos[m][0], limbo_pos[m][1] + 6)
    if masked:
        height += 70
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

    marks = set()
    for q in world.questions.values():
        if q.id in s.resolved:
            continue
        tq = q.truth
        primary = (tq.get("src") or tq.get("target") or tq.get("anchor")
                   or tq.get("a"))
        if primary in seen:
            marks.add(primary)

    names = _disp_names(world)

    def disp(m):
        return names[m]

    # rects first, then titles and nodes - a later district's rect must
    # never paint over an earlier one's title (staff audit)
    base_parts = parts
    overlay = []
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        x, y, w, h = boxes[z.id]
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" '
            f'class="zone{" cleared" if z.id in s.cleared else ""}"/>')
    for z in sorted(world.zones.values(), key=lambda z: z.order):
        x, y, w, h = boxes[z.id]
        parts = overlay
        # the district is NAMED by the same rule the CLI map uses: a
        # member must be READ (the atlas naming zones the shell still
        # called '???' was a groundedness break, not a convenience)
        known = any(m in disc for m in z.members)
        title = z.name if known else "??? unexplored district"
        zq = [q for q in world.questions.values() if q.zone == z.id and not q.boss]
        nboss = sum(1 for q in world.questions.values()
                    if q.zone == z.id and q.boss)
        done = sum(1 for q in zq if q.id in s.resolved)
        badge = " ✦ CLEARED" if z.id in s.cleared else (
            f"  {done}/{len(zq)} quests" if zq else "")
        if nboss and z.id not in s.cleared:
            badge += f" +{nboss} boss"
        # truncation eats the NAME, never the payload - a cut quest
        # count is disinformation, a cut name is just short
        max_chars = max(8, (w - 20) // 8)
        if len(title) + len(badge) > max_chars:
            keep = max(4, max_chars - len(badge) - 1)
            title = title[:keep] + "…"
        full = f"{title}{badge}"
        parts.append(
            f'<text x="{x + 12}" y="{y + 24}" class="ztitle">'
            f'{html.escape(full)}</text>')
        for mi, m in enumerate(mm for mm in z.members if mm not in masked):
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
                f'<title>{html.escape(m)} ({mod.role}, {mod.commits} '
                f'commit{"s" if mod.commits != 1 else ""})</title></circle>')
            dy = 20 if mi % 2 == 0 else 31
            parts.append(
                f'<text x="{cx}" y="{cy + dy}" class="mlabel">'
                f'{html.escape(disp(m))}</text>')
            if m == s.here:
                parts.append(f'<text x="{cx - 18}" y="{cy + 3}" '
                             f'class="you" style="text-anchor:end">'
                             f'YOU</text>')
            if m in marks:
                parts.append(f'<circle cx="{cx}" cy="{cy}" r="13" '
                             f'class="mark"/>')
                parts.append(f'<text x="{cx + 15}" y="{cy + 4}" '
                             f'class="bang">!</text>')
    if masked:
        overlay.append(
            f'<rect x="20" y="{limbo_y + 8}" width="{max(300, 140 * len(masked) + 120)}" '
            f'height="56" rx="10" class="zone" stroke-dasharray="6 4"/>')
        overlay.append(
            f'<text x="32" y="{limbo_y + 28}" class="ztitle">unplaced '
            f'sightings - district unknown until a scout places them</text>')
        for m in sorted(masked):
            cx, cy = pos[m]
            mod = world.modules[m]
            color = ROLE_COLOR.get(mod.role, "#8a8a8a")
            fill = color if m in disc else "none"
            overlay.append(
                f'<circle class="node" data-m="{html.escape(m)}" cx="{cx}" '
                f'cy="{cy}" r="7" fill="{fill}" stroke="{color}">'
                f'<title>{html.escape(m)} - unplaced</title></circle>')
            overlay.append(f'<text x="{cx}" y="{cy + 20}" class="mlabel">'
                           f'{html.escape(disp(m))}</text>')
            if m in marks:
                overlay.append(f'<circle cx="{cx}" cy="{cy}" r="13" '
                               f'class="mark"/>')
    parts = base_parts + overlay  # edges+rects below, titles+nodes above

    # per-node dossier for the click panel - fog-respecting: discovered
    # modules carry full detail, merely-seen ones only their name and zone
    import json as _json
    info = {}
    for m in seen:
        if m not in world.modules:
            continue
        mod = world.modules[m]
        zone_known = any(x in disc for x in world.zones[mod.zone].members)
        zname = (world.zones[mod.zone].name if zone_known
                 else "an unnamed district")
        if m in masked:
            zname = "??? - a scout must place this module"
        

        def n_(n, word):
            return f"{n} {word}{'s' if n != 1 else ''}"

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
                       "s": (f"{n_(mod.loc, 'line')} · "
                             f"{n_(mod.commits, 'commit')} · "
                             f"{n_(mod.authors, 'author')}"
                             + (f" · born {mod.born}" if mod.born else "")),
                       "i": "imports: " + (", ".join(outs) or "nothing internal")}
        else:
            # a sighted-but-unread module still has public facts: its role
            # and churn are on the map and in every edges/status readout -
            # only its file contents (docstring, imports) stay behind a read
            info[m] = {"t": f"{m} — {mod.role or 'worker'}, seen, not yet read",
                       "d": zname,
                       "s": (f"{n_(mod.commits, 'commit')} · "
                             f"{n_(mod.authors, 'author')}"
                             + (f" · born {mod.born}" if mod.born else "")),
                       "i": "spyglass it (buzz look) or fly there (buzz go) "
                            "to read its imports"}
    info_json = _json.dumps(info)
    # graph data for the interactive layer - fog-safe BY CONSTRUCTION:
    # only nodes the session has seen, only edges already drawn above
    nodes_json = _json.dumps({m: [round(pos[m][0]), round(pos[m][1])]
                              for m in seen if m in pos})
    edges_json = _json.dumps(
        [[e.src, e.dst, e.kind] for e in world.edges
         if e.src in disc and e.dst in seen
         and (e.kind != LAZY or tunnel)])
    content_w = max(x + w for x, y, w, h in boxes.values()) + 24
    name = world.repo.rsplit("/", 1)[-1]
    header = (f"THE HIVE · {html.escape(name)} · quests "
              f"{len(s.resolved)}/{len(world.questions)} · modules visited "
              f"{d}/{total} · XP {s.xp} · rank {html.escape(rank(world, s))}")
    js = (
        "var INFO=" + info_json + ";var NODES=" + nodes_json
        + ";var EDGES=" + edges_json + ";" + _ATLAS_JS)
    return f"""<meta charset="utf-8">
<title>buzz atlas — {html.escape(name)}</title>
<style>
  body {{ background:#151310; color:#e8e0d0; font:14px/1.4 ui-monospace,monospace;
         margin:0; padding:16px; }}
  h1 {{ font-size:15px; letter-spacing:.06em; color:#e9c46a; }}
  svg {{ width:100%; height:auto; }}
  #town {{ height:auto; aspect-ratio:{content_w}/{height}; max-height:78vh;
           cursor:grab; background:#171411; border:1px solid #33302a;
           border-radius:10px; }}
  #town:active {{ cursor:grabbing; }}
  #bar {{ display:flex; gap:8px; align-items:center; margin:8px 0; flex-wrap:wrap; }}
  #bar input {{ background:#241f18; color:#e8e0d0; border:1px solid #4d4436;
    border-radius:6px; padding:6px 10px; font:13px ui-monospace,monospace; width:220px; }}
  #bar button {{ background:#241f18; color:#cdbfa3; border:1px solid #4d4436;
    border-radius:6px; padding:6px 12px; font:13px ui-monospace,monospace; cursor:pointer; }}
  #bar button.on {{ border-color:#e9c46a; color:#e9c46a; }}
  #probemsg {{ color:#9a8f7a; font-size:12px; }}
  .zone {{ fill:#1f1b16; stroke:#4d4436; stroke-width:1.4; }}
  .zone.cleared {{ stroke:#e9c46a; }}
  .ztitle {{ fill:#cdbfa3; font-size:13px; font-weight:bold; }}
  .mlabel {{ fill:#9a8f7a; font-size:9px; text-anchor:middle;
    paint-order:stroke; stroke:#171411; stroke-width:3px; }}
  .you {{ fill:#e9c46a; font-size:9px; font-weight:bold;
    paint-order:stroke; stroke:#171411; stroke-width:3px; }}
  .ztitle {{ paint-order:stroke; stroke:#171411; stroke-width:4px; }}
  .fog {{ fill:#33302a; }}
  .mark {{ fill:none; stroke:#e76f51; stroke-width:1.6; }}
  .bang {{ fill:#e76f51; font-size:13px; font-weight:bold; }}
  .play {{ fill:#e9c46a; font-size:11px; }}
  .hit {{ fill:none; stroke:#e9c46a; stroke-width:2.5; }}
  #route {{ pointer-events:none; }}
  .rseg {{ stroke:#e9c46a; stroke-width:2.5; }}
  .rseg.lazy {{ stroke:#c77b3f; stroke-dasharray:6 4; }}
  .rseg.type {{ stroke:#8a8a8a; stroke-dasharray:2 4; }}
  .rstop {{ fill:none; stroke:#e9c46a; stroke-width:1.4; }}
  .jdot {{ fill:#e9c46a; }}
  #bar button.on {{ background:#e9c46a; color:#151310; border-color:#e9c46a;
    font-weight:bold; }}
  line.top {{ stroke:#6f8f6a; stroke-width:1.1; opacity:.6; }}
  line.tunnel {{ stroke:#c77b3f; stroke-width:1.1; stroke-dasharray:5 3; opacity:.8; }}
  line.typeonly {{ stroke:#666; stroke-width:1; stroke-dasharray:1 3; opacity:.5; }}
  line.sealed {{ stroke:#8a3b2f; stroke-width:2; stroke-dasharray:3 3; }}
  .legend {{ color:#9a8f7a; font-size:12px; margin-top:10px; }}
</style>
<h1>{header}</h1>
<div id="bar">
  <input id="q" placeholder="search a seen module..." size="26"
         autocomplete="off">
  <button id="probe" title="click two modules to trace the real import route
between them - only over edges you have earned sight of">PROBE ROUTE</button>
  <button id="reset">RESET VIEW</button>
  <span id="probemsg">drag pans · wheel zooms · click a building for its
dossier · ! marks an open quest's starting tile</span>
</div>
<svg id="town" viewBox="0 0 {content_w} {height}" preserveAspectRatio="xMidYMid meet"
     xmlns="http://www.w3.org/2000/svg">
<defs><marker id="rarr" markerWidth="10" markerHeight="10" refX="9"
 refY="4" orient="auto"><path d="M0,0 L9,4 L0,8" fill="none"
 stroke="#e9c46a" stroke-width="1.6"/></marker></defs>
{chr(10).join(parts)}
<g id="route"></g>
</svg>
<div class="legend">
filled dot = visited · hollow dot = seen · speck = fog · gold ring = boss ·
blue = bedrock · purple = gate · green = swamp ·
solid line = top-level import · orange dash = tunnel (unlocked) ·
red stub = sealed tunnel · faint dots = types-only ·
edges appear once you have read the importing file
</div>
<div class="legend">regenerate after moving: <b>buzz atlas</b></div>
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
  .node {{ cursor:pointer; pointer-events:all; }}  /* hollow (seen,
    unread) circles must catch clicks in their interior, not just on
    their 1px ring - caught by a headless-browser drive */
</style>
<script>
{js}
</script>
"""


def write_atlas(world: World, s: Session, out: Path) -> Path:
    out.write_text(render_atlas(world, s))
    return out
