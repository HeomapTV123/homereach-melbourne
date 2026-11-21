# HomeReach Melbourne — location review checkpoint

This is a *candidate discovery* step and deliberately does not modify
`config/routing_pilot.json` or assert a valid route.

## Source provenance

- GTFS: existing pinned `data/raw/transport/gtfs.zip`, service 2026-10-13;
  SHA-256 `c88af3abcaf0872e45196dcc1d5af9bc20a82c54a00a9dfef46c809ec2e34814`.
- OSM: `data/raw/routing/victoria-261001.osm.pbf`, SHA-256
  `5e775844a1b4424dc3c549e601c4a014f4d2816fe7f0ea3fda7d1b39fb966cc0`.
  Header replication timestamp 2026-10-01T20:22:06Z; last object timestamp
  2026-10-01T20:12:02Z; size 241,895,835 bytes.
- Time mismatch is explicit: OSM 1 October vs GTFS service 13 October 2026.
- Candidate place names: Footscray, Coburg, Box Hill, Dandenong stations;
  destination Flinders Street Station. These are *initial search anchors*.

## Run

From project root, after copying the script and config from this ZIP:

```
conda run --no-capture-output -n homereach python scripts/inspect_routing_location_candidates.py
```

Optional machine-readable output:

```
conda run --no-capture-output -n homereach python scripts/inspect_routing_location_candidates.py --json
```

The utility verifies the pinned archive hash, reads nested train-feed stops,
prints matching GTFS stop and station records and writes no files. It does not
require R5py or Osmium. Record the actual returned IDs/coordinates before
selecting a unique station location or independent public entrance.

## Review gates before routing

1. Confirm one public pedestrian entry to Flinders Street Station; a GTFS stop
   coordinate is not automatically an entrance or pedestrian-network node.
2. Select and document four public origin points *separately* from the train
   station platforms if the experiment aims to include walking access time.
3. Validate all points against the OSM walking network; note CRS EPSG:4326,
   coordinates, public source, review date, and any snapping distance.
4. Define buffered metropolitan extraction coverage after points are selected.
   Preserve complete OSM ways. Do not assume the cut automatically preserves
   complete transit itineraries or all cross-boundary walking connections.
5. Validate complete GTFS stop_times and transfer semantics, and test the
   routing runtime before publishing travel-time estimates.

**Do not replace the existing null `locations` and `street_network` fields in
`config/routing_pilot.json` with unvalidated candidate information.**
