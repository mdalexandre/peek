"""R9: the tests themselves keep every temp file inside the repo."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from conftest import TOOL


def test_tmpdir_fixture_points_inside_pytest_basetemp_inside_the_run_folder(
    request: pytest.FixtureRequest,
):
    """R9: gettempdir() is under --basetemp, which is inside the repo."""
    base = request.config.getoption("basetemp")
    assert base is not None, "run pytest with --basetemp=.pytest-tmp (set in pyproject addopts)"
    base_path = Path(base).resolve()
    assert base_path.is_relative_to(TOOL.resolve())
    assert Path(tempfile.gettempdir()).resolve().is_relative_to(base_path)
