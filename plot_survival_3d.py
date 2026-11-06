"""Writes an interactive 3D scatter of prey survival against entropy level and lacunarity: one point per world.

Drag to rotate, scroll to zoom, hover a point for its world and values, click a legend entry to hide it.
The orange line joins the mean of each entropy level. Worlds without occlusions have no lacunarity, so they
are left out of the plot (they are in the table below it). Statistics come from plot_survival_worlds.

    .venv/bin/python plot_survival_3d.py
    explorer.exe survival_3d.html

The page loads plotly.js from cdnjs, so it needs an internet connection.
"""
import argparse
import html
import json
import math

import numpy as np

from plot_survival_worlds import world_rows

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Survival in 3D</title>
<style>
  :root { color-scheme: light; --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
          --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10); --mean:#eb6834; }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) { color-scheme: dark; --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff;
          --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10); --mean:#d95926; }
  }
  :root[data-theme="dark"] { color-scheme: dark; --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7;
          --muted:#898781; --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10); --mean:#d95926; }
  body { margin:0; background:var(--page); color:var(--ink); font:14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width:1100px; margin:0 auto; padding:20px 16px 32px; }
  h1 { font-size:18px; margin:0 0 4px; }
  .sub { color:var(--ink2); margin:0 0 12px; }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:6px; }
  #plot { width:100%; height:min(76vh, 720px); }
  .note { color:var(--muted); font-size:12px; margin:8px 2px 0; }
  details { margin-top:16px; }
  summary { cursor:pointer; color:var(--ink2); }
  .table { overflow-x:auto; margin-top:8px; }
  table { border-collapse:collapse; width:100%; font-size:13px; font-variant-numeric:tabular-nums; }
  th, td { text-align:right; padding:3px 10px; border-bottom:1px solid var(--grid); white-space:nowrap; }
  th { color:var(--ink2); font-weight:600; }
  th:first-child, td:first-child { text-align:left; }
</style></head>
<body><main>
<h1>Survival vs entropy and lacunarity</h1>
<p class="sub">__SUBTITLE__</p>
<div class="card"><div id="plot" role="img" aria-label="3D scatter of survival rate against entropy level and lacunarity, one point per world"></div></div>
<p class="note">__NOTE__</p>
<details><summary>Table of all __COUNT__ worlds</summary><div class="table"><table>
<thead><tr><th>world</th><th>entropy level</th><th>occluded cells</th><th>entropy</th><th>lacunarity</th><th>survived</th><th>survival</th></tr></thead>
<tbody>__TABLE__</tbody></table></div></details>
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/plotly.js/4.1.2/plotly-gl3d.min.js"></script>
<script>
const WORLDS = __WORLDS__;
const MEANS = __MEANS__;
const LEVELS = MEANS.x;

function isDark() {
  const theme = document.documentElement.dataset.theme;
  return theme === "dark" || (theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
}

function draw() {
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const [surface, ink2, muted, grid, axis, mean] = ["--surface", "--ink2", "--muted", "--grid", "--axis", "--mean"].map(css);
  // sequential blue for survival: light ends no lighter than step 250, dark ends no darker than step 600
  const ramp = isDark()
    ? [[0, "#184f95"], [0.33, "#2a78d6"], [0.66, "#6da7ec"], [1, "#cde2fb"]]
    : [[0, "#86b6ef"], [0.33, "#3987e5"], [0.66, "#1c5cab"], [1, "#0d366b"]];
  const axisStyle = title => ({
    title: {text: title, font: {color: ink2, size: 12}}, color: ink2, gridcolor: grid, linecolor: axis,
    zerolinecolor: axis, showbackground: true, backgroundcolor: surface, tickfont: {color: ink2, size: 11},
  });
  const worlds = {
    type: "scatter3d", mode: "markers", name: "one world",
    x: WORLDS.x, y: WORLDS.y, z: WORLDS.z, customdata: WORLDS.info,
    marker: {size: 6, color: WORLDS.z, colorscale: ramp, cmin: 0, cmax: 1, opacity: 0.95,
             line: {color: surface, width: 1},
             colorbar: {title: {text: "survival", font: {color: ink2, size: 12}}, tickformat: ".0%",
                        tickfont: {color: ink2, size: 11}, outlinewidth: 0, thickness: 12, len: 0.6, x: 1.0}},
    hovertemplate: "<b>%{customdata[0]}</b><br>entropy level %{x:.1f} (measured %{customdata[1]:.3f})" +
                   "<br>lacunarity %{y:.2f}<br>survival %{z:.0%} (%{customdata[2]})<extra></extra>",
  };
  const means = {
    type: "scatter3d", mode: "lines+markers", name: "entropy level mean",
    x: MEANS.x, y: MEANS.y, z: MEANS.z, customdata: MEANS.n,
    line: {color: mean, width: 5}, marker: {size: 4, color: mean, line: {color: surface, width: 1}},
    hovertemplate: "<b>entropy level %{x:.1f}</b><br>%{customdata} worlds<br>lacunarity %{y:.2f} (geometric mean)" +
                   "<br>survival %{z:.0%} (mean)<extra></extra>",
  };
  const layout = {
    paper_bgcolor: surface, font: {family: 'system-ui, -apple-system, "Segoe UI", sans-serif', color: ink2},
    margin: {l: 0, r: 0, t: 0, b: 0}, showlegend: true,
    legend: {x: 0.01, y: 0.99, bgcolor: "rgba(0,0,0,0)", font: {color: ink2, size: 12}},
    hoverlabel: {bgcolor: surface, bordercolor: axis, font: {color: ink2}},
    scene: {
      xaxis: {...axisStyle("entropy level"), tickvals: LEVELS, range: [LEVELS[0] - 0.05, LEVELS[LEVELS.length - 1] + 0.05]},
      yaxis: {...axisStyle("lacunarity (log)"), type: "log"},
      zaxis: {...axisStyle("survival"), tickformat: ".0%", range: [0, 1]},
      aspectmode: "cube", camera: {eye: {x: 1.55, y: -1.65, z: 0.85}},
    },
  };
  // plotly.js 4 shows a button that uploads the chart data to cloud.plotly.com by default; keep the data local
  Plotly.react("plot", [worlds, means], layout, {responsive: true, displaylogo: false, showSendToCloud: false});
}

if (window.Plotly) {
  draw();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
  new MutationObserver(draw).observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
} else {
  document.getElementById("plot").textContent = "Could not load plotly.js from cdnjs; the table below has every value.";
}
</script>
</body></html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worlds", default="published_worlds", help="world folder (cellworld cache layout)")
    parser.add_argument("--results", default="cellworld_simulation/results_published",
                        help="folder with the <world>_seed_<n>.json result files")
    parser.add_argument("--out", default="survival_3d.html")
    args = parser.parse_args()

    rows, radii = world_rows(args.worlds, args.results)
    plotted = [r for r in rows if math.isfinite(r["lacunarity"])]
    worlds = {"x": [r["entropy_level"] / 10 for r in plotted], "y": [r["lacunarity"] for r in plotted],
              "z": [r["survival"] for r in plotted],
              "info": [[r["world"], r["entropy"], f"{r['survived']}/{r['episodes']}"] for r in plotted]}
    means = {"x": [], "y": [], "z": [], "n": []}
    for level in sorted({r["entropy_level"] for r in plotted}):
        at = [r for r in plotted if r["entropy_level"] == level]
        means["x"].append(level / 10)
        means["y"].append(float(np.exp(np.mean([math.log(r["lacunarity"]) for r in at]))))
        means["z"].append(float(np.mean([r["survival"] for r in at])))
        means["n"].append(len(at))

    episodes = sorted({r["episodes"] for r in rows})
    counts = str(episodes[0]) if len(episodes) == 1 else f"{episodes[0]}–{episodes[-1]}"
    left_out = len(rows) - len(plotted)
    note = (f"Each point is one world: the share of its {counts} episodes in which the prey reached the goal "
            f"(about ±{math.sqrt(0.25 / episodes[0]):.2f} at 50%). "
            f"Lacunarity: gliding box, radii {', '.join(map(str, radii))}, geometric mean. Entropy level is the one "
            f"in the world name.")
    if left_out:
        note += f" {left_out} worlds without occlusions have no lacunarity and are only in the table."
    note += f" Results: {args.results}"
    table = "\n".join(
        f"<tr><td>{html.escape(r['world'])}</td><td>{r['entropy_level'] / 10:.1f}</td><td>{r['occluded']}</td>"
        f"<td>{r['entropy']:.3f}</td><td>{r['lacunarity']:.2f}</td>".replace(">nan<", ">—<")
        + f"<td>{r['survived']}/{r['episodes']}</td><td>{r['survival']:.0%}</td></tr>" for r in rows)
    page = (PAGE.replace("__SUBTITLE__", html.escape(f"{len(plotted)} worlds from {args.worlds}, coloured by survival"))
            .replace("__NOTE__", html.escape(note)).replace("__COUNT__", str(len(rows)))
            .replace("__TABLE__", table).replace("__WORLDS__", json.dumps(worlds)).replace("__MEANS__", json.dumps(means)))
    with open(args.out, "w") as f:
        f.write(page)
    print(f"saved {args.out}: {len(plotted)} worlds plotted, {left_out} without lacunarity left out")


if __name__ == "__main__":
    main()
