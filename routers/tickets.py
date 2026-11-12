from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from database import get_db
from fsm import TicketStateMachine, trigger_ticket_event
from models import (
    CATEGORIES,
    PRIORITIES,
    STATUS_LABELS,
    Comment,
    History,
    Ticket,
    User,
    calculate_sla_deadline,
)
from web import (
    get_current_user,
    parse_optional_int,
    render_template,
    save_uploaded_files,
)

router = APIRouter(tags=["tickets"])


@router.get("/", response_class=HTMLResponse)
@router.get("/tickets", response_class=HTMLResponse)
async def list_tickets(
    request: Request,
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    assignee_id: Optional[str] = Query(None),
    creator_id: Optional[str] = Query(None),
    overdue: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    msg: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Ticket).options(
        joinedload(Ticket.creator),
        joinedload(Ticket.assignee),
        joinedload(Ticket.attachments),
        joinedload(Ticket.comments),
    )

    clean_status = status.strip() if status and status.strip() else None
    clean_priority = priority.strip() if priority and priority.strip() else None
    clean_category = category.strip() if category and category.strip() else None
    clean_q = q.strip() if q and q.strip() else None

    if clean_status and clean_status in STATUS_LABELS:
        query = query.filter(Ticket.status == clean_status)

    if clean_priority and clean_priority in PRIORITIES:
        query = query.filter(Ticket.priority == clean_priority)

    if clean_category:
        query = query.filter(Ticket.category == clean_category)

    if assignee_id is not None and assignee_id.strip():
        if assignee_id.strip().lower() == "unassigned":
            query = query.filter(Ticket.assignee_id.is_(None))
        else:
            parsed_assignee = parse_optional_int(assignee_id)
            if parsed_assignee is not None:
                query = query.filter(Ticket.assignee_id == parsed_assignee)

    parsed_creator = parse_optional_int(creator_id)
    if parsed_creator is not None:
        query = query.filter(Ticket.creator_id == parsed_creator)

    if overdue and overdue.strip().lower() in {"1", "true", "yes", "on"}:
        query = query.filter(Ticket.is_overdue.is_(True))

    if clean_q:
        search_pattern = f"%{clean_q}%"
        query = query.filter(
            or_(
                Ticket.title.ilike(search_pattern),
                Ticket.description.ilike(search_pattern),
            )
        )

    tickets = query.order_by(Ticket.is_overdue.desc(), Ticket.created_at.desc()).all()

    filters = {
        "status": clean_status or "",
        "priority": clean_priority or "",
        "category": clean_category or "",
        "assignee_id": assignee_id.strip() if assignee_id else "",
        "creator_id": str(parsed_creator) if parsed_creator is not None else "",
        "overdue": "1" if (overdue and overdue.strip().lower() in {"1", "true", "yes", "on"}) else "",
        "q": clean_q or "",
    }

    return render_template(
        "index.html",
        request=request,
        db=db,
        current_user=current_user,
        context={
            "tickets": tickets,
            "filters": filters,
            "msg": msg,
            "error": error,
        },
    )


@router.get("/tickets/create", response_class=HTMLResponse)
@router.get("/create", response_class=HTMLResponse)
async def create_ticket_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return render_template(
        "create.html",
        request=request,
        db=db,
        current_user=current_user,
        context={"error": None, "form_data": {}},
    )


@router.post("/tickets/create", response_class=HTMLResponse)
@router.post("/create", response_class=HTMLResponse)
async def create_ticket_submit(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    category: str = Form(...),
    priority: str = Form("medium"),
    assignee_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    files: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    clean_title = title.strip()
    clean_description = description.strip()
    clean_category = category.strip() if category else CATEGORIES[0]
    clean_priority = priority if priority in PRIORITIES else "medium"

    if not clean_title or not clean_description:
        return render_template(
            "create.html",
            request=request,
            db=db,
            current_user=current_user,
            status_code=400,
            context={
                "error": "Заголовок и описание заявки не могут быть пустыми.",
                "form_data": {
                    "title": title,
                    "description": description,
                    "category": clean_category,
                    "priority": clean_priority,
                    "assignee_id": assignee_id or "",
                },
            },
        )

    parsed_assignee_id = parse_optional_int(assignee_id)
    if parsed_assignee_id is not None:
        assignee_exists = db.query(User.id).filter(User.id == parsed_assignee_id).first()
        if not assignee_exists:
            parsed_assignee_id = None

    now = datetime.now()
    sla_deadline = calculate_sla_deadline(clean_priority, from_time=now)

    new_ticket = Ticket(
        title=clean_title,
        description=clean_description,
        category=clean_category,
        priority=clean_priority,
        status="new",
        creator_id=current_user.id,
        assignee_id=parsed_assignee_id,
        sla_deadline=sla_deadline,
        is_overdue=False,
        created_at=now,
        updated_at=now,
    )
    db.add(new_ticket)
    db.flush()

    priority_label = PRIORITIES[clean_priority]["label"]
    db.add(
        History(
            ticket_id=new_ticket.id,
            user_id=current_user.id,
            action=(
                f"Заявка создана пользователем {current_user.full_name} "
                f"(категория: «{clean_category}», приоритет: «{priority_label}», "
                f"SLA до {sla_deadline.strftime('%d.%m.%Y %H:%M')})"
            ),
            is_notification=True,
        )
    )

    if parsed_assignee_id is not None:
        assigned_user = db.query(User).filter(User.id == parsed_assignee_id).first()
        if assigned_user:
            db.add(
                History(
                    ticket_id=new_ticket.id,
                    user_id=current_user.id,
                    action=f"При создании назначен исполнитель: {assigned_user.full_name}",
                    is_notification=True,
                )
            )

    all_uploads: List[UploadFile] = []
    if file is not None and file.filename:
        all_uploads.append(file)
    if files:
        all_uploads.extend([f for f in files if f is not None and f.filename])

    if all_uploads:
        await save_uploaded_files(
            ticket=new_ticket,
            uploaded_files=all_uploads,
            db=db,
            actor=current_user,
            write_history=True,
        )

    db.commit()

    success_msg = quote("Заявка успешно создана")
    return RedirectResponse(url=f"/tickets/{new_ticket.id}?msg={success_msg}", status_code=303)


@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
async def ticket_detail(
    ticket_id: int,
    request: Request,
    msg: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = (
        db.query(Ticket)
        .options(
            joinedload(Ticket.creator),
            joinedload(Ticket.assignee),
            joinedload(Ticket.comments).joinedload(Comment.user),
            joinedload(Ticket.attachments),
            joinedload(Ticket.history).joinedload(History.user),
        )
        .filter(Ticket.id == ticket_id)
        .first()
    )

    if ticket is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    state_machine = TicketStateMachine(ticket, db=db, actor_id=current_user.id)
    available_actions = state_machine.get_available_actions()

    return render_template(
        "detail.html",
        request=request,
        db=db,
        current_user=current_user,
        context={
            "ticket": ticket,
            "available_actions": available_actions,
            "msg": msg,
            "error": error,
        },
    )


@router.post("/tickets/{ticket_id}/transition")
@router.post("/tickets/{ticket_id}/action")
async def ticket_transition(
    ticket_id: int,
    event: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "client" and event.strip() not in ("close_ticket", "reopen"):
        err = quote("Клиент может только подтвердить закрытие или переоткрыть решенную заявку")
        return RedirectResponse(url=f"/tickets/{ticket_id}?error={err}", status_code=303)

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    success, message = trigger_ticket_event(
        ticket=ticket,
        event_name=event.strip(),
        db=db,
        actor_id=current_user.id,
    )

    if success:
        return RedirectResponse(url=f"/tickets/{ticket_id}?msg={quote(message)}", status_code=303)
    return RedirectResponse(url=f"/tickets/{ticket_id}?error={quote(message)}", status_code=303)


@router.post("/tickets/{ticket_id}/assign")
async def ticket_assign(
    ticket_id: int,
    assignee_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "client":
        err = quote("Клиент не может назначать исполнителей")
        return RedirectResponse(url=f"/tickets/{ticket_id}?error={err}", status_code=303)

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    raw_val = (assignee_id or "").strip()

    if raw_val.lower() == "self":
        new_assignee = current_user
    elif not raw_val or raw_val.lower() in {"none", "unassigned", "0"}:
        new_assignee = None
    else:
        parsed_id = parse_optional_int(raw_val)
        new_assignee = db.query(User).filter(User.id == parsed_id).first() if parsed_id else None
        if new_assignee is None:
            err = quote("Выбранный исполнитель не найден")
            return RedirectResponse(url=f"/tickets/{ticket_id}?error={err}", status_code=303)

    new_assignee_id = new_assignee.id if new_assignee else None
    if ticket.assignee_id == new_assignee_id:
        info = quote("Исполнитель не изменился")
        return RedirectResponse(url=f"/tickets/{ticket_id}?msg={info}", status_code=303)

    ticket.assignee_id = new_assignee_id
    ticket.updated_at = datetime.now()

    action_text = (
        f"Назначен исполнитель: {new_assignee.full_name}"
        if new_assignee is not None
        else "Исполнитель снят с заявки"
    )

    db.add(
        History(
            ticket_id=ticket.id,
            user_id=current_user.id,
            action=action_text,
            is_notification=True,
        )
    )
    db.commit()

    return RedirectResponse(url=f"/tickets/{ticket_id}?msg={quote(action_text)}", status_code=303)


@router.post("/tickets/{ticket_id}/comments")
async def add_ticket_comment(
    ticket_id: int,
    text: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    clean_text = text.strip()
    if not clean_text:
        err = quote("Текст комментария не может быть пустым")
        return RedirectResponse(url=f"/tickets/{ticket_id}?error={err}", status_code=303)

    comment = Comment(
        ticket_id=ticket.id,
        user_id=current_user.id,
        text=clean_text,
        created_at=datetime.now(),
    )
    ticket.updated_at = datetime.now()

    db.add(comment)
    db.add(
        History(
            ticket_id=ticket.id,
            user_id=current_user.id,
            action=f"Добавлен комментарий от {current_user.full_name}",
            is_notification=True,
        )
    )
    db.commit()

    return RedirectResponse(url=f"/tickets/{ticket_id}?msg={quote('Комментарий добавлен')}", status_code=303)


@router.post("/tickets/{ticket_id}/attachments")
@router.post("/tickets/{ticket_id}/upload")
async def upload_ticket_attachment(
    ticket_id: int,
    file: Optional[UploadFile] = File(None),
    files: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    all_uploads: List[UploadFile] = []
    if file is not None and file.filename:
        all_uploads.append(file)
    if files:
        all_uploads.extend([f for f in files if f is not None and f.filename])

    if not all_uploads:
        err = quote("Файл для загрузки не выбран")
        return RedirectResponse(url=f"/tickets/{ticket_id}?error={err}", status_code=303)

    saved = await save_uploaded_files(
        ticket=ticket,
        uploaded_files=all_uploads,
        db=db,
        actor=current_user,
        write_history=True,
    )

    if not saved:
        err = quote("Не удалось сохранить файл (возможно, файл пустой)")
        return RedirectResponse(url=f"/tickets/{ticket_id}?error={err}", status_code=303)

    ticket.updated_at = datetime.now()
    db.commit()

    ok = quote(f"Загружено файлов: {len(saved)}")
    return RedirectResponse(url=f"/tickets/{ticket_id}?msg={ok}", status_code=303)

