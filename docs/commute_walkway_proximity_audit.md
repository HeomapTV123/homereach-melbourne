# Melbourne pilot: preliminary walkway proximity, not connectivity

The reviewed Victoria source PBF has SHA-256 `5e775844a1b4424dc3c549e601c4a014f4d2816fe7f0ea3fda7d1b39fb966cc0` and an internal timestamp of 2026-10-01T20:22:06Z. Original GTFS train feed 2 is dated for service on 2026-10-13. The highway subset was extracted from `melbourne_pedestrian_review.osm.pbf` using `osmium tags-filter ... w/highway` with referenced nodes retained, resulting in 394,496 ways and 2,096,899 nodes. Raw inputs are not committed.

## Prepare input (Windows Anaconda Prompt)

From the project root, **only if the output does not already exist**:

```
conda run --no-capture-output -n homereach-osm osmium export "data\interim\routing\melbourne_highway_ways.osm.pbf" --geometry-types=linestring --attributes=type,id -o "data\interim\routing\melbourne_highway_ways.geojsonseq"
```

Then run:

```
conda run --no-capture-output -n homereach python scripts/audit_routing_walkway_proximity.py
conda run --no-capture-output -n homereach python -m pytest -q tests/test_routing_walkway_proximity.py
```

The audit reads line by line and reports closest **candidate** way geometries to one GTFS parent station and four unverified OSM tagged entrance nodes. It uses local point-to-segment straight-line proximity within 100 m, excludes some clearly restricted ways, and prints top five candidates. This is NOT a complete interpretation of OSM access and foot restrictions; crossing rules, sidewalks, turn restrictions, crossings, barriers, steps, levels, bridges, tunnels, station gating, public access and connected pedestrian components are **not checked**. A way near a point does not prove you can walk to or from it. Particularly, Flinders Street's point is a GTFS station centre, not a public entrance. Do not use the results to claim reachable pedestrian connections or train journeys.

Consult `https://wiki.openstreetmap.org/wiki/Key:access` for OSM mode-specific precedence and `https://docs.osmcode.org/osmium/latest/osmium-export.html` for the export semantics. Later implement the network graph/routing engine and independent map checks before approving station access.
