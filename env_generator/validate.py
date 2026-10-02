"""Rebuilds the published hexagonal.21_05 resources from its occlusions and checks they match exactly.

    python -m env_generator.validate [--cache cellworld_simulation/build/.cellworld_cache]
"""
import argparse
import json

import numpy as np

from .lattice import Lattice, load_resource
from .pois import astar_paths, options_graph, points_of_interest
from .visibility import visibility_graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default="cellworld_simulation/build/.cellworld_cache")
    parser.add_argument("--occlusions", default="21_05")
    args = parser.parse_args()

    lattice = Lattice.hexagonal(args.cache)
    published = {
        "occlusions": load_resource(args.cache, "cell_group", "hexagonal", args.occlusions, "occlusions"),
        "lppo": load_resource(args.cache, "cell_group", "hexagonal", args.occlusions, "lppo"),
        "cell_visibility": load_resource(args.cache, "graph", "hexagonal", args.occlusions, "cell_visibility"),
        "options": load_resource(args.cache, "graph", "hexagonal", args.occlusions, "options"),
        "astar": load_resource(args.cache, "paths", "hexagonal", args.occlusions, "astar"),
    }
    occluded = np.zeros(lattice.n, dtype=bool)
    occluded[published["occlusions"]] = True

    moves, steps, distance = astar_paths(lattice, occluded)
    pois, _ = points_of_interest(lattice, occluded, count=len(published["lppo"]))
    rebuilt = {
        "cell_visibility": visibility_graph(lattice, occluded),
        "astar": {"moves": lattice.to_json_coordinates(moves), "steps": steps.tolist()},
        "lppo": pois,
        "options": options_graph(lattice, occluded, published["lppo"], moves, distance),
    }
    ok = True
    for name, value in rebuilt.items():
        match = value == published[name]
        ok &= match
        print(f"{name:16s} {'match' if match else 'MISMATCH'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
