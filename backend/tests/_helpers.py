import io
from pathlib import Path
import pypdf

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]


def extract_pdf_pages(pdf_bytes: bytes) -> list[str]:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return [page.extract_text() or "" for page in reader.pages]


def extract_pdf_text(pdf_bytes: bytes) -> str:
    return "".join(extract_pdf_pages(pdf_bytes))
