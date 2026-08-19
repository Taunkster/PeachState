"""PeachState CoolChain services — minimal pure-Python PDF writer.

No external PDF dependency (reportlab/fpdf are not in the project deps),
so the synthetic report card / digest PDFs are produced with a tiny,
dependency-free writer that emits a valid single-page PDF.

The report generator renders plain text lines (title + body) using the
built-in Helvetica font. Used as the **Basic-plan fallback** when the
Premium Heat Intelligence PDF is unavailable.
"""

from __future__ import annotations

from pathlib import Path

# Letter page size (points).
_PAGE_W = 612.0
_PAGE_H = 792.0


def _esc(text: str) -> str:
    """Escape PDF string literals and keep the stream ASCII-safe."""
    out = (
        str(text)
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    return "".join(
        ch if 32 <= ord(ch) < 127 else "_" for ch in out
    )


def write_text_pdf(
    path: Path | str,
    title: str,
    lines: list[str] | None = None,
    *,
    meta: dict | None = None,
    title_size: int = 16,
    body_size: int = 10,
) -> Path:
    """Write a single-page text PDF and return the path.

    Args:
        path: destination file path.
        title: page title (rendered in a larger font).
        lines: body lines rendered top-to-bottom (font size ``body_size``).
        meta: unused metadata placeholder (kept for API symmetry with the
            Premium report generator).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = lines or []

    content = []
    content.append(
        f"BT /F1 {title_size} Tf 50 {_PAGE_H - 52} Td ({_esc(title)}) Tj ET"
    )
    y = _PAGE_H - 92
    for line in lines:
        if y < 60:
            break
        content.append(
            f"BT /F1 {body_size} Tf 50 {y} Td ({_esc(line)}) Tj ET"
        )
        y -= body_size + 6

    stream = "\n".join(content).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [3 0 R] /Count 1 >>".encode("latin-1"),
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
            f"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ).encode("latin-1"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]

    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode()
        buf += obj + b"\nendobj\n"

    xref = len(buf)
    buf += f"xref\n0 {len(objects) + 1}\n".encode()
    buf += b"0000000000 65535 f \n"
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()

    path.write_bytes(bytes(buf))
    return path


def write_report_card_pdf(
    path: Path | str,
    *,
    title: str,
    sections: dict[str, list[str]],
) -> Path:
    """Render a multi-section report card (headers + body lines)."""
    lines: list[str] = []
    for header, body in sections.items():
        lines.append(f"[{header}]")
        lines.extend(body)
        lines.append("")
    return write_text_pdf(path, title, lines)


__all__ = ["write_text_pdf", "write_report_card_pdf"]