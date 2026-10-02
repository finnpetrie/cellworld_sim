"""Recomputes the points of interest (lppo) and options graph of an existing world folder with another POI
method, keeping the occlusions, visibility and paths. Use it to compare POI methods on the same worlds.

    .venv/bin/python -m env_generator.recompute_pois --worlds generated_worlds_margin2 \\
        --out generated_worlds_margin2_vv --poi-method vv

The output folder is a complete world folder (the unchanged files are hard links to the originals).
"""
import argparse
import concurrent.futures
import json
import os
import shutil

import numpy as np

from .generate import add_poi_arguments, choose_pois, poi_settings, write_json
from .lattice import Lattice, load_resource
from .pois import astar_paths, options_graph

_lattice = None


def _link(source, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    if os.path.exists(destination):
        os.remove(destination)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copyfile(source, destination)


def _init(worlds):
    global _lattice
    _lattice = Lattice.hexagonal(worlds)


def _recompute(worlds, name, required, settings):
    configuration = _lattice.configuration_name
    occluded = np.zeros(_lattice.n, dtype=bool)
    occluded[load_resource(worlds, "cell_group", configuration, name, "occlusions")] = True
    visibility = load_resource(worlds, "graph", configuration, name, "cell_visibility")
    moves, _, distance = astar_paths(_lattice, occluded)
    pois = choose_pois(_lattice, occluded, required, settings, visibility)
    return name, pois, options_graph(_lattice, occluded, pois, moves, distance)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worlds", required=True, help="existing generator output folder")
    parser.add_argument("--out", required=True, help="new world folder")
    parser.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 1))
    add_poi_arguments(parser)
    args = parser.parse_args()
    if os.path.abspath(args.worlds) == os.path.abspath(args.out):
        raise SystemExit("--out must be a different folder")

    with open(os.path.join(args.worlds, "manifest.json")) as f:
        manifest = json.load(f)
    configuration = manifest["world_configuration"]
    lattice = Lattice.hexagonal(args.worlds)
    required = [lattice.index[(c["x"], c["y"])] for c in manifest["start_goal"]]
    settings = poi_settings(args)

    for resource, file_name in [("world_configuration", configuration),
                                ("world_implementation", f"{configuration}.{manifest['world_implementation']}")]:
        _link(os.path.join(args.worlds, resource, file_name), os.path.join(args.out, resource, file_name))
    for world in manifest["worlds"]:
        name = world["occlusions"]
        for resource, kind in [("cell_group", "occlusions"), ("graph", "cell_visibility"), ("paths", "astar")]:
            file_name = f"{configuration}.{name}.{kind}"
            _link(os.path.join(args.worlds, resource, file_name), os.path.join(args.out, resource, file_name))

    counts = {}
    with concurrent.futures.ProcessPoolExecutor(args.workers, initializer=_init, initargs=(args.worlds,)) as pool:
        jobs = [pool.submit(_recompute, args.worlds, w["occlusions"], required, settings) for w in manifest["worlds"]]
        for done, job in enumerate(concurrent.futures.as_completed(jobs), 1):
            name, pois, options = job.result()
            write_json(args.out, "cell_group", f"{configuration}.{name}.lppo", pois)
            write_json(args.out, "graph", f"{configuration}.{name}.options", options)
            counts[name] = len(pois)
            print(f"[{done}/{len(jobs)}] {name}: {len(pois)} POIs", flush=True)

    for world in manifest["worlds"]:
        world["poi_count"] = counts[world["occlusions"]]
    manifest["pois"] = settings
    manifest["pois_recomputed_from"] = args.worlds
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    values = list(counts.values())
    print(f"POIs per world: {min(values)}-{max(values)} (median {sorted(values)[len(values) // 2]})")


if __name__ == "__main__":
    main()
