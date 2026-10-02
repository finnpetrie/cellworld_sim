"""Plots prey survival rate against world lacunarity.

Reads the simulation result files (<world>_seed_<n>.json), averages survival over seeds for each world,
then over the worlds (replicates) at each lacunarity level. Lacunarity values come from the generator's
manifest.json. An episode counts as survived when the prey reached the goal (result == 1).

    .venv/bin/python plot_survival.py
    .venv/bin/python plot_survival.py --results cellworld_simulation/build --manifest generated_worlds_100/manifest.json
"""
import argparse
import collections
import glob
import json
import os
import re

import matplotlib.pyplot as plt
import numpy as np

RESULT_NAME = re.compile(r"(?P<world>.+)_seed_(?P<seed>\d+)\.json$")


def load_survival(results_folder):
    """{world name: [result of each seed]}"""
    survival = collections.defaultdict(list)
    for path in glob.glob(os.path.join(results_folder, "*_seed_*.json")):
        match = RESULT_NAME.match(os.path.basename(path))
        if not match:
            continue
        with open(path) as f:
            survival[match["world"]].append(json.load(f)["result"])
    return survival


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", default="cellworld_simulation/build", help="folder with the result .json files")
    parser.add_argument("--manifest", default="generated_worlds_100/manifest.json")
    parser.add_argument("--out", default="survival_vs_lacunarity.png")
    args = parser.parse_args()

    with open(args.manifest) as f:
        worlds = {w["occlusions"]: w for w in json.load(f)["worlds"]}
    survival = load_survival(args.results)
    missing = sorted(set(survival) - set(worlds))
    if missing:
        print(f"ignoring {len(missing)} worlds not in the manifest, e.g. {missing[0]}")

    # per world: mean over seeds; per level: mean and standard error over worlds
    levels = collections.defaultdict(list)
    for name, results in survival.items():
        if name in worlds:
            levels[worlds[name]["level"]].append((worlds[name]["lacunarity"], np.mean(results), len(results)))
    if not levels:
        raise SystemExit(f"no result files in {args.results} match worlds in {args.manifest}")

    print(f"{'level':>5} {'lacunarity':>10} {'worlds':>6} {'episodes':>8} {'survival':>8} {'sem':>6}")
    summary = []
    for level in sorted(levels):
        lacunarity, rates, episodes = map(np.array, zip(*levels[level]))
        sem = rates.std(ddof=1) / np.sqrt(len(rates)) if len(rates) > 1 else 0.0
        summary.append((lacunarity.mean(), rates.mean(), sem))
        print(f"{level:5d} {lacunarity.mean():10.2f} {len(rates):6d} {episodes.sum():8d} {rates.mean():8.3f} {sem:6.3f}")

    figure, axes = plt.subplots(figsize=(6, 4))
    for level in sorted(levels):
        lacunarity, rates, _ = zip(*levels[level])
        axes.scatter(lacunarity, rates, s=12, color="0.75", zorder=1)
    x, y, sem = map(np.array, zip(*summary))
    axes.errorbar(x, y, yerr=sem, color="C0", marker="o", capsize=3, zorder=2, label="mean ± SEM over worlds")
    axes.set_xlabel("lacunarity")
    axes.set_ylabel("survival rate")
    axes.set_ylim(-0.02, 1.02)
    axes.set_title("Prey survival vs lacunarity")
    axes.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(args.out, dpi=150)
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
