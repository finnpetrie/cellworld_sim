"""World statistics: occupancy entropy, gliding-box lacunarity and centrality derivative."""
import math

import numpy as np
from scipy import sparse


def occupancy_entropy(occlusion_count, cell_count):
    """cellworld World.entropy: binary entropy of the occluded fraction, normalised to [0, 1].
    This is the "05" in world names such as 21_05 (36 of 331 cells occluded -> 0.496)."""
    h = 0.0
    for p in (occlusion_count / cell_count, 1 - occlusion_count / cell_count):
        if p > 0:
            h -= p * math.log2(p)
    return h


def occlusion_count_for_entropy(entropy, cell_count):
    """Occlusion count (below half the cells) whose entropy is closest to the target."""
    return min(range(cell_count // 2 + 1), key=lambda c: abs(occupancy_entropy(c, cell_count) - entropy))


class Lacunarity:
    """Gliding-box lacunarity of the occlusion pattern: L(r) = E[D^2] / E[D]^2, where D is the occluded
    fraction of the box of radius r centred on each cell (hexagons on the hex lattice, cubes on the cubic
    one). Boxes are clipped to the world and measured as densities, so cells near the walls weigh about
    as much as interior ones; with boxes that must fit inside the world, the most lacunar arrangement
    is just occlusions packed into the corners. The summary value is the geometric mean over radii."""

    def __init__(self, lattice, radii):
        self.radii = list(radii)
        self.boxes = [lattice.boxes(r) for r in self.radii]
        self.sizes = [(b >= 0).sum(axis=1) for b in self.boxes]

    def per_radius(self, occluded):
        padded = np.append(occluded, False)  # index -1 -> outside the world
        values = []
        for boxes, sizes in zip(self.boxes, self.sizes):
            density = padded[boxes].sum(axis=1) / sizes
            mean = density.mean()
            values.append(float((density ** 2).mean() / mean ** 2) if mean > 0 else float("nan"))
        return values

    def log_value(self, occluded):
        return float(np.mean(np.log(self.per_radius(occluded))))

    def __call__(self, occluded):
        return math.exp(self.log_value(occluded))


def spatial_adjacency(lattice, occluded):
    """Movement graph between free cells as a sparse matrix."""
    rows, cols = np.nonzero(lattice.neighbours >= 0)
    dst = lattice.neighbours[rows, cols]
    keep = ~occluded[rows] & ~occluded[dst]
    return sparse.csr_matrix((np.ones(keep.sum()), (rows[keep], dst[keep])), shape=(lattice.n, lattice.n))


def adjacency_from_lists(graph):
    rows = np.repeat(np.arange(len(graph)), [len(g) for g in graph])
    cols = np.concatenate([np.asarray(g, dtype=int) for g in graph])
    return sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(graph), len(graph)))


def centrality(adjacency, depth=1, tolerance=1e-10, max_iterations=10000):
    """cellworld get_centrality: `depth` rounds of c <- A c, normalised by the maximum.
    depth=1 is degree centrality (what the published lppo files use); depth=0 iterates to convergence,
    which is eigenvector centrality (iterating on A + I so bipartite lattices like the cube converge)."""
    c = np.ones(adjacency.shape[0])
    if depth > 0:
        for _ in range(depth):
            c = adjacency @ c
            c /= c.max()
        return c
    shifted = adjacency + sparse.identity(adjacency.shape[0], format="csr")
    for _ in range(max_iterations):
        new = shifted @ c
        new /= new.max()
        if np.abs(new - c).max() < tolerance:
            return new * (adjacency.getnnz(axis=1) > 0)  # isolated (occluded) cells have no centrality
        c = new
    raise RuntimeError("eigenvector centrality did not converge")


def centrality_derivative(lattice, occluded, values):
    """cellworld World.get_centrality_derivative_product: for every free cell, the product over opposite
    neighbour pairs of |c(neighbour) - c(opposite)|, with missing or occluded neighbours counting as 0."""
    padded = np.append(np.where(occluded, 0.0, values), 0.0)  # index -1 -> 0
    derivative = np.ones(lattice.n)
    for k, opposite in lattice.pattern_pairs():
        derivative *= np.abs(padded[lattice.neighbours[:, k]] - padded[lattice.neighbours[:, opposite]])
    derivative[occluded] = 0
    return derivative / 2
