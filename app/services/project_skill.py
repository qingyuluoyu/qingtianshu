from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from app.config import Settings


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class ProjectSkillPrompt:
    name: str
    description: str
    digest: str
    instructions: str

    def public_metadata(self) -> dict[str, str | bool]:
        return {
            "active": True,
            "name": self.name,
            "description": self.description,
            "digest": self.digest,
        }


class ProjectSkillLoader:
    """Load a trusted project-owned SKILL.md for server-side model prompts."""

    def __init__(self, settings: Settings):
        self.enabled = settings.ai_research_skill_enabled
        self.path = settings.ai_research_skill_path
        self._cache_key: tuple[tuple[str, int, int], ...] | None = None
        self._cached: ProjectSkillPrompt | None = None

    def load(self) -> ProjectSkillPrompt | None:
        if not self.enabled:
            return None
        skill_file = self.path / "SKILL.md"
        if not skill_file.is_file():
            return None
        rule_file = self.path / "references" / "rules.md"
        files = [skill_file]
        if rule_file.is_file():
            files.append(rule_file)
        cache_key = tuple(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size)
            for path in files
        )
        if cache_key == self._cache_key and self._cached is not None:
            return self._cached

        skill_text = skill_file.read_text(encoding="utf-8").strip()
        frontmatter = _FRONTMATTER_RE.match(skill_text)
        metadata_text = frontmatter.group("body") if frontmatter else ""
        name = self._metadata_value(metadata_text, "name") or self.path.name
        description = self._description_value(metadata_text)
        resources = [skill_text]
        if rule_file.is_file():
            resources.append(
                "# 老李交易体系可执行规则\n\n"
                + rule_file.read_text(encoding="utf-8").strip()
            )
        instructions = "\n\n---\n\n".join(resources)
        digest = hashlib.sha256(instructions.encode("utf-8")).hexdigest()[:16]
        self._cached = ProjectSkillPrompt(
            name=name,
            description=description,
            digest=digest,
            instructions=instructions,
        )
        self._cache_key = cache_key
        return self._cached

    @staticmethod
    def _metadata_value(frontmatter: str, key: str) -> str:
        match = re.search(
            rf"(?m)^{re.escape(key)}:\s*[\"']?(.*?)[\"']?\s*$",
            frontmatter,
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _description_value(frontmatter: str) -> str:
        scalar = ProjectSkillLoader._metadata_value(frontmatter, "description")
        if scalar and scalar != "|":
            return scalar
        match = re.search(
            r"(?ms)^description:\s*\|\s*\n(?P<value>(?:[ \t]+.*\n?)+)",
            frontmatter,
        )
        if not match:
            return ""
        return " ".join(
            line.strip()
            for line in match.group("value").splitlines()
            if line.strip()
        )
