# Commute pilot: OSM-tagged public-entrance candidates (review only)

## Scope and sources

The five reference points in `config/routing_station_references.json` were transcribed from the verified GTFS **parent station** records returned on 2026-11-14. They are not public entrances, walking network vertices or homes. The OSM snapshot is the locally retained Geofabrik `victoria-261001.osm.pbf`, timestamp `2026-10-01T20:22:06Z`, SHA-256 `5e775844a1b4424dc3c549e601c4a014f4d2816fe7f0ea3fda7d1b39fb966cc0`. OSM/ODbL attribution is required for any derived or displayed data; see https://www.openstreetmap.org/copyright and https://download.geofabrik.de/.

This step collects **OSM point features with entrance-related tags** within 450 metres (straight-line, not walking distance) of each GTFS parent station. Building entrances can be unrelated, station entrances can be on ways/relations or untagged, and access restrictions can be seasonal or absent. Do not select a public station entrance automatically. No pedestrian connectivity or R5 routing is tested.

## Commands (Anaconda Prompt, project root, branch `feat/commute-location-review`)

Create a local ignored workspace:

```bat
if not exist "data\interim\routing" mkdir "data\interim\routing"
```

Extract **nodes only** with an entrance-related OSM tag, retaining no unrelated referenced geometry:

```bat
conda run --no-capture-output -n homereach-osm osmium tags-filter "data\raw\routing\victoria-261001.osm.pbf" n/entrance n/railway=subway_entrance n/public_transport=entrance -R -o "data\interim\routing\osm_entrance_nodes.osm.pbf"
```

Export these nodes as streaming GeoJSON, retaining stable OSM object identifiers:

```bat
conda run --no-capture-output -n homereach-osm osmium export "data\interim\routing\osm_entrance_nodes.osm.pbf" --geometry-types=point --attributes=type,id -o "data\interim\routing\osm_entrance_candidates.geojsonseq"
```

Run nearest-candidate review with your original Python environment:

```bat
conda run --no-capture-output -n homereach python scripts/review_osm_entrance_candidates.py
conda run --no-capture-output -n homereach python -m pytest -q tests/test_routing_osm_entrance_review.py
```

If a command reports that the output already exists, check the existing file and its provenance before removing it. Do not use `-O` to overwrite earlier evidence without review. These intermediate files are local only: do not commit raw OSM extracts or exports. Check `git status --short` before staging.

## Interpretation, validation gates

The script reports only the **nearest 12** matching point features within the search radius per station (and no automatic winner). It is not a complete inventory of entrances. It also does not prove access through fare gates, elevators, or tunnels, or how a routing engine snaps points. For each proposed entry point, manually review on an OSM map and independent current station-access information, record OSM object ID, access/entrance designation, version/timestamp, public entrance evidence, and whether it is pedestrian accessible. Later check routing engine connectivity and itineraries, plus OSM/GTFS differences in vintage. The routing config's `street_network` and `locations` remain `null` until reviewed.

Official references: https://docs.osmcode.org/osmium/latest/osmium-tags-filter.html and https://docs.osmcode.org/osmium/latest/osmium-export.html
