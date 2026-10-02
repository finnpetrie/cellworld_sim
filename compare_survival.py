"""Compares prey survival against lacunarity across several world sets (e.g. different margins) on one plot.

Each set is LABEL=RESULTS_FOLDER=MANIFEST. For every set it prints overall survival and tests for a trend
across worlds (Spearman correlation and a linear fit of survival on log lacunarity).

    .venv/bin/python compare_survival.py
    .venv/bin/python compare_survival.py --set "margin 2=cellworld_simulation/results_margin2=generated_worlds_margin2/manifest.json" ...
"""
import argparse
import collections
import json

import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

from plot_survival import load_survival

DEFAULT_SETS = [
    f"{label}=cellworld_simulation/results_margin{m}=generated_worlds_margin{m}/manifest.json"
    for label, m in [("no margin", 0), ("margin 2", 2), ("margin 4", 4)]
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", action="append", dest="sets", metavar="LABEL=RESULTS=MANIFEST")
    parser.add_argument("--out", default="survival_comparison.png")
    args = parser.parse_args()

    figure, axes = plt.subplots(figsize=(7, 4.5))
    print(f"{'set':>10} {'worlds':>6} {'episodes':>8} {'survival':>8} {'lacunarity':>11} {'rho':>6} {'p':>6} {'slope':>6} {'p':>6}")
    for k, entry in enumerate(args.sets or DEFAULT_SETS):
        label, results, manifest_path = entry.split("=")
        with open(manifest_path) as f:
            worlds = {w["occlusions"]: w for w in json.load(f)["worlds"]}
        survival = {name: r for name, r in load_survival(results).items() if name in worlds}
        if not survival:
            print(f"{label:>10}: no results in {results}")
            continue
        color = f"C{k}"
        lacunarity = np.array([worlds[name]["lacunarity"] for name in survival])
        rate = np.array([np.mean(r) for r in survival.values()])
        episodes = sum(len(r) for r in survival.values())
        rho, rho_p = stats.spearmanr(lacunarity, rate)
        fit = stats.linregress(np.log(lacunarity), rate)
        print(f"{label:>10} {len(rate):6d} {episodes:8d} {np.mean(rate):8.3f} {lacunarity.min():5.2f}-{lacunarity.max():<5.2f}"
              f" {rho:6.2f} {rho_p:6.3f} {fit.slope:6.3f} {fit.pvalue:6.3f}")

        levels = collections.defaultdict(list)
        for name, r in zip(survival, rate):
            levels[worlds[name]["level"]].append((worlds[name]["lacunarity"], r))
        x, y, sem = [], [], []
        for level in sorted(levels):
            lac, r = map(np.array, zip(*levels[level]))
            x.append(lac.mean())
            y.append(r.mean())
            sem.append(r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 1 else 0)
        axes.scatter(lacunarity, rate, s=8, color=color, alpha=.25, linewidths=0)
        axes.errorbar(x, y, yerr=sem, color=color, marker="o", markersize=4, capsize=2,
                      label=f"{label} (mean {np.mean(rate):.2f}, ρ={rho:.2f}, p={rho_p:.2f})")

    axes.set_xscale("log")
    axes.set_xticks([1, 1.5, 2, 3, 4, 5, 7])
    axes.get_xaxis().set_major_formatter(plt.ScalarFormatter())
    axes.get_xaxis().set_minor_formatter(plt.NullFormatter())
    axes.set_xlabel("lacunarity (log scale)")
    axes.set_ylabel("survival rate")
    axes.set_ylim(-0.02, 1.02)
    axes.set_title("Prey survival vs lacunarity: mean ± SEM per level, dots are worlds")
    axes.title.set_fontsize(11)
    axes.legend(frameon=False, fontsize=9)
    figure.tight_layout()
    figure.savefig(args.out, dpi=150)
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
