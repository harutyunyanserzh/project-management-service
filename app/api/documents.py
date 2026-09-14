from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_document_access_or_403, get_project_access_or_403
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
    for f in files:
        _validate_content_type(f.content_type or "")

    created: list[Document] = []
    for f in files:
        document = Document(
            project_id=access.project_id,
            uploaded_by_id=access.user_id,
            file_name=f.filename or "unnamed",
            content_type=f.content_type or "application/octet-stream",
            size_bytes=0,
            s3_key="",
        )
        db.add(document)
        db.flush()

        s3_key = storage.build_s3_key(access.project_id, document.id, document.file_name)
        contents = f.file.read()
        f.file.seek(0)
        storage.upload_file(s3_key, f.file, content_type=document.content_type)

        document.s3_key = s3_key
        document.size_bytes = len(contents)
        created.append(document)

    db.commit()
    for d in created:
        db.refresh(d)

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

    contents = file.file.read()
    file.file.seek(0)
    storage.upload_file(document.s3_key, file.file, content_type=file.content_type or "")

    document.file_name = file.filename or document.file_name
    document.content_type = file.content_type or document.content_type
    document.size_bytes = len(contents)

    db.add(document)
    db.commit()
    db.refresh(document)

    return document


@router.delete("/document/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document: Document = Depends(get_document_access_or_403),
    db: Session = Depends(get_db),
) -> None:
    storage.delete_file(document.s3_key)
    db.delete(document)
    db.commit()
