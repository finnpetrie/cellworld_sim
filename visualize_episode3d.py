"""Writes an HTML player for simulation episodes in a 3D (cubic) world: a rotatable 3D view and a z-slice view of the
prey and predator moving step by step, with their trails, the goal, and the cells the prey can see. All seeds of the
episode's world are bundled, so you can switch between them on the page.

    .venv/bin/python visualize_episode3d.py                                  # first episode in results_cube8
    .venv/bin/python visualize_episode3d.py --list                           # list episodes with result and length
    .venv/bin/python visualize_episode3d.py cellworld_simulation/results_cube8/lac05_05_r03_seed_0.json

Open the .html in a browser (from WSL: explorer.exe lac05_05_r03.html). The 3D view loads three.js from cdnjs, so it
needs an internet connection; the slice view works without it.
"""
import argparse
import glob
import json
import os
import re

from visualize_worlds import load, visibility_bits

RESULT_NAME = re.compile(r"(?P<world>.+)_seed_(?P<seed>\d+)\.json$")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
  :root { --bg:#f6f5f2; --panel:#fff; --ink:#1d1d1b; --muted:#6b6a66; --free:#e9e7e1; --occluded:#3a3a38;
          --seen:#f4cf55; --prey:#2f8f4e; --predator:#c8402f; --goal:#3b6fb6; --line:#d6d3cc; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#161615; --panel:#1f1f1d; --ink:#ecebe7; --muted:#9a988f; --free:#34332f; --occluded:#0b0b0a;
            --seen:#b8962a; --prey:#4cc274; --predator:#ee6450; --goal:#6b9be0; --line:#3a3935; }
  }
  body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.4 system-ui, sans-serif; }
  main { max-width:1200px; margin:0 auto; padding:20px 16px; }
  .top { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:4px; }
  .top h1 { font-size:18px; margin:0 auto 0 0; }
  .sub { color:var(--muted); margin-bottom:12px; }
  button, select, input { font:inherit; padding:4px 10px; border-radius:6px; border:1px solid var(--line); background:var(--panel); color:var(--ink); }
  button { cursor:pointer; }
  .layout { display:grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap:14px; align-items:start; }
  @media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px; }
  .card h2 { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:0 0 6px; }
  #view { width:100%; aspect-ratio:1; display:block; border-radius:6px; cursor:grab; touch-action:none; }
  #slice { width:100%; height:auto; display:block; }
  #nogl { color:var(--muted); padding:40px 10px; text-align:center; }
  .row { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:8px; color:var(--muted); }
  .row input[type=range] { flex:1; min-width:120px; }
  .controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:14px 0 6px; }
  .controls input[type=range] { flex:1; min-width:160px; padding:0; }
  .status { display:flex; flex-wrap:wrap; gap:16px; color:var(--muted); font-variant-numeric:tabular-nums; }
  .status b { color:var(--ink); font-weight:600; }
  .legend { display:flex; flex-wrap:wrap; gap:14px; color:var(--muted); margin-top:8px; font-size:13px; }
  .legend span::before { content:""; display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:5px; vertical-align:-1px; background:var(--c); }
  label { color:var(--muted); user-select:none; }
</style></head>
<body><main>
  <div class="top">
    <h1 id="title"></h1>
    <button id="prevEp">◀ prev</button><select id="pick"></select><button id="nextEp">next ▶</button>
  </div>
  <div class="sub" id="subtitle"></div>
  <div class="layout">
    <div class="card">
      <h2>3D view · drag to rotate, scroll to zoom</h2>
      <canvas id="view"></canvas>
      <div id="nogl" hidden>3D view unavailable (needs WebGL and an internet connection for three.js). The slice view still works.</div>
      <div class="row">occlusions
        <select id="occStyle"><option value="ghost" selected>transparent</option><option value="solid">solid</option><option value="hide">hidden</option></select>
        z ≤ <b id="cutLabel"></b><input type="range" id="cut" min="0" value="0"></div>
    </div>
    <div class="card">
      <h2>Slice</h2>
      <svg id="slice"></svg>
      <div class="row">z = <b id="zLabel"></b><input type="range" id="z" min="0" value="0">
        <label><input type="checkbox" id="follow" checked> follow prey</label></div>
      <div class="row" style="font-size:12px">Faded markers: agent is on another layer (its z is shown).</div>
    </div>
  </div>
  <div class="controls">
    <button id="play">Play</button>
    <button id="back">◀</button><button id="next">▶</button>
    <input id="slider" type="range" min="0" value="0">
    <label>speed <select id="speed"><option value="600">slow</option><option value="250" selected>normal</option><option value="80">fast</option></select></label>
  </div>
  <div class="status" id="status"></div>
  <div class="legend">
    <span style="--c:var(--prey)">prey</span><span style="--c:var(--predator)">predator</span><span style="--c:var(--goal)">goal</span>
    <span style="--c:var(--seen)">visible to prey</span><span style="--c:var(--occluded)">occlusion</span>
    <label><input type="checkbox" id="showSeen" checked> prey's view</label>
    <label><input type="checkbox" id="showTrails" checked> trails</label>
  </div>
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const n = D.coordinates.length, size = D.size;
const $ = id => document.getElementById(id);
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };
const occluded = new Uint8Array(n); D.occlusions.forEach(i => occluded[i] = 1);
const visible = Uint8Array.from(atob(D.visibility), c => c.charCodeAt(0));
const sees = (i, j) => { const k = i * n + j; return (visible[k >> 3] >> (k & 7)) & 1; };
const C = i => D.coordinates[i];

let ep, t = 0, timer = null;

// ---------- slice view
const slice = $("slice");
slice.setAttribute("viewBox", `-0.1 -0.1 ${size + 0.14} ${size + 0.14}`);
const sy = y => size - 1 - y;
const sliceCells = [];
for (let y = 0; y < size; y++) for (let x = 0; x < size; x++)
  sliceCells.push([x, y, el("rect", { x, y: sy(y), width: 0.94, height: 0.94, rx: 0.12 }, slice)]);
const sliceTrails = el("g", {}, slice), sliceMarks = el("g", {}, slice);

// ---------- 3D view
let three = null;
if (window.THREE && (() => { try { return !!document.createElement("canvas").getContext("webgl"); } catch (e) { return false; } })()) {
  const canvas = $("view");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 1000);
  camera.up.set(0, 0, 1);
  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const sun = new THREE.DirectionalLight(0xffffff, 0.7); sun.position.set(1, -2, 3); scene.add(sun);
  const c = (size - 1) / 2, centre = new THREE.Vector3(c, c, c);
  const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(size, size, size)), new THREE.LineBasicMaterial({ color: 0x999999 }));
  frame.position.copy(centre); scene.add(frame);
  const box = new THREE.BoxGeometry(0.92, 0.92, 0.92);
  const occMaterial = new THREE.MeshLambertMaterial({ color: 0x55534e, transparent: true, opacity: 0.18, depthWrite: false });
  const occludedMesh = new THREE.InstancedMesh(box, occMaterial, n);
  const ball = new THREE.SphereGeometry(1, 16, 12);
  const seenMesh = new THREE.InstancedMesh(ball, new THREE.MeshBasicMaterial({ color: 0xe0b630 }), n);
  scene.add(seenMesh, occludedMesh);
  const marker = (color, radius) => { const m = new THREE.Mesh(ball, new THREE.MeshLambertMaterial({ color })); m.scale.setScalar(radius); scene.add(m); return m; };
  const preyMark = marker(0x2f8f4e, 0.36), predMark = marker(0xc8402f, 0.36), goalMark = marker(0x3b6fb6, 0.24);
  const trail = color => { const l = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color })); scene.add(l); return l; };
  const preyTrail = trail(0x2f8f4e), predTrail = trail(0xc8402f);
  const sight = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: 0xc8402f, dashSize: 0.25, gapSize: 0.18 }));
  scene.add(sight);
  let theta = -0.9, phi = 1.05, radius = size * 2.6;
  const m4 = new THREE.Matrix4();
  function place(mesh, cells, scale) {
    cells.forEach((i, k) => { const p = C(i); m4.makeScale(scale, scale, scale).setPosition(p[0], p[1], p[2]); mesh.setMatrixAt(k, m4); });
    mesh.count = cells.length; mesh.instanceMatrix.needsUpdate = true;
  }
  const line = (obj, cells) => { obj.geometry.setFromPoints(cells.map(i => new THREE.Vector3(...C(i)))); obj.computeLineDistances && obj.computeLineDistances(); };
  function render() {
    const rect = canvas.getBoundingClientRect();
    renderer.setPixelRatio(window.devicePixelRatio); renderer.setSize(rect.width, rect.width, false);
    camera.position.set(c + radius * Math.sin(phi) * Math.cos(theta), c + radius * Math.sin(phi) * Math.sin(theta), c + radius * Math.cos(phi));
    camera.lookAt(centre); renderer.render(scene, camera);
  }
  let drag = null;
  canvas.addEventListener("pointerdown", e => { drag = [e.clientX, e.clientY]; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", e => { if (!drag) return; theta -= (e.clientX - drag[0]) * 0.01; phi = Math.min(3.1, Math.max(0.05, phi - (e.clientY - drag[1]) * 0.01)); drag = [e.clientX, e.clientY]; render(); });
  canvas.addEventListener("pointerup", () => drag = null);
  canvas.addEventListener("wheel", e => { e.preventDefault(); radius = Math.min(size * 6, Math.max(size, radius * (1 + e.deltaY * 0.001))); render(); }, { passive: false });
  window.addEventListener("resize", render);
  three = {
    update(s, seen, contact) {
      const cut = +$("cut").value, below = i => C(i)[2] <= cut, style = $("occStyle").value;
      occMaterial.opacity = style === "solid" ? 1 : 0.18; occMaterial.depthWrite = style === "solid"; occMaterial.transparent = style !== "solid";
      place(occludedMesh, style === "hide" ? [] : D.occlusions.filter(below), 1);
      place(seenMesh, seen.filter(i => below(i) && i !== s.prey), 0.1);
      preyMark.position.set(...C(s.prey)); predMark.position.set(...C(s.predator)); goalMark.position.set(...C(D.goal));
      const trails = $("showTrails").checked, past = ep.steps.slice(0, t + 1);
      line(preyTrail, trails ? past.map(x => x.prey) : []); line(predTrail, trails ? past.map(x => x.predator) : []);
      line(sight, contact ? [s.prey, s.predator] : []);
      render();
    }
  };
} else {
  $("view").hidden = true; $("nogl").hidden = false;
}

// ---------- drawing
function draw() {
  const s = ep.steps[t];
  const seen = $("showSeen").checked ? [...Array(n).keys()].filter(j => sees(s.prey, j)) : [];
  const seenSet = new Set(seen);
  const contact = sees(s.prey, s.predator);
  if ($("follow").checked) $("z").value = C(s.prey)[2];
  const z = +$("z").value;
  $("zLabel").textContent = z; $("cutLabel").textContent = $("cut").value;
  const at = (x, y) => D.index[`${x},${y},${z}`];
  for (const [x, y, r] of sliceCells) { const i = at(x, y); r.setAttribute("fill", occluded[i] ? "var(--occluded)" : seenSet.has(i) ? "var(--seen)" : "var(--free)"); }

  sliceTrails.replaceChildren();
  if ($("showTrails").checked) for (const [k, color] of [["prey", "var(--prey)"], ["predator", "var(--predator)"]]) {
    const pts = ep.steps.slice(0, t + 1).map(x => C(x[k]));
    for (let q = 1; q < pts.length; q++) {  // project the trail; segments on this layer drawn solid, others faint
      const [a, b] = [pts[q - 1], pts[q]];
      if (a[0] === b[0] && a[1] === b[1]) continue;
      el("line", { x1: a[0] + .47, y1: sy(a[1]) + .47, x2: b[0] + .47, y2: sy(b[1]) + .47, stroke: color, "stroke-width": .12,
                   "stroke-linecap": "round", opacity: a[2] === z && b[2] === z ? .7 : .2 }, sliceTrails);
    }
  }
  sliceMarks.replaceChildren();
  const mark = (c, color, label, r) => {
    const here = c[2] === z;
    el("circle", { cx: c[0] + .47, cy: sy(c[1]) + .47, r, fill: color, opacity: here ? 1 : .3 }, sliceMarks);
    const tx = el("text", { x: c[0] + .47, y: sy(c[1]) + .62, "text-anchor": "middle", "font-size": .4, fill: here ? "#fff" : "var(--ink)", "font-weight": 700 }, sliceMarks);
    tx.textContent = here ? label : `z${c[2]}`;
  };
  mark(C(D.goal), "var(--goal)", "G", .3);
  mark(C(s.predator), "var(--predator)", "P", .38);
  mark(C(s.prey), "var(--prey)", "R", .38);
  if (contact && C(s.prey)[2] === z && C(s.predator)[2] === z) {
    const [a, b] = [C(s.prey), C(s.predator)];
    el("line", { x1: a[0] + .47, y1: sy(a[1]) + .47, x2: b[0] + .47, y2: sy(b[1]) + .47, stroke: "var(--predator)", "stroke-width": .06, "stroke-dasharray": ".2 .14" }, sliceMarks);
  }

  const prev = ep.steps[t - 1];
  const mover = !prev ? "start" : prev.prey !== s.prey ? "prey moved" : prev.predator !== s.predator ? "predator moved" : "no move";
  const fmt = i => `(${C(i).join(", ")})`;
  $("status").innerHTML = `<span>step <b>${t}</b> / ${ep.steps.length - 1}</span><span>iteration <b>${s.iteration}</b></span>` +
    `<span><b>${mover}</b></span><span>prey <b>${fmt(s.prey)}</b></span><span>predator <b>${fmt(s.predator)}</b></span>` +
    `<span>${contact ? "<b>predator in view</b>" : "predator hidden"}</span>`;
  $("slider").value = t;
  if (three) three.update(s, seen, contact);
}

function open(k) {
  stop();
  const e = (k + D.episodes.length) % D.episodes.length;
  ep = D.episodes[e]; t = 0;
  $("pick").value = e;
  $("slider").max = ep.steps.length - 1;
  $("subtitle").textContent = `world ${D.world}` + (D.lacunarity ? ` · lacunarity ${D.lacunarity.toFixed(2)}` : "") +
    ` · seed ${ep.seed} · ${ep.result ? "prey reached the goal" : "prey was caught"} after ${ep.iterations} iterations` +
    ` · ${D.episodes.filter(x => x.result).length}/${D.episodes.length} seeds survived`;
  draw();
}
function go(k) { t = Math.max(0, Math.min(ep.steps.length - 1, k)); draw(); }
function stop() { clearInterval(timer); timer = null; $("play").textContent = "Play"; }

$("title").textContent = D.world;
D.episodes.forEach((x, k) => { const o = document.createElement("option"); o.value = k; o.textContent = `seed ${x.seed} · ${x.result ? "survived" : "caught"} · ${x.iterations} it`; $("pick").appendChild(o); });
$("pick").onchange = () => open(+$("pick").value);
$("prevEp").onclick = () => open(+$("pick").value - 1);
$("nextEp").onclick = () => open(+$("pick").value + 1);
$("play").onclick = () => {
  if (timer) return stop();
  if (t === ep.steps.length - 1) t = 0;
  $("play").textContent = "Pause";
  timer = setInterval(() => { if (t >= ep.steps.length - 1) return stop(); go(t + 1); }, +$("speed").value);
};
$("speed").onchange = () => { if (timer) { stop(); $("play").click(); } };
$("back").onclick = () => { stop(); go(t - 1); };
$("next").onclick = () => { stop(); go(t + 1); };
$("slider").oninput = () => { stop(); go(+$("slider").value); };
$("z").oninput = () => { $("follow").checked = false; draw(); };
$("z").max = $("cut").max = size - 1; $("cut").value = size - 1;
for (const id of ["showSeen", "showTrails", "follow", "cut", "occStyle"]) $(id).oninput = draw;
document.addEventListener("keydown", e => {
  if (e.target.tagName === "SELECT") return;
  if (e.key === "ArrowRight") { stop(); go(t + 1); }
  if (e.key === "ArrowLeft") { stop(); go(t - 1); }
  if (e.key === " ") { e.preventDefault(); $("play").click(); }
});
open(D.first);
</script></body></html>
"""


def read_episode(path, index):
    with open(path) as f:
        episode = json.load(f)
    cell = lambda c: index[(c["x"], c["y"], c.get("z", 0))]  # the writer omits z when it is 0
    return {"seed": int(RESULT_NAME.match(os.path.basename(path))["seed"]),
            "result": episode["result"], "iterations": episode["iterations"],
            "steps": [{"iteration": s["iteration"], "prey": cell(s["prey"]), "predator": cell(s["predator"])}
                      for s in episode["steps"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("episode", nargs="?", help="result .json file (default: the first one in --results)")
    parser.add_argument("--results", default="cellworld_simulation/results_cube8", help="folder with the result .json files")
    parser.add_argument("--worlds", default="generated_worlds_cube8", help="generator output folder (with manifest.json)")
    parser.add_argument("--goal", default="7,4,4", help="prey goal in run.cpp (x,y,z)")
    parser.add_argument("--list", action="store_true", help="list episodes and exit")
    parser.add_argument("--out", help="output .html (default: <world>.html)")
    args = parser.parse_args()

    paths = sorted(glob.glob(os.path.join(args.results, "*_seed_*.json")))
    if args.list:
        for path in paths:
            with open(path) as f:
                episode = json.load(f)
            print(f"{path}  {'survived' if episode['result'] else 'caught  '}  {episode['iterations']:4d} iterations")
        return
    episode_path = args.episode or (paths[0] if paths else None)
    if not episode_path:
        raise SystemExit(f"no result files in {args.results}")
    world = RESULT_NAME.match(os.path.basename(episode_path))["world"]

    with open(os.path.join(args.worlds, "manifest.json")) as f:
        manifest = json.load(f)
    configuration = manifest["world_configuration"]
    config = load(args.worlds, "world_configuration", configuration)
    if "z" not in config["cell_coordinates"][0]:
        raise SystemExit("this player draws 3D (cubic) worlds; use visualize_episode.py for hexagonal ones")
    coordinates = [[c["x"], c["y"], c["z"]] for c in config["cell_coordinates"]]
    index = {tuple(c): i for i, c in enumerate(coordinates)}

    seed_paths = sorted(glob.glob(os.path.join(os.path.dirname(episode_path), f"{world}_seed_*.json")),
                        key=lambda p: int(RESULT_NAME.match(os.path.basename(p))["seed"]))
    episodes = [read_episode(p, index) for p in seed_paths]
    data = {
        "world": world,
        "lacunarity": next((w["lacunarity"] for w in manifest["worlds"] if w["occlusions"] == world), None),
        "coordinates": coordinates,
        "index": {",".join(map(str, c)): i for i, c in enumerate(coordinates)},
        "size": max(max(c) for c in coordinates) + 1,
        "goal": index[tuple(int(v) for v in args.goal.split(","))],
        "occlusions": load(args.worlds, "cell_group", f"{configuration}.{world}.occlusions"),
        "visibility": visibility_bits(load(args.worlds, "graph", f"{configuration}.{world}.cell_visibility"), len(coordinates)),
        "episodes": episodes,
        "first": [os.path.normpath(p) for p in seed_paths].index(os.path.normpath(episode_path)),
    }
    out = args.out or world + ".html"
    with open(out, "w") as f:
        f.write(PAGE.replace("__TITLE__", world).replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    print(f"wrote {out}  ({len(episodes)} seeds, {os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
