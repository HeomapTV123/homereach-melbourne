"""Exercise environment diagnostics in fresh interpreters, before any data access."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
BLOCK_IMPORT = """
import runpy
import sys

script, missing, *options = sys.argv[1:]

class MissingModule:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == missing:
            raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)

sys.meta_path.insert(0, MissingModule())
sys.argv = [script, *options]
runpy.run_path(script, run_name='__main__')
"""


def run_with_missing_module(tmp_path, missing, *options):
    return subprocess.run(
        [sys.executable, '-c', BLOCK_IMPORT,
         str(ROOT / 'scripts/check_routing_inputs.py'), missing,
         '--project-root', str(tmp_path), *options],
        capture_output=True, text=True, check=False, timeout=30,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
    )


@pytest.mark.parametrize('as_json', [False, True])
@pytest.mark.parametrize('missing', ['numpy', 'pandas'])
def test_missing_dependency_reports_interpreter_without_claiming_invalid_data(tmp_path, as_json, missing):
    result = run_with_missing_module(tmp_path, missing, *(['--json'] if as_json else []))
    assert result.returncode == 1
    if as_json:
        report = json.loads(result.stdout)
        assert report['status'] == 'environment_error'
        assert report['error'] == f'Missing Python dependency: {missing}'
        assert Path(report['python_executable']).resolve() == Path(sys.executable).resolve()
        assert 'conda run --no-capture-output -n homereach' in report['hint']
        assert result.stderr == ''
    else:
        assert f'ENVIRONMENT ERROR: Missing Python dependency: {missing}' in result.stderr
        assert sys.executable in result.stderr
        assert 'conda run --no-capture-output -n homereach' in result.stderr
        assert result.stdout == ''
    assert 'Traceback' not in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []


def test_missing_project_module_keeps_original_exception(tmp_path):
    result = run_with_missing_module(tmp_path, 'homereach.routing', '--json')
    assert result.returncode == 1
    assert result.stdout == ''
    assert "ModuleNotFoundError: No module named 'homereach.routing'" in result.stderr
    assert 'ENVIRONMENT ERROR' not in result.stderr
    assert list(tmp_path.iterdir()) == []
