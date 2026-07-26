from __future__ import annotations

import json

import pytest

from app.services.five_dimension_skill import (
    FiveDimensionSkillError,
    FiveDimensionSkillLoader,
)


EXPECTED_DIMENSIONS = [
    "fundamental",
    "industry",
    "valuation",
    "technical",
    "risk",
]


def test_five_dimension_loader_reads_complete_v7_bundle(settings):
    bundle = FiveDimensionSkillLoader(settings).load_all()

    assert list(bundle) == EXPECTED_DIMENSIONS
    assert {item.version for item in bundle.values()} == {"7.0.0"}
    assert all(item.instructions for item in bundle.values())
    assert all(item.output_schema for item in bundle.values())
    assert all(len(item.digest) == 16 for item in bundle.values())


def test_five_dimension_public_metadata_hides_private_prompts(settings):
    metadata = FiveDimensionSkillLoader(settings).public_metadata()
    encoded = json.dumps(metadata, ensure_ascii=False)

    assert metadata["name"] == "A股通用五维分析"
    assert metadata["version"] == "7.0.0"
    assert [item["dimension"] for item in metadata["dimensions"]] == EXPECTED_DIMENSIONS
    assert "instructions" not in encoded
    assert "output_schema" not in encoded


def test_five_dimension_loader_fails_closed_when_bundle_is_missing(settings, tmp_path):
    missing = tmp_path / "missing-five-dimension-bundle"
    loader = FiveDimensionSkillLoader(
        settings,
        enabled=True,
        path=missing,
    )

    with pytest.raises(FiveDimensionSkillError, match="Skill"):
        loader.load_all()
