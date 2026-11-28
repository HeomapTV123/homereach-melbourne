"""Read-only conservative OSM-way connectivity audit. Requires stdlib + osmium CLI.

This deliberately does NOT compute routes, snap locations, model crossings,
validate public station access, or identify wheelchair-accessible journeys.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

WALK_TYPES = {"footway", "path", "pedestrian", "living_street"}
RESTRICTED = {"no", "private", "customers", "permit", "delivery", "agricultural", "forestry"}


def parse_tags(field: str) -> dict[str, str]:
    """Parse OPL way tags; this diagnostic only needs simple ASCII key/value tags."""
    if not field.startswith("T"):
        return {}
    tags: dict[str, str] = {}
    for token in field[1:].split(","):
        key, sep, value = token.partition("=")
        if sep:
            tags[key] = value
    return tags


def exclusion_reasons(tags: dict[str, str]) -> list[str]:
    """List every failed rule of the original strict subset, without relaxing it."""
    checks = (
        ("highway_outside_strict_subset", tags.get("highway") not in WALK_TYPES),
        ("area_yes", tags.get("area") == "yes"),
        ("indoor_yes", tags.get("indoor") == "yes"),
        ("foot_restricted", tags.get("foot") in RESTRICTED),
        ("access_restricted", tags.get("access") in RESTRICTED),
        ("tunnel_present", tags.get("tunnel") not in (None, "no")),
        ("level_outside_ground", tags.get("level") not in (None, "0", "0.0")),
        ("layer_outside_ground", tags.get("layer") not in (None, "0")),
    )
    return [reason for reason, failed in checks if failed]


def eligible(tags: dict[str, str]) -> bool:
    """Strict surface-footway subset; NOT a complete legal walkability model."""
    return not exclusion_reasons(tags)


def parse_way(line: str):
    """Parse a way from osmium OPL, preserving actual node references."""
    if not line.startswith("w"):
        return None
    fields = line.strip().split(" ")
    try:
        way_id = int(fields[0][1:])
    except ValueError:
        return None
    n_field = next((f for f in fields[1:] if f.startswith("N")), None)
    t_field = next((f for f in fields[1:] if f.startswith("T")), "T")
    if not n_field or len(n_field) <= 1:
        return None
    try:
        refs = [int(s.removeprefix("n")) for s in n_field[1:].split(",") if s]
    except ValueError:
        return None
    return way_id, refs, parse_tags(t_field)


class Components:
    def __init__(self):
        self.parent: dict[int, int] = {}
        self.size: dict[int, int] = {}

    def find(self, n: int) -> int:
        if n not in self.parent:
            self.parent[n] = n
            self.size[n] = 1
            return n
        root = n
        while self.parent[root] != root:
            root = self.parent[root]
        while n != root:
            nxt = self.parent[n]
            self.parent[n] = root
            n = nxt
        return root

    def join(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]
        del self.size[rb]


class StrictState:
    """First-pass graph and report; OSM way records are not retained."""

    def __init__(self, components, report, targets, way_digest, validated):
        self.components = components
        self.report = report
        self.targets = dict(targets)
        self.way_digest = way_digest
        self.validated = validated


def _validated_way(line: str):
    """Reject malformed way records instead of silently omitting boundary evidence."""
    parsed = parse_way(line)
    fields = line.rstrip("\r\n").split(" ")
    node_fields = [field for field in fields[1:] if field.startswith("N")]
    tag_fields = [field for field in fields[1:] if field.startswith("T")]
    if parsed is None or len(node_fields) != 1 or len(tag_fields) > 1:
        raise ValueError("Malformed OPL way record; boundary scan aborted.")
    tokens = node_fields[0][1:].split(",")
    if any(not token.startswith("n") or not token[1:].lstrip("-").isdigit() for token in tokens):
        raise ValueError("Malformed OPL node references; boundary scan aborted.")
    seen_keys = set()
    for tag in tag_fields[0][1:].split(",") if tag_fields and tag_fields[0] != "T" else []:
        key, separator, _ = tag.partition("=")
        if not key or not separator or key in seen_keys:
            raise ValueError("Malformed or duplicate OPL tag; boundary scan aborted.")
        seen_keys.add(key)
    return parsed


def _strict_report(comps, counts, incident, targets):
    results = []
    for label, node in targets.items():
        if node is None:
            results.append({"id": label, "node": None, "result": "unresolved_entrance"})
        elif node not in comps.parent:
            results.append({"id": label, "node": node, "result": "no_strict_way_node_membership", "incident_ways": []})
        else:
            root = comps.find(node)
            results.append({"id": label, "node": node, "result": "strict_component_found",
                            "incident_ways": sorted(incident[node]), "component_nodes": comps.size[root]})
    return {"counts": dict(counts), "results": results, "warnings": [
        "This tests exact OSM node-sharing in a deliberately restricted set of ways, not full pedestrian routing.",
        "Excluded stairs, all indoor ways, tunnels, area polygons, nonzero levels/layers and most roads; false negatives expected.",
        "OSM node-sharing does not certify legal public access, vertical movement, entrance identity, barriers, or reachable transit platforms.",
        "Component node counts are diagnostics only; component connections can be interrupted by unmapped barriers or access rules.",
        "This input is an extracted highway dataset, not a validated routing-engine network."
    ]}


def build_strict_state(lines: Iterable[str], targets: dict[str, int | None], *,
                       validate_ways: bool = False) -> StrictState:
    """Build the original strict graph; boundary mode additionally validates OPL ways."""
    comps = Components()
    counts = Counter()
    incident: dict[int, list[int]] = {n: [] for n in targets.values() if n is not None}
    digest = hashlib.sha256()
    seen_way_ids: set[int] = set()
    for line in lines:
        if not line.startswith("w"):
            continue
        digest.update(line.encode("utf-8"))
        parsed = _validated_way(line) if validate_ways else parse_way(line)
        if parsed is None:
            continue
        way_id, refs, tags = parsed
        if validate_ways:
            if way_id in seen_way_ids:
                raise ValueError("Duplicate OPL way ID; boundary scan requires a non-history snapshot.")
            seen_way_ids.add(way_id)
        counts["ways_seen"] += 1
        if not eligible(tags):
            counts["ways_excluded"] += 1
            continue
        counts["ways_included"] += 1
        for a, b in zip(refs, refs[1:]):
            comps.join(a, b)
        if len(refs) == 1:
            comps.find(refs[0])
        for n in set(refs) & incident.keys():
            incident[n].append(way_id)
    return StrictState(comps, _strict_report(comps, counts, incident, targets),
                       targets, digest.hexdigest(), validate_ways)


def audit_lines(lines: Iterable[str], targets: dict[str, int | None]) -> dict:
    return build_strict_state(lines, targets).report


def _component_ids(comps: Components) -> dict[int, int]:
    """Stable diagnostic IDs: the minimum node ID in each strict component."""
    minimum = {}
    for node in comps.parent:
        root = comps.find(node)
        minimum[root] = min(node, minimum.get(root, node))
    return minimum


class BoundaryExamples:
    """Count every touching way while retaining at most limit example records."""

    def __init__(self, limit: int):
        self.limit = limit
        self.total = 0
        self.reasons = Counter()
        self.relationships = Counter()
        self.examples = []

    def add(self, record: dict):
        self.total += 1
        self.reasons.update(record["exclusion_reasons"])
        self.relationships[record["relationship"]] += 1
        priority = 0 if record["other_strict_components"] else 1
        entry = (-priority, -record["way_id"], record)
        if len(self.examples) < self.limit:
            heapq.heappush(self.examples, entry)
        elif entry[:2] > self.examples[0][:2]:
            heapq.heapreplace(self.examples, entry)

    def report(self) -> dict:
        examples = [item[2] for item in sorted(self.examples, key=lambda item: (-item[0], -item[1]))]
        return {
            "excluded_ways_touching": self.total,
            "exclusion_reason_counts": dict(sorted(self.reasons.items())),
            "relationship_counts": dict(sorted(self.relationships.items())),
            "examples_shown": len(examples),
            "examples_omitted": self.total - len(examples),
            "examples": examples,
        }


def _way_membership(refs, comps):
    groups = {}
    outside = 0
    for node in set(refs):
        # find() creates unknown nodes. Never call it before checking membership.
        if node not in comps.parent:
            outside += 1
            continue
        groups.setdefault(comps.find(node), []).append(node)
    return groups, outside


def _boundary_record(way_id, tags, reasons, groups, outside, selected_root, comps, component_ids):
    others = [
        {"component_id_min_node": component_ids[root], "component_nodes": comps.size[root],
         "shared_nodes": sorted(nodes)}
        for root, nodes in groups.items() if root != selected_root
    ]
    others.sort(key=lambda item: item["component_id_min_node"])
    if others:
        relationship = "touches_other_strict_components"
    elif outside:
        relationship = "extends_outside_strict_graph"
    else:
        relationship = "within_same_strict_component"
    return {
        "way_id": way_id,
        "tags_opl": dict(sorted(tags.items())),
        "exclusion_reasons": reasons,
        "shared_component_nodes": sorted(groups[selected_root]),
        "other_strict_components": others,
        "nodes_outside_strict_graph_count": outside,
        "relationship": relationship,
    }


def _boundary_results(state, selected, component_ids, summaries):
    strict_results = {result["id"]: result for result in state.report["results"]}
    results = []
    for label in selected:
        original = strict_results[label]
        if original["result"] != "strict_component_found":
            results.append({**original, "boundary_scan": "not_available"})
            continue
        root = state.components.find(original["node"])
        results.append({
            "id": label, "node": original["node"], "result": "strict_component_boundary_review",
            "component_id_min_node": component_ids[root],
            "component_nodes": original["component_nodes"], **summaries[root].report(),
        })
    return results


def scan_boundary_lines(state: StrictState, lines: Iterable[str], boundary_locations: list[str], *,
                        limit: int = 20) -> dict:
    """Inspect excluded ways touching selected strict components, without adding edges."""
    if not state.validated:
        raise ValueError("Boundary scan requires a validated first pass.")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("Boundary example limit must be a positive integer.")
    selected = list(boundary_locations)
    if not selected or len(selected) != len(set(selected)) or any(label not in state.targets for label in selected):
        raise ValueError("Choose one or more distinct configured boundary locations.")
    comps = state.components
    component_ids = _component_ids(comps)
    summaries = {
        comps.find(state.targets[label]): BoundaryExamples(limit)
        for label in selected if state.targets[label] in comps.parent
    }
    digest = hashlib.sha256()
    ways_seen = 0
    seen_way_ids: set[int] = set()
    for line in lines:
        if not line.startswith("w"):
            continue
        digest.update(line.encode("utf-8"))
        way_id, refs, tags = _validated_way(line)
        if way_id in seen_way_ids:
            raise ValueError("Duplicate OPL way ID in second pass; boundary report discarded.")
        seen_way_ids.add(way_id)
        ways_seen += 1
        reasons = exclusion_reasons(tags)
        if not reasons:
            continue
        groups, outside = _way_membership(refs, comps)
        for root in summaries.keys() & groups.keys():
            record = _boundary_record(way_id, tags, reasons, groups, outside, root, comps, component_ids)
            summaries[root].add(record)
    if digest.hexdigest() != state.way_digest or ways_seen != state.report["counts"].get("ways_seen", 0):
        raise ValueError("OSM way stream changed between passes; boundary report discarded.")
    return {
        "strict_audit": state.report,
        "boundary_review": {
            "selected_locations": selected,
            "example_limit_per_component": limit,
            "example_order": "touches_other_strict_components_first_then_way_id",
            "results": _boundary_results(state, selected, component_ids, summaries),
            "warnings": [
                "Only excluded ways sharing an exact node with a selected strict component are inspected; excluded-way chains are not followed.",
                "Touching another strict component is structural evidence only, not a usable connection, public-access certification, or route.",
                "Area rings and ways with stairs, indoor levels, restrictions or barriers can share nodes without providing a usable pedestrian connection.",
                "Tags retain OPL percent escapes. Every matching strict exclusion is counted, so reason counts can exceed the number of excluded ways.",
                "Examples are bounded per component; totals include all touching excluded ways. No excluded edge is added to the strict graph.",
            ],
        },
        "verification": {
            "two_pass_way_stream_matches": True,
            "way_stream_sha256": state.way_digest,
            "ways_scanned_each_pass": ways_seen,
        },
    }


def read_osmium(source: Path, consume):
    """Stream ways from the trusted environment executable; propagate failures."""
    command = ["osmium", "cat", "--object-type=way", "-f", "opl", str(source)]
    try:
        proc = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            # Inherit stderr so diagnostics cannot fill an unread pipe.
            text=True, encoding="utf-8", errors="strict", bufsize=1024 * 1024,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Missing osmium executable. Activate homereach-osm.") from exc
    with proc:
        if proc.stdout is None:
            raise RuntimeError("osmium stdout was not available")
        try:
            result = consume(proc.stdout)
        except BaseException:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            raise
        finally:
            proc.stdout.close()
        code = proc.wait()
        if code:
            raise RuntimeError(f"osmium failed with exit code {code}; see its diagnostic above")
    return result


def source_fingerprint(source: Path) -> dict:
    """Record the observed derivative; no expected derivative hash is assumed."""
    with source.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
        size = handle.seek(0, 2)
    return {"sha256": digest, "bytes": size}


def load_review_config(root: Path, config_name: str) -> tuple[Path, dict[str, int | None]]:
    config_path = (root / config_name).resolve()
    if not config_path.is_relative_to(root):
        raise ValueError("Configuration path escapes project root")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("Expected a schema_version=1 topology review configuration")
    source_name = config.get("source_pbf")
    if not isinstance(source_name, str) or not source_name:
        raise ValueError("Configuration needs a source_pbf path")
    source = (root / source_name).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise ValueError("Source missing or outside project root")
    locations = config.get("locations")
    if not isinstance(locations, list) or not locations:
        raise ValueError("Configuration needs a nonempty locations list")
    targets: dict[str, int | None] = {}
    for location in locations:
        if not isinstance(location, dict):
            raise ValueError("Each location must be an object")
        label, node = location.get("id"), location.get("node_id")
        if not isinstance(label, str) or not label or label in targets:
            raise ValueError("Location IDs must be nonempty and unique")
        if "node_id" not in location or (node is not None and (type(node) is not int or node <= 0)):
            raise ValueError(f"Location {label} needs a positive integer node_id or null")
        targets[label] = node
    return source, targets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/routing_walk_topology_review.json")
    # Use the osmium executable from the activated, trusted Conda environment.
    # Never accept an arbitrary executable path from CLI input.
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--boundary-locations", nargs="+", metavar="LOCATION_ID",
        help="Also inspect excluded ways touching these strict components (two passes)",
    )
    parser.add_argument(
        "--boundary-limit", type=int, default=20, metavar="N",
        help="Maximum displayed excluded-way examples per component (default: 20); totals stay complete",
    )
    args = parser.parse_args(argv)
    if args.boundary_limit < 1:
        parser.error("--boundary-limit must be at least 1")
    root = Path(args.project_root).resolve()
    try:
        source, targets = load_review_config(root, args.config)
        if args.boundary_locations:
            unknown = set(args.boundary_locations) - targets.keys()
            if unknown:
                raise ValueError("Unknown boundary location IDs: " + ", ".join(sorted(unknown)))
            if len(set(args.boundary_locations)) != len(args.boundary_locations):
                raise ValueError("Boundary location IDs must be unique")
            print("OSM STRICT COMPONENT BOUNDARY REVIEW — NOT A ROUTE", flush=True)
            before = source_fingerprint(source)
            print("Pass 1/2: building the unchanged strict graph; several hundred MB may be needed.", flush=True)
            state = read_osmium(source, lambda lines: build_strict_state(lines, targets, validate_ways=True))
            print("Pass 2/2: inspecting excluded ways that share exact component nodes.", flush=True)
            result = read_osmium(source, lambda lines: scan_boundary_lines(
                state, lines, args.boundary_locations, limit=args.boundary_limit,
            ))
            if source_fingerprint(source) != before:
                raise ValueError("Source changed during the audit; the report was discarded")
            result["source"] = {
                "path": source.relative_to(root).as_posix(), **before,
                "unchanged_during_audit": True, "expected_derived_sha256": None,
            }
        else:
            print("OSM STRICT WALKING COMPONENT DIAGNOSTIC — NOT A ROUTE", flush=True)
            print("Reading OSM ways; this can use several hundred MB of memory.", flush=True)
            result = read_osmium(source, lambda lines: audit_lines(lines, targets))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Topology audit failed: {exc}. No completed audit report.", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    print("Files written: 0 | Journeys computed: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
