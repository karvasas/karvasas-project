from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User

router = APIRouter(tags=["users"])


@router.post("/switch-user")
async def switch_user_post(
    request: Request,
    user_id: int = Form(...),
    redirect_to: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    target_url = redirect_to or request.headers.get("referer") or "/"
    response = RedirectResponse(url=target_url, status_code=303)
    response.set_cookie(
        key="current_user_id",
        value=str(target_user.id),
        httponly=True,
        max_age=60 * 60 * 24 * 30,
        samesite="lax",
    )
    return response


@router.get("/switch-user/{user_id}")
async def switch_user_get(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    target_url = request.headers.get("referer") or "/"
    response = RedirectResponse(url=target_url, status_code=303)
    response.set_cookie(
        key="current_user_id",
        value=str(target_user.id),
        httponly=True,
        max_age=60 * 60 * 24 * 30,
        samesite="lax",
    )
    return response