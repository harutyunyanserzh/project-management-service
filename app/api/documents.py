from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_document_access_or_403, get_project_access_or_403
from app.core.config import settings
from app.db.session import get_db
from app.models.document import Document
from app.models.project import ProjectAccess
from app.schemas.document import DocumentRead
from app.services import storage

router = APIRouter(tags=["documents"])

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _validate_content_type(content_type: str) -> None:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .pdf and .docx files are allowed",
        )


def _file_size(file: UploadFile) -> int:
    """Measure an upload without loading the whole file into memory."""
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    return size


def _check_storage_limit(project_id, incoming_bytes: int, replacing_bytes: int = 0) -> None:
    current_bytes = storage.project_storage_size(project_id)
    projected_bytes = current_bytes - replacing_bytes + incoming_bytes
    if projected_bytes > settings.MAX_PROJECT_STORAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Project storage limit exceeded",
        )


@router.get("/project/{project_id}/documents", response_model=list[DocumentRead])
def list_project_documents(
    access: ProjectAccess = Depends(get_project_access_or_403),
    db: Session = Depends(get_db),
) -> list[Document]:
    return db.query(Document).filter(Document.project_id == access.project_id).all()


@router.post(
    "/project/{project_id}/documents",
    response_model=list[DocumentRead],
    status_code=status.HTTP_201_CREATED,
)
def upload_project_documents(
    files: list[UploadFile],
    access: ProjectAccess = Depends(get_project_access_or_403),
    db: Session = Depends(get_db),
) -> list[Document]:
    sizes: list[int] = []
    for file in files:
        _validate_content_type(file.content_type or "")
        sizes.append(_file_size(file))

    _check_storage_limit(access.project_id, sum(sizes))

    created: list[Document] = []
    uploaded_keys: list[str] = []
    try:
        for file, size_bytes in zip(files, sizes):
            document = Document(
                project_id=access.project_id,
                uploaded_by_id=access.user_id,
                file_name=file.filename or "unnamed",
                content_type=file.content_type or "application/octet-stream",
                size_bytes=size_bytes,
                s3_key="",
            )
            db.add(document)
            db.flush()

            s3_key = storage.build_s3_key(access.project_id, document.id, document.file_name)
            storage.upload_file(s3_key, file.file, content_type=document.content_type)
            uploaded_keys.append(s3_key)
            document.s3_key = s3_key
            created.append(document)

        db.commit()
    except Exception:
        db.rollback()
        for key in uploaded_keys:
            try:
                storage.delete_file(key)
            except Exception:
                pass
        raise

    for document in created:
        db.refresh(document)
    return created


@router.get("/document/{document_id}")
def download_document(document: Document = Depends(get_document_access_or_403)) -> Response:
    try:
        contents, content_type = storage.download_file(document.s3_key)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found in storage"
        )

    return Response(
        content=contents,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{document.file_name}"'},
    )


@router.put("/document/{document_id}", response_model=DocumentRead)
def update_document(
    file: UploadFile,
    document: Document = Depends(get_document_access_or_403),
    db: Session = Depends(get_db),
) -> Document:
    _validate_content_type(file.content_type or "")
    new_size = _file_size(file)
    _check_storage_limit(document.project_id, new_size, replacing_bytes=document.size_bytes)

    old_key = document.s3_key
    new_name = file.filename or document.file_name
    new_key = storage.build_s3_key(document.project_id, document.id, new_name)

    storage.upload_file(new_key, file.file, content_type=file.content_type or document.content_type)

    document.file_name = new_name
    document.content_type = file.content_type or document.content_type
    document.size_bytes = new_size
    document.s3_key = new_key

    try:
        db.add(document)
        db.commit()
        db.refresh(document)
    except Exception:
        db.rollback()
        if new_key != old_key:
            storage.delete_file(new_key)
        raise

    if new_key != old_key:
        storage.delete_file(old_key)

    return document


@router.delete("/document/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document: Document = Depends(get_document_access_or_403),
    db: Session = Depends(get_db),
) -> None:
    storage.delete_file(document.s3_key)
    db.delete(document)
    db.commit()
