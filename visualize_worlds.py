"""Writes an HTML browser for a folder of generated worlds: step through them, click cells to see what they can
see and their options-graph links, and show where the predator can spawn.

    .venv/bin/python visualize_worlds.py                                  # generated_worlds_100 -> worlds.html
    .venv/bin/python visualize_worlds.py --worlds generated_worlds_margin2 --out worlds_margin2.html

Open the .html in a browser (from WSL: explorer.exe worlds.html).
"""
import argparse
import base64
import json
import os


def load(folder, resource, file_name):
    with open(os.path.join(folder, resource, file_name)) as f:
        return json.load(f)


def parse_cell(text):
    return [int(v) for v in text.split(",")]


def visibility_bits(visibility, n):
    bits = bytearray((n * n + 7) // 8)
    for i, row in enumerate(visibility):
        for j in row:
            k = i * n + j
            bits[k >> 3] |= 1 << (k & 7)
    return base64.b64encode(bytes(bits)).decode()


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>World browser</title>
<style>
  :root { --bg:#f6f5f2; --panel:#fff; --ink:#1d1d1b; --muted:#6b6a66; --free:#e9e7e1; --occluded:#3a3a38;
          --seen:#fbe7a6; --poi:#8a8780; --prey:#2f8f4e; --predator:#c8402f; --spawn:#f2b8ad; --option:#3b6fb6;
          --line:#d6d3cc; --select:#1d1d1b; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#161615; --panel:#1f1f1d; --ink:#ecebe7; --muted:#9a988f; --free:#34332f; --occluded:#0b0b0a;
            --seen:#6b5a1e; --poi:#8d8a80; --prey:#4cc274; --predator:#ee6450; --spawn:#6e3a32; --option:#7fa8e6;
            --line:#3a3935; --select:#ecebe7; }
  }
  body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.4 system-ui, sans-serif; }
  main { max-width:1000px; margin:0 auto; padding:20px 16px; }
  h1 { font-size:18px; margin:0; }
  .top { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:10px; }
  .top h1 { margin-right:auto; }
  button, select, input { font:inherit; padding:4px 10px; border-radius:6px; border:1px solid var(--line); background:var(--panel); color:var(--ink); }
  button { cursor:pointer; }
  input[type=number] { width:4em; }
  .layout { display:grid; grid-template-columns: minmax(0, 1fr) 260px; gap:14px; }
  @media (max-width: 760px) { .layout { grid-template-columns: 1fr; } }
  svg.map { width:100%; height:auto; background:var(--panel); border:1px solid var(--line); border-radius:8px; display:block; }
  .side { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; }
  .side h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:14px 0 6px; }
  .side h2:first-child { margin-top:0; }
  .stats { display:grid; grid-template-columns:auto 1fr; gap:2px 10px; font-variant-numeric:tabular-nums; }
  .stats dt { color:var(--muted); } .stats dd { margin:0; }
  label { display:block; color:var(--muted); margin:4px 0; user-select:none; }
  .swatch { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:-1px; background:var(--c); }
  .hint { color:var(--muted); font-size:12px; margin-top:10px; }
  svg.strip { width:100%; height:auto; margin-top:12px; background:var(--panel); border:1px solid var(--line); border-radius:8px; display:block; }
  #hover { color:var(--muted); font-variant-numeric:tabular-nums; min-height:1.4em; margin-top:6px; }
</style></head>
<body><main>
  <div class="top">
    <h1 id="title"></h1>
    <button id="prev">◀ prev</button>
    <select id="pick"></select>
    <button id="next">next ▶</button>
  </div>
  <div class="layout">
    <div>
      <svg class="map" id="map"></svg>
      <div id="hover"></div>
      <svg class="strip" id="strip"></svg>
    </div>
    <div class="side">
      <h2>World</h2>
      <dl class="stats" id="stats"></dl>
      <h2>Show</h2>
      <label><input type="checkbox" id="showSeen" checked> <span class="swatch" style="--c:var(--seen)"></span>visible from selected cell</label>
      <label><input type="checkbox" id="showOptions" checked> <span class="swatch" style="--c:var(--option)"></span>options from selected cell</label>
      <label><input type="checkbox" id="showPois" checked> <span class="swatch" style="--c:var(--poi)"></span>POIs</label>
      <label><input type="checkbox" id="showSpawn" checked> <span class="swatch" style="--c:var(--spawn)"></span>predator spawn cells</label>
      <label>spawn radius <input type="number" id="radius" min="1" max="40"></label>
      <div class="hint">Click a cell to select it (default: prey start). Hover for coordinates.
        ←/→ change world. Spawn cells follow the simulation: free, hidden from the prey start, within the
        radius of the predator location (or the closest hidden cells if none are).</div>
    </div>
  </div>
</main>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const n = D.cells.length;
const key = (x, y) => x + "," + y;
const index = new Map(D.coordinates.map((c, i) => [key(c[0], c[1]), i]));
const neighbours = D.coordinates.map(c => D.pattern.map(p => index.get(key(c[0] + p[0], c[1] + p[1]))).filter(i => i !== undefined));
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };

// ---- map
const svg = document.getElementById("map");
const R = D.radius, pad = R * 1.5;
const xs = D.cells.map(c => c[0]), ys = D.cells.map(c => c[1]);
const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad, minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
svg.setAttribute("viewBox", `${minX} ${-maxY} ${maxX - minX} ${maxY - minY}`);
const P = i => [D.cells[i][0], -D.cells[i][1]];
const hexes = D.cells.map((c, i) => {
  const [cx, cy] = P(i);
  const pts = [...Array(6).keys()].map(k => { const t = k * Math.PI / 3; return `${cx + R * Math.sin(t)},${cy - R * Math.cos(t)}`; }).join(" ");
  const h = el("polygon", { points: pts, stroke: "var(--panel)", "stroke-width": R * 0.12, style: "cursor:pointer" }, svg);
  h.addEventListener("click", () => { selected = i; draw(); });
  h.addEventListener("mouseenter", () => hoverInfo(i));
  return h;
});
const optionLayer = el("g", {}, svg);
const poiLayer = el("g", {}, svg);
const marks = el("g", {}, svg);
const ring = el("polygon", { fill: "none", stroke: "var(--select)", "stroke-width": R * 0.22 }, svg);
const mark = (i, color, label) => {
  const [x, y] = P(i);
  el("circle", { cx: x, cy: y, r: R * 0.55, fill: color, stroke: "var(--panel)", "stroke-width": R * 0.1 }, marks);
  const t = el("text", { x, y: y + R * 0.28, "text-anchor": "middle", "font-size": R * 0.8, fill: "#fff", "font-weight": 700 }, marks);
  t.textContent = label;
};

// ---- per-world state
let w = 0, selected = index.get(key(...D.start)), world, occluded, visible;
const decode = b64 => Uint8Array.from(atob(b64), c => c.charCodeAt(0));
const sees = (i, j) => { const k = i * n + j; return (visible[k >> 3] >> (k & 7)) & 1; };

function load(k) {
  w = (k + D.worlds.length) % D.worlds.length;
  world = D.worlds[w];
  occluded = new Uint8Array(n); world.occlusions.forEach(i => occluded[i] = 1);
  visible = decode(world.visibility);
  if (occluded[selected]) selected = index.get(key(...D.start));
  document.getElementById("pick").value = w;
  draw();
}

function spawnCells(radius) {
  const center = index.get(key(...D.predator)), start = index.get(key(...D.start));
  const dist = new Int32Array(n).fill(-1);
  if (occluded[center]) return [];
  dist[center] = 0; const queue = [center];
  for (let q = 0; q < queue.length; q++) for (const j of neighbours[queue[q]])
    if (!occluded[j] && dist[j] < 0) { dist[j] = dist[queue[q]] + 1; queue.push(j); }
  const hidden = [...Array(n).keys()].filter(i => dist[i] > 0 && !sees(start, i));
  if (!hidden.length) return [];
  const r = Math.max(radius, Math.min(...hidden.map(i => dist[i])));
  return hidden.filter(i => dist[i] <= r);
}

function draw() {
  const spawn = new Set(document.getElementById("showSpawn").checked ? spawnCells(+document.getElementById("radius").value) : []);
  const seenOn = document.getElementById("showSeen").checked;
  hexes.forEach((h, i) => h.setAttribute("fill",
    occluded[i] ? "var(--occluded)" : seenOn && sees(selected, i) ? "var(--seen)" : spawn.has(i) ? "var(--spawn)" : "var(--free)"));
  const [sx, sy] = P(selected);
  ring.setAttribute("points", [...Array(6).keys()].map(k => { const t = k * Math.PI / 3; return `${sx + R * Math.sin(t)},${sy - R * Math.cos(t)}`; }).join(" "));

  optionLayer.replaceChildren();
  if (document.getElementById("showOptions").checked)
    for (const j of world.options[selected] || []) if (j !== selected) {
      const [x, y] = P(j);
      el("line", { x1: sx, y1: sy, x2: x, y2: y, stroke: "var(--option)", "stroke-width": R * 0.12, opacity: .7 }, optionLayer);
    }
  poiLayer.replaceChildren();
  if (document.getElementById("showPois").checked)
    world.pois.forEach(i => { const [x, y] = P(i); el("circle", { cx: x, cy: y, r: R * 0.22, fill: "var(--poi)" }, poiLayer); });
  marks.replaceChildren();
  mark(index.get(key(...D.start)), "var(--prey)", "S");
  mark(index.get(key(...D.goal)), "var(--prey)", "G");
  if (!occluded[index.get(key(...D.predator))]) mark(index.get(key(...D.predator)), "var(--predator)", "P");

  document.getElementById("title").textContent = world.name;
  const stats = [
    ["level", world.level], ["replicate", world.replicate],
    ["lacunarity", world.lacunarity.toFixed(2)],
    ...Object.entries(world.per_radius).map(([r, v]) => [`  radius ${r}`, v.toFixed(2)]),
    ["entropy", D.entropy.toFixed(3)], ["occlusions", world.occlusions.length],
    ["POIs", world.pois.length], ["visual-degree entropy", world.visual_entropy.toFixed(2)],
    ["spawn cells", spawn.size || (document.getElementById("showSpawn").checked ? "none hidden" : "-")],
  ];
  document.getElementById("stats").innerHTML = stats.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  stripDots.forEach((d, k) => { d.setAttribute("r", k === w ? 5 : 3); d.setAttribute("fill", k === w ? "var(--predator)" : "var(--muted)"); });
  hoverInfo(selected);
}

function hoverInfo(i) {
  const c = D.coordinates[i];
  document.getElementById("hover").textContent =
    `cell ${i} (${c[0]}, ${c[1]})` + (occluded[i] ? " · occluded" : ` · sees ${[...Array(n).keys()].filter(j => sees(i, j)).length} cells`) +
    (world.pois.includes(i) ? " · POI" : "");
}

// ---- strip of all worlds by lacunarity
const strip = document.getElementById("strip");
const lac = D.worlds.map(x => Math.log(x.lacunarity)), lo = Math.min(...lac), hi = Math.max(...lac);
const reps = Math.max(...D.worlds.map(x => x.replicate)) + 1;
const SW = 600, SH = 30 + reps * 9;
strip.setAttribute("viewBox", `0 0 ${SW} ${SH}`);
el("text", { x: 10, y: 14, "font-size": 11, fill: "var(--muted)" }, strip).textContent = "all worlds by lacunarity (click to open)";
const sx = v => 20 + (SW - 40) * (hi > lo ? (v - lo) / (hi - lo) : .5);
el("text", { x: 20, y: SH - 4, "font-size": 10, fill: "var(--muted)" }, strip).textContent = Math.exp(lo).toFixed(2);
el("text", { x: SW - 20, y: SH - 4, "font-size": 10, fill: "var(--muted)", "text-anchor": "end" }, strip).textContent = Math.exp(hi).toFixed(2);
const stripDots = D.worlds.map((x, k) => {
  const d = el("circle", { cx: sx(lac[k]), cy: 24 + x.replicate * 9, r: 3, style: "cursor:pointer" }, strip);
  el("title", {}, d).textContent = `${x.name} · lacunarity ${x.lacunarity.toFixed(2)}`;
  d.addEventListener("click", () => load(k));
  return d;
});

// ---- controls
const pick = document.getElementById("pick");
D.worlds.forEach((x, k) => { const o = document.createElement("option"); o.value = k; o.textContent = `${x.name} (${x.lacunarity.toFixed(2)})`; pick.appendChild(o); });
pick.onchange = () => load(+pick.value);
document.getElementById("prev").onclick = () => load(w - 1);
document.getElementById("next").onclick = () => load(w + 1);
document.getElementById("radius").value = D.spawn_radius;
for (const id of ["showSeen", "showOptions", "showPois", "showSpawn", "radius"]) document.getElementById(id).oninput = draw;
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
    parser.add_argument("--worlds", default="generated_worlds_100", help="generator output folder (with manifest.json)")
    parser.add_argument("--start", default="-20,0", help="prey start (default matches run.cpp)")
    parser.add_argument("--goal", default="20,0")
    parser.add_argument("--predator", default="20,0", help="predator_location in run.cpp")
    parser.add_argument("--radius", type=int, default=5, help="predator_spawn_radius in run.cpp")
    parser.add_argument("--out", default="worlds.html")
    args = parser.parse_args()

    with open(os.path.join(args.worlds, "manifest.json")) as f:
        manifest = json.load(f)
    configuration = manifest["world_configuration"]
    config = load(args.worlds, "world_configuration", configuration)
    impl = load(args.worlds, "world_implementation", f"{configuration}.{manifest['world_implementation']}")
    if "z" in config["cell_coordinates"][0]:
        raise SystemExit("this browser draws 2D (hexagonal) worlds only")
    n = len(config["cell_coordinates"])
    data = {
        "cells": [[l["x"], l["y"]] for l in impl["cell_locations"]],
        "coordinates": [[c["x"], c["y"]] for c in config["cell_coordinates"]],
        "pattern": [[c["x"], c["y"]] for c in config["connection_pattern"]],
        "radius": impl["cell_transformation"]["size"] / 2,
        "entropy": manifest["entropy"],
        "start": parse_cell(args.start), "goal": parse_cell(args.goal), "predator": parse_cell(args.predator),
        "spawn_radius": args.radius,
        "worlds": [],
    }
    for w in sorted(manifest["worlds"], key=lambda w: (w["level"], w["replicate"])):
        name = w["occlusions"]
        data["worlds"].append({
            "name": name, "level": w["level"], "replicate": w["replicate"],
            "lacunarity": w["lacunarity"], "per_radius": w["lacunarity_per_radius"],
            "visual_entropy": w["visual_degree_entropy"],
            "occlusions": load(args.worlds, "cell_group", f"{configuration}.{name}.occlusions"),
            "pois": load(args.worlds, "cell_group", f"{configuration}.{name}.lppo"),
            "options": load(args.worlds, "graph", f"{configuration}.{name}.options"),
            "visibility": visibility_bits(load(args.worlds, "graph", f"{configuration}.{name}.cell_visibility"), n),
        })
    with open(args.out, "w") as f:
        f.write(PAGE.replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    print(f"wrote {args.out}  ({len(data['worlds'])} worlds, {os.path.getsize(args.out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
