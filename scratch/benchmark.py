import fitz
import time
from pathlib import Path

docs_dir = Path("docs")
pdfs = list(docs_dir.rglob("*.pdf"))

print(f"Found {len(pdfs)} PDFs to benchmark:")
for pdf in pdfs:
    print(f" - {pdf.name} ({pdf.stat().st_size / 1024 / 1024:.2f} MB)")

for pdf in pdfs:
    print(f"\nBenchmarking {pdf.name}...")
    doc = fitz.open(str(pdf))
    num_pages = len(doc)
    print(f"Total pages: {num_pages}")
    
    # 1. Benchmark text extraction only
    t0 = time.time()
    for page in doc:
        _ = page.get_text("blocks")
    t1 = time.time()
    text_time = t1 - t0
    print(f"  Text extraction: {text_time:.3f} seconds ({text_time / num_pages * 1000:.2f} ms/page)")
    
    # 2. Benchmark find_tables
    t0 = time.time()
    num_tables_found = 0
    pages_with_tables = 0
    slow_pages = []
    
    for i, page in enumerate(doc):
        pt0 = time.time()
        try:
            finder = page.find_tables()
            tables = finder.tables if hasattr(finder, "tables") else []
            if tables:
                num_tables_found += len(tables)
                pages_with_tables += 1
        except Exception as e:
            pass
        pt1 = time.time()
        page_dur = pt1 - pt0
        if page_dur > 0.5:
            slow_pages.append((i + 1, page_dur))
            
    t1 = time.time()
    table_time = t1 - t0
    print(f"  Table extraction: {table_time:.3f} seconds ({table_time / num_pages * 1000:.2f} ms/page)")
    print(f"  Tables found: {num_tables_found} on {pages_with_tables} pages")
    if slow_pages:
        print(f"  Slow pages (>0.5s): {len(slow_pages)} pages. Top 5: {sorted(slow_pages, key=lambda x: x[1], reverse=True)[:5]}")
    
    doc.close()
