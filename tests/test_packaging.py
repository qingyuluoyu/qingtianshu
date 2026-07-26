from __future__ import annotations

from pathlib import Path


def test_pyproject_limits_setuptools_package_discovery_to_app() -> None:
    text = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.setuptools.packages.find]" in text
    assert 'include = ["app*"]' in text


def test_pyproject_packages_versioned_five_dimension_skill_assets() -> None:
    text = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.setuptools.package-data]" in text
    assert "skills/a_share_five_dimension_v7" in text
