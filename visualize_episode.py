"""Writes an HTML player for one simulation episode: the world, the prey and predator moving step by step,
their trails, and the cells the prey can see.

    .venv/bin/python visualize_episode.py                      # first successful episode in the results
    .venv/bin/python visualize_episode.py --list               # list successful episodes
    .venv/bin/python visualize_episode.py cellworld_simulation/build/lac00_05_r01_seed_18.json

Open the .html it writes in a browser (from WSL: explorer.exe episode.html).
"""
import argparse
import glob
import json
import os
import re

RESULT_NAME = re.compile(r"(?P<world>.+)_seed_(?P<seed>\d+)\.json$")


def load(folders, resource, file_name):
    for folder in folders:
        path = os.path.join(folder, resource, file_name)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    raise SystemExit(f"{resource}/{file_name} not found in {folders}")


def successful_episodes(results_folder):
    episodes = []
    for path in sorted(glob.glob(os.path.join(results_folder, "*_seed_*.json"))):
        with open(path) as f:
            episode = json.load(f)
        if episode["result"] == 1:
            episodes.append((path, episode["iterations"]))
    return episodes


def episode_data(path, folders, configuration="hexagonal", implementation="canonical"):
    world = RESULT_NAME.match(os.path.basename(path))["world"]
    with open(path) as f:
        episode = json.load(f)
    config = load(folders, "world_configuration", configuration)
    impl = load(folders, "world_implementation", f"{configuration}.{implementation}")
    occlusions = set(load(folders, "cell_group", f"{configuration}.{world}.occlusions"))
    pois = set(load(folders, "cell_group", f"{configuration}.{world}.lppo"))
    visibility = load(folders, "graph", f"{configuration}.{world}.cell_visibility")
    index = {(c["x"], c["y"]): i for i, c in enumerate(config["cell_coordinates"])}
    radius = impl["cell_transformation"]["size"] / 2
    cells = [{"x": l["x"], "y": l["y"], "occluded": i in occlusions, "poi": i in pois}
             for i, l in enumerate(impl["cell_locations"])]
    steps = [{"iteration": s["iteration"],
              "prey": index[(s["prey"]["x"], s["prey"]["y"])],
              "predator": index[(s["predator"]["x"], s["predator"]["y"])]} for s in episode["steps"]]
    lacunarity = None
    for folder in folders:
        manifest = os.path.join(folder, "manifest.json")
        if os.path.exists(manifest):
            with open(manifest) as f:
                lacunarity = next((w["lacunarity"] for w in json.load(f)["worlds"] if w["occlusions"] == world), None)
    return {"name": os.path.basename(path)[:-5], "world": world, "lacunarity": lacunarity,
            "result": episode["result"], "iterations": episode["iterations"], "radius": radius,
            "cells": cells, "visibility": visibility, "steps": steps}


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
  :root { --bg:#f6f5f2; --panel:#fff; --ink:#1d1d1b; --muted:#6b6a66; --free:#e9e7e1; --occluded:#3a3a38;
          --seen:#fbe7a6; --poi:#8a8780; --prey:#2f8f4e; --predator:#c8402f; --line:#d6d3cc; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#161615; --panel:#1f1f1d; --ink:#ecebe7; --muted:#9a988f; --free:#34332f; --occluded:#0b0b0a;
            --seen:#6b5a1e; --poi:#8d8a80; --prey:#4cc274; --predator:#ee6450; --line:#3a3935; }
  }
  body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.4 system-ui, sans-serif; }
  main { max-width:900px; margin:0 auto; padding:20px 16px; }
  h1 { font-size:18px; margin:0 0 2px; }
  .sub { color:var(--muted); margin-bottom:12px; }
  svg { width:100%; height:auto; background:var(--panel); border:1px solid var(--line); border-radius:8px; display:block; }
  .controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:12px 0 6px; }
  button { font:inherit; padding:5px 12px; border-radius:6px; border:1px solid var(--line); background:var(--panel); color:var(--ink); cursor:pointer; }
  input[type=range] { flex:1; min-width:160px; }
  .status { display:flex; flex-wrap:wrap; gap:16px; color:var(--muted); font-variant-numeric:tabular-nums; }
  .status b { color:var(--ink); font-weight:600; }
  .legend { display:flex; flex-wrap:wrap; gap:14px; color:var(--muted); margin-top:8px; font-size:13px; }
  .legend span::before { content:""; display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:5px; vertical-align:-1px; background:var(--c); }
  label { color:var(--muted); user-select:none; }
</style></head>
<body><main>
  <h1 id="title"></h1>
  <div class="sub" id="subtitle"></div>
  <svg id="map"></svg>
  <div class="controls">
    <button id="play">Play</button>
    <button id="back">◀</button><button id="next">▶</button>
    <input id="slider" type="range" min="0" value="0">
    <label>speed <select id="speed"><option value="600">slow</option><option value="250" selected>normal</option><option value="80">fast</option></select></label>
  </div>
  <div class="status" id="status"></div>
  <div class="legend">
    <span style="--c:var(--prey)">prey</span><span style="--c:var(--predator)">predator</span>
    <span style="--c:var(--seen)">visible to prey</span><span style="--c:var(--occluded)">occlusion</span>
    <span style="--c:var(--poi)">POI</span>
    <label><input type="checkbox" id="showSeen" checked> prey's view</label>
    <label><input type="checkbox" id="showTrails" checked> trails</label>
  </div>
</main>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const svg = document.getElementById("map");
const pad = D.radius * 1.5;
const xs = D.cells.map(c => c.x), ys = D.cells.map(c => c.y);
const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad, minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
svg.setAttribute("viewBox", `${minX} ${-maxY} ${maxX - minX} ${maxY - minY}`);  // y up
const P = i => [D.cells[i].x, -D.cells[i].y];
const el = (tag, attrs, parent = svg) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };

const hexes = D.cells.map((c, i) => {
  const [cx, cy] = P(i);
  const pts = [...Array(6).keys()].map(k => { const t = k * Math.PI / 3; return `${cx + D.radius * Math.sin(t)},${cy - D.radius * Math.cos(t)}`; }).join(" ");
  return el("polygon", { points: pts, fill: c.occluded ? "var(--occluded)" : "var(--free)", stroke: "var(--panel)", "stroke-width": D.radius * 0.12 });
});
D.cells.forEach((c, i) => { if (c.poi) { const [x, y] = P(i); el("circle", { cx: x, cy: y, r: D.radius * 0.18, fill: "var(--poi)" }); } });
const preyTrail = el("polyline", { fill: "none", stroke: "var(--prey)", "stroke-width": D.radius * 0.25, "stroke-linejoin": "round", opacity: 0.55 });
const predTrail = el("polyline", { fill: "none", stroke: "var(--predator)", "stroke-width": D.radius * 0.25, "stroke-linejoin": "round", opacity: 0.55 });
const sight = el("line", { stroke: "var(--predator)", "stroke-width": D.radius * 0.12, "stroke-dasharray": `${D.radius * 0.4} ${D.radius * 0.3}` });
const prey = el("circle", { r: D.radius * 0.62, fill: "var(--prey)", stroke: "var(--panel)", "stroke-width": D.radius * 0.12 });
const pred = el("circle", { r: D.radius * 0.62, fill: "var(--predator)", stroke: "var(--panel)", "stroke-width": D.radius * 0.12 });

document.getElementById("title").textContent = D.name;
document.getElementById("subtitle").textContent =
  `world ${D.world}` + (D.lacunarity ? ` · lacunarity ${D.lacunarity.toFixed(2)}` : "") +
  ` · ${D.result ? "prey reached the goal" : "prey was caught"} after ${D.iterations} iterations`;

const slider = document.getElementById("slider"), status = document.getElementById("status");
const showSeen = document.getElementById("showSeen"), showTrails = document.getElementById("showTrails");
slider.max = D.steps.length - 1;
let t = 0, timer = null;

function draw() {
  const s = D.steps[t];
  const seen = new Set(showSeen.checked ? D.visibility[s.prey] : []);
  hexes.forEach((h, i) => h.setAttribute("fill", D.cells[i].occluded ? "var(--occluded)" : seen.has(i) ? "var(--seen)" : "var(--free)"));
  const trail = key => D.steps.slice(0, t + 1).map(x => P(x[key]).join(",")).join(" ");
  preyTrail.setAttribute("points", showTrails.checked ? trail("prey") : "");
  predTrail.setAttribute("points", showTrails.checked ? trail("predator") : "");
  const [ax, ay] = P(s.prey), [bx, by] = P(s.predator);
  prey.setAttribute("cx", ax); prey.setAttribute("cy", ay);
  pred.setAttribute("cx", bx); pred.setAttribute("cy", by);
  const contact = D.visibility[s.prey].includes(s.predator);
  sight.setAttribute("x1", ax); sight.setAttribute("y1", ay); sight.setAttribute("x2", bx); sight.setAttribute("y2", by);
  sight.style.display = contact ? "" : "none";
  const mover = t === 0 ? "start" : (D.steps[t - 1].prey !== s.prey ? "prey moved" : D.steps[t - 1].predator !== s.predator ? "predator moved" : "no move");
  status.innerHTML = `<span>step <b>${t}</b> / ${D.steps.length - 1}</span><span>iteration <b>${s.iteration}</b></span>` +
    `<span><b>${mover}</b></span><span>${contact ? "<b>predator in view</b>" : "predator hidden"}</span>`;
  slider.value = t;
}
function go(n) { t = Math.max(0, Math.min(D.steps.length - 1, n)); draw(); }
function stop() { clearInterval(timer); timer = null; document.getElementById("play").textContent = "Play"; }
document.getElementById("play").onclick = () => {
  if (timer) return stop();
  if (t === D.steps.length - 1) t = 0;
  document.getElementById("play").textContent = "Pause";
  timer = setInterval(() => { if (t >= D.steps.length - 1) return stop(); go(t + 1); }, +document.getElementById("speed").value);
};
document.getElementById("speed").onchange = () => { if (timer) { stop(); document.getElementById("play").click(); } };
document.getElementById("back").onclick = () => { stop(); go(t - 1); };
document.getElementById("next").onclick = () => { stop(); go(t + 1); };
slider.oninput = () => { stop(); go(+slider.value); };
showSeen.onchange = draw; showTrails.onchange = draw;
document.addEventListener("keydown", e => {
  if (e.key === "ArrowRight") { stop(); go(t + 1); }
  if (e.key === "ArrowLeft") { stop(); go(t - 1); }
  if (e.key === " ") { e.preventDefault(); document.getElementById("play").click(); }
});
draw();
</script></body></html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("episode", nargs="?", help="result .json file (default: first successful episode)")
    parser.add_argument("--results", default="cellworld_simulation/build", help="folder with the result .json files")
    parser.add_argument("--worlds", nargs="+", default=["generated_worlds_100", "cellworld_simulation/build/.cellworld_cache"],
                        help="folders holding the world files, searched in order")
    parser.add_argument("--list", action="store_true", help="list successful episodes and exit")
    parser.add_argument("--out", help="output .html (default: <episode name>.html)")
    args = parser.parse_args()

    if args.list or not args.episode:
        episodes = successful_episodes(args.results)
        if args.list:
            for path, iterations in episodes:
                print(f"{path}  ({iterations} iterations)")
            print(f"{len(episodes)} successful episodes")
            return
        if not episodes:
            raise SystemExit(f"no successful episodes in {args.results}")
        args.episode = episodes[0][0]

    data = episode_data(args.episode, args.worlds)
    out = args.out or data["name"] + ".html"
    with open(out, "w") as f:
        f.write(PAGE.replace("__TITLE__", data["name"]).replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    print(f"wrote {out}  ({data['name']}, {len(data['steps'])} steps)")


if __name__ == "__main__":
    main()
