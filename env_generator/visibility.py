"""Cell visibility graphs (the cellworld `cell_visibility` resource)."""
import itertools
import math

import numpy as np

TWO_PI = 2 * math.pi


def _atan(src, dst):
    # cellworld Location::atan uses atan2(x, y): angles are measured from the y axis
    d = dst - src
    return np.arctan2(d[..., 0], d[..., 1])


def _normalize(a):
    return np.where(a < 0, a + TWO_PI, a)


def _angle_difference(a1, a2):
    d = np.abs(_normalize(a1) - _normalize(a2))
    return np.where(d < math.pi, d, TWO_PI - d)


def _direction(a1, a2):
    a1, a2 = _normalize(a1), _normalize(a2)
    sign = np.where(a1 > a2, 1, -1)
    return np.where(np.abs(a1 - a2) < math.pi, sign, -sign)


def _polygon_blocked(lattice, occluded, sources, destinations, chunk=20000):
    """Port of Location_visibility::is_visible / Polygon::is_between (cellworld shape.cpp)."""
    transformation = lattice.implementation["cell_transformation"]
    sides = lattice.configuration["cell_shape"]["sides"]
    radius = transformation["size"] / 2
    # cellworld converts the rotation to radians twice (visibility.cpp and the Polygon constructor)
    rotation = math.radians(math.radians(transformation["rotation"]))
    angles = rotation + np.arange(sides) * math.radians(360.0 / sides)
    centers = lattice.locations[occluded]                                  # (o, 2)
    vertices = centers[:, None, :] + radius * np.stack([np.sin(angles), np.cos(angles)], -1)[None]
    blocked = np.zeros(len(sources), dtype=bool)
    for start in range(0, len(sources), chunk):
        src = lattice.locations[sources[start:start + chunk]][:, None, :]  # (p, 1, 2)
        dst = lattice.locations[destinations[start:start + chunk]][:, None, :]
        theta = _atan(src, dst)                                            # (p, 1)
        dist = np.linalg.norm(dst - src, axis=-1)
        dist_center = np.linalg.norm(centers[None] - src, axis=-1)         # (p, o)
        candidate = dist >= dist_center - radius
        theta_center = _atan(src, centers[None])
        diff_center = _angle_difference(theta, theta_center)
        candidate &= diff_center <= np.arctan2(dist_center, radius)
        direction_center = _direction(theta, theta_center)
        hit = np.zeros_like(candidate)
        for k in range(sides):
            v = vertices[None, :, k, :]
            theta_vertex = _atan(src, v)
            hit |= ((np.linalg.norm(v - src, axis=-1) < dist)
                    & (direction_center == -_direction(theta, theta_vertex))
                    & (diff_center + _angle_difference(theta, theta_vertex) < math.pi))
        blocked[start:start + chunk] = (candidate & hit).any(axis=1)
    return blocked


def _traversed_offsets(delta):
    """Voxels whose interior the segment from the origin to `delta` crosses, excluding both ends."""
    crossings = [0.0, 1.0]
    for d in delta:
        crossings += [(j + .5) / abs(d) for j in range(abs(d))]
    t = np.unique(np.round(crossings, 9))
    midpoints = (t[:-1] + t[1:]) / 2
    cells = {tuple(c) for c in np.rint(midpoints[:, None] * np.asarray(delta)[None]).astype(int)}
    cells -= {tuple([0] * len(delta)), tuple(delta)}
    return np.array(sorted(cells), dtype=int).reshape(-1, len(delta))


def _voxel_visibility(lattice, occluded):
    """Exact line of sight between voxel centres on a full grid. A segment is blocked when it passes
    through the interior of an occluded voxel; grazing an edge or corner does not block."""
    shape = lattice.coordinates.max(axis=0) + 1
    assert np.prod(shape) == lattice.n, "voxel visibility needs a full rectangular grid"
    grid_id = np.full(shape, -1)
    grid_id[tuple(lattice.coordinates.T)] = np.arange(lattice.n)
    grid_occluded = np.zeros(shape, dtype=bool)
    grid_occluded[tuple(lattice.coordinates[occluded].T)] = True
    sources, destinations = [], []
    for delta in itertools.product(*[range(-s + 1, s) for s in shape]):
        if delta <= (0,) * len(shape):  # each unordered pair once
            continue
        lo = [max(0, -d) for d in delta]
        hi = [s - max(0, d) for s, d in zip(shape, delta)]
        window = tuple(slice(l, h) for l, h in zip(lo, hi))
        visible = ~grid_occluded[window] & ~grid_occluded[tuple(slice(l + d, h + d) for l, h, d in zip(lo, hi, delta))]
        for o in _traversed_offsets(delta):
            visible &= ~grid_occluded[tuple(slice(l + d, h + d) for l, h, d in zip(lo, hi, o))]
        src = grid_id[window][visible]
        sources.append(src)
        destinations.append(grid_id[tuple(slice(l + d, h + d) for l, h, d in zip(lo, hi, delta))][visible])
    return np.concatenate(sources), np.concatenate(destinations)


def visibility_graph(lattice, occluded):
    """Adjacency lists in cellworld format: every free cell sees itself, occluded cells see nothing."""
    occluded = np.asarray(occluded, dtype=bool)
    free = np.flatnonzero(~occluded)
    if lattice.occluder == "polygon":
        i, j = np.triu_indices(len(free), 1)
        visible = ~_polygon_blocked(lattice, np.flatnonzero(occluded), free[i], free[j])
        src, dst = free[i][visible], free[j][visible]
    else:
        src, dst = _voxel_visibility(lattice, occluded)
    graph = [[] for _ in range(lattice.n)]
    for s in free:
        graph[s].append(int(s))
    for s, d in zip(src.tolist(), dst.tolist()):
        graph[s].append(d)
        graph[d].append(s)
    return [sorted(g) for g in graph]
