"""Plots prey survival against each world's lacunarity and entropy.

Lacunarity and entropy are computed from each world's occlusions with the generator's definitions
(env_generator.metrics: gliding-box lacunarity, geometric mean over the box radii, and cellworld's binary
occupancy entropy), so the values are comparable with the generated worlds' manifests. A world's survival
is the fraction of its episodes (<world>_seed_<n>.json) in which the prey reached the goal.

The entropy panel uses the entropy level in the world name (the 05 in 21_05 or ent04_05_r00, i.e. entropy
x10). The measured entropy is in the CSV: past half the cells occluded it falls again, so the densest
published level (10, 170-253 of 331 cells occluded) measures 0.79-1.00 rather than 1.0.

    .venv/bin/python plot_survival_worlds.py
    .venv/bin/python plot_survival_worlds.py --worlds generated_worlds_cube16_corners \\
        --results cellworld_simulation/results_cube16_corners --out survival_cube16_corners.png

Writes the figure and, next to it, a CSV of every world's statistics (the figure's table view).
"""
import argparse
import csv
import json
import os
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.ticker import FixedLocator, NullLocator, PercentFormatter
from scipy.stats import spearmanr

from env_generator.lattice import Lattice
from env_generator.metrics import Lacunarity, occupancy_entropy
from plot_survival import load_survival

# chart chrome, the accent, and the sequential blue ramp (steps 250..700) for entropy levels 1..10
SURFACE, INK, INK_SECONDARY, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
ACCENT = "#2a78d6"
RAMP = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
LEVEL = re.compile(r"(\d\d)(?:_r\d+)?$")  # the entropy level: 21_05 -> 5, ent03_04_r00 -> 4


def load_lattice(worlds):
    """The lattice of the world configuration in the folder, and the generator's default box radii for it."""
    configuration = os.listdir(os.path.join(worlds, "world_configuration"))[0]
    if configuration == "hexagonal":
        return Lattice.hexagonal(worlds), [1, 2, 3]
    cubic = re.fullmatch(r"cubic(\d+)n(\d+)", configuration)
    if cubic:
        return Lattice.cubic(int(cubic[1]), int(cubic[2])), [1, 2]
    raise SystemExit(f"unknown world configuration {configuration} in {worlds}/world_configuration")


def world_statistics(worlds, lattice, lacunarity, name):
    with open(os.path.join(worlds, "cell_group", f"{lattice.configuration_name}.{name}.occlusions")) as f:
        occlusions = json.load(f)
    occluded = np.zeros(lattice.n, dtype=bool)
    occluded[occlusions] = True
    per_radius = lacunarity.per_radius(occluded)  # nan without occlusions: E[D] is 0
    return {"occluded": len(occlusions), "entropy": occupancy_entropy(len(occlusions), lattice.n),
            "lacunarity": float(np.exp(np.mean(np.log(per_radius)))),
            **{f"lacunarity_r{r}": v for r, v in zip(lacunarity.radii, per_radius)}}


def style(axes):
    axes.set_facecolor(SURFACE)
    axes.grid(True, color=GRID, linewidth=0.8)
    axes.set_axisbelow(True)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(AXIS)
    axes.tick_params(length=0, labelcolor=INK_SECONDARY, labelsize=9)
    axes.yaxis.set_major_formatter(PercentFormatter(1.0))
    axes.set_ylim(-0.03, 1.03)


def signed(value):
    return f"{value:.2f}".replace("-", "−")


def heading(axes, title, subtitle):
    axes.annotate(title, xy=(0, 1), xycoords="axes fraction", xytext=(0, 24), textcoords="offset points",
                  fontsize=12, fontweight="bold", color=INK)
    axes.annotate(subtitle, xy=(0, 1), xycoords="axes fraction", xytext=(0, 9), textcoords="offset points",
                  fontsize=9, color=INK_SECONDARY)


def world_rows(worlds, results_folder):
    """One row per world with results: its entropy level, statistics and survival. Also the box radii used."""
    lattice, radii = load_lattice(worlds)
    survival = load_survival(results_folder)
    prefix, suffix = f"{lattice.configuration_name}.", ".occlusions"
    in_folder = sorted(f[len(prefix):-len(suffix)] for f in os.listdir(os.path.join(worlds, "cell_group"))
                       if f.startswith(prefix) and f.endswith(suffix))
    names = [n for n in in_folder if n in survival]
    if not names:
        raise SystemExit(f"no result files in {results_folder} match worlds in {worlds}")
    without = [n for n in in_folder if n not in survival]
    if without:
        print(f"{len(without)} worlds have no results: {' '.join(without)}")

    lacunarity_of = Lacunarity(lattice, radii)
    rows = []
    for name in names:
        results = survival[name]
        rows.append({"world": name, "entropy_level": int(LEVEL.search(name)[1]),
                     **world_statistics(worlds, lattice, lacunarity_of, name),
                     "episodes": len(results), "survived": int(sum(results)), "survival": float(np.mean(results))})
    return rows, radii


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worlds", default="published_worlds", help="world folder (cellworld cache layout)")
    parser.add_argument("--results", default="cellworld_simulation/results_published",
                        help="folder with the <world>_seed_<n>.json result files")
    parser.add_argument("--out", default="survival_published_worlds.png")
    args = parser.parse_args()

    rows, radii = world_rows(args.worlds, args.results)
    csv_path = os.path.splitext(args.out)[0] + ".csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    level = np.array([r["entropy_level"] for r in rows])
    lacunarity = np.array([r["lacunarity"] for r in rows])
    rate = np.array([r["survival"] for r in rows])
    episodes = np.array([r["episodes"] for r in rows])
    finite = np.isfinite(lacunarity)

    # lacunarity falls as occlusions get denser, so check it within each entropy level as well as overall
    overall = spearmanr(lacunarity[finite], rate[finite]).statistic
    print(f"{'level':>5} {'worlds':>6} {'lacunarity':>16} {'survival':>8} {'sem':>6} {'rho(lac, surv)':>15}")
    levels, within = sorted(set(level)), []
    means, sems = [], []
    for l in levels:
        at = level == l
        means.append(rate[at].mean())
        sems.append(rate[at].std(ddof=1) / np.sqrt(at.sum()) if at.sum() > 1 else 0.0)
        lac = lacunarity[at & finite]
        rho = float("nan")
        if len(lac) >= 4 and np.ptp(rate[at & finite]) > 0:
            rho = spearmanr(lac, rate[at & finite]).statistic
            within.append(rho)
        span = f"{lac.min():.2f}..{lac.max():.2f}" if len(lac) else "undefined"
        print(f"{l:5d} {at.sum():6d} {span:>16} {means[-1]:8.3f} {sems[-1]:6.3f} {rho:15.2f}")
    print(f"Spearman rho(lacunarity, survival): {overall:.2f} over {finite.sum()} worlds, "
          f"median {np.median(within):.2f} within entropy levels")

    figure, (left, right) = plt.subplots(1, 2, figsize=(11.5, 5.2), sharey=True, facecolor=SURFACE)
    figure.subplots_adjust(left=0.065, right=0.985, top=0.84, bottom=0.25, wspace=0.12)
    for axes in (left, right):
        style(axes)

    cmap = ListedColormap(RAMP)
    norm = BoundaryNorm(np.arange(0.5, len(RAMP) + 1), cmap.N)
    dots = left.scatter(lacunarity[finite], rate[finite], c=np.clip(level[finite], 1, len(RAMP)), cmap=cmap,
                        norm=norm, s=40, edgecolors=SURFACE, linewidths=1, zorder=2)
    left.set_xscale("log")
    low, high = lacunarity[finite].min(), lacunarity[finite].max()
    left.xaxis.set_major_locator(FixedLocator([t for t in (1, 1.5, 2, 3, 5, 10, 20, 50, 100, 200)
                                               if low / 1.2 <= t <= high * 1.2]))
    left.xaxis.set_major_formatter(lambda t, _: f"{t:g}")
    left.xaxis.set_minor_locator(NullLocator())
    left.set_xlabel(f"lacunarity (gliding box, radii {', '.join(map(str, radii))}; log scale)",
                    color=INK_SECONDARY, fontsize=9)
    left.set_ylabel("survival rate", color=INK_SECONDARY, fontsize=9)
    heading(left, "Survival vs lacunarity",
            f"{finite.sum()} worlds · Spearman ρ {signed(overall)} overall, "
            f"median {signed(np.median(within))} within an entropy level")
    bar = figure.colorbar(dots, ax=left, ticks=range(1, len(RAMP) + 1), pad=0.015, fraction=0.04, aspect=30)
    bar.set_ticklabels([f"{t / 10:.1f}" for t in range(1, len(RAMP) + 1)])
    bar.ax.tick_params(length=0, labelcolor=INK_SECONDARY, labelsize=8)
    bar.outline.set_visible(False)
    bar.set_label("entropy level", color=INK_SECONDARY, fontsize=9)

    jitter = np.random.default_rng(0).uniform(-0.012, 0.012, len(rows))
    right.scatter(level / 10 + jitter, rate, s=22, color=MUTED, alpha=0.55, linewidths=0, zorder=1,
                  label="one world")
    right.errorbar(np.array(levels) / 10, means, yerr=sems, color=ACCENT, linewidth=2, marker="o", markersize=6,
                   markeredgecolor=SURFACE, markeredgewidth=1.2, elinewidth=1.5, capsize=0, zorder=3,
                   solid_capstyle="round", label="mean ± SEM over worlds")
    right.set_xticks(np.array(levels) / 10, [f"{l / 10:.1f}" for l in levels])
    right.grid(False, axis="x")  # the levels are labelled; vertical lines would run through the error bars
    right.set_xlabel("entropy level (from the world name)", color=INK_SECONDARY, fontsize=9)
    right.legend(frameon=False, loc="upper right", fontsize=9, labelcolor=INK_SECONDARY)
    heading(right, "Survival vs entropy", f"{len(rows)} worlds, {len(levels)} entropy levels")

    excluded = (~finite).sum()
    notes = [f"Each dot is one world: the share of its {episodes.min()}"
             + (f"–{episodes.max()}" if episodes.max() != episodes.min() else "")
             + f" episodes in which the prey reached the goal, so single worlds are noisy "
             f"(±{np.sqrt(0.25 / np.median(episodes)):.2f} at 50%)."]
    if excluded:
        notes.append(f"Lacunarity is undefined without occlusions, so the {excluded} empty worlds are only on the right.")
    notes.append(f"Results: {args.results}")
    figure.text(0.065, 0.03, "\n".join(notes), fontsize=8, color=MUTED, linespacing=1.5)
    figure.savefig(args.out, dpi=150, facecolor=SURFACE)
    print(f"saved {args.out} and {csv_path}")


if __name__ == "__main__":
    main()
