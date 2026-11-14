# HomeReach: diagnostic OSM walking-topology review

This package supplements, and does not overwrite, the existing commute location candidate and proximity audits. It records the OSM nodes already verified by hand and conducts a deliberately **strict**, read-only OSM graph component check. It is **not** a routing model or proof that a station is publicly accessible.

## Verified manual evidence

- Footscray node `3953464544` belongs to footway `241661387`.
- Coburg node `13503054206` belongs to `1368503589`, with `foot=designated`, `level=0`, `wheelchair=yes`.
- Box Hill node `8317160002` belongs to indoor corridor `639791167` and Market Street pedestrian way `894767007`.
- Dandenong node `13830533511` belongs to level-1 indoor corridors `32806565` and `1513944196`. Alternative node `13901273237` belongs to level-0 footway `1413163523`.
- Flinders Street's investigated `railway=subway_entrance` features include connections via stairs, underground corridors, pedestrian-area polygons, and footways. **Do not** assert that these are a verified Flinders Street Railway Station public main entrance. In particular `w46325052` is stairs (`step_count=9`, `ramp=no`), `w712606593` is an `area=yes` pedestrian polygon, and `w1166108770` is a footway involving a Degraves Street subway entrance.

## Diagnostic graph scope

Reads `data/interim/routing/melbourne_highway_ways.osm.pbf`, derived from the separately verified Victoria PBF (original SHA-256 in config). Reads OPL ways through `osmium cat` and unions **consecutive exact node references** only for the strict subset of `highway=footway|path|pedestrian|living_street` lacking obvious restricted access tags. Excludes stairs, indoor corridors, tunnels, area polygons, nonzero `level`/`layer`, and many legally walkable road types. This intentionally creates *false negatives*, not a full walking network. It does not inspect barriers at nodes, real-world restrictions, crossing delays, transit entrances, or levels. A large connected component does not imply a validated walking route.

For Windows Anaconda Prompt:

```bat
cd /d "D:\My project\homereach_melbourne"
conda activate homereach-osm
python scripts/audit_routing_walk_topology.py
```

The `homereach-osm` environment currently contains Osmium but may not contain Python. Instead, use the installed Python from `base` via the full executable path, while Osmium is on PATH:

```bat
conda activate homereach-osm
"C:\Users\PhamDang\anaconda3\python.exe" scripts/audit_routing_walk_topology.py
```

Or stay in `(base)` and use `--osmium` with the full path printed by `conda run -n homereach-osm where osmium` (the executable location depends on the Conda build):

```bat
conda run -n homereach-osm where osmium
python scripts/audit_routing_walk_topology.py --osmium "<path-to-osmium.exe>"
```

Use `conda run --no-capture-output -n homereach python -m pytest -q tests/test_routing_walk_topology.py` for fixture-only tests. There is no project-data write and no request to edit the raw snapshots. Do not commit until the real run is reviewed.

## Next milestone

After diagnosis, review Flinders Street's **actual railway** public entrance from an authoritative station plan or verified OSM mapping, differentiate Town Hall subway entrances from Flinders Street railway entrances, review barriers and vertical transitions, and then test a realistic walking router on a bounded network. Preserve mixed-vintage October 2026 OSM/GTFS reporting.
