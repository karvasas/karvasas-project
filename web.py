import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from fsm import EVENT_BUTTONS
from models import (
    CATEGORIES,
    PRIORITIES,
    STATUS_LABELS,
    Attachment,
    History,
    Ticket,
    User,
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def parse_optional_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"none", "null", "unassigned", "all"}:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Определяет текущего пользователя из query-параметра, cookie или берет первого в БД."""
    raw_query_id = request.query_params.get("user_id") or request.query_params.get("switch_user")
    user_id = parse_optional_int(raw_query_id)

    if user_id is None:
        user_id = parse_optional_int(request.cookies.get("current_user_id"))

    if user_id is not None:
        user = db.query(User).filter(User.id == user_id).first()
        if user is not None:
            return user

    fallback_user = db.query(User).order_by(User.id.asc()).first()
    if fallback_user is None:
        raise HTTPException(
            status_code=500,
            detail="В базе данных нет ни одного пользователя. Проверьте работу seed_database().",
        )
    return fallback_user


def render_template(
    template_name: str,
    request: Request,
    db: Session,
    current_user: User,
    context: Optional[dict] = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Формирует общий контекст для всех Jinja2-шаблонов."""
    all_users = db.query(User).order_by(User.id.asc()).all()
    agents = [u for u in all_users if u.role in ("agent", "admin")]

    base_context = {
        "request": request,
        "current_user": current_user,
        "all_users": all_users,
        "agents": agents,
        "categories": CATEGORIES,
        "priorities": PRIORITIES,
        "status_labels": STATUS_LABELS,
        "event_buttons": EVENT_BUTTONS,
        "now": datetime.now(),
    }
    if context:
        base_context.update(context)

    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=base_context,
        status_code=status_code,
    )


async def save_uploaded_files(
    ticket: Ticket,
    uploaded_files: List[UploadFile],
    db: Session,
    actor: User,
    write_history: bool = True,
) -> List[Attachment]:
    """Сохраняет загруженные файлы в uploads/ и создает записи Attachment."""
    saved_attachments: List[Attachment] = []

    for upload in uploaded_files:
        if upload is None or not upload.filename:
            continue

        content = await upload.read()
        if not content:
            continue

        original_name = Path(upload.filename).name
        unique_name = f"{ticket.id}_{uuid.uuid4().hex[:8]}_{original_name}"
        destination = UPLOAD_DIR / unique_name

        with open(destination, "wb") as f:
            f.write(content)

        attachment = Attachment(
            ticket_id=ticket.id,
            filename=original_name,
            filepath=f"uploads/{unique_name}",
        )
        db.add(attachment)
        saved_attachments.append(attachment)

        if write_history:
            db.add(
                History(
                    ticket_id=ticket.id,
                    user_id=actor.id,
                    action=f"Прикреплен файл: «{original_name}»",
                    is_notification=True,
                )
            )

    return saved_attachments