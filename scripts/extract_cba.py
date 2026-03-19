import json
import os
from pathlib import Path

from PyPDF2 import PdfReader

ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = Path("/Users/gaojunyao/Downloads/25da5eb0-15eb-11ee-b5b3-fbd321202bdf-Final-2023-NBA-Collective-Bargaining-Agreement-6-28-23.pdf")
RAW_DIR = ROOT / "data" / "cba" / "raw"
OUT_DIR = ROOT / "data" / "cba" / "parsed"

RAW_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Copy PDF into project for traceability
if PDF_PATH.exists():
    target_pdf = RAW_DIR / PDF_PATH.name
    if not target_pdf.exists():
        target_pdf.write_bytes(PDF_PATH.read_bytes())
else:
    raise FileNotFoundError(f"PDF not found: {PDF_PATH}")

reader = PdfReader(str(PDF_PATH))

paragraphs_path = OUT_DIR / "cba_paragraphs.jsonl"
page_text_path = OUT_DIR / "cba_pages.txt"

with paragraphs_path.open("w", encoding="utf-8") as para_f, page_text_path.open("w", encoding="utf-8") as page_f:
    for page_idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        # Basic cleanup
        text = text.replace("\r", "")
        page_f.write(f"\n\n=== PAGE {page_idx} ===\n\n")
        page_f.write(text)

        # Split into paragraphs by blank lines
        raw_paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        for para_idx, para in enumerate(raw_paras, start=1):
            record = {
                "page": page_idx,
                "para": para_idx,
                "text": " ".join(line.strip() for line in para.split("\n") if line.strip()),
            }
            para_f.write(json.dumps(record, ensure_ascii=False) + "\n")

print(f"Wrote: {paragraphs_path}")
print(f"Wrote: {page_text_path}")
