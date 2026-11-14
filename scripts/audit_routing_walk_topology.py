"""Read-only conservative OSM-way connectivity audit. Requires stdlib + osmium CLI.

This deliberately does NOT compute routes, snap locations, model crossings,
validate public station access, or identify wheelchair-accessible journeys.
"""
from __future__ import annotations

import argparse
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


def eligible(tags: dict[str, str]) -> bool:
    """Strict surface-footway subset; NOT a complete legal walkability model."""
    if tags.get("highway") not in WALK_TYPES:
        return False
    if tags.get("area") == "yes" or tags.get("indoor") == "yes":
        return False
    if tags.get("foot") in RESTRICTED or tags.get("access") in RESTRICTED:
        return False
    if tags.get("tunnel") not in (None, "no"):
        return False
    if tags.get("level") not in (None, "0", "0.0"):
        return False
    if tags.get("layer") not in (None, "0"):
        return False
    return True


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


def audit_lines(lines: Iterable[str], targets: dict[str, int | None]) -> dict:
    comps = Components()
    counts = Counter()
    incident: dict[int, list[int]] = {n: [] for n in targets.values() if n is not None}
    for line in lines:
        parsed = parse_way(line)
        if parsed is None:
            continue
        way_id, refs, tags = parsed
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/routing_walk_topology_review.json")
    parser.add_argument("--osmium", default="osmium", help="Path to osmium executable available in PATH")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    config_path = (root / args.config).resolve()
    if not config_path.is_relative_to(root):
        parser.error("Configuration path escapes project root")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source = (root / config["source_pbf"]).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        parser.error("Source missing or outside project root")
    targets = {x["id"]: x["node_id"] for x in config["locations"]}
    command = [args.osmium, "cat", "-f", "opl", str(source)]
    print("OSM STRICT WALKING COMPONENT DIAGNOSTIC — NOT A ROUTE", flush=True)
    print("Reading OSM ways; this can use several hundred MB of memory.", flush=True)
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace", bufsize=1024 * 1024) as proc:
            assert proc.stdout is not None
            result = audit_lines(proc.stdout, targets)
            err = proc.stderr.read() if proc.stderr is not None else ""
            code = proc.wait()
    except FileNotFoundError:
        print("Missing osmium executable. Activate homereach-osm; no audit performed.", file=sys.stderr)
        return 2
    if code:
        print("osmium failed: " + err[-2000:], file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    print("Files written: 0 | Journeys computed: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
