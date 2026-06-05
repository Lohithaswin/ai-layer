import os
from pathlib import Path

path_str = "C:/path/to/your/Release-Documents"
p = Path(path_str)

print("Exists:", p.exists())
if p.exists():
    pdfs = list(p.rglob("*.pdf"))
    print("Number of PDFs:", len(pdfs))
    total_size = sum(f.stat().st_size for f in pdfs)
    print(f"Total size: {total_size / 1024 / 1024:.2f} MB")
    print("First 10 PDFs:")
    for f in pdfs[:10]:
        print(f"  - {f.name} ({f.stat().st_size / 1024 / 1024:.2f} MB)")
else:
    print("Directory does not exist.")
