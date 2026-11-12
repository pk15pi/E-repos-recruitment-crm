"""Text extraction. OCR runs only when OCR_ENABLED is set and a page has almost no text."""

from __future__ import annotations

import io
import subprocess
import tempfile

from django.conf import settings


class TextExtractError(Exception):
    pass


def extract_document(kind: str, data: bytes) -> tuple[str, list[dict], int | None]:
    if kind == "txt":
        text = data.decode("utf-8", errors="replace")
        return text, [{"page": 1, "text": text}], 1
    if kind == "pdf":
        return _pdf(data)
    if kind == "docx":
        return _docx(data)
    if kind == "doc":
        return _doc(data)
    if kind in {"png", "jpeg"}:
        text = _ocr_image(data)
        return text, [{"page": 1, "text": text}], 1
    raise TextExtractError("This file type cannot be read.")


def _pdf(data: bytes) -> tuple[str, list[dict], int]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise TextExtractError("The PDF could not be read.") from exc
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append({"page": index, "text": text})
    if not pages:
        raise TextExtractError("The PDF has no pages.")
    if sum(len(page["text"].strip()) for page in pages) < 40:
        if not settings.OCR_ENABLED:
            raise TextExtractError(
                "No text could be extracted. The PDF may be a scan. Set OCR_ENABLED=true to read scanned pages."
            )
        ocr_pages = _ocr_pdf(data)
        if sum(len(page["text"].strip()) for page in ocr_pages) < 20:
            raise TextExtractError("OCR could not read text from this PDF.")
        pages = ocr_pages
    text = "\n\n".join(page["text"] for page in pages)
    return text, pages, len(pages)


def _docx(data: bytes) -> tuple[str, list[dict], None]:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise TextExtractError("The DOCX file could not be read.") from exc
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    text = "\n".join(parts)
    if not text.strip():
        raise TextExtractError("The DOCX file did not contain readable text.")
    return text, [{"page": None, "text": text}], None


def _doc(data: bytes) -> tuple[str, list[dict], None]:
    with tempfile.NamedTemporaryFile(suffix=".doc") as handle:
        handle.write(data)
        handle.flush()
        try:
            completed = subprocess.run(
                ["antiword", handle.name],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TextExtractError("DOC extraction is unavailable. Convert the file to DOCX or PDF.") from exc
    if completed.returncode != 0 or not completed.stdout.strip():
        raise TextExtractError("DOC extraction failed. Convert the file to DOCX or PDF.")
    text = completed.stdout.decode("utf-8", errors="replace")
    return text, [{"page": None, "text": text}], None


def _ocr_image(data: bytes) -> str:
    if not settings.OCR_ENABLED:
        raise TextExtractError("Image OCR is not enabled.")
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise TextExtractError("OCR dependencies are not installed.") from exc
    try:
        text = pytesseract.image_to_string(Image.open(io.BytesIO(data)))
    except Exception as exc:
        raise TextExtractError("OCR failed to read this image.") from exc
    if not text.strip():
        raise TextExtractError("OCR did not find text in this image.")
    return text


def _ocr_pdf(data: bytes) -> list[dict]:
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise TextExtractError("OCR dependencies are not installed.") from exc
    try:
        images = convert_from_bytes(data, dpi=200, timeout=60)
    except Exception as exc:
        raise TextExtractError("The scanned PDF could not be rendered for OCR.") from exc
    pages = []
    for index, image in enumerate(images, start=1):
        try:
            text = pytesseract.image_to_string(image)
        except Exception:
            text = ""
        pages.append({"page": index, "text": text})
    return pages


def chunk_text(pages: list[dict], size: int = 1200) -> list[dict]:
    chunks = []
    buffer = ""
    page_number = None
    for page in pages:
        page_number = page.get("page")
        for paragraph in (page.get("text") or "").splitlines():
            piece = paragraph.strip()
            if not piece:
                continue
            if len(buffer) + len(piece) + 1 > size and buffer:
                chunks.append({"page": page_number, "text": buffer})
                buffer = piece
            else:
                buffer = f"{buffer}\n{piece}".strip()
    if buffer:
        chunks.append({"page": page_number, "text": buffer})
    return chunks[:30]
