import hashlib
import io
import json
import re
import subprocess
import sys
import uuid

from bs4 import BeautifulSoup
from pypdf import PdfReader

from quarry.config import settings


def isolated_extract(body: bytes, media_type: str, name: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "quarry.parse_document", media_type, name],
            input=body,
            capture_output=True,
            timeout=25,
            check=False,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "PYTHONPATH": "/app",
                "LANG": "C.UTF-8",
                "QUARRY_SESSION_SECRET": "isolated-parser-without-application-credentials-0000000000",
                "QUARRY_DATA_DIR": ".",
                "QUARRY_MAX_UPLOAD_BYTES": str(settings().max_upload_bytes),
                "QUARRY_MAX_DOCUMENT_CHARS": str(settings().max_document_chars),
            },
        )
    except subprocess.TimeoutExpired:
        raise ValueError(
            "Document parsing exceeded 25 seconds; simplify or split the document"
        ) from None
    if result.returncode:
        raise ValueError("Document parser exceeded a resource limit or terminated unexpectedly")
    value = json.loads(result.stdout)
    if "error" in value:
        raise ValueError(value["error"])
    return value["text"]


def extract(body: bytes, media_type: str, name: str = "") -> str:
    if len(body) > settings().max_upload_bytes:
        raise ValueError("Document exceeds the 10 MiB upload limit")
    if media_type == "application/pdf" or name.lower().endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(body))
            if reader.is_encrypted:
                raise ValueError("Password-protected PDFs are not supported")
            if len(reader.pages) > 250:
                raise ValueError("PDF exceeds the 250-page limit")
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
            if sum(len(p) for p in pages) < 40:
                raise ValueError("No readable text found. Scanned PDFs need OCR before upload")
            text = "\f".join(pages)
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("PDF could not be parsed; upload a valid text-based PDF") from error
    elif media_type in {"text/html", "application/xhtml+xml"}:
        soup = BeautifulSoup(body, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "iframe", "form"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
    elif media_type.startswith("text/") or name.lower().endswith((".md", ".txt")):
        try:
            text = body.decode("utf-8-sig")
        except UnicodeError as error:
            raise ValueError("Text documents must use UTF-8 encoding") from error
    else:
        raise ValueError("Supported formats: text PDF, Markdown, plain text, HTML")
    text = text.replace("\x00", "").strip()
    if not text:
        raise ValueError("Document contains no readable text")
    if len(text) > settings().max_document_chars:
        raise ValueError("Extracted document exceeds 500,000 characters; split it before upload")
    return text


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def chunk_text(document_id: str, text: str) -> list[dict]:
    chunks = []
    position = 0
    for page_number, page in enumerate(text.split("\f"), 1):
        section = "Introduction"
        # Paragraph boundaries retain headings; short overlapping windows bound encoder input.
        for paragraph in re.split(r"\n\s*\n", page):
            heading = re.match(r"^#{1,6}\s+([^\n]+)", paragraph)
            if heading:
                section = heading.group(1)[:240]
            words = paragraph.split()
            for start in range(0, len(words), 136):
                window = " ".join(words[start : start + 160])
                chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{position}"))
                chunks.append(
                    {
                        "id": chunk_id,
                        "position": position,
                        "text": window,
                        "page": page_number,
                        "section": section,
                    }
                )
                position += 1
                if start + 160 >= len(words):
                    break
    return chunks
