"""Upload checks: type, size, signature, and zip-bomb limits."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

from django.conf import settings
from rest_framework.exceptions import ValidationError

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

EXT_FOR_KIND = {
    "pdf": {"pdf"},
    "docx": {"docx"},
    "doc": {"doc"},
    "zip": {"zip"},
    "png": {"png"},
    "jpeg": {"jpg", "jpeg"},
    "txt": {"txt"},
}


class FileRejected(ValidationError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff(data: bytes, filename: str) -> str:
    if not data:
        raise FileRejected("The file is empty.")
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise FileRejected(f"Files must be {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller.")
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if data.startswith(b"%PDF"):
        kind = "pdf"
    elif data.startswith(b"PK\x03\x04"):
        kind = "docx" if _is_docx(data) else "zip"
    elif data.startswith(b"\xd0\xcf\x11\xe0"):
        kind = "doc"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        kind = "png"
    elif data.startswith(b"\xff\xd8\xff"):
        kind = "jpeg"
    elif _looks_text(data):
        kind = "txt"
    else:
        raise FileRejected("Unrecognized file signature. Upload PDF, DOCX, DOC, TXT, or ZIP.")
    if ext not in EXT_FOR_KIND[kind]:
        raise FileRejected(f"The file extension does not match its contents ({kind}).")
    if kind in {"png", "jpeg"} and not settings.OCR_ENABLED:
        raise FileRejected("Image OCR is not enabled. Upload PDF, DOCX, DOC, or TXT, or set OCR_ENABLED=true.")
    return kind


def expand_zip(data: bytes) -> list[tuple[str, bytes]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FileRejected("The ZIP archive is invalid.") from exc
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > settings.MAX_ZIP_FILES:
        raise FileRejected("The ZIP archive contains too many files.")
    total = 0
    members: list[tuple[str, bytes]] = []
    for info in infos:
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            raise FileRejected("The ZIP archive contains an unsafe path.")
        if info.file_size > settings.MAX_ZIP_UNCOMPRESSED_BYTES:
            raise FileRejected("A file inside the ZIP archive is too large.")
        ratio = info.file_size / max(info.compress_size, 1)
        if info.file_size > 1024 * 1024 and ratio > settings.MAX_ZIP_COMPRESSION_RATIO:
            raise FileRejected("The ZIP archive exceeds the compression safety limit.")
        total += info.file_size
        if total > settings.MAX_ZIP_UNCOMPRESSED_BYTES:
            raise FileRejected("The ZIP archive exceeds the uncompressed size limit.")
        leaf = Path(name).name
        if leaf.lower().endswith(".zip"):
            raise FileRejected("Nested archives are not accepted.")
        payload = archive.read(info)
        if len(payload) != info.file_size and len(payload) > settings.MAX_ZIP_UNCOMPRESSED_BYTES:
            raise FileRejected("The ZIP archive expanded beyond the safety limit.")
        members.append((leaf, payload))
    if not members:
        raise FileRejected("The ZIP archive is empty.")
    return members


def scan_bytes(data: bytes) -> tuple[str, str]:
    if EICAR in data:
        return "infected", "The scan hook rejected this file (EICAR test signature)."
    if settings.CLAMAV_HOST:
        return _clam_scan(data)
    if settings.DEBUG or settings.ALLOW_UNSCANNED_UPLOADS or settings.SABLE_TESTING:
        return "skipped_unconfigured", "No antivirus scanner is configured."
    return "error", "Malware scanning is not configured. Set CLAMAV_HOST or ALLOW_UNSCANNED_UPLOADS=true."


def _clam_scan(data: bytes) -> tuple[str, str]:
    import socket
    import struct

    host, port = settings.CLAMAV_HOST.rsplit(":", 1)
    try:
        with socket.create_connection((host, int(port)), timeout=15) as sock:
            sock.sendall(b"zINSTREAM\0")
            view = memoryview(data)
            for offset in range(0, len(view), 65536):
                chunk = view[offset : offset + 65536]
                sock.sendall(struct.pack("!I", len(chunk)) + chunk)
            sock.sendall(struct.pack("!I", 0))
            response = sock.recv(4096).decode(errors="replace")
    except OSError:
        return "error", "The antivirus scanner is unavailable."
    if "FOUND" in response:
        return "infected", "The antivirus scanner rejected this file."
    if response.strip().endswith("OK"):
        return "clean", "clean"
    return "error", "The antivirus scanner returned an unexpected response."


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _looks_text(data: bytes) -> bool:
    if b"\x00" in data[:4096]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    sample = data[:2000]
    if not sample:
        return False
    printable = sum(1 for byte in sample if byte in b"\t\r\n" or 32 <= byte < 127 or byte >= 128)
    return printable / len(sample) > 0.9
