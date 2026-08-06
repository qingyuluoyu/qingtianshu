from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from app.db import Database


_LATIN_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._+-]{1,}")
_CHINESE_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


class KnowledgeService:
    def __init__(self, database: Database, common_root: Path):
        self.database = database
        self.common_root = Path(common_root)

    def seed_common_documents(self) -> int:
        count = 0
        for path in sorted(self.common_root.glob("*.md")):
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            source_key = f"builtin:{path.name}"
            document_id = "common-" + hashlib.sha256(
                source_key.encode("utf-8")
            ).hexdigest()[:24]
            self.database.upsert_knowledge_document(
                document_id=document_id,
                owner_user_id=None,
                scope="common",
                title=self._title_from_content(content, path.stem),
                original_name=path.name,
                mime_type="text/markdown",
                content=content,
                source_key=source_key,
            )
            count += 1
        return count

    def create_user_document(
        self,
        user_id: str,
        original_name: str,
        mime_type: str,
        raw: bytes,
    ) -> dict[str, Any]:
        content = self.decode_text(raw).strip()
        if not content:
            raise ValueError("资料内容为空")
        document_id = str(uuid4())
        source_key = hashlib.sha256(raw).hexdigest()
        return self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=user_id,
            scope="user",
            title=self._title_from_content(content, Path(original_name).stem),
            original_name=Path(original_name).name[:180],
            mime_type=mime_type,
            content=content,
            source_key=source_key,
        )

    @staticmethod
    def decode_text(raw: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("资料必须是 UTF-8 或 GB18030 可读文本")

    def retrieve(
        self,
        user_id: str,
        query: str,
        max_results: int = 5,
        required_source_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        documents = self.database.list_knowledge_documents(
            user_id, include_content=True
        )
        query_tokens = self._tokens(query)
        ranked: list[dict[str, Any]] = []
        for document in documents:
            best_excerpt = ""
            best_score = 0.0
            title_tokens = self._tokens(str(document.get("title") or ""))
            title_score = len(query_tokens & title_tokens) * 4.0
            for excerpt in self._chunks(str(document.get("content") or "")):
                excerpt_tokens = self._tokens(excerpt)
                overlap = query_tokens & excerpt_tokens
                if not overlap:
                    continue
                score = title_score + sum(
                    1.0 + min(excerpt.casefold().count(token), 3) * 0.25
                    for token in overlap
                )
                if score > best_score:
                    best_score = score
                    best_excerpt = excerpt
            if best_score > 0:
                ranked.append(
                    {
                        "document_id": document["id"],
                        "title": document["title"],
                        "scope": document["scope"],
                        "source_key": document.get("source_key"),
                        "excerpt": best_excerpt[:1400],
                        "relevance_score": round(best_score, 2),
                        "updated_at": document["updated_at"],
                    }
                )
        ranked.sort(
            key=lambda item: (item["relevance_score"], item["updated_at"]),
            reverse=True,
        )
        required_items = []
        ranked_by_source = {
            item.get("source_key"): item
            for item in ranked
            if item.get("source_key")
        }
        documents_by_source = {
            item.get("source_key"): item
            for item in documents
            if item.get("source_key")
        }
        for source_key in required_source_keys or []:
            item = ranked_by_source.get(source_key)
            if item is None and source_key in documents_by_source:
                document = documents_by_source[source_key]
                chunks = self._chunks(str(document.get("content") or ""))
                item = {
                    "document_id": document["id"],
                    "title": document["title"],
                    "scope": document["scope"],
                    "source_key": document.get("source_key"),
                    "excerpt": (chunks[0] if chunks else "")[:1400],
                    "relevance_score": 0.0,
                    "updated_at": document["updated_at"],
                }
            if item is not None:
                required_items.append(item)
        required_ids = {item["document_id"] for item in required_items}
        items = (
            required_items
            + [item for item in ranked if item["document_id"] not in required_ids]
        )[:max_results]
        return {
            "query": query,
            "items": items,
            "coverage": {
                "available_documents": len(documents),
                "matched_documents": len(items),
                "common_documents": sum(
                    item.get("scope") == "common" for item in documents
                ),
                "user_documents": sum(
                    item.get("scope") == "user" for item in documents
                ),
            },
        }

    @staticmethod
    def public_document(document: dict[str, Any]) -> dict[str, Any]:
        return {
            key: document.get(key)
            for key in (
                "id",
                "scope",
                "title",
                "original_name",
                "mime_type",
                "content_chars",
                "created_at",
                "updated_at",
            )
        }

    @staticmethod
    def _title_from_content(content: str, fallback: str) -> str:
        first_line = next(
            (line.strip().lstrip("# ").strip() for line in content.splitlines() if line.strip()),
            "",
        )
        return (first_line or fallback or "未命名资料")[:160]

    @staticmethod
    def _chunks(content: str, size: int = 1400, overlap: int = 180) -> list[str]:
        normalized = re.sub(r"\n{3,}", "\n\n", content).strip()
        if not normalized:
            return []
        chunks = []
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + size)
            chunk = normalized[start:end]
            if end < len(normalized):
                boundary = max(chunk.rfind("\n\n"), chunk.rfind("。"))
                if boundary >= size // 2:
                    end = start + boundary + 1
                    chunk = normalized[start:end]
            chunks.append(chunk.strip())
            if end >= len(normalized):
                break
            start = max(start + 1, end - overlap)
        return chunks

    @staticmethod
    def _tokens(value: str) -> set[str]:
        folded = value.casefold()
        tokens = set(_LATIN_TOKEN_RE.findall(folded))
        for run in _CHINESE_RUN_RE.findall(folded):
            tokens.add(run)
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
            if len(run) >= 3:
                tokens.update(run[index : index + 3] for index in range(len(run) - 2))
        return tokens
