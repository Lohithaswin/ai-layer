import time
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.config import DOCS_DIR, ROLE_ATTR_DIR
from src.ingest import main as ingest_pdfs
from src.role_ingestor import run_ingestion as ingest_role_sql
import subprocess
import sys

class DebouncedHandler(FileSystemEventHandler):
    def __init__(self, debounce_seconds=3):
        self.debounce_seconds = debounce_seconds
        self._timers = {}
        self._lock = threading.Lock()

    def _trigger_ingest(self, target):
        try:
            if target == "docs":
                print("\n[Watcher] Detected changes in DOCS_DIR. Triggering incremental ingestion...")
                ingest_pdfs()
            elif target == "roles":
                print("\n[Watcher] Detected changes in ROLE_ATTR_DIR. Triggering role ingestion...")
                # Run the exact match SQL ingestion
                ingest_role_sql()
                # Run the vector db role ingestion (as a subprocess to avoid module conflicts)
                script_path = Path(__file__).resolve().parent.parent / "scripts" / "ingest_roles.py"
                subprocess.run([sys.executable, str(script_path)], capture_output=True)
                print("[Watcher] Role ingestion complete.")
        except Exception as e:
            print(f"[Watcher] Error during ingestion: {e}")

    def _schedule(self, target):
        with self._lock:
            # Cancel existing timer if any
            if target in self._timers:
                self._timers[target].cancel()
            
            # Start new timer
            timer = threading.Timer(self.debounce_seconds, self._trigger_ingest, args=[target])
            timer.start()
            self._timers[target] = timer

    def on_modified(self, event):
        if event.is_directory:
            return
        self._handle_event(event)

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle_event(event)
        
    def _handle_event(self, event):
        path = Path(event.src_path)
        # Skip temp files like ~$Role Attributes Doc.xlsx
        if path.name.startswith("~$") or path.name.startswith(".~"):
            return
            
        ext = path.suffix.lower()
        if ext not in [".pdf", ".xlsx", ".docx"]:
            return

        # Determine which folder it belongs to
        try:
            if str(DOCS_DIR) in str(path):
                self._schedule("docs")
            elif str(ROLE_ATTR_DIR) in str(path):
                self._schedule("roles")
        except Exception as e:
            pass


def start_watcher():
    observer = Observer()
    handler = DebouncedHandler(debounce_seconds=5)
    
    if DOCS_DIR and DOCS_DIR.exists():
        observer.schedule(handler, str(DOCS_DIR), recursive=True)
        print(f"[Watcher] Monitoring {DOCS_DIR}...")
        
    if ROLE_ATTR_DIR and ROLE_ATTR_DIR.exists():
        observer.schedule(handler, str(ROLE_ATTR_DIR), recursive=True)
        print(f"[Watcher] Monitoring {ROLE_ATTR_DIR}...")

    observer.start()
    return observer

if __name__ == "__main__":
    observer = start_watcher()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
