import fitz
import sys

pdf_path = r"C:\path\to\your\documents\FAT-document.pdf"
doc = fitz.open(pdf_path)

print(f"Total pages: {len(doc)}")
for i, page in enumerate(doc):
    text = page.get_text()
    if "localhost:30004" in text or "audit logs" in text.lower() or "fat format" in text.lower():
        print(f"=== Page {i+1} ===")
        print(text[:800])
        print("-" * 50)
doc.close()
