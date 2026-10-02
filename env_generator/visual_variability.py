"""Visual Variability (VV) points of interest, after Lai et al., "How threat visibility shapes peeking and
hiding in mice".

VV(p1, p2) = area(I1 ∪ I2) − area(I1 ∩ I2): how much of the visible area changes when moving from p1 to p2,
where I1 and I2 are the 360° isovists at the two points. High VV marks places where a small step reveals or
hides a lot (obstacle corners, gaps): candidate peeking locations.

On the cellworld hex lattice the free space is the union of the hexagonal cells minus the occluded ones,
graph nodes are free cell centres and edges join neighbouring cells. Areas are measured in cells (the area
of one hexagonal cell), lengths in cell spacings (the distance between neighbouring cell centres).

Sanity checks and a heatmap of one world:

    .venv/bin/python -m env_generator.visual_variability --check
    .venv/bin/python -m env_generator.visual_variability --worlds generated_worlds_margin2 --world lac09_05_r00
"""
import argparse
import json
import math
import os

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union


def hexagon(center, radius):
    # pointy-top hexagons, as the cells tile (neighbours along x share a vertical edge)
    angles = np.arange(6) * math.pi / 3
    return np.round(np.stack([center[0] + radius * np.sin(angles), center[1] + radius * np.cos(angles)], -1), 9)


class Geometry:
    """Free space of a hex world and ray-cast isovists inside it."""

    def __init__(self, lattice, occluded, rays=720, epsilon=1e-7):
        if lattice.dim != 2 or lattice.occluder != "polygon":
            raise ValueError("visual variability is implemented for the 2D hexagonal lattice only")
        self.radius = lattice.implementation["cell_transformation"]["size"] / 2
        self.spacing = self.radius * math.sqrt(3)                 # distance between neighbouring centres
        self.cell_area = 1.5 * math.sqrt(3) * self.radius ** 2
        cells = [Polygon(hexagon(c, self.radius)) for c in lattice.locations]
        arena = unary_union(cells)
        blocked = unary_union([cells[i] for i in np.flatnonzero(occluded)]) if occluded.any() else Polygon()
        self.space = arena.difference(blocked).buffer(0)
        rings = []
        for polygon in getattr(self.space, "geoms", [self.space]):
            rings += [polygon.exterior] + list(polygon.interiors)
        starts, ends = [], []
        for ring in rings:
            coordinates = np.asarray(ring.coords)
            starts.append(coordinates[:-1])
            ends.append(coordinates[1:])
        self.a = np.concatenate(starts)
        self.edge = np.concatenate(ends) - self.a
        self.vertices = self.a
        self.base_angles = np.linspace(0, 2 * math.pi, rays, endpoint=False)
        self.epsilon = epsilon

    def isovist(self, point):
        """Visibility polygon from `point`: rays every 360/rays degrees plus rays just either side of every
        boundary vertex, each stopped at the nearest boundary edge."""
        p = np.asarray(point, dtype=float)
        to_vertex = self.vertices - p
        vertex_angles = np.arctan2(to_vertex[:, 1], to_vertex[:, 0])
        angles = np.unique(np.concatenate([self.base_angles, vertex_angles - self.epsilon, vertex_angles + self.epsilon])
                           % (2 * math.pi))
        d = np.stack([np.cos(angles), np.sin(angles)], -1)                      # (m, 2)
        w = self.a - p                                                          # (s, 2)
        denominator = d[:, None, 0] * self.edge[None, :, 1] - d[:, None, 1] * self.edge[None, :, 0]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (w[None, :, 0] * self.edge[None, :, 1] - w[None, :, 1] * self.edge[None, :, 0]) / denominator
            u = (w[None, :, 0] * d[:, None, 1] - w[None, :, 1] * d[:, None, 0]) / denominator
        hit = (denominator != 0) & (t > 1e-12) & (u >= -1e-12) & (u <= 1 + 1e-12)
        distance = np.where(hit, t, np.inf).min(axis=1)
        points = p + distance[:, None] * d
        return Polygon(points).buffer(0)


def edge_variability(geometry, lattice, occluded, step=0.5):
    """VV of every graph edge, in cells of area. Edges longer than `step` (in cell spacings) are split into
    equal sub-steps and VV is summed over consecutive sub-step points. Returns {(u, v): vv} with u < v."""
    cache = {}

    def isovist(point):
        key = tuple(np.round(point, 9))
        if key not in cache:
            cache[key] = geometry.isovist(point)
        return cache[key]

    vv = {}
    for u in np.flatnonzero(~occluded):
        for v in lattice.neighbours[u]:
            if v <= u or occluded[v]:
                continue
            a, b = lattice.locations[u], lattice.locations[v]
            parts = max(1, math.ceil(np.linalg.norm(b - a) / (step * geometry.spacing) - 1e-9))
            points = [a + (b - a) * k / parts for k in range(parts + 1)]
            vv[(int(u), int(v))] = sum(isovist(p).symmetric_difference(isovist(q)).area
                                       for p, q in zip(points, points[1:])) / geometry.cell_area
    return vv


def node_variability(lattice, occluded, vv, aggregate="mean", per_length=False, geometry=None):
    """VV of each free cell from its incident edges: mean (closest to the paper) or max. per_length divides
    each edge's VV by its length in cell spacings (all hex edges have length 1, so it only matters for
    other graphs)."""
    incident = {i: [] for i in np.flatnonzero(~occluded)}
    for (u, v), value in vv.items():
        if per_length and geometry is not None:
            value /= np.linalg.norm(lattice.locations[u] - lattice.locations[v]) / geometry.spacing
        incident[u].append(value)
        incident[v].append(value)
    reduce = np.mean if aggregate == "mean" else np.max
    values = np.zeros(lattice.n)
    for i, edges in incident.items():
        values[i] = reduce(edges) if edges else 0.0
    return values


def free_neighbours(lattice, occluded):
    return [[int(j) for j in lattice.neighbours[i] if j >= 0 and not occluded[j]] if not occluded[i] else []
            for i in range(lattice.n)]


def vv_points_of_interest(lattice, occluded, required=(), rays=720, step=0.5, aggregate="mean", smooth=True,
                          hops=2, percentile=90, min_separation=3.0):
    """Places of interest from node VV: local maxima within `hops` graph steps that are in the top
    (100 - percentile)% of free cells, thinned so no two are closer than `min_separation` cell spacings
    (the higher VV one is kept). `required` cells (start, goal) are always included.
    Returns (sorted POI ids, node VV, [(id, x, y, vv)] sorted by VV)."""
    geometry = Geometry(lattice, occluded, rays)
    values = node_variability(lattice, occluded, edge_variability(geometry, lattice, occluded, step), aggregate)
    neighbours = free_neighbours(lattice, occluded)
    free = np.flatnonzero(~occluded)
    if smooth:
        smoothed = values.copy()
        for i in free:
            smoothed[i] = np.mean([values[i]] + [values[j] for j in neighbours[i]])
        values = smoothed
    threshold = np.percentile(values[free], percentile)
    candidates = []
    for i in free:
        reach, frontier = {i}, {i}
        for _ in range(hops):
            frontier = {j for f in frontier for j in neighbours[f]} - reach
            reach |= frontier
        if values[i] >= threshold and values[i] >= max(values[j] for j in reach):
            candidates.append(int(i))
    kept = []
    for i in sorted(candidates, key=lambda c: -values[c]):
        if all(np.linalg.norm(lattice.locations[i] - lattice.locations[k]) >= min_separation * geometry.spacing
               for k in kept):
            kept.append(i)
    pois = sorted(set(kept) | {int(r) for r in required})
    table = sorted(((i, *lattice.locations[i], values[i]) for i in kept), key=lambda r: -r[3])
    return pois, values, table


def binned(lattice, occluded, values, bins=40):
    """The paper's spatial binning: a bins × bins grid over the arena. Graph nodes are sparser than the bins,
    so each bin takes the VV of the cell containing its centre; bins in obstacles or outside are NaN."""
    lo, hi = lattice.locations.min(axis=0), lattice.locations.max(axis=0)
    radius = lattice.implementation["cell_transformation"]["size"] / 2
    lo, hi = lo - radius, hi + radius
    centres = np.stack(np.meshgrid(*[lo[k] + (np.arange(bins) + .5) * (hi[k] - lo[k]) / bins for k in range(2)]), -1)
    nearest = np.linalg.norm(centres[:, :, None, :] - lattice.locations[None, None], axis=-1).argmin(axis=-1)
    offset = np.abs(centres - lattice.locations[nearest])
    # inside the nearest cell's pointy-top hexagon, so bins outside the arena are masked
    inside = (offset[..., 0] <= radius * math.sqrt(3) / 2) & (offset[..., 1] <= radius - offset[..., 0] / math.sqrt(3))
    grid = np.where(inside & ~occluded[nearest], values[nearest], np.nan)
    return grid, (lo, hi)


def plot(lattice, occluded, values, pois, out, title="", grid=None):
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib import cm

    panels = 2 if grid is not None else 1
    figure, axes = plt.subplots(1, panels, figsize=(6 * panels, 5.5))
    axes = np.atleast_1d(axes)
    radius = lattice.implementation["cell_transformation"]["size"] / 2
    free = ~occluded
    norm = plt.Normalize(0, values[free].max() or 1)
    colours = [cm.viridis(norm(v)) if f else (0.15, 0.15, 0.15, 1) for v, f in zip(values, free)]
    axes[0].add_collection(PolyCollection([hexagon(c, radius) for c in lattice.locations], facecolors=colours,
                                          edgecolors="white", linewidths=0.3))
    axes[0].scatter(*lattice.locations[pois].T, s=40, facecolors="none", edgecolors="red", linewidths=1.5, label="POI")
    axes[0].set_title(title or "node VV (cells of area)", fontsize=10)
    figure.colorbar(cm.ScalarMappable(norm=norm, cmap="viridis"), ax=axes[0], fraction=0.04)
    axes[0].legend(loc="lower right", fontsize=8)
    if grid is not None:
        values_grid, (lo, hi) = grid
        image = axes[1].imshow(values_grid, origin="lower", extent=[lo[0], hi[0], lo[1], hi[1]], cmap="viridis")
        axes[1].set_title("40×40 binned VV (paper style)", fontsize=10)
        figure.colorbar(image, ax=axes[1], fraction=0.04)
    for a in axes:
        a.set_aspect("equal")
        a.autoscale_view()
        a.set_xticks([])
        a.set_yticks([])
    figure.tight_layout()
    figure.savefig(out, dpi=150)
    plt.close(figure)


def check(cache):
    """The sanity checks from the spec, on synthetic occlusion patterns in the hexagonal world."""
    from .lattice import Lattice
    lattice = Lattice.hexagonal(cache)
    walls = lattice.wall_distance()
    ok = True

    open_world = np.zeros(lattice.n, dtype=bool)
    geometry = Geometry(lattice, open_world)
    values = node_variability(lattice, open_world, edge_variability(geometry, lattice, open_world))
    interior, edge = values[walls >= 3].mean(), values[walls == 0].mean()
    passed = interior < 0.05 * edge
    ok &= passed
    print(f"open arena: interior VV {interior:.4f}, wall-cell VV {edge:.4f} -> {'ok' if passed else 'FAIL'}")

    u, v = lattice.index[(0, 0)], lattice.index[(2, 0)]
    a, b = geometry.isovist(lattice.locations[u]), geometry.isovist(lattice.locations[v])
    passed = abs(a.symmetric_difference(b).area - b.symmetric_difference(a).area) < 1e-12
    ok &= passed
    print(f"symmetry: VV(u,v) == VV(v,u) -> {'ok' if passed else 'FAIL'}")

    # a wall with a gap: cells beside the gap's corners should beat cells deep behind the wall and cells
    # in the open far from it
    blocked = np.zeros(lattice.n, dtype=bool)
    for y in range(-10, 11):
        for x in (-1, 1, 0):
            i = lattice.index.get((x, y))
            if i is not None and abs(y) > 1:
                blocked[i] = True
    geometry = Geometry(lattice, blocked)
    values = node_variability(lattice, blocked, edge_variability(geometry, lattice, blocked))
    near_gap = np.mean([values[lattice.index[c]] for c in [(-3, 1), (-3, -1), (3, 1), (3, -1)]])
    behind = np.mean([values[lattice.index[c]] for c in [(-4, 8), (4, 8), (-4, -8), (4, -8)]])
    open_far = np.mean([values[lattice.index[c]] for c in [(-14, 0), (14, 0)]])
    passed = near_gap > 2 * behind and near_gap > 2 * open_far
    ok &= passed
    print(f"wall with a gap: beside gap corners {near_gap:.2f}, behind the wall {behind:.2f}, "
          f"open far side {open_far:.2f} -> {'ok' if passed else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="run the sanity checks")
    parser.add_argument("--cache", default="cellworld_simulation/build/.cellworld_cache")
    parser.add_argument("--worlds", default="generated_worlds_margin2", help="generator output folder")
    parser.add_argument("--world", default="lac09_05_r00", help="occlusions name")
    parser.add_argument("--rays", type=int, default=720)
    parser.add_argument("--step", type=float, default=0.5, help="sub-step length in cell spacings")
    parser.add_argument("--aggregate", choices=["mean", "max"], default="mean")
    parser.add_argument("--hops", type=int, default=2)
    parser.add_argument("--percentile", type=float, default=90)
    parser.add_argument("--min-separation", type=float, default=3.0, help="in cell spacings")
    parser.add_argument("--out", help="heatmap image (default: vv_<world>.png)")
    args = parser.parse_args()
    if args.check:
        check(args.cache)

    from .lattice import Lattice
    lattice = Lattice.hexagonal(args.worlds if os.path.exists(os.path.join(args.worlds, "world_configuration")) else args.cache)
    occluded = np.zeros(lattice.n, dtype=bool)
    with open(os.path.join(args.worlds, "cell_group", f"{lattice.configuration_name}.{args.world}.occlusions")) as f:
        occluded[json.load(f)] = True
    pois, values, table = vv_points_of_interest(lattice, occluded, rays=args.rays, step=args.step,
                                                aggregate=args.aggregate, hops=args.hops,
                                                percentile=args.percentile, min_separation=args.min_separation)
    print(f"{len(table)} places of interest (node, x, y, vv in cells of area):")
    for node, x, y, value in table:
        print(f"  {node:4d}  {x:.4f}  {y:.4f}  {value:7.3f}")
    out = args.out or f"vv_{args.world}.png"
    plot(lattice, occluded, values, pois, out, title=f"{args.world}: node VV ({args.aggregate})",
         grid=binned(lattice, occluded, values))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
