"""Run golden retrieval tests (no pytest required)."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("USE_RERANKER", "false")

from tests.test_golden_retrieval import test_golden_retrieval_recall

if __name__ == "__main__":
    test_golden_retrieval_recall()
    print("OK — golden retrieval tests passed.")
