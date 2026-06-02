"""Artifactory document connector for listing and downloading PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


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


class ArtifactoryConnector:
    """
    JFrog Artifactory connector for listing and downloading PDFs.
    
    Requirements:
    - Artifactory server (cloud or on-prem)
    - API key (from Admin → User Settings → API Key)
    - Repository name(s) to scan
    
    Future implementation will:
    1. Query Artifactory REST API
    2. List PDFs from specified repositories/paths
    3. Download to temp location for processing
    4. Track artifact version to avoid re-indexing
    """
    
    def __init__(self, base_url: str, api_key: str, repo_names: list[str]):
        """
        Initialize Artifactory connector.
        
        Args:
            base_url: https://artifactory.example.com
            api_key: Artifactory API key
            repo_names: List of repositories to scan (e.g., ["docs", "policies"])
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.repo_names = repo_names
        # TODO: Initialize HTTP client with auth
    
    def list_pdfs(self, repo: str | None = None) -> list[Document]:
        """
        List all PDFs in Artifactory repositories.
        
        Args:
            repo: Specific repository to scan (if None, scan all configured repos)
            
        Returns:
            List of Document objects with metadata
        """
        # TODO: Implement
        # 1. Use AQL (Artifactory Query Language) to find *.pdf files
        # 2. Query: items.find({"repo": "repo_name", "name": {"$match": "*.pdf"}})
        # 3. Extract: name, modified, size, download URL
        # 4. Return list of Document objects
        raise NotImplementedError("Artifactory connector not yet implemented")
    
    def download_pdf(self, doc: Document, dest: Path) -> Path:
        """
        Download a PDF from Artifactory to local path.
        
        Args:
            doc: Document object from list_pdfs()
            dest: Destination directory
            
        Returns:
            Path to downloaded file
        """
        # TODO: Implement
        # 1. Use download_url with authentication header (X-JFrog-Art-Api: api_key)
        # 2. Stream download to dest/{doc.name}
        # 3. Handle retries on network errors
        # 4. Return path
        raise NotImplementedError("Artifactory connector not yet implemented")


class ArtifactoryConnectorMock:
    """Mock connector for testing without real Artifactory access."""
    
    def list_pdfs(self, repo: str | None = None) -> list[Document]:
        """Return mock documents for testing."""
        return [
            Document(
                name="api-security.pdf",
                source_file="api-security.pdf",
                source_type="Artifactory",
                path="/docs/api-security.pdf",
                last_modified=datetime.now(),
                size_bytes=98000,
                download_url="https://artifactory.example.com/artifactory/docs/api-security.pdf",
            ),
        ]
