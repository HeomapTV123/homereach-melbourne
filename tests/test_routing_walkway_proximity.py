"""Small fictional fixtures for the preliminary walkway audit."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'audit_routing_walkway_proximity.py'
spec = importlib.util.spec_from_file_location('walkway_audit', SCRIPT)
audit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_mod)


def test_foot_permissions_and_hard_exclusions():
    assert audit_mod.potentially_walkable({'highway': 'footway'})
    assert not audit_mod.potentially_walkable({'highway': 'motorway'})
    assert not audit_mod.potentially_walkable({'highway': 'footway', 'foot': 'no'})
    assert not audit_mod.potentially_walkable({'highway': 'residential', 'access': 'private'})
    assert audit_mod.potentially_walkable({'highway': 'footway', 'access': 'private', 'foot': 'yes'})
    assert not audit_mod.potentially_walkable({'highway': 'cycleway'})


def test_distance_uses_segment_not_only_vertices():
    dist = audit_mod.linestring_distance_m(0.0, 0.0, [[-0.001, 0.0], [0.001, 0.0]])
    assert dist == pytest.approx(0.0, abs=1e-6)
    dist2 = audit_mod.linestring_distance_m(0.001, 0.0, [[-0.001, 0.0], [0.001, 0.0]])
    assert 110 <= dist2 <= 112


def test_streaming_audit_filters_and_keeps_nearest():
    def line(ident, highway, y):
        return json.dumps({'type':'Feature', 'geometry':{'type':'LineString','coordinates':[[-0.001,y],[0.001,y]]}, 'properties':{'@id':ident,'highway':highway}})
    stream = io.StringIO('\x1e'+line(1,'motorway',0.0)+'\n'+line(2,'footway',0.0001)+'\n'+line(3,'residential',0.0002)+'\n')
    total, considered, output = audit_mod.audit(stream, [{'id':'test','latitude':0,'longitude':0}], 50, 1)
    assert (total, considered) == (3, 2)
    assert len(output['test']) == 1 and output['test'][0]['osm_way'] == 2
