from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import CATEGORIES, PRIORITIES, STATUS_LABELS, History, Ticket, User
from web import get_current_user, render_template

router = APIRouter(tags=["stats"])


@router.get("/stats", response_class=HTMLResponse)
async def statistics_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    all_tickets = (
        db.query(Ticket)
        .options(
            joinedload(Ticket.assignee),
            joinedload(Ticket.creator),
        )
        .all()
    )
    all_users = db.query(User).order_by(User.id.asc()).all()

    total_tickets = len(all_tickets)
    open_tickets = sum(1 for t in all_tickets if t.status not in ("resolved", "closed"))
    in_progress_tickets = sum(1 for t in all_tickets if t.status == "in_progress")
    resolved_tickets = sum(1 for t in all_tickets if t.status in ("resolved", "closed"))
    overdue_tickets = sum(1 for t in all_tickets if t.is_overdue)
    active_overdue_tickets = sum(
        1 for t in all_tickets if t.is_overdue and t.status not in ("resolved", "closed")
    )

    sla_compliance_rate = (
        round(((total_tickets - overdue_tickets) / total_tickets) * 100, 1)
        if total_tickets > 0
        else 100.0
    )

    resolution_durations_hours = [
        (t.resolved_at - t.created_at).total_seconds() / 3600.0
        for t in all_tickets
        if t.resolved_at is not None and t.created_at is not None
    ]
    avg_resolution_hours = (
        round(sum(resolution_durations_hours) / len(resolution_durations_hours), 1)
        if resolution_durations_hours
        else None
    )

    by_status = [
        {
            "key": status_key,
            "label": status_label,
            "count": (cnt := sum(1 for t in all_tickets if t.status == status_key)),
            "percent": round((cnt / total_tickets) * 100, 1) if total_tickets > 0 else 0.0,
        }
        for status_key, status_label in STATUS_LABELS.items()
    ]

    by_priority = [
        {
            "key": prio_key,
            "label": prio_meta["label"],
            "sla_hours": prio_meta["sla_hours"],
            "count": (cnt := sum(1 for t in all_tickets if t.priority == prio_key)),
            "percent": round((cnt / total_tickets) * 100, 1) if total_tickets > 0 else 0.0,
        }
        for prio_key, prio_meta in PRIORITIES.items()
    ]

    category_names = list(CATEGORIES)
    for t in all_tickets:
        if t.category and t.category not in category_names:
            category_names.append(t.category)

    by_category = [
        {
            "name": cat_name,
            "count": (cnt := sum(1 for t in all_tickets if t.category == cat_name)),
            "percent": round((cnt / total_tickets) * 100, 1) if total_tickets > 0 else 0.0,
        }
        for cat_name in category_names
    ]

    agents = [u for u in all_users if u.role in ("agent", "admin")]
    by_agent = []
    for agent in agents:
        agent_tickets = [t for t in all_tickets if t.assignee_id == agent.id]
        by_agent.append(
            {
                "user": agent,
                "total": len(agent_tickets),
                "active": sum(1 for t in agent_tickets if t.status not in ("resolved", "closed")),
                "resolved": sum(1 for t in agent_tickets if t.status in ("resolved", "closed")),
                "overdue": sum(1 for t in agent_tickets if t.is_overdue),
            }
        )

    unassigned_count = sum(1 for t in all_tickets if t.assignee_id is None)

    recent_history = (
        db.query(History)
        .options(joinedload(History.ticket), joinedload(History.user))
        .order_by(History.created_at.desc())
        .limit(15)
        .all()
    )

    stats_summary = {
        "total_tickets": total_tickets,
        "open_tickets": open_tickets,
        "in_progress_tickets": in_progress_tickets,
        "resolved_tickets": resolved_tickets,
        "overdue_tickets": overdue_tickets,
        "active_overdue_tickets": active_overdue_tickets,
        "unassigned_tickets": unassigned_count,
        "sla_compliance_rate": sla_compliance_rate,
        "avg_resolution_hours": avg_resolution_hours,
    }

    return render_template(
        "stats.html",
        request=request,
        db=db,
        current_user=current_user,
        context={
            "stats": stats_summary,
            "by_status": by_status,
            "by_priority": by_priority,
            "by_category": by_category,
            "by_agent": by_agent,
            "recent_history": recent_history,
        },
    )