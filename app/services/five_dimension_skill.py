from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from app.config import Settings


FIVE_DIMENSION_VERSION = "7.0.0"
FIVE_DIMENSION_KEYS = (
    "fundamental",
    "industry",
    "valuation",
    "technical",
    "risk",
)


class FiveDimensionSkillError(RuntimeError):
    """The trusted five-dimension Skill bundle is incomplete or invalid."""


@dataclass(frozen=True)
class DimensionSkillPrompt:
    key: str
    name: str
    version: str
    digest: str
    instructions: str
    output_schema: dict[str, Any]

    def public_metadata(self) -> dict[str, str]:
        return {
            "dimension": self.key,
            "name": self.name,
            "version": self.version,
            "digest": self.digest,
        }


class FiveDimensionSkillLoader:
    """Load the project-owned v7 five-dimension prompt bundle."""

    def __init__(
        self,
        settings: Settings,
        *,
        enabled: bool | None = None,
        path: Path | None = None,
    ) -> None:
        self.enabled = (
            settings.five_dimension_skill_enabled if enabled is None else enabled
        )
        self.path = path or settings.five_dimension_skill_path
        self._cache_key: tuple[tuple[str, int, int], ...] | None = None
        self._cached: dict[str, DimensionSkillPrompt] | None = None

    def load_all(self) -> dict[str, DimensionSkillPrompt]:
        if not self.enabled:
            raise FiveDimensionSkillError("五维分析 Skill 未启用")
        common_file = self.path / "COMMON_RUNTIME_STANDARD.md"
        required_files = [common_file]
        for dimension in FIVE_DIMENSION_KEYS:
            dimension_dir = self.path / dimension
            required_files.extend(
                (
                    dimension_dir / "SKILL.md",
                    dimension_dir / "manifest.json",
                    dimension_dir / "OUTPUT_SCHEMA.json",
                )
            )
        missing = [path for path in required_files if not path.is_file()]
        if missing:
            raise FiveDimensionSkillError(
                f"五维分析 Skill 资产缺失：{missing[0].name}"
            )

        cache_key = tuple(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size)
            for path in required_files
        )
        if cache_key == self._cache_key and self._cached is not None:
            return self._cached

        common = common_file.read_text(encoding="utf-8").strip()
        loaded: dict[str, DimensionSkillPrompt] = {}
        for dimension in FIVE_DIMENSION_KEYS:
            dimension_dir = self.path / dimension
            manifest = self._read_json(dimension_dir / "manifest.json")
            schema = self._read_json(dimension_dir / "OUTPUT_SCHEMA.json")
            version = str(manifest.get("version") or "")
            manifest_dimension = str(manifest.get("dimension") or "")
            if version != FIVE_DIMENSION_VERSION:
                raise FiveDimensionSkillError(
                    f"{dimension} Skill 版本不匹配：{version or 'missing'}"
                )
            if manifest_dimension != dimension:
                raise FiveDimensionSkillError(
                    f"{dimension} Skill 维度声明不匹配：{manifest_dimension or 'missing'}"
                )
            if not isinstance(schema, dict) or not schema:
                raise FiveDimensionSkillError(
                    f"{dimension} Skill 输出 Schema 无效"
                )
            skill_text = (dimension_dir / "SKILL.md").read_text(
                encoding="utf-8"
            ).strip()
            if not skill_text:
                raise FiveDimensionSkillError(f"{dimension} Skill 内容为空")
            instructions = (
                f"# 五维分析通用运行规范\n\n{common}\n\n"
                f"---\n\n# {dimension} 维度 Skill\n\n{skill_text}"
            )
            digest = hashlib.sha256(
                (
                    instructions
                    + "\n"
                    + json.dumps(schema, ensure_ascii=False, sort_keys=True)
                ).encode("utf-8")
            ).hexdigest()[:16]
            loaded[dimension] = DimensionSkillPrompt(
                key=dimension,
                name=str(manifest.get("name") or dimension),
                version=version,
                digest=digest,
                instructions=instructions,
                output_schema=schema,
            )
        self._cache_key = cache_key
        self._cached = loaded
        return loaded

    def public_metadata(self) -> dict[str, Any]:
        bundle = self.load_all()
        return {
            "name": "A股通用五维分析",
            "version": FIVE_DIMENSION_VERSION,
            "dimensions": [bundle[key].public_metadata() for key in FIVE_DIMENSION_KEYS],
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FiveDimensionSkillError(
                f"五维分析 Skill JSON 无法读取：{path.name}"
            ) from exc
        if not isinstance(value, dict):
            raise FiveDimensionSkillError(
                f"五维分析 Skill JSON 必须是对象：{path.name}"
            )
        return value
