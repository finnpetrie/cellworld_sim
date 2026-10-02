"""Paths, points of interest (lppo) and the options graph the planner searches over."""
import numpy as np
from scipy.sparse import csgraph

from .metrics import adjacency_from_lists, centrality, centrality_derivative, spatial_adjacency


def astar_paths(lattice, occluded):
    """Port of cellworld Paths::get_astar. From s towards d, take the neighbour (in connection-pattern
    order) that is one step closer to d; ties go to the neighbour whose location is nearest d.
    Returns (moves (n*n, dim), steps (n*n,), distance matrix)."""
    distance = csgraph.shortest_path(spatial_adjacency(lattice, occluded), unweighted=True)
    np.fill_diagonal(distance, 0)
    n, neighbours = lattice.n, lattice.neighbours
    locations = lattice.locations  # double precision reproduces the published tie-breaking
    moves = np.zeros((n, n, lattice.dim), dtype=int)
    chunk = max(1, 2_000_000 // (neighbours.shape[1] * n))
    for start in range(0, n, chunk):
        s = np.arange(start, min(start + chunk, n))
        nb = neighbours[s]                                              # (c, m)
        valid = (nb >= 0) & ~occluded[np.where(nb >= 0, nb, 0)]
        closer = valid[:, :, None] & (distance[np.where(valid, nb, 0)] == distance[s][:, None, :] - 1)
        closer &= np.isfinite(distance[s])[:, None, :] & ~occluded[s][:, None, None] & ~occluded[None, None, :]
        offset = locations[np.where(valid, nb, 0)][:, :, None, :] - locations[None, None, :, :]
        score = np.where(closer, np.sqrt((offset * offset).sum(-1)), np.inf)
        best = score.argmin(axis=1)                                     # first neighbour wins ties
        found = np.isfinite(np.take_along_axis(score, best[:, None, :], axis=1)[:, 0, :])
        target = np.take_along_axis(nb, best, axis=1)                   # (c, n)
        moves[s] = np.where(found[..., None],
                            lattice.coordinates[np.where(found, target, 0)] - lattice.coordinates[s][:, None, :], 0)
    steps = np.where(np.isfinite(distance), distance, -1).astype(int)
    return moves.reshape(n * n, lattice.dim), steps.ravel(), distance


def points_of_interest(lattice, occluded, count, required=(), depth=1, graph="spatial", visibility=None):
    """Cells with the highest centrality derivative (cellworld lppo), plus `required` cells (start/goal).
    With depth=1 on the spatial graph this reproduces the published hexagonal.21_05.lppo exactly."""
    adjacency = spatial_adjacency(lattice, occluded) if graph == "spatial" else adjacency_from_lists(visibility)
    derivative = centrality_derivative(lattice, occluded, centrality(adjacency, depth))
    free = np.flatnonzero(~occluded)
    ranked = free[np.argsort(-derivative[free], kind="stable")]
    ranked = ranked[derivative[ranked] > 0]
    chosen = list(dict.fromkeys(int(c) for c in required))
    for cell in ranked:
        if len(chosen) >= count:
            break
        if cell not in chosen:
            chosen.append(int(cell))
    return sorted(int(c) for c in chosen), derivative


def options_graph(lattice, occluded, pois, moves, distance):
    """options[i] = POIs j whose path from i passes through no other POI (i itself is allowed).
    This reproduces the published hexagonal.21_05.options exactly."""
    n = lattice.n
    is_poi = np.zeros(n, dtype=bool)
    is_poi[pois] = True
    moves = moves.reshape(n, n, lattice.dim)
    options = [[] for _ in range(n)]
    for j in pois:
        reachable = np.flatnonzero(np.isfinite(distance[:, j]) & ~occluded)
        next_cell = np.array([lattice.index[tuple(c)] for c in lattice.coordinates[reachable] + moves[reachable, j]])
        nxt = np.full(n, -1)
        nxt[reachable] = next_cell
        through_poi = np.zeros(n, dtype=bool)
        for s in reachable[np.argsort(distance[reachable, j], kind="stable")]:
            if s != j and nxt[s] != j:
                through_poi[s] = is_poi[nxt[s]] or through_poi[nxt[s]]
        for s in reachable[~through_poi[reachable]]:
            options[s].append(int(j))
    return [sorted(o) for o in options]
