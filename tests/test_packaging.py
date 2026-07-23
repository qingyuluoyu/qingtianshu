from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOTS = (
    Path("app/static"),
    Path("app/skills"),
    Path("app/knowledge"),
)
PACKAGED_BRIDGE = "app/hermes_stream_bridge.py"


def _copy_build_source(destination: Path) -> None:
    shutil.copy2(PROJECT_ROOT / "pyproject.toml", destination / "pyproject.toml")
    shutil.copy2(PROJECT_ROOT / "README.md", destination / "README.md")
    shutil.copytree(
        PROJECT_ROOT / "app",
        destination / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    # Runtime storage is deliberately present: package discovery must not treat
    # an existing data directory as a second Python package on reinstall.
    runtime_data = destination / "data" / "workspaces"
    runtime_data.mkdir(parents=True)
    (runtime_data / "placeholder.txt").write_text("runtime data", encoding="utf-8")


def _expected_asset_paths() -> set[str]:
    return {
        path.relative_to(PROJECT_ROOT).as_posix()
        for root in ASSET_ROOTS
        for path in (PROJECT_ROOT / root).rglob("*")
        if path.is_file()
    }


def _sdist_members(archive: Path) -> set[str]:
    with tarfile.open(archive, "r:gz") as bundle:
        return {
            "/".join(Path(name).parts[1:])
            for name in bundle.getnames()
            if len(Path(name).parts) > 1
        }


def _wheel_members(archive: Path) -> set[str]:
    with zipfile.ZipFile(archive) as bundle:
        return set(bundle.namelist())


def test_distribution_builds_with_runtime_data_and_contains_product_assets(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    assert uv is not None, "packaging regression test requires the project uv tool"

    source = tmp_path / "source"
    source.mkdir()
    _copy_build_source(source)
    output = tmp_path / "dist"

    result = subprocess.run(
        [uv, "build", "--out-dir", str(output), str(source)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    wheels = list(output.glob("*.whl"))
    sdists = list(output.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1

    expected_assets = _expected_asset_paths()
    assert expected_assets

    wheel_members = _wheel_members(wheels[0])
    sdist_members = _sdist_members(sdists[0])
    assert expected_assets <= wheel_members
    assert expected_assets <= sdist_members
    assert PACKAGED_BRIDGE in wheel_members
    assert PACKAGED_BRIDGE in sdist_members
    assert not any(member.startswith("data/") for member in wheel_members)
    assert not any(member.startswith("data/") for member in sdist_members)
