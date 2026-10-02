# env_generator

Generates cellworld environments that vary in **lacunarity** at constant **entropy**. For each world it writes
every resource the simulation loads: occlusions, cell visibility, A* paths, POIs (`lppo`) and the
options ("quick") graph.

```
python3 -m venv .venv && .venv/bin/pip install -r env_generator/requirements.txt
.venv/bin/python -m env_generator.validate                      # rebuilds hexagonal.21_05, checks it matches
.venv/bin/python -m env_generator.generate --levels 10 --replicates 10 --margin 2 --start=-20,0 --goal 20,0 --keep-free 10,10
.venv/bin/python -m env_generator.generate --lattice cubic --size 8 --levels 5   # 3D (needs the 3D C++ port)
```

Run from `cellworld_sim/`. Write negative coordinates as `--start=-20,0`; otherwise they are read as a flag.
`--margin N` keeps the cells within N steps of the outer wall free. Without it, high-lacunarity clumps form
against the wall; with `--margin 2` they form in the middle of the world. The output folder (`generated_worlds/` by default) is laid out like a cellworld cache.
To use a world in the simulation, set `CELLWORLD_CACHE` to that folder, or copy its files into the
`.cellworld_cache` the binary runs from. Then set `world_info.occlusions` to the world's name (e.g.
`lac02_05_r00`). `manifest.json` lists every world with its target and achieved lacunarity.

## Definitions

- **Entropy** follows cellworld's `World.entropy`: the binary entropy of the occluded fraction. The `05` in
  `21_05` means 36 of 331 cells are occluded (0.496). Holding entropy constant therefore means holding the
  occlusion count fixed, so only the arrangement changes.
- **Lacunarity** is gliding-box lacunarity, `E[D²]/E[D]²`. D is the occluded fraction of the box centred on
  each cell (hexagons on the hex lattice, cubes on the cubic one), with boxes clipped to the world. The
  reported value is the geometric mean over `--radii`. Arrangements are found by simulated annealing over
  occluded/free swaps, keeping all free cells connected.
- **POIs** are the free cells with the highest centrality derivative. For each cell this is the product,
  over opposite neighbour pairs, of `|c(n) − c(n')|` (cellworld `get_centrality_derivative_product`). With
  `--centrality-depth 1` (degree centrality, spatial graph) this reproduces the published `21_05.lppo`
  exactly. `--centrality-depth 0` uses converged eigenvector centrality instead.
- **VV POIs** (`--poi-method vv`): visual variability after Lai et al., "How threat visibility shapes peeking
  and hiding in mice". VV(p1, p2) = area(I1 ∪ I2) − area(I1 ∩ I2), where I1 and I2 are 360° ray-cast
  isovists (720 rays plus rays either side of every obstacle vertex). Each graph edge is split into half-cell
  sub-steps (about the paper's 2.5% of arena width) and VV is summed along it. A node's VV is the mean (or
  max) over its edges, averaged with its neighbours. POIs are local maxima within 2 steps that are in the
  top 10%, at least 3 cells apart, plus start and goal. Areas are in cells, lengths in cell spacings, and all
  of these are `--vv-*` options. VV gives far fewer POIs (about 2–10 per world) than the derivative's 35.
  `python -m env_generator.visual_variability --check` runs the sanity checks, and `--worlds F --world W`
  plots one world's VV heatmap and the paper-style 40×40 binned map.
  The **shelter index** (fraction of free neighbours, product of differences across opposite neighbours) is
  the default derivative method: same ranking, different constant.
- **Same worlds, different POIs**: `python -m env_generator.recompute_pois --worlds F --out F_vv --poi-method vv`
  writes a copy of a world folder with only the POIs and options graph recomputed.
- **Options graph**: `options[i]` holds the POIs whose A* path from `i` passes through no other POI. This
  reproduces the published `21_05.options` exactly.
- **Visibility**: on the hex lattice, a port of cellworld's polygon line-of-sight test (exact match with
  published data). On the cubic lattice, exact voxel traversal: a sight line is blocked when it passes
  through an occluded voxel's interior, and grazing an edge or corner does not block.
