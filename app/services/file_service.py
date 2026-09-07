import os
import uuid
from typing import Tuple
from fastapi import HTTPException, UploadFile, status

# Allowed MIME types and extensions for candidate documents
ALLOWED_CV_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
ALLOWED_CV_MIMETYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/jpg",
}
MAX_CV_FILE_SIZE_BYTES = 100 * 1024  # 100 KB limit for CV documents


class SecureFileService:
    """Security-hardened file validation and storage handler against Path Traversal & Shell Uploads."""

    def __init__(self, upload_dir: str = "uploads/cv"):
        self.upload_dir = upload_dir
        os.makedirs(self.upload_dir, exist_ok=True)

    def validate_cv_file(self, file: UploadFile, file_bytes: bytes) -> Tuple[str, int]:
        """Validate candidate CV file size, extension, and content type."""
        # 1. Size checking
        size = len(file_bytes)
        if size > MAX_CV_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Ukuran berkas CV melebihi batas maksimal {MAX_CV_FILE_SIZE_BYTES // 1024} KB.",
            )

        # 2. Extension checking
        _, ext = os.path.splitext(file.filename or "")
        ext = ext.lower()
        if ext not in ALLOWED_CV_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Format berkas tidak diizinkan. Hanya menerima PDF, JPG, atau PNG.",
            )

        # 3. Content-Type checking
        if file.content_type and file.content_type.lower() not in ALLOWED_CV_MIMETYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"MIME type '{file.content_type}' tidak diizinkan.",
            )

        # 4. Generate random UUID filename (Path Traversal protection)
        safe_filename = f"cv_{uuid.uuid4().hex}{ext}"
        destination_path = os.path.join(self.upload_dir, safe_filename)

        with open(destination_path, "wb") as f:
            f.write(file_bytes)

        # Return relative path and size
        return f"/uploads/cv/{safe_filename}", size


file_service = SecureFileService()
