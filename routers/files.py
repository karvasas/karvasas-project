from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models import Attachment
from web import UPLOAD_DIR

router = APIRouter(tags=["files"])


@router.get("/attachments/{attachment_id}/download")
@router.get("/attachments/{attachment_id}")
async def download_attachment_by_id(
    attachment_id: int,
    db: Session = Depends(get_db),
):
    attachment = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Вложение не найдено в базе данных")

    stored_basename = Path(attachment.filepath).name
    resolved_path = (UPLOAD_DIR / stored_basename).resolve()

    if not resolved_path.is_relative_to(UPLOAD_DIR) or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Файл отсутствует на сервере")

    return FileResponse(
        path=str(resolved_path),
        filename=attachment.filename,
        media_type="application/octet-stream",
    )


@router.get("/uploads/{filename}")
async def download_file_from_uploads(
    filename: str,
    db: Session = Depends(get_db),
):
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="Некорректное имя файла")

    resolved_path = (UPLOAD_DIR / safe_name).resolve()
    if not resolved_path.is_relative_to(UPLOAD_DIR) or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")

    attachment = (
        db.query(Attachment)
        .filter(
            or_(
                Attachment.filepath == f"uploads/{safe_name}",
                Attachment.filepath == safe_name,
            )
        )
        .first()
    )
    download_name = attachment.filename if attachment else safe_name

    return FileResponse(
        path=str(resolved_path),
        filename=download_name,
        media_type="application/octet-stream",
    )