"""Unified document manager to list PDFs from all sources."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.config import ROOT
from src.artifactory_connector import ArtifactoryConnector, ArtifactoryConnectorMock
from src.sharepoint_connector import SharePointConnector, SharePointConnectorMock


@dataclass
class Document:
    """Unified document metadata across sources."""
    name: str
    source_file: str
    source_type: str  # "SharePoint", "Artifactory", "Local"
    path: str
    last_modified: datetime
    size_bytes: int
    download_url: str | None = None
    content_hash: str = ""  # SHA256 of content (for change detection)


INDEX_PATH = ROOT / "data" / "indexed_documents.json"


@dataclass
class DocumentIndex:
    """Track indexed documents to avoid re-embedding unchanged files."""
    indexed_documents: dict[str, dict] = field(default_factory=dict)
    # Key: "{source_type}:{source_file}"
    # Value: {"content_hash": "...", "indexed_at": "...", "page_count": ...}
    
    def load(self, path: Path = INDEX_PATH) -> None:
        if path.exists():
            try:
                self.indexed_documents = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"Warning: Failed to load document index: {e}")
                self.indexed_documents = {}
        else:
            self.indexed_documents = {}
            
    def save(self, path: Path = INDEX_PATH) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.indexed_documents, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"Warning: Failed to save document index: {e}")

    def is_indexed(self, doc: Document, content_hash: str) -> bool:
        """Check if document with same hash is already indexed."""
        key = f"{doc.source_type}:{doc.source_file}"
        if key not in self.indexed_documents:
            return False
        return self.indexed_documents[key].get("content_hash") == content_hash
    
    def mark_indexed(self, doc: Document, content_hash: str, page_count: int) -> None:
        """Mark document as indexed."""
        key = f"{doc.source_type}:{doc.source_file}"
        self.indexed_documents[key] = {
            "content_hash": content_hash,
            "indexed_at": datetime.now().isoformat(),
            "page_count": page_count,
        }
    
    def remove(self, doc: Document) -> None:
        """Mark document as removed (for cleanup)."""
        key = f"{doc.source_type}:{doc.source_file}"
        if key in self.indexed_documents:
            del self.indexed_documents[key]

    def remove_by_key(self, key: str) -> None:
        """Remove document by its full key."""
        if key in self.indexed_documents:
            del self.indexed_documents[key]


class DocumentManager:
    """
    Unified manager for PDFs from multiple sources.
    
    Supports:
    - Local docs/ folder
    - SharePoint sites
    - Artifactory repositories
    
    Provides:
    - Unified listing interface
    - Change detection (avoid re-indexing unchanged docs)
    - Source metadata (for filtering/ACLs in future)
    """
    
    def __init__(
        self,
        local_docs_dir: Path | None = None,
        sharepoint: SharePointConnector | None = None,
        artifactory: ArtifactoryConnector | None = None,
        use_mocks: bool = False,
    ):
        """
        Initialize document manager.
        
        Args:
            local_docs_dir: Path to local docs/ folder
            sharepoint: SharePoint connector (or None to disable)
            artifactory: Artifactory connector (or None to disable)
            use_mocks: If True, use mock connectors for testing
        """
        self.local_docs_dir = local_docs_dir
        self.sharepoint = sharepoint or (SharePointConnectorMock() if use_mocks else None)
        self.artifactory = artifactory or (ArtifactoryConnectorMock() if use_mocks else None)
        self.index = DocumentIndex()
        self.index.load()
    
    def list_all_pdfs(self) -> list[Document]:
        """
        List all PDFs from all configured sources.
        
        Returns:
            List of Document objects (deduplicated by name)
        """
        docs = {}
        
        # List local PDFs
        if self.local_docs_dir and self.local_docs_dir.exists():
            for pdf_path in self.local_docs_dir.rglob("*.pdf"):
                try:
                    rel_path = str(pdf_path.relative_to(self.local_docs_dir.parent))
                except Exception:
                    try:
                        rel_path = str(pdf_path.relative_to(pdf_path.parents[1]))
                    except Exception:
                        rel_path = pdf_path.name
                rel_path = rel_path.replace("\\", "/") # normalize backslashes on Windows
                doc = Document(
                    name=pdf_path.name,
                    source_file=rel_path,
                    source_type="Local",
                    path=str(pdf_path),
                    last_modified=datetime.fromtimestamp(pdf_path.stat().st_mtime),
                    size_bytes=pdf_path.stat().st_size,
                )
                docs[f"Local:{rel_path}"] = doc
        
        # List SharePoint PDFs
        if self.sharepoint:
            try:
                for doc in self.sharepoint.list_pdfs():
                    key = f"{doc.source_type}:{doc.name}"
                    docs[key] = doc
            except Exception as e:
                print(f"Warning: SharePoint listing failed: {e}")
        
        # List Artifactory PDFs
        if self.artifactory:
            try:
                for doc in self.artifactory.list_pdfs():
                    key = f"{doc.source_type}:{doc.name}"
                    docs[key] = doc
            except Exception as e:
                print(f"Warning: Artifactory listing failed: {e}")
        
        return list(docs.values())
    
    def list_new_or_changed_pdfs(self) -> list[Document]:
        """
        List PDFs that are new or have been modified.
        
        Uses content hashing to detect changes efficiently.
        
        Returns:
            List of Document objects that need (re-)indexing
        """
        all_docs = self.list_all_pdfs()
        to_index = []
        
        for doc in all_docs:
            # Skip remote sources for now (would need download to hash)
            if doc.source_type != "Local":
                to_index.append(doc)
                continue
            
            # For local docs, compute hash
            if Path(doc.path).exists():
                with open(doc.path, "rb") as f:
                    content_hash = hashlib.sha256(f.read()).hexdigest()
                
                if not self.index.is_indexed(doc, content_hash):
                    doc.content_hash = content_hash
                    to_index.append(doc)
        
        return to_index
    
    def mark_ingested(self, doc: Document, page_count: int) -> None:
        """Mark document as successfully ingested."""
        self.index.mark_indexed(doc, doc.content_hash, page_count)
