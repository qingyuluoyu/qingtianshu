from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from markitdown import MarkItDown, StreamInfo


SUPPORTED_DOCUMENT_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_OFFICE_REQUIRED_MEMBER = {
    ".docx": "word/document.xml",
    ".xlsx": "xl/workbook.xml",
}
_MAX_OFFICE_MEMBERS = 10_000
_MAX_OFFICE_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
_MAX_MARKDOWN_CHARS = 4_000_000


class DocumentConversionError(ValueError):
    """Raised when an uploaded document cannot be safely converted."""


@dataclass(frozen=True)
class ConvertedDocument:
    markdown: str
    mime_type: str
    suffix: str


class DocumentConversionService:
    """Convert a narrow allowlist of uploaded files into retrieval-ready Markdown."""

    def __init__(self) -> None:
        self._converter = MarkItDown(enable_plugins=False)

    def convert(
        self,
        *,
        raw: bytes,
        original_name: str,
    ) -> ConvertedDocument:
        safe_name = Path(original_name).name[:180]
        suffix = Path(safe_name).suffix.casefold()
        mime_type = SUPPORTED_DOCUMENT_MIME_TYPES.get(suffix)
        if mime_type is None:
            raise DocumentConversionError("仅支持 PDF、DOCX 和 XLSX 文件")

        self._validate_signature(raw, suffix)
        try:
            result = self._converter.convert_stream(
                BytesIO(raw),
                stream_info=StreamInfo(
                    mimetype=mime_type,
                    extension=suffix,
                    filename=safe_name,
                ),
            )
        except Exception as exc:
            raise DocumentConversionError(
                "文档解析失败；请确认文件未损坏、未加密且格式与扩展名一致"
            ) from exc

        markdown = str(
            getattr(result, "markdown", None)
            or getattr(result, "text_content", None)
            or ""
        ).strip()
        if not markdown:
            raise DocumentConversionError(
                "文档中没有提取到可读文字；扫描版 PDF 暂不支持 OCR"
            )
        if len(markdown) > _MAX_MARKDOWN_CHARS:
            raise DocumentConversionError("文档转换后的文字过多，请拆分后重新上传")
        return ConvertedDocument(
            markdown=markdown,
            mime_type=mime_type,
            suffix=suffix,
        )

    @staticmethod
    def _validate_signature(raw: bytes, suffix: str) -> None:
        if suffix == ".pdf":
            if not raw.startswith(b"%PDF-"):
                raise DocumentConversionError("文件内容不是有效的 PDF")
            return

        required_member = _OFFICE_REQUIRED_MEMBER[suffix]
        try:
            with ZipFile(BytesIO(raw)) as archive:
                members = archive.infolist()
                if len(members) > _MAX_OFFICE_MEMBERS:
                    raise DocumentConversionError("Office 文档包含过多内部文件")
                if sum(item.file_size for item in members) > (
                    _MAX_OFFICE_UNCOMPRESSED_BYTES
                ):
                    raise DocumentConversionError("Office 文档解压后体积过大")
                if required_member not in {item.filename for item in members}:
                    raise DocumentConversionError(
                        "文件内容与 DOCX/XLSX 扩展名不一致"
                    )
        except BadZipFile as exc:
            raise DocumentConversionError("Office 文档结构无效或已经损坏") from exc


__all__ = [
    "ConvertedDocument",
    "DocumentConversionError",
    "DocumentConversionService",
    "SUPPORTED_DOCUMENT_MIME_TYPES",
]
