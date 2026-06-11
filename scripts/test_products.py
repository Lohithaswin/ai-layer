import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from api import list_products

def main():
    print(list_products())

if __name__ == "__main__":
    main()
