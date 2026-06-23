"""
Lightweight file-change queue writer.

This replaces the real-time ingestion watcher. Instead of triggering heavy
ingestion immediately (which would block the bot), it simply appends newly
detected file paths to a JSON queue file at data/pending_ingest.json.

The actual ingestion is done nightly by scripts/nightly_ingest.ps1 (Windows
Task Scheduler) or scripts/nightly_ingest.sh (Linux cron). This keeps bot
response time completely unaffected.

Run standalone to start monitoring:
    python -m src.file_queue_watcher
"""

import json
import time
import threading
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.config import DOCS_DIR, ROLE_ATTR_DIR

# Queue file — the nightly job reads and clears this
QUEUE_FILE = Path(__file__).resolve().parent.parent / "data" / "pending_ingest.json"

WATCHED_EXTENSIONS = {".pdf", ".xlsx", ".docx"}
SKIP_PREFIXES = ("~$", ".~", ".")   # temp files (Word/Excel drafts, hidden)


def _load_queue() -> dict:
    """Load the current pending queue from disk."""
    try:
        if QUEUE_FILE.exists():
            return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"pending_docs": [], "pending_roles": [], "last_updated": None}


def _save_queue(q: dict) -> None:
    """Persist queue to disk atomically."""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(q, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(QUEUE_FILE)


def queue_file(path: Path, kind: str) -> None:
    """
    Add a file to the nightly ingestion queue.
    kind = 'docs' | 'roles'
    Skips duplicates.
    """
    key = "pending_docs" if kind == "docs" else "pending_roles"
    q = _load_queue()
    str_path = str(path)
    if str_path not in q[key]:
        q[key].append(str_path)
        q["last_updated"] = datetime.now().isoformat()
        _save_queue(q)
        print(f"[FileQueue] Queued for nightly ingest ({kind}): {path.name}")


class QueueWriterHandler(FileSystemEventHandler):
    """Watches folders and queues changed files — does NO ingestion itself."""

    def __init__(self):
        self._lock = threading.Lock()
        self._debounce: dict[str, float] = {}
        self._debounce_secs = 3.0    # avoid bursts from OneDrive sync

    def _handle(self, path: Path, kind: str) -> None:
        now = time.monotonic()
        key = str(path)
        with self._lock:
            last = self._debounce.get(key, 0)
            if now - last < self._debounce_secs:
                return
            self._debounce[key] = now
        queue_file(path, kind)

    def _classify(self, src_path: str):
        path = Path(src_path)
        # Skip temp / hidden files
        if any(path.name.startswith(p) for p in SKIP_PREFIXES):
            return None, None
        if path.suffix.lower() not in WATCHED_EXTENSIONS:
            return None, None
        try:
            if DOCS_DIR and str(DOCS_DIR) in str(path):
                return path, "docs"
            if ROLE_ATTR_DIR and str(ROLE_ATTR_DIR) in str(path):
                return path, "roles"
        except Exception:
            pass
        return None, None

    def on_created(self, event):
        if not event.is_directory:
            path, kind = self._classify(event.src_path)
            if path:
                self._handle(path, kind)

    def on_modified(self, event):
        if not event.is_directory:
            path, kind = self._classify(event.src_path)
            if path:
                self._handle(path, kind)

    def on_moved(self, event):
        if not event.is_directory:
            path, kind = self._classify(event.dest_path)
            if path:
                self._handle(path, kind)


def start_queue_watcher() -> Observer:
    """Start the lightweight file-queue watcher. Returns the Observer."""
    observer = Observer()
    handler = QueueWriterHandler()
    watched = 0

    if DOCS_DIR and DOCS_DIR.exists():
        observer.schedule(handler, str(DOCS_DIR), recursive=True)
        print(f"[FileQueue] Monitoring DOCS_DIR: {DOCS_DIR}")
        watched += 1

    if ROLE_ATTR_DIR and ROLE_ATTR_DIR.exists():
        observer.schedule(handler, str(ROLE_ATTR_DIR), recursive=True)
        print(f"[FileQueue] Monitoring ROLE_ATTR_DIR: {ROLE_ATTR_DIR}")
        watched += 1

    if watched == 0:
        print("[FileQueue] Warning: No watch folders exist — watcher inactive.")

    print(f"[FileQueue] Queue file: {QUEUE_FILE}")
    print("[FileQueue] Watcher started. New files will be queued for nightly ingestion.")
    observer.start()
    return observer


if __name__ == "__main__":
    observer = start_queue_watcher()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    print("[FileQueue] Watcher stopped.")
