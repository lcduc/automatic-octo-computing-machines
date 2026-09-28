"""
Uploaded files waiting to be ingested, kept on disk shared by the API and the worker.
"""

# Standard library imports
import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


class UploadStore:
    """
    One file per queued document, named ``<document id>.<file type>``.

    The API writes a file when an upload is accepted; the ingestion worker
    reads it and deletes it once the document is ``ready`` or ``failed``.
    Names are built only from the document's UUID and its validated file
    type, never from the client's filename.
    """

    def __init__(self, root: str):
        """
        Args:
            root: Directory holding the files (created on first write).
        """
        self._root = Path(root)

    def path_for(self, document_id: uuid.UUID, file_type: str) -> Path:
        """Where the upload of a document is stored."""
        return self._root / f"{document_id}.{file_type}"

    def save(self, document_id: uuid.UUID, file_type: str, content: bytes) -> None:
        """
        Write an upload atomically, so the worker never reads a half-written file.

        Raises:
            OSError: The file could not be written.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        target = self.path_for(document_id, file_type)
        partial = target.with_name(target.name + ".part")
        with open(partial, "wb") as handle:
            handle.write(content)
        os.replace(partial, target)
        logger.debug("Stored upload %s (%d bytes)", target.name, len(content))

    def read(self, document_id: uuid.UUID, file_type: str) -> bytes:
        """
        Bytes of a stored upload.

        Raises:
            FileNotFoundError: No file is stored for this document.
        """
        with open(self.path_for(document_id, file_type), "rb") as handle:
            return handle.read()

    def delete(self, document_id: uuid.UUID, file_type: str) -> None:
        """Remove a stored upload; a file that is already gone is not an error."""
        try:
            self.path_for(document_id, file_type).unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not delete stored upload for %s", document_id)
