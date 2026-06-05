import fitz
import sys

pdf_path = r"C:\path\to\your\documents\FAT-document.pdf"
doc = fitz.open(pdf_path)
page = doc[5] # Page 6 (0-indexed is page 5)

print("=== RAW TEXT ===")
print(page.get_text())

print("\n=== BLOCKS ===")
for b in page.get_text("blocks"):
    print(f"Bbox: {b[:4]} | Text: {repr(b[4])}")

print("\n=== TABLES ===")
finder = page.find_tables()
tables = finder.tables if hasattr(finder, "tables") else []
print(f"Number of tables: {len(tables)}")
for i, t in enumerate(tables):
    print(f"\nTable {i+1} bbox: {t.bbox}")
    try:
        rows = t.extract()
        for r_idx, r in enumerate(rows):
            print(f"  Row {r_idx+1}: {r}")
    except Exception as e:
        print(f"  Failed to extract table: {e}")

doc.close()
