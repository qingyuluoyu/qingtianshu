from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook
import pytest

from app.services.document_conversion import (
    DocumentConversionError,
    DocumentConversionService,
)


def _minimal_pdf() -> bytes:
    stream = b"BT /F1 12 Tf 72 720 Td (Qingshu PDF Revenue 2026) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        (
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    return bytes(payload)


def _minimal_docx() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels"
    ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>清数智算研究资料</w:t></w:r></w:p>
    <w:p><w:r><w:t>文档结论：主营业务收入保持增长。</w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>""",
        )
    return output.getvalue()


def _minimal_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Financial Data"
    sheet.append(["Metric", "2025", "2026E"])
    sheet.append(["Revenue", 120, 138])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


@pytest.mark.parametrize(
    ("name", "raw", "expected"),
    [
        ("report.pdf", _minimal_pdf(), "Revenue 2026"),
        ("report.docx", _minimal_docx(), "主营业务收入保持增长"),
        ("forecast.xlsx", _minimal_xlsx(), "Financial Data"),
    ],
)
def test_supported_documents_convert_to_markdown(
    name: str,
    raw: bytes,
    expected: str,
) -> None:
    converted = DocumentConversionService().convert(
        raw=raw,
        original_name=name,
    )

    assert expected in converted.markdown
    assert converted.suffix == f".{name.rsplit('.', 1)[1]}"


def test_rejects_extension_spoofing_and_legacy_formats() -> None:
    converter = DocumentConversionService()

    with pytest.raises(DocumentConversionError, match="不是有效的 PDF"):
        converter.convert(raw=b"not a pdf", original_name="spoofed.pdf")
    with pytest.raises(DocumentConversionError, match="仅支持"):
        converter.convert(raw=b"legacy", original_name="legacy.doc")


def test_document_uploads_enter_private_knowledge_flow(client, app) -> None:
    user = client.post("/users", json={"name": "Document Upload User"}).json()
    cases = [
        ("report.pdf", _minimal_pdf(), "application/pdf", "Revenue 2026"),
        (
            "report.docx",
            _minimal_docx(),
            (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            "主营业务收入保持增长",
        ),
        (
            "forecast.xlsx",
            _minimal_xlsx(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "Financial Data",
        ),
    ]
    uploaded = []

    for name, raw, mime_type, expected in cases:
        response = client.post(
            "/me/knowledge",
            files={"file": (name, raw, mime_type)},
        )
        assert response.status_code == 201, response.text
        document = response.json()
        uploaded.append(document)
        assert document["scope"] == "user"
        assert document["mime_type"] == mime_type
        detail = client.get(f"/me/knowledge/{document['id']}")
        assert detail.status_code == 200
        assert expected in detail.json()["content"]

        source_path = (
            Path(app.state.database.get_user(user["id"])["workspace_path"])
            / "uploads"
            / "documents"
            / f"{document['id']}{Path(name).suffix}"
        )
        assert source_path.read_bytes() == raw

    for index in range(8):
        app.state.database.upsert_knowledge_document(
            document_id=f"competing-common-{index}",
            owner_user_id=None,
            scope="common",
            title=f"主营业务收入公共资料 {index}",
            original_name=f"common-{index}.md",
            mime_type="text/markdown",
            content="主营业务收入保持增长的公共研究资料。",
            source_key=f"builtin:competing-common-{index}.md",
        )

    chat = client.post(
        "/me/chat",
        json={
            "message": "请根据我的资料说明主营业务收入保持增长的结论",
            "execute_agent": False,
        },
    )
    assert chat.status_code == 200
    assert any(
        item["document_id"] == uploaded[1]["id"]
        for item in chat.json()["knowledge"]["items"]
    )

    removed = uploaded[0]
    assert client.delete(f"/me/knowledge/{removed['id']}").status_code == 204
    source_path = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "uploads"
        / "documents"
        / f"{removed['id']}.pdf"
    )
    assert not source_path.exists()
