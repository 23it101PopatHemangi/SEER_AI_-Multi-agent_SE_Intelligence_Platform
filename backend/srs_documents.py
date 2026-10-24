import io
import re
import uuid
import zipfile
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

import schemas
from database import Project, SRSDocument, get_db

router = APIRouter(prefix="/api/projects", tags=["SRS Documents"])


def _extract_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        paragraphs = []
        for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
            text = "".join(node.text or "" for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
            if text.strip():
                paragraphs.append(text.strip())
        return "\n".join(paragraphs)
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not parse DOCX file: {exc}")


def _extract_pdf(data: bytes) -> str:
    # Handles text-based PDFs without adding a heavyweight parser dependency.
    raw = data.decode("latin-1", errors="ignore")
    strings = re.findall(r"\(([^()]*)\)\s*Tj", raw)
    text = "\n".join(value.replace(r"\)", ")").replace(r"\(", "(") for value in strings)
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This PDF has no extractable text. Upload a text-based PDF or DOCX file.",
        )
    return text


def extract_text(filename: str, content_type: Optional[str], data: bytes) -> str:
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if extension in {"txt", "md", "csv", "rst"} or (content_type or "").startswith("text/"):
        text = data.decode("utf-8", errors="replace")
    elif extension == "docx" or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        text = _extract_docx(data)
    elif extension == "pdf" or content_type == "application/pdf":
        text = _extract_pdf(data)
    else:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Supported SRS formats are TXT, Markdown, DOCX, and text-based PDF.")
    text = text.replace("\x00", "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded SRS document is empty.")
    if len(text) > 2_000_000:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The SRS document is too large. Maximum extracted text is 2 MB.")
    return text


@router.post("/{project_id}/srs", response_model=schemas.SRSDocumentResponse)
async def upload_srs(
    project_id: str,
    file: UploadFile = File(...),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    data = await file.read()
    text = extract_text(file.filename or "srs.txt", file.content_type, data)
    document = SRSDocument(
        id=str(uuid.uuid4()),
        project_id=project_id,
        filename=file.filename or "srs.txt",
        content_type=file.content_type,
        extracted_text=text,
        created_by_email=x_user_email,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return schemas.SRSDocumentResponse(
        id=document.id,
        project_id=document.project_id,
        filename=document.filename,
        content_type=document.content_type,
        character_count=len(document.extracted_text),
        created_at=document.created_at,
    )


@router.get("/{project_id}/srs", response_model=list[schemas.SRSDocumentResponse])
def list_srs(project_id: str, db: Session = Depends(get_db)):
    documents = db.query(SRSDocument).filter(SRSDocument.project_id == project_id).order_by(SRSDocument.created_at.desc()).all()
    return [schemas.SRSDocumentResponse(id=d.id, project_id=d.project_id, filename=d.filename, content_type=d.content_type, character_count=len(d.extracted_text), created_at=d.created_at) for d in documents]
