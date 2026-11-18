# Inspecting strict walking-component boundaries

## Purpose

The recorded strict audit found a 17-node component at the Footscray candidate and a 537-node component at the Dandenong candidate. Those sizes do not identify why the components stop, and they do not establish that the stations are inaccessible. The deliberately narrow policy excludes many kinds of mapped connection.

The boundary diagnostic lists excluded OSM ways that share an exact node ID with either selected component, together with every applicable exclusion reason. It leaves those ways out of the graph. This supplies concrete way IDs and tags for the next review without silently broadening the walking model.

## Recorded comparison checkpoint

The maintainer's run with the script changes committed as `9d02105` reported the following on `data/interim/routing/melbourne_highway_ways.osm.pbf`:

| Location | Candidate OSM node | Strict component nodes | Incident strict way |
| --- | ---: | ---: | ---: |
| Flinders Street | unresolved | unavailable | unavailable |
| Footscray | 3953464544 | 17 | 241661387 |
| Coburg | 13503054206 | 75,962 | 1368503589 |
| Box Hill | 8317160002 | 215,100 | 894767007 |
| Dandenong | 13901273237 | 537 | 1413163523 |

There were **394,496 ways**, of which **161,371 were included** and **233,125 excluded**. These are previously reported observations, not new results from the boundary diagnostic. No real-data boundary report has yet been recorded in this guide. The same unchanged derivative should reproduce this strict summary.

The Dandenong node is the alternative candidate on level-0 footway `1413163523`. It is different from node `13830533511`, which was examined earlier on level-1 indoor corridors. The configuration still leaves Flinders Street unresolved.

## Run on Windows

Use Anaconda Prompt / CMD from the project root. The existing `homereach-osm` environment supplies Osmium, and the explicit base Python executable supplies Python; the script itself uses only the standard library.

```bat
cd /d "D:\My project\homereach_melbourne"
conda activate homereach-osm
"C:\Users\PhamDang\anaconda3\python.exe" scripts/audit_routing_walk_topology.py --boundary-locations orig_footscray orig_dandenong
```

This reads the same PBF twice. The first pass builds the strict graph; the second examines excluded ways. It retains the graph and bounded examples in memory, rather than retaining every OPL way record. As with the strict audit, several hundred MB of memory may be needed. It does not download data or write project files.

The default display limit is 20 examples per selected component. Use `--boundary-limit 50` if additional examples are needed. Counts always cover every touching excluded way, regardless of the display limit. Examples touching other strict components appear first, followed by other examples; within those groups, way IDs are ascending. This is an inspection order, not a ranking of route quality or access.

Running the script without `--boundary-locations` continues to produce the original single-pass strict report. The removed `--osmium` executable override remains unsupported.

## Read the report

| Field | Meaning |
| --- | --- |
| `strict_audit` | The original five-location strict summary, with the same eligibility policy. |
| `component_id_min_node` | The smallest OSM node ID in that strict component; an order-independent diagnostic identifier. |
| `excluded_ways_touching` | Complete count of excluded ways sharing at least one exact node with the selected component. |
| `exclusion_reason_counts` | Count of each applicable policy reason. A way can fail several rules, so these counts can sum to more than the number of ways. |
| `shared_component_nodes` | Exact node IDs shared by that excluded way and the selected strict component. |
| `other_strict_components` | Other strict components touched by the same excluded way, with their sizes and shared node IDs. |
| `nodes_outside_strict_graph_count` | Number of distinct way references absent from every strict component. These references are not inserted into the graph. |
| `relationship` | Summary of whether the way touches another strict component, extends only to references outside the strict graph, or stays within the selected component. Other-component and outside-node details remain separate. |
| `examples_shown` / `examples_omitted` | Explicit extent of the displayed sample. An omitted example is still counted in the totals. |
| `tags_opl` | Tags from Osmium's OPL stream. Text retains OPL percent escapes, for example `Market%20%Street`. |

A null entrance or a node absent from the strict graph receives `boundary_scan: "not_available"`. It is not reported as a successfully inspected component with zero excluded ways.

The strict policy remains deliberately narrow: only `footway`, `path`, `pedestrian`, and `living_street` highway types are considered. Area polygons, indoor ways, restricted foot/access tags, tunnels, and non-ground level/layer values are excluded. Existing details are preserved, including accepting `level=0.0` but excluding `layer=0.0`, and excluding `access=private` even when `foot=yes`. These are diagnostic rules, not a complete model of pedestrian permission.

## Input consistency and failure handling

Boundary mode hashes the derived PBF before and after the two passes and requires identical way-stream hashes and counts across the passes. It rejects malformed or duplicate way records and stops if either Osmium invocation fails. Its parser supports the plain, single-version OPL ways used by this audit, with nonempty node ID lists; it is not a general OPL validator and does not accept node-list encodings with embedded coordinates. It prints a completed report only after these checks pass. Osmium's error stream is inherited so an unread error pipe cannot stall the scan.

`source.sha256` is the hash observed for this **derived highway PBF**. `expected_derived_sha256: null` means there is no separately recorded expected hash for it. An unchanged hash during a run does not prove that the derivative was created correctly from the original snapshot. The original Victoria PBF hash recorded in the configuration is a separate provenance claim and is not reverified by this diagnostic. The command reads the fixed `osmium` executable from the trusted, activated environment and enforces project containment for configuration and source paths.

Synthetic regression cases exercise exact node sharing, multiple exclusion reasons, unchanged strict results, absent nodes, component identifiers, bounded examples with complete totals, malformed/duplicate input, changed streams, failed subprocesses, path containment, and a changed source file. They do not validate Melbourne entrance identity or real travel times.

## What the result can establish

The result can identify a particular excluded way as a structural explanation worth inspecting. It does not establish that the way is a usable walking connection: stairs, indoor levels, private access, or an area boundary can touch multiple strict components. It does not snap coordinates, follow chains of excluded ways, add edges, inspect node barriers, model vertical transfers, or compute journeys.

Next, review the reported tags and exact shared nodes for Footscray and Dandenong. Keep public entrance identity and routing-engine validation as separate decisions. Flinders Street remains unresolved until its station identity and public access are supported by appropriate evidence. The original OSM snapshot is dated 1 October 2026, while the GTFS service date is 13 October 2026; this diagnostic does not erase that difference.

## Format references

- [Osmium `cat` manual](https://docs.osmcode.org/osmium/latest/osmium-cat.html): streaming conversion, object-type filtering, and exit codes.
- [Osmium OPL format](https://osmcode.org/opl-file-format/): exact way-node references and tag escaping.
