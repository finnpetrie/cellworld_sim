"""Cell lattices: coordinates, locations and neighbour patterns.

A Lattice is everything about a world that does not depend on the occlusions.
`hexagonal` reproduces the cellworld "hexagonal"/"canonical" world exactly;
`cubic` is a 3D voxel lattice for the 3D port of the simulation.
"""
import itertools
import json
import os
import urllib.request

import numpy as np

CELLWORLD_DATA_URL = "https://raw.githubusercontent.com/germanespinosa/cellworld_data/master/"


def load_resource(cache_dir, resource, *keys):
    """Loads a cellworld_data resource from a cellworld cache folder, downloading it if missing."""
    file_name = ".".join(keys)
    path = os.path.join(cache_dir, resource, file_name)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with urllib.request.urlopen(CELLWORLD_DATA_URL + resource + "/" + file_name) as response:
            content = response.read()
        with open(path, "wb") as f:
            f.write(content)
    with open(path) as f:
        return json.load(f)


def _ball_offsets(steps, radius):
    """All offsets reachable from the origin in at most `radius` steps."""
    ball = {(0,) * steps.shape[1]}
    frontier = set(ball)
    for _ in range(radius):
        frontier = {tuple(np.add(o, s)) for o in frontier for s in steps} - ball
        ball |= frontier
    return np.array(sorted(ball), dtype=int)


class Lattice:
    def __init__(self, configuration_name, implementation_name, configuration, implementation,
                 box_pattern, occluder):
        self.configuration_name = configuration_name
        self.implementation_name = implementation_name
        self.configuration = configuration      # world_configuration JSON
        self.implementation = implementation    # world_implementation JSON
        axes = "xyz"
        self.dim = 3 if "z" in configuration["cell_coordinates"][0] else 2
        self.axes = axes[:self.dim]
        self.coordinates = np.array([[c[a] for a in self.axes] for c in configuration["cell_coordinates"]], dtype=int)
        self.locations = np.array([[l[a] for a in self.axes] for l in implementation["cell_locations"]], dtype=float)
        # movement offsets, in cellworld order (neighbour order matters for path tie-breaking)
        self.pattern = np.array([[c[a] for a in self.axes] for c in configuration["connection_pattern"]], dtype=int)
        self.box_pattern = np.asarray(box_pattern, dtype=int)  # steps that grow lacunarity boxes
        self.occluder = occluder                               # "polygon" or "voxel"
        self.n = len(self.coordinates)
        self.index = {tuple(c): i for i, c in enumerate(self.coordinates)}
        self.neighbours = self.offset_table(self.pattern)      # (n, m), -1 where outside the world

    def offset_table(self, offsets):
        table = np.full((self.n, len(offsets)), -1, dtype=int)
        for i, c in enumerate(self.coordinates):
            for k, o in enumerate(offsets):
                table[i, k] = self.index.get(tuple(c + o), -1)
        return table

    def wall_distance(self):
        """Steps from each cell to the nearest cell on the edge of the world (edge cells are 0)."""
        distance = np.where((self.neighbours < 0).any(axis=1), 0, -1)
        frontier = np.flatnonzero(distance == 0)
        step = 0
        while frontier.size:
            step += 1
            reached = np.unique(self.neighbours[frontier])
            reached = reached[(reached >= 0) & (distance[np.maximum(reached, 0)] < 0)]
            distance[reached] = step
            frontier = reached
        return distance

    def pattern_pairs(self):
        """Opposite neighbour pairs (k, k_opposite), in Connection_pattern::get_pairs order."""
        pairs, seen = [], set()
        for k, o in enumerate(self.pattern):
            if tuple(o) in seen:
                continue
            opposite = next(j for j, p in enumerate(self.pattern) if (p == -o).all())
            seen |= {tuple(o), tuple(-o)}
            pairs.append((k, opposite))
        return pairs

    def boxes(self, radius):
        """Boxes of the given radius centred on every cell: (n, box_size) cell ids, -1 outside the world."""
        return self.offset_table(_ball_offsets(self.box_pattern, radius))

    def to_json_coordinates(self, offsets):
        return [{a: int(v) for a, v in zip(self.axes, o)} for o in offsets]

    @staticmethod
    def hexagonal(cache_dir, implementation_name="canonical"):
        configuration = load_resource(cache_dir, "world_configuration", "hexagonal")
        implementation = load_resource(cache_dir, "world_implementation", "hexagonal", implementation_name)
        pattern = [[c["x"], c["y"]] for c in configuration["connection_pattern"]]
        return Lattice("hexagonal", implementation_name, configuration, implementation,
                       box_pattern=pattern, occluder="polygon")

    @staticmethod
    def cubic(size, connectivity=6):
        """size**3 voxel world in the unit cube. connectivity: 6 (faces), 18 (+edges) or 26 (+corners)."""
        offsets = [o for o in itertools.product((-1, 0, 1), repeat=3) if any(o)]
        pattern = sorted((o for o in offsets if sum(map(abs, o)) <= {6: 1, 18: 2, 26: 3}[connectivity]),
                         key=lambda o: (sum(map(abs, o)), o))
        cells = list(itertools.product(range(size), repeat=3))
        configuration = {
            "cell_shape": {"sides": 6},
            "cell_coordinates": [{"x": x, "y": y, "z": z} for x, y, z in cells],
            "connection_pattern": [{"x": x, "y": y, "z": z} for x, y, z in pattern],
        }
        implementation = {
            "cell_locations": [{"x": (x + .5) / size, "y": (y + .5) / size, "z": (z + .5) / size} for x, y, z in cells],
            "space": {"center": {"x": .5, "y": .5, "z": .5}, "shape": {"sides": 6},
                      "transformation": {"size": 1, "rotation": 0}},
            "cell_transformation": {"size": 1 / size, "rotation": 0},
        }
        return Lattice(f"cubic{size}n{connectivity}", "canonical", configuration, implementation,
                       box_pattern=offsets, occluder="voxel")
