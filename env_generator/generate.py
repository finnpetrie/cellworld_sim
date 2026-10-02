"""Generates cellworld environments that span a range of lacunarity at constant entropy.

Entropy here is cellworld's world entropy (the "05" in 21_05): the binary entropy of the occluded
fraction. Fixing the occlusion count fixes it exactly, so lacunarity is varied purely by how the
occlusions are arranged. Each arrangement is found by simulated annealing over swaps of occluded and
free cells, keeping every free cell reachable and the start/goal cells free.

For every world it writes the same resources cellworld_data publishes (occlusions, cell_visibility,
astar paths, lppo points of interest and the options graph), laid out like a cellworld cache folder,
plus manifest.json with the statistics of every world.

    python -m env_generator.generate --levels 5 --replicates 2 --out generated_worlds
    python -m env_generator.generate --lattice cubic --size 8 --entropy 0.5 --levels 4
"""
import argparse
import json
import math
import os

import numpy as np
from scipy.sparse import csgraph

from .lattice import Lattice
from .metrics import Lacunarity, occlusion_count_for_entropy, occupancy_entropy, spatial_adjacency
from .pois import astar_paths, options_graph, points_of_interest
from .visibility import visibility_graph
from .visual_variability import vv_points_of_interest


class Annealer:
    def __init__(self, lattice, occlusion_count, keep_free, lacunarity, rng):
        self.lattice = lattice
        self.count = occlusion_count
        self.lacunarity = lacunarity
        self.rng = rng
        self.adjacency = spatial_adjacency(lattice, np.zeros(lattice.n, dtype=bool))
        self.movable = np.setdiff1d(np.arange(lattice.n), keep_free)

    def connected(self, occluded):
        free = np.flatnonzero(~occluded)
        return csgraph.connected_components(self.adjacency[free][:, free], directed=False)[0] == 1

    def random_arrangement(self, attempts=10000):
        for _ in range(attempts):
            occluded = np.zeros(self.lattice.n, dtype=bool)
            occluded[self.rng.choice(self.movable, self.count, replace=False)] = True
            if self.connected(occluded):
                return occluded
        raise RuntimeError("could not place the occlusions without disconnecting the world")

    def run(self, energy, steps, t_start, t_end, tolerance=None, occluded=None):
        """Minimises energy(log_lacunarity) by swapping an occluded cell with a free one. Half the swaps
        move an occlusion next to another occlusion, which lets clustered arrangements form quickly."""
        occluded = self.random_arrangement() if occluded is None else occluded.copy()
        current = energy(self.lacunarity.log_value(occluded))
        best, best_occluded = current, occluded.copy()
        neighbours = self.lattice.neighbours
        for step in range(steps):
            if tolerance is not None and best <= tolerance:
                break
            temperature = t_start * (t_end / t_start) ** (step / steps)
            occupied = np.flatnonzero(occluded[self.movable])
            vacant = np.flatnonzero(~occluded[self.movable])
            a = self.movable[self.rng.choice(occupied)]
            b = None
            if self.rng.random() < .5:
                anchor = self.movable[self.rng.choice(occupied)]
                around = [c for c in neighbours[anchor] if c >= 0 and not occluded[c] and c in self.movable]
                if around:
                    b = self.rng.choice(around)
            if b is None:
                b = self.movable[self.rng.choice(vacant)]
            occluded[a], occluded[b] = False, True
            proposed = energy(self.lacunarity.log_value(occluded))
            accept = proposed <= current or self.rng.random() < math.exp((current - proposed) / temperature)
            if accept and self.connected(occluded):
                current = proposed
                if current < best:
                    best, best_occluded = current, occluded.copy()
            else:
                occluded[a], occluded[b] = True, False
        return best_occluded


def parse_cells(lattice, cells):
    ids = []
    for cell in cells:
        coordinates = tuple(int(v) for v in cell.split(","))
        if coordinates not in lattice.index:
            raise SystemExit(f"cell {cell} is not in the world")
        ids.append(lattice.index[coordinates])
    return ids


def write_json(root, resource, file_name, content):
    os.makedirs(os.path.join(root, resource), exist_ok=True)
    with open(os.path.join(root, resource, file_name), "w") as f:
        json.dump(content, f, separators=(",", ":"))


def add_poi_arguments(parser):
    group = parser.add_argument_group("points of interest")
    group.add_argument("--poi-method", choices=["derivative", "vv"], default="derivative",
                       help="derivative: centrality derivative (as published; with depth 1 this is the shelter "
                            "index). vv: visual variability peaks (Lai et al.)")
    group.add_argument("--poi-fraction", type=float, default=35 / 295,
                       help="derivative: fraction of free cells that become POIs (default matches 21_05: 35 of 295)")
    group.add_argument("--centrality-depth", type=int, default=1,
                       help="derivative: centrality iterations; 1 = degree (as published), 0 = eigenvector centrality")
    group.add_argument("--centrality-graph", choices=["spatial", "visual"], default="spatial")
    group.add_argument("--vv-rays", type=int, default=720, help="vv: rays per isovist")
    group.add_argument("--vv-step", type=float, default=0.5,
                       help="vv: sub-step length in cell spacings (0.5 is about the paper's 2.5%% of arena width)")
    group.add_argument("--vv-aggregate", choices=["mean", "max"], default="mean", help="vv: node VV from its edges")
    group.add_argument("--vv-no-smooth", action="store_true", help="vv: skip averaging node VV with neighbours")
    group.add_argument("--vv-hops", type=int, default=2, help="vv: POIs are maxima within this many steps")
    group.add_argument("--vv-percentile", type=float, default=90, help="vv: POIs are above this percentile")
    group.add_argument("--vv-min-separation", type=float, default=3.0, help="vv: minimum POI spacing, in cells")


def poi_settings(args):
    if args.poi_method == "vv":
        return {"poi_method": "vv", "rays": args.vv_rays, "step": args.vv_step, "aggregate": args.vv_aggregate,
                "smooth": not args.vv_no_smooth, "hops": args.vv_hops, "percentile": args.vv_percentile,
                "min_separation": args.vv_min_separation}
    return {"poi_method": "derivative", "poi_fraction": args.poi_fraction,
            "centrality_depth": args.centrality_depth, "centrality_graph": args.centrality_graph}


def choose_pois(lattice, occluded, required, settings, visibility):
    if settings["poi_method"] == "vv":
        pois, _, _ = vv_points_of_interest(lattice, occluded, required, rays=settings["rays"], step=settings["step"],
                                           aggregate=settings["aggregate"], smooth=settings["smooth"],
                                           hops=settings["hops"], percentile=settings["percentile"],
                                           min_separation=settings["min_separation"])
        return pois
    count = round(settings["poi_fraction"] * int((~occluded).sum()))
    pois, _ = points_of_interest(lattice, occluded, count, required, depth=settings["centrality_depth"],
                                 graph=settings["centrality_graph"], visibility=visibility)
    return pois


def build_world(lattice, occluded, required, settings):
    visibility = visibility_graph(lattice, occluded)
    moves, steps, distance = astar_paths(lattice, occluded)
    pois = choose_pois(lattice, occluded, required, settings, visibility)
    return {
        "occlusions": np.flatnonzero(occluded).tolist(),
        "cell_visibility": visibility,
        "astar": {"moves": lattice.to_json_coordinates(moves), "steps": steps.tolist()},
        "lppo": pois,
        "options": options_graph(lattice, occluded, pois, moves, distance),
    }


def save_world(root, lattice, name, world):
    prefix = f"{lattice.configuration_name}.{name}"
    write_json(root, "cell_group", f"{prefix}.occlusions", world["occlusions"])
    write_json(root, "cell_group", f"{prefix}.lppo", world["lppo"])
    write_json(root, "graph", f"{prefix}.cell_visibility", world["cell_visibility"])
    write_json(root, "graph", f"{prefix}.options", world["options"])
    write_json(root, "paths", f"{prefix}.astar", world["astar"])


def visual_degree_entropy(visibility):
    """Shannon entropy (bits) of how many cells each free cell sees (cellworld Graph.complexity)."""
    degrees = [len(v) for v in visibility if v]
    _, counts = np.unique(degrees, return_counts=True)
    p = counts / counts.sum()
    return float(-(p * np.log2(p)).sum())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lattice", choices=["hexagonal", "cubic"], default="hexagonal")
    parser.add_argument("--cache", default="cellworld_simulation/build/.cellworld_cache",
                        help="cellworld cache holding the hexagonal world configuration (downloaded if missing)")
    parser.add_argument("--size", type=int, default=8, help="cubic: cells per side")
    parser.add_argument("--connectivity", type=int, choices=[6, 18, 26], default=6, help="cubic: neighbours per cell")
    occlusion = parser.add_mutually_exclusive_group()
    occlusion.add_argument("--entropy", type=float, default=0.5, help="world entropy to hold constant (default 0.5)")
    occlusion.add_argument("--occlusion-count", type=int, help="number of occluded cells, instead of --entropy")
    parser.add_argument("--levels", type=int, default=5, help="lacunarity levels, evenly spaced in log lacunarity")
    parser.add_argument("--targets", type=float, nargs="+", help="explicit lacunarity targets instead of --levels")
    parser.add_argument("--replicates", type=int, default=1, help="worlds per lacunarity level")
    parser.add_argument("--radii", type=int, nargs="+", help="gliding-box radii (default: 1 2 3 hex, 1 2 cubic)")
    parser.add_argument("--start", metavar="X,Y[,Z]", help="prey start: kept free and always a POI "
                                                           "(default: one end of the world)")
    parser.add_argument("--goal", metavar="X,Y[,Z]", help="prey goal: kept free and always a POI "
                                                          "(default: the other end of the world)")
    parser.add_argument("--keep-free", nargs="+", default=[], metavar="X,Y[,Z]",
                        help="other cells that must stay free, e.g. the predator start")
    parser.add_argument("--margin", type=int, default=0,
                        help="keep cells within this many steps of the outer wall free, so occlusions "
                             "(and high-lacunarity clumps) stay in the middle of the world")
    parser.add_argument("--steps", type=int, default=20000, help="annealing steps per world")
    parser.add_argument("--tolerance", type=float, default=.01, help="accepted |log lacunarity - log target|")
    parser.add_argument("--prefix", default="lac", help="occlusions name prefix")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="generated_worlds")
    add_poi_arguments(parser)
    args = parser.parse_args()

    if args.lattice == "hexagonal":
        lattice = Lattice.hexagonal(args.cache)
        ends = ["-20,0", "20,0"]
        radii = args.radii or [1, 2, 3]
    else:
        lattice = Lattice.cubic(args.size, args.connectivity)
        middle = args.size // 2
        ends = [f"0,{middle},{middle}", f"{args.size - 1},{middle},{middle}"]
        radii = args.radii or [1, 2]
    required = parse_cells(lattice, [args.start or ends[0], args.goal or ends[1]])
    keep_free = required + parse_cells(lattice, args.keep_free)
    keep_free += np.flatnonzero(lattice.wall_distance() < args.margin).tolist()
    count = args.occlusion_count if args.occlusion_count is not None else occlusion_count_for_entropy(args.entropy, lattice.n)
    entropy = occupancy_entropy(count, lattice.n)
    settings = poi_settings(args)
    lacunarity = Lacunarity(lattice, radii)
    rng = np.random.default_rng(args.seed)
    annealer = Annealer(lattice, count, keep_free, lacunarity, rng)
    print(f"{lattice.configuration_name}: {lattice.n} cells, {count} occluded (entropy {entropy:.3f}), "
          f"POIs by {args.poi_method}, box radii {radii}, {lattice.n - len(set(keep_free))} cells can be occluded")

    if args.targets:
        targets = [math.log(t) for t in args.targets]
    else:
        t_start, t_end = .05, 1e-4
        low = lacunarity.log_value(annealer.run(lambda x: x, args.steps, t_start, t_end))
        high = lacunarity.log_value(annealer.run(lambda x: -x, args.steps, t_start, t_end))
        print(f"reachable lacunarity: {math.exp(low):.3f} .. {math.exp(high):.3f}")
        margin = .05 * (high - low)  # the extremes are hard to re-reach from a random start
        targets = np.linspace(low + margin, high - margin, args.levels).tolist()

    os.makedirs(args.out, exist_ok=True)
    write_json(args.out, "world_configuration", lattice.configuration_name, lattice.configuration)
    write_json(args.out, "world_implementation", f"{lattice.configuration_name}.{lattice.implementation_name}",
               lattice.implementation)
    manifest = {"world_configuration": lattice.configuration_name, "pois": settings,
                "world_implementation": lattice.implementation_name,
                "occlusion_count": count, "entropy": entropy, "box_radii": radii, "margin": args.margin,
                "start_goal": lattice.to_json_coordinates(lattice.coordinates[required]),
                "keep_free": lattice.to_json_coordinates(lattice.coordinates[keep_free]), "worlds": []}
    for level, target in enumerate(targets):
        for replicate in range(args.replicates):
            occluded = annealer.run(lambda x: abs(x - target), args.steps, .05, 1e-4, tolerance=args.tolerance)
            name = f"{args.prefix}{level:02d}_{round(entropy * 10):02d}_r{replicate:02d}"
            world = build_world(lattice, occluded, required, settings)
            save_world(args.out, lattice, name, world)
            achieved = lacunarity(occluded)
            within = abs(math.log(achieved) - target) <= args.tolerance
            manifest["worlds"].append({
                "occlusions": name, "level": level, "replicate": replicate,
                "target_lacunarity": math.exp(target), "lacunarity": achieved, "within_tolerance": within,
                "lacunarity_per_radius": dict(zip(map(str, radii), lacunarity.per_radius(occluded))),
                "entropy": entropy, "visual_degree_entropy": visual_degree_entropy(world["cell_visibility"]),
                "poi_count": len(world["lppo"])})
            print(f"{name}: lacunarity {achieved:.3f} (target {math.exp(target):.3f})"
                  + ("" if within else "  ** outside tolerance, try more --steps"))
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    main()
