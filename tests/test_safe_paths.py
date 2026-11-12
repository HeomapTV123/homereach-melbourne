"""Metadata must not redirect local pipelines outside their selected project."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from homereach.geography import lga
from homereach.io.dffh_rent import fingerprint, load_snapshot
from homereach.io.paths import contained_path, safe_filename
from homereach.transport import pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def link_to(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"This environment cannot create filesystem symlinks: {error}")


@pytest.mark.parametrize("name", ["rents 2025.xlsx", "Merri-bek.csv", ".audit.json"])
def test_portable_filename_is_preserved(name):
    assert safe_filename(name) == name


@pytest.mark.parametrize("name", [
    "../outside.xlsx", r"..\outside.xlsx", "/tmp/outside.xlsx",
    r"\\server\share\rents.xlsx", r"C:\outside.xlsx", "C:rents.xlsx",
    "rents.xlsx:stream", "CON.xlsx", "NUL", "COM1.csv", "LPT9.txt",
    "rents.xlsx.", "rents.xlsx ", "", "..", "x\x00.xlsx", None, 42,
])
def test_filename_rejects_both_platform_path_syntaxes(name):
    with pytest.raises(ValueError, match="filename"):
        safe_filename(name)


@pytest.mark.parametrize("config,loader", [
    ("rent_snapshot.json", load_snapshot), ("lga_snapshot.json", lga.load_geo_snapshot),
])
@pytest.mark.parametrize("name", ["../outside.xlsx", r"C:\outside.xlsx"])
def test_snapshot_loaders_enforce_filename_contract(tmp_path, config, loader, name):
    spec = json.loads((PROJECT_ROOT / "config" / config).read_text())
    spec["filename"] = name
    path = tmp_path / config
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="filename"):
        loader(path)


@pytest.mark.parametrize("relative", ["../outside", r"data\..\outside", "/outside"])
def test_invalid_relative_path_is_rejected_before_filesystem_resolution(tmp_path, monkeypatch, relative):
    def unexpected_resolution(*args, **kwargs):
        pytest.fail("Unsafe metadata must be rejected before filesystem resolution.")

    monkeypatch.setattr(Path, "resolve", unexpected_resolution)
    with pytest.raises(ValueError, match="filename|relative"):
        contained_path(tmp_path, relative)


def test_explicit_root_and_internal_symlink_remain_supported(tmp_path):
    root = tmp_path / "chosen project"
    root.mkdir()
    actual = root / "actual"
    actual.mkdir()
    link_to(root / "data", actual)
    path = contained_path(root, "data/new.csv")
    assert path == root / "data/new.csv"
    assert not path.exists()


def test_fingerprint_preserves_explicit_external_source_and_optional_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    external = tmp_path / "explicit-source.bin"
    content = b"unchanged audited source\x00\xff\r\n"
    external.write_bytes(content)
    assert fingerprint(external) == hashlib.sha256(content).hexdigest()
    with pytest.raises(ValueError, match="escapes"):
        fingerprint(external, root=root)
    local = root / "local.bin"
    local.write_bytes(content)
    assert fingerprint("local.bin", root=root) == fingerprint(local)
    assert external.read_bytes() == content


def test_fingerprint_rejects_symlinked_base_escape(tmp_path):
    root, external = tmp_path / "project", tmp_path / "external"
    root.mkdir()
    external.mkdir()
    (external / "source.bin").write_bytes(b"outside")
    link_to(root / "data", external)
    with pytest.raises(ValueError, match="escapes"):
        fingerprint(root / "data/source.bin", root=root)


def test_fingerprint_accepts_explicitly_selected_root_symlink(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    source = actual / "source.bin"
    source.write_bytes(b"selected project")
    selected = tmp_path / "selected"
    link_to(selected, actual)
    assert fingerprint(selected / source.name, root=selected) == fingerprint(source)


def rental_spec(root: Path) -> dict:
    spec = json.loads((PROJECT_ROOT / "config/rent_snapshot.json").read_text())
    path = root / "config/rent_snapshot.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(spec))
    return spec


@pytest.mark.parametrize("location", ["raw_base", "raw_file", "optional_base"])
def test_geography_rejects_escapes_before_reading_quality_or_probing_raw(tmp_path, location):
    root, external = tmp_path / "project", tmp_path / "external"
    spec = rental_spec(root)
    external.mkdir()
    if location == "raw_base":
        link_to(root / "data/raw/rent", external)
    elif location == "raw_file":
        source = external / "source.xlsx"
        source.write_bytes(b"outside")
        link_to(root / "data/raw/rent" / spec["filename"], source)
    else:
        link_to(root / "docs", external)
    # Quality/panel files deliberately do not exist: containment must fail first.
    with pytest.raises(ValueError, match="escapes"):
        lga.read_inputs(root, {"filename": "boundaries.zip"})


def test_geography_rejects_filename_before_reading_any_config(tmp_path):
    with pytest.raises(ValueError, match="filename"):
        lga.read_inputs(tmp_path, {"filename": r"..\outside.zip"})


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "scripts" / f"{name}.py")
    if spec is None:
        raise RuntimeError(f"Cannot load script: {name}")
    loader = spec.loader
    if loader is None:
        raise RuntimeError(f"Script has no loader: {name}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.mark.parametrize("script_name", ["build_rent_panel", "build_lga_geography"])
def test_cli_rejects_config_directory_escape_before_loading(tmp_path, monkeypatch, script_name):
    root, external = tmp_path / "project", tmp_path / "external"
    root.mkdir()
    external.mkdir()
    (root / "pyproject.toml").write_text("")
    link_to(root / "config", external)
    script = load_script(script_name)

    def unexpected_load(*args, **kwargs):
        pytest.fail("The CLI must contain the config path before opening it.")

    if script_name == "build_rent_panel":
        monkeypatch.setattr(script, "__file__", str(root / "scripts/build_rent_panel.py"))
        monkeypatch.setattr(script, "load_snapshot", unexpected_load)
        assert script.main(["--check-only"]) == 1
    else:
        monkeypatch.setattr(script, "load_geo_snapshot", unexpected_load)
        monkeypatch.setattr(sys, "argv", [script_name, "--project-root", str(root), "--check-only"])
        with pytest.raises(ValueError, match="escapes"):
            script.main()


def export_tables():
    sample = pd.DataFrame({"id": ["001"], "count": [2]})
    return ({name: sample for name in pipeline.SPATIAL_NAMES},
            {name: sample for name in pipeline.SERVICE_NAMES})


@pytest.mark.parametrize("relative", [
    "data/processed", "data/processed/transport/service",
    "data/processed/transport/service/lga_service_indicators.csv",
    "data/processed/transport/transport_pipeline_report.json",
    "data/interim/gtfs_spatial", "data/interim/gtfs_service/feed_service_summary.csv",
    "data/processed/transport/unrelated.txt",
])
@pytest.mark.parametrize("check_only", [True, False])
def test_transport_rejects_reference_and_destination_escapes_before_writes(tmp_path, relative, check_only):
    root, external = tmp_path / "project", tmp_path / "external"
    root.mkdir()
    if Path(relative).suffix:
        external.write_bytes(b"outside must remain unchanged")
    else:
        external.mkdir()
        (external / "sentinel.txt").write_bytes(b"outside must remain unchanged")
    link_to(root / relative, external)
    before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    spatial, services = export_tables()
    with pytest.raises(ValueError, match="escapes"):
        pipeline.export_outputs(root, spatial, None, services, {}, {}, check_only=check_only)
    assert sorted(str(path.relative_to(root)) for path in root.rglob("*")) == before
    sentinel = external if external.is_file() else external / "sentinel.txt"
    assert sentinel.read_bytes() == b"outside must remain unchanged"


@pytest.mark.parametrize("name", ["../outside.csv", r"..\outside.csv", "C:outside.csv"])
def test_transport_export_inventory_rejects_untrusted_keys(tmp_path, name):
    spatial, services = export_tables()
    spatial = {(name if key == pipeline.SPATIAL_NAMES[0] else key): value
               for key, value in spatial.items()}
    with pytest.raises(ValueError, match="inventory"):
        pipeline.export_outputs(tmp_path, spatial, None, services, {}, {}, check_only=False)
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("relative", [
    "config", "data/raw/transport", "data/raw/transport/gtfs.zip",
    "data/processed/geography/metro_lga_2025.gpkg",
    "data/interim/geography/geography_pipeline_report.json",
    "docs", "notebooks/reference.ipynb", "data/interim/gtfs_spatial",
    "data/interim/gtfs_service/reference.csv", "data/processed/rent_quarterly.csv",
    "data/interim/gtfs_audit/audit_summary.json",
])
def test_transport_input_paths_reject_escapes_before_content_reads(tmp_path, monkeypatch, relative):
    root, external = tmp_path / "project", tmp_path / "external"
    root.mkdir()
    if Path(relative).suffix:
        external.write_bytes(b"outside")
    else:
        external.mkdir()
    link_to(root / relative, external)

    def unexpected_read(*args, **kwargs):
        pytest.fail("Reject escaping input paths before opening configs or hashing content.")

    monkeypatch.setattr(pipeline, "load_geo_snapshot", unexpected_read)
    monkeypatch.setattr(pipeline, "sha256_file", unexpected_read)
    # Other prerequisites are intentionally absent: containment must fail first.
    with pytest.raises(ValueError, match="escapes"):
        pipeline.read_inputs(root, {})


@pytest.mark.parametrize("symlink_base", [True, False])
def test_transport_contains_config_selected_boundary_before_hashing(tmp_path, monkeypatch, symlink_base):
    root, external = tmp_path / "project", tmp_path / "external"
    geo_spec = json.loads((PROJECT_ROOT / "config/lga_snapshot.json").read_text())
    for relative in (
        "data/raw/transport/gtfs.zip", "config/lga_name_aliases_2025.csv",
        "data/processed/geography/metro_lga_2025.gpkg",
        "data/interim/geography/lga_crosswalk_2025.csv",
        "data/interim/geography/geography_pipeline_report.json", "config/gtfs_snapshot.json",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"prerequisite")
    (root / "config/lga_snapshot.json").write_text(json.dumps(geo_spec))
    external.mkdir()
    source = external / geo_spec["filename"]
    source.write_bytes(b"outside boundary")
    if symlink_base:
        link_to(root / "data/raw/geography", external)
    else:
        link_to(root / "data/raw/geography" / geo_spec["filename"], source)

    def unexpected_hash(*args, **kwargs):
        pytest.fail("The config-selected boundary must be contained before fingerprinting.")

    monkeypatch.setattr(pipeline, "sha256_file", unexpected_hash)
    with pytest.raises(ValueError, match="escapes"):
        pipeline.read_inputs(root, {})
    assert source.read_bytes() == b"outside boundary"


@pytest.mark.parametrize("relative", ["config", "config/gtfs_snapshot.json"])
def test_transport_entrypoint_contains_initial_snapshot_before_loading(tmp_path, monkeypatch, relative):
    root, external = tmp_path / "project", tmp_path / "external"
    root.mkdir()
    if Path(relative).suffix:
        external.write_text("{}")
    else:
        external.mkdir()
    link_to(root / relative, external)

    def unexpected_load(*args, **kwargs):
        pytest.fail("The transport entrypoint must contain its initial snapshot path.")

    monkeypatch.setattr(pipeline, "load_transport_snapshot", unexpected_load)
    with pytest.raises(ValueError, match="escapes"):
        pipeline.run_transport(root, check_only=True)


def test_transport_valid_inputs_preserve_inventory_and_bytes(tmp_path, monkeypatch):
    root = tmp_path / "chosen project"

    def path(relative):
        value = root / relative
        value.parent.mkdir(parents=True, exist_ok=True)
        return value

    spec = json.loads((PROJECT_ROOT / "config/gtfs_snapshot.json").read_text())
    gtfs = path("data/raw/transport/gtfs.zip")
    with ZipFile(gtfs, "w") as archive:
        for member in spec["outer_members"]:
            archive.writestr(member, b"outer-inventory fixture")
    spec["sha256"] = hashlib.sha256(gtfs.read_bytes()).hexdigest()
    path("config/gtfs_snapshot.json").write_text(json.dumps(spec))
    geo_spec = json.loads((PROJECT_ROOT / "config/lga_snapshot.json").read_text())
    boundary = path("data/raw/geography/" + geo_spec["filename"])
    boundary.write_bytes(b"boundary-reader fixture")
    geo_spec["sha256"] = hashlib.sha256(boundary.read_bytes()).hexdigest()
    path("config/lga_snapshot.json").write_text(json.dumps(geo_spec))

    codes = [str(20000 + i) for i in range(31)]
    names = [f"Area {i:02d}" for i in range(31)]
    native = gpd.GeoDataFrame(
        {pipeline.CODE: codes, pipeline.NAME: names},
        geometry=[box(145 + i / 100, -38, 145.005 + i / 100, -37.995) for i in range(31)], crs=7844,
    )
    native_path = path("data/processed/geography/metro_lga_2025.gpkg")
    native.to_file(native_path, layer="metro_lga_2025", driver="GPKG", engine="pyogrio")
    aliases = pd.DataFrame(columns=lga.ALIAS_COLUMNS).astype("string")
    aliases.to_csv(path("config/lga_name_aliases_2025.csv"), index=False)
    source_names = pd.DataFrame({"rental_area_name": names, "source_region": "Fixture region"})
    crosswalk = lga.build_crosswalk(source_names, native[[pipeline.CODE, pipeline.NAME]], aliases)
    crosswalk_path = path("data/interim/geography/lga_crosswalk_2025.csv")
    crosswalk.to_csv(crosswalk_path, index=False)
    report = {
        "boundary_snapshot": geo_spec, "check_only": False,
        "gpkg_readback_matches": True, "geojson_readback_matches": True, "csv_readback_matches": True,
        "output_sha256": {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (native_path, crosswalk_path)},
    }
    path("data/interim/geography/geography_pipeline_report.json").write_text(json.dumps(report))
    path("data/interim/gtfs_audit/audit_summary.json").write_text(json.dumps({
        "source": {"sha256": spec["sha256"]}, "source_unchanged": True,
        "proposed_service_date": spec["service_date"],
    }))
    for relative in ("docs/audit.md", "notebooks/reference.ipynb",
                     "data/interim/gtfs_spatial/reference.csv", "data/processed/rent_quarterly.csv"):
        path(relative).write_bytes(b"retained evidence")

    def audited_boundaries(source_path, received_spec):
        # Boundary-format validation has its own tests; keep this case focused
        # on input selection, real CSV/GPKG comparisons, and tracked fingerprints.
        assert source_path == boundary and received_spec == geo_spec
        return native.rename(columns={pipeline.CODE: "LGA_CODE25", pipeline.NAME: "LGA_NAME25"}), None, None

    monkeypatch.setattr(pipeline, "read_boundaries", audited_boundaries)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    source, loaded_native, loaded_crosswalk, hashes = pipeline.read_inputs(root, spec)
    assert source == gtfs
    assert loaded_native[pipeline.CODE].tolist() == codes
    assert loaded_crosswalk[pipeline.CODE].tolist() == codes
    assert hashes == {p: hashlib.sha256(content).hexdigest() for p, content in before.items()}
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
