"""The catalogue is sharded into one YAML file per auth mode.

These tests guard the invariants the sharding relies on: every file holds only
its own auth mode, ids are unique across files, and a connector id resolves the
same however the catalogue is spelled on disk.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from connector_manager import AuthMode, ConnectorRegistry
from connector_manager.registry import CONNECTORS_DIR, _load_definitions

REPO_ROOT = Path(__file__).resolve().parent.parent
SPLIT_SCRIPT = REPO_ROOT / "scripts" / "split_connectors.py"


@pytest.fixture(scope="module")
def registry() -> ConnectorRegistry:
    return ConnectorRegistry()


@pytest.fixture(scope="module")
def shards() -> dict[Path, dict]:
    return {path: yaml.safe_load(path.read_text(encoding="utf-8")) or {} for path in sorted(CONNECTORS_DIR.glob("*.yaml"))}


def test_catalogue_is_sharded(shards: dict[Path, dict]) -> None:
    assert CONNECTORS_DIR.is_dir(), "expected a data/connectors/ directory"
    assert len(shards) > 1, "expected the catalogue split across several files"
    # The names the split script derives from the auth modes.
    assert {"api-key.yaml", "oauth2.yaml", "basic.yaml"} <= {p.name for p in shards}


def test_no_file_is_oversized(shards: dict[Path, dict]) -> None:
    """The point of the split: no single file back near the old 840 KB."""
    for path in shards:
        size_kb = path.stat().st_size / 1024
        assert size_kb < 512, f"{path.name} is {size_kb:.0f} KB -- shard it further"


def test_ids_are_unique_across_shards(shards: dict[Path, dict]) -> None:
    seen: dict[str, Path] = {}
    for path, entries in shards.items():
        for key in entries:
            assert key not in seen, f"{key} appears in both {seen[key].name} and {path.name}"
            seen[key] = path


def test_every_shard_holds_only_its_own_auth_mode(shards: dict[Path, dict], registry: ConnectorRegistry) -> None:
    for path, entries in shards.items():
        expected = AuthMode.parse(path.stem.upper().replace("-", "_"))
        for key in entries:
            # Compare against the resolved mode: aliases inherit their target's.
            assert registry.get(key).auth_mode is expected, f"{key} is in {path.name} but resolves to {registry.get(key).auth_mode.value}"


def test_shards_are_sorted_by_connector_id(shards: dict[Path, dict]) -> None:
    for path, entries in shards.items():
        assert list(entries) == sorted(entries), f"{path.name} is not sorted by connector id"


def test_split_script_reports_no_drift() -> None:
    """Regrouping the catalogue must be a no-op -- otherwise a file is stale."""
    result = subprocess.run(
        [sys.executable, str(SPLIT_SCRIPT), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_a_single_file_catalogue_still_loads(tmp_path: Path, registry: ConnectorRegistry) -> None:
    """Back-compat: pre-0.1.3 bundles and custom catalogues are one file."""
    merged = {}
    for path in sorted(CONNECTORS_DIR.glob("*.yaml")):
        merged.update(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    single = tmp_path / "connectors.yaml"
    single.write_text(yaml.safe_dump(merged, sort_keys=True, allow_unicode=True, width=10**9), encoding="utf-8")

    from_file = ConnectorRegistry(connectors_file=single)
    assert len(from_file) == len(registry)
    assert from_file.raw("slack") == registry.raw("slack")
    assert from_file.connectors_file == single


def test_duplicate_ids_across_files_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("dup:\n  auth_mode: API_KEY\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("dup:\n  auth_mode: BASIC\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate connector id"):
        _load_definitions(tmp_path)


def test_alias_chains_resolve_regardless_of_file_order(tmp_path: Path) -> None:
    """google-calendar-mcp -> google-calendar -> google spans three files."""
    # Written so the alphabetical merge order puts the target file *last*.
    (tmp_path / "z-target.yaml").write_text(
        "root:\n  auth_mode: OAUTH2\n  display_name: Root\n  categories: [x]\n", encoding="utf-8"
    )
    (tmp_path / "m-middle.yaml").write_text("middle:\n  alias: root\n  display_name: Middle\n", encoding="utf-8")
    (tmp_path / "a-leaf.yaml").write_text("leaf:\n  alias: middle\n  display_name: Leaf\n", encoding="utf-8")

    entries = _load_definitions(tmp_path)
    assert entries["leaf"]["auth_mode"] == "OAUTH2"
    assert entries["leaf"]["display_name"] == "Leaf"
    assert entries["middle"]["auth_mode"] == "OAUTH2"


def test_alias_cycle_does_not_hang(tmp_path: Path) -> None:
    (tmp_path / "cycle.yaml").write_text("a:\n  alias: b\nb:\n  alias: a\n", encoding="utf-8")
    entries = _load_definitions(tmp_path)
    assert set(entries) == {"a", "b"}


def test_dangling_alias_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "dangling.yaml").write_text("orphan:\n  alias: nowhere\n  auth_mode: API_KEY\n", encoding="utf-8")
    entries = _load_definitions(tmp_path)
    assert entries["orphan"]["auth_mode"] == "API_KEY"
