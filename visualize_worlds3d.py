"""Writes an HTML browser for a folder of generated 3D (cubic) worlds: a rotatable 3D view of the occlusions and a
z-slice view. Click a cell to see what it can see; POIs, start/goal and the predator spawn cells are marked.

    .venv/bin/python visualize_worlds3d.py --worlds generated_worlds_cube8
    .venv/bin/python visualize_worlds3d.py --worlds generated_worlds_cube8 --predator 7,4,4 --radius 5 --out cube8.html

Open the .html in a browser (from WSL: explorer.exe cube8.html). The 3D view loads three.js from cdnjs, so it
needs an internet connection; the slice view works without it.
"""
import argparse
import json
import os

from visualize_worlds import load, parse_cell, visibility_bits

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>3D world browser</title>
<style>
  :root { --bg:#f6f5f2; --panel:#fff; --ink:#1d1d1b; --muted:#6b6a66; --free:#e9e7e1; --occluded:#3a3a38;
          --seen:#f4cf55; --poi:#8a8780; --prey:#2f8f4e; --predator:#c8402f; --spawn:#f2b8ad; --line:#d6d3cc; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#161615; --panel:#1f1f1d; --ink:#ecebe7; --muted:#9a988f; --free:#34332f; --occluded:#0b0b0a;
            --seen:#b8962a; --poi:#8d8a80; --prey:#4cc274; --predator:#ee6450; --spawn:#7a4038; --line:#3a3935; }
  }
  body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.4 system-ui, sans-serif; }
  main { max-width:1200px; margin:0 auto; padding:20px 16px; }
  .top { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:10px; }
  .top h1 { font-size:18px; margin:0 auto 0 0; }
  button, select, input { font:inherit; padding:4px 10px; border-radius:6px; border:1px solid var(--line); background:var(--panel); color:var(--ink); }
  button { cursor:pointer; }
  input[type=number] { width:4em; }
  .layout { display:grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) 240px; gap:14px; align-items:start; }
  @media (max-width: 980px) { .layout { grid-template-columns: 1fr; } }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px; }
  .card h2 { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:0 0 6px; }
  #view { width:100%; aspect-ratio:1; display:block; border-radius:6px; cursor:grab; touch-action:none; }
  #slice { width:100%; height:auto; display:block; }
  .row { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:8px; color:var(--muted); }
  .row input[type=range] { flex:1; min-width:120px; }
  .stats { display:grid; grid-template-columns:auto 1fr; gap:2px 10px; font-variant-numeric:tabular-nums; margin:0; }
  .stats dt { color:var(--muted); } .stats dd { margin:0; }
  label { display:block; color:var(--muted); margin:4px 0; user-select:none; }
  .swatch { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:-1px; background:var(--c); }
  .hint { color:var(--muted); font-size:12px; margin-top:10px; }
  #hover { color:var(--muted); font-variant-numeric:tabular-nums; min-height:1.4em; margin-top:6px; }
  #nogl { color:var(--muted); padding:40px 10px; text-align:center; }
  svg.strip { width:100%; height:auto; margin-top:12px; background:var(--panel); border:1px solid var(--line); border-radius:8px; display:block; }
</style></head>
<body><main>
  <div class="top">
    <h1 id="title"></h1>
    <button id="prev">◀ prev</button><select id="pick"></select><button id="next">next ▶</button>
  </div>
  <div class="layout">
    <div class="card">
      <h2>3D view · drag to rotate, scroll to zoom</h2>
      <canvas id="view"></canvas>
      <div id="nogl" hidden>3D view unavailable (needs WebGL and an internet connection for three.js). The slice view still works.</div>
      <div class="row">show layers z ≤ <b id="cutLabel"></b><input type="range" id="cut" min="0" value="0"></div>
    </div>
    <div class="card">
      <h2>Slice · click a cell to select it</h2>
      <svg id="slice"></svg>
      <div class="row">z = <b id="zLabel"></b><input type="range" id="z" min="0" value="0"></div>
      <div id="hover"></div>
    </div>
    <div class="card">
      <h2>World</h2>
      <dl class="stats" id="stats"></dl>
      <h2 style="margin-top:14px">Show</h2>
      <label><input type="checkbox" id="showSeen" checked> <span class="swatch" style="--c:var(--seen)"></span>visible from selected</label>
      <label><input type="checkbox" id="showPois" checked> <span class="swatch" style="--c:var(--poi)"></span>POIs</label>
      <label><input type="checkbox" id="showSpawn" checked> <span class="swatch" style="--c:var(--spawn)"></span>predator spawn cells</label>
      <label>spawn radius <input type="number" id="radius" min="1" max="60"></label>
      <div class="hint">Green: prey start (S) and goal (G). Red: predator location (P; "G·P" when it is the goal). Spawn cells follow the
        simulation: free, hidden from S, within the radius of P (or the closest hidden cells).
        ←/→ change world.</div>
    </div>
  </div>
  <svg class="strip" id="strip"></svg>
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const n = D.coordinates.length, size = D.size;
const key = c => c.join(",");
const index = new Map(D.coordinates.map((c, i) => [key(c), i]));
const neighbours = D.coordinates.map(c => D.pattern.map(p => index.get(key([c[0] + p[0], c[1] + p[1], c[2] + p[2]]))).filter(i => i !== undefined));
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const $ = id => document.getElementById(id);
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };

let w = 0, world, occluded, visible, spawn = new Set();
let selected = index.get(key(D.start));
const decode = b64 => Uint8Array.from(atob(b64), c => c.charCodeAt(0));
const sees = (i, j) => { const k = i * n + j; return (visible[k >> 3] >> (k & 7)) & 1; };

function spawnCells(radius) {
  const center = index.get(key(D.predator)), start = index.get(key(D.start));
  if (center === undefined || occluded[center]) return [];
  const dist = new Int32Array(n).fill(-1); dist[center] = 0; const queue = [center];
  for (let q = 0; q < queue.length; q++) for (const j of neighbours[queue[q]])
    if (!occluded[j] && dist[j] < 0) { dist[j] = dist[queue[q]] + 1; queue.push(j); }
  const hidden = [...Array(n).keys()].filter(i => dist[i] > 0 && !sees(start, i));
  if (!hidden.length) return [];
  const r = Math.max(radius, Math.min(...hidden.map(i => dist[i])));
  return hidden.filter(i => dist[i] <= r);
}

// ---------- slice view
const slice = $("slice");
slice.setAttribute("viewBox", `-0.1 -0.1 ${size + 0.14} ${size + 0.14}`);
const sliceCells = [];
for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
  const r = el("rect", { x, y: size - 1 - y, width: 0.94, height: 0.94, rx: 0.12, style: "cursor:pointer" }, slice);
  r.addEventListener("click", () => { const i = index.get(key([x, y, +$("z").value])); if (!occluded[i]) { selected = i; draw(); } });
  r.addEventListener("mouseenter", () => hoverInfo(index.get(key([x, y, +$("z").value]))));
  sliceCells.push([x, y, r]);
}
const sliceMarks = el("g", {}, slice);
const sliceRing = el("rect", { width: 0.94, height: 0.94, rx: 0.12, fill: "none", "stroke-width": 0.12 }, slice);

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
  const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(size, size, size)),
                                       new THREE.LineBasicMaterial({ color: 0x999999 }));
  frame.position.copy(centre); scene.add(frame);
  const box = new THREE.BoxGeometry(0.92, 0.92, 0.92);
  const occludedMesh = new THREE.InstancedMesh(box, new THREE.MeshLambertMaterial({ color: 0x55534e }), n);
  const spawnMesh = new THREE.InstancedMesh(box, new THREE.MeshLambertMaterial({ color: 0xe8806e, transparent: true, opacity: 0.45 }), n);
  const ball = new THREE.SphereGeometry(1, 12, 8);
  const poiMesh = new THREE.InstancedMesh(ball, new THREE.MeshLambertMaterial({ color: 0x77746c }), n);
  const seenMesh = new THREE.InstancedMesh(ball, new THREE.MeshBasicMaterial({ color: 0xe0b630 }), n);
  scene.add(occludedMesh, spawnMesh, poiMesh, seenMesh);
  const marker = (color, radius) => { const m = new THREE.Mesh(ball, new THREE.MeshLambertMaterial({ color })); m.scale.setScalar(radius); scene.add(m); return m; };
  const startMark = marker(0x2f8f4e, 0.38), goalMark = marker(0x2f8f4e, 0.38), predMark = marker(0xc8402f, 0.38);
  const selectBox = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1.02, 1.02, 1.02)), new THREE.LineBasicMaterial({ color: 0x1d1d1b }));
  scene.add(selectBox);
  let theta = -0.9, phi = 1.05, radius = size * 2.6;
  const m4 = new THREE.Matrix4();
  function place(mesh, cells, scale) {
    cells.forEach((i, k) => { const p = D.coordinates[i]; m4.makeScale(scale, scale, scale).setPosition(p[0], p[1], p[2]); mesh.setMatrixAt(k, m4); });
    mesh.count = cells.length; mesh.instanceMatrix.needsUpdate = true;
  }
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
    update(cut, seen) {
      const below = i => D.coordinates[i][2] <= cut;
      place(occludedMesh, world.occlusions.filter(below), 1);
      place(spawnMesh, [...spawn].filter(below), 1);
      place(poiMesh, $("showPois").checked ? world.pois.filter(below) : [], 0.16);
      place(seenMesh, seen.filter(i => below(i) && i !== selected), 0.11);
      const put = (m, c) => { m.visible = !!c && c[2] <= cut; if (c) m.position.set(...c); };
      put(startMark, D.start); put(goalMark, D.goal); put(predMark, occluded[index.get(key(D.predator))] ? null : D.predator);
      selectBox.position.set(...D.coordinates[selected]);
      render();
    }
  };
} else {
  $("view").hidden = true; $("nogl").hidden = false;
}

// ---------- drawing
function load(k) {
  w = (k + D.worlds.length) % D.worlds.length;
  world = D.worlds[w];
  occluded = new Uint8Array(n); world.occlusions.forEach(i => occluded[i] = 1);
  visible = decode(world.visibility);
  if (occluded[selected]) selected = index.get(key(D.start));
  $("pick").value = w;
  draw();
}

function draw() {
  spawn = new Set($("showSpawn").checked ? spawnCells(+$("radius").value) : []);
  const seen = $("showSeen").checked ? [...Array(n).keys()].filter(j => sees(selected, j)) : [];
  const seenSet = new Set(seen), poiSet = new Set($("showPois").checked ? world.pois : []);
  const z = +$("z").value;
  $("zLabel").textContent = z; $("cutLabel").textContent = $("cut").value;
  for (const [x, y, r] of sliceCells) {
    const i = index.get(key([x, y, z]));
    r.setAttribute("fill", occluded[i] ? "var(--occluded)" : seenSet.has(i) ? "var(--seen)" : spawn.has(i) ? "var(--spawn)" : "var(--free)");
  }
  sliceMarks.replaceChildren();
  for (const i of poiSet) { const c = D.coordinates[i]; if (c[2] === z) el("circle", { cx: c[0] + .47, cy: size - 1 - c[1] + .47, r: .14, fill: "var(--poi)" }, sliceMarks); }
  const mark = (c, color, label) => { if (!c || c[2] !== z) return;
    el("circle", { cx: c[0] + .47, cy: size - 1 - c[1] + .47, r: .36, fill: color }, sliceMarks);
    const t = el("text", { x: c[0] + .47, y: size - 1 - c[1] + .62, "text-anchor": "middle", "font-size": .45, fill: "#fff", "font-weight": 700 }, sliceMarks); t.textContent = label; };
  const predatorAtGoal = key(D.predator) === key(D.goal);
  mark(D.start, "var(--prey)", "S");
  mark(D.goal, predatorAtGoal ? "var(--predator)" : "var(--prey)", predatorAtGoal ? "G·P" : "G");
  if (!predatorAtGoal && !occluded[index.get(key(D.predator))]) mark(D.predator, "var(--predator)", "P");
  const s = D.coordinates[selected];
  sliceRing.setAttribute("x", s[0]); sliceRing.setAttribute("y", size - 1 - s[1]);
  sliceRing.setAttribute("stroke", s[2] === z ? css("--ink") : "none");

  $("title").textContent = world.name;
  const stats = [["level", world.level], ["replicate", world.replicate], ["lacunarity", world.lacunarity.toFixed(2)],
    ...Object.entries(world.per_radius).map(([r, v]) => [`  radius ${r}`, v.toFixed(2)]),
    ["entropy", D.entropy.toFixed(3)], ["occlusions", world.occlusions.length], ["POIs", world.pois.length],
    ["selected", `(${s.join(", ")}) sees ${seen.length || "–"}`],
    ["spawn cells", $("showSpawn").checked ? (spawn.size || "none hidden") : "–"]];
  $("stats").innerHTML = stats.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  stripDots.forEach((d, k) => { d.setAttribute("r", k === w ? 5 : 3); d.setAttribute("fill", k === w ? "var(--predator)" : "var(--muted)"); });
  if (three) three.update(+$("cut").value, seen);
}

function hoverInfo(i) {
  const c = D.coordinates[i];
  $("hover").textContent = `cell ${i} (${c.join(", ")})` + (occluded[i] ? " · occluded" : ` · sees ${[...Array(n).keys()].filter(j => sees(i, j)).length} cells`) + (world.pois.includes(i) ? " · POI" : "");
}

// ---------- strip of worlds by lacunarity
const strip = $("strip");
const lac = D.worlds.map(x => Math.log(x.lacunarity)), lo = Math.min(...lac), hi = Math.max(...lac);
const reps = Math.max(...D.worlds.map(x => x.replicate)) + 1, SW = 900, SH = 30 + reps * 9;
strip.setAttribute("viewBox", `0 0 ${SW} ${SH}`);
el("text", { x: 10, y: 14, "font-size": 11, fill: "var(--muted)" }, strip).textContent = "all worlds by lacunarity (click to open)";
el("text", { x: 20, y: SH - 4, "font-size": 10, fill: "var(--muted)" }, strip).textContent = Math.exp(lo).toFixed(2);
el("text", { x: SW - 20, y: SH - 4, "font-size": 10, fill: "var(--muted)", "text-anchor": "end" }, strip).textContent = Math.exp(hi).toFixed(2);
const stripDots = D.worlds.map((x, k) => {
  const d = el("circle", { cx: 20 + (SW - 40) * (hi > lo ? (lac[k] - lo) / (hi - lo) : .5), cy: 24 + x.replicate * 9, r: 3, style: "cursor:pointer" }, strip);
  el("title", {}, d).textContent = `${x.name} · lacunarity ${x.lacunarity.toFixed(2)}`;
  d.addEventListener("click", () => load(k));
  return d;
});

// ---------- controls
D.worlds.forEach((x, k) => { const o = document.createElement("option"); o.value = k; o.textContent = `${x.name} (${x.lacunarity.toFixed(2)})`; $("pick").appendChild(o); });
$("pick").onchange = () => load(+$("pick").value);
$("prev").onclick = () => load(w - 1);
$("next").onclick = () => load(w + 1);
$("z").max = $("cut").max = size - 1; $("z").value = D.start[2]; $("cut").value = size - 1;
$("radius").value = D.spawn_radius;
for (const id of ["showSeen", "showPois", "showSpawn", "radius", "z", "cut"]) $(id).oninput = draw;
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.key === "ArrowRight") load(w + 1);
  if (e.key === "ArrowLeft") load(w - 1);
});
load(0);
</script></body></html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worlds", default="generated_worlds_cube8", help="generator output folder (with manifest.json)")
    parser.add_argument("--start", help="prey start (default: from the manifest)")
    parser.add_argument("--goal", help="prey goal (default: from the manifest)")
    parser.add_argument("--predator", help="predator_location in run.cpp (default: the goal)")
    parser.add_argument("--radius", type=int, default=5, help="predator_spawn_radius in run.cpp")
    parser.add_argument("--out", help="output .html (default: <worlds folder>.html)")
    args = parser.parse_args()

    with open(os.path.join(args.worlds, "manifest.json")) as f:
        manifest = json.load(f)
    configuration = manifest["world_configuration"]
    config = load(args.worlds, "world_configuration", configuration)
    if "z" not in config["cell_coordinates"][0]:
        raise SystemExit("this browser draws 3D (cubic) worlds; use visualize_worlds.py for hexagonal ones")
    coordinates = [[c["x"], c["y"], c["z"]] for c in config["cell_coordinates"]]
    start_goal = [[c["x"], c["y"], c["z"]] for c in manifest["start_goal"]]
    start = parse_cell(args.start) if args.start else start_goal[0]
    goal = parse_cell(args.goal) if args.goal else start_goal[1]
    n = len(coordinates)
    data = {
        "coordinates": coordinates,
        "size": max(max(c) for c in coordinates) + 1,
        "pattern": [[c["x"], c["y"], c["z"]] for c in config["connection_pattern"]],
        "entropy": manifest["entropy"],
        "start": start, "goal": goal, "predator": parse_cell(args.predator) if args.predator else goal,
        "spawn_radius": args.radius,
        "worlds": [],
    }
    for w in sorted(manifest["worlds"], key=lambda w: (w["level"], w["replicate"])):
        name = w["occlusions"]
        data["worlds"].append({
            "name": name, "level": w["level"], "replicate": w["replicate"],
            "lacunarity": w["lacunarity"], "per_radius": w["lacunarity_per_radius"],
            "occlusions": load(args.worlds, "cell_group", f"{configuration}.{name}.occlusions"),
            "pois": load(args.worlds, "cell_group", f"{configuration}.{name}.lppo"),
            "visibility": visibility_bits(load(args.worlds, "graph", f"{configuration}.{name}.cell_visibility"), n),
        })
    out = args.out or os.path.basename(os.path.normpath(args.worlds)) + ".html"
    with open(out, "w") as f:
        f.write(PAGE.replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    print(f"wrote {out}  ({len(data['worlds'])} worlds, {os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
