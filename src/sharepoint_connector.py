"""SharePoint document connector for listing and downloading PDFs."""

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


class SharePointConnector:
    """
    Placeholder for SharePoint integration.
    
    Requirements:
    - Office365-REST-Python-Client or Microsoft Graph SDK
    - Azure AD application registration
    - Tenant URL, client ID, client secret
    
    Future implementation will:
    1. Authenticate to tenant
    2. List PDFs from specified site/library
    3. Download to temp location for processing
    4. Track document version/hash to avoid re-indexing
    """
    
    def __init__(self, tenant_url: str, site_id: str, library_name: str):
        """
        Initialize SharePoint connector.
        
        Args:
            tenant_url: https://yourorg.sharepoint.com
            site_id: Site ID containing PDFs
            library_name: Document library name (e.g., "Shared Documents")
        """
        self.tenant_url = tenant_url
        self.site_id = site_id
        self.library_name = library_name
        # TODO: Initialize authentication
    
    def list_pdfs(self) -> list[Document]:
        """
        List all PDFs in the SharePoint library.
        
        Returns:
            List of Document objects with metadata
        """
        # TODO: Implement
        # 1. Use Microsoft Graph API to list items
        # 2. Filter for .pdf extension
        # 3. Extract: name, modified date, download URL
        # 4. Return list of Document objects
        raise NotImplementedError("SharePoint connector not yet implemented")
    
    def download_pdf(self, doc: Document, dest: Path) -> Path:
        """
        Download a PDF from SharePoint to local path.
        
        Args:
            doc: Document object from list_pdfs()
            dest: Destination directory
            
        Returns:
            Path to downloaded file
        """
        # TODO: Implement
        # 1. Use download_url to fetch file
        # 2. Handle authentication
        # 3. Save to dest/{doc.name}
        # 4. Return path
        raise NotImplementedError("SharePoint connector not yet implemented")


class SharePointConnectorMock:
    """Mock connector for testing without real SharePoint access."""
    
    def list_pdfs(self) -> list[Document]:
        """Return mock documents for testing."""
        return [
            Document(
                name="deployment-guide.pdf",
                source_file="deployment-guide.pdf",
                source_type="SharePoint",
                path="/Shared Documents/deployment-guide.pdf",
                last_modified=datetime.now(),
                size_bytes=125000,
                download_url="https://yourorg.sharepoint.com/.../deployment-guide.pdf",
            ),
        ]
