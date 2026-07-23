"""Tests for yamlfile.py — shared atomic YAML read/write helpers."""

import os
import stat

import pytest

from agent_knots.yamlfile import atomic_write_yaml, safe_read_yaml


@pytest.fixture
def path(tmp_path):
    return tmp_path / "data.yaml"


class TestAtomicWriteYaml:
    def test_writes_readable_yaml(self, path):
        atomic_write_yaml(path, {"a": 1, "b": [1, 2, 3]})
        assert safe_read_yaml(path) == {"a": 1, "b": [1, 2, 3]}

    def test_no_leftover_tmp_file(self, path):
        atomic_write_yaml(path, {"a": 1})
        assert not path.with_suffix(".tmp").exists()

    def test_chmods_to_given_mode_by_default_0600(self, path):
        atomic_write_yaml(path, {"a": 1})
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    def test_mode_none_skips_chmod(self, path):
        # Just confirm it doesn't raise and the file is still written —
        # exact resulting permissions depend on umask, not asserted here.
        atomic_write_yaml(path, {"a": 1}, mode=None)
        assert path.exists()

    def test_overwrites_existing_file(self, path):
        atomic_write_yaml(path, {"a": 1})
        atomic_write_yaml(path, {"a": 2})
        assert safe_read_yaml(path) == {"a": 2}

    def test_sort_keys_false_by_default_preserves_insertion_order(self, path):
        atomic_write_yaml(path, {"z": 1, "a": 2})
        text = path.read_text()
        assert text.index("z:") < text.index("a:")


class TestSafeReadYaml:
    def test_missing_file_returns_default(self, path):
        assert safe_read_yaml(path) is None
        assert safe_read_yaml(path, default={}) == {}

    def test_malformed_yaml_returns_default(self, path):
        path.write_text(":\n  - this: is: not: valid: yaml: [")
        assert safe_read_yaml(path, default="fallback") == "fallback"

    def test_valid_yaml_round_trips(self, path):
        path.write_text("name: test\ncount: 3\n")
        assert safe_read_yaml(path) == {"name": "test", "count": 3}
