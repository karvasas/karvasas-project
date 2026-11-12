import inspect
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from database import SessionLocal
from models import History, Ticket
from seed import seed_database

logger = logging.getLogger("servicedesk.tasks")
scheduler = BackgroundScheduler()


def check_sla_overdues() -> None:
    db: Session = SessionLocal()
    try:
        now = datetime.now()
        expired_tickets = (
            db.query(Ticket)
            .filter(
                Ticket.status.notin_(["resolved", "closed"]),
                Ticket.is_overdue.is_(False),
                Ticket.sla_deadline < now,
            )
            .all()
        )

        if not expired_tickets:
            return

        for ticket in expired_tickets:
            ticket.is_overdue = True
            ticket.updated_at = now
            db.add(
                History(
                    ticket_id=ticket.id,
                    user_id=None,
                    action=(
                        f"Нарушен регламентный срок SLA "
                        f"(дедлайн: {ticket.sla_deadline.strftime('%d.%m.%Y %H:%M')}). "
                        f"Заявка автоматически помечена как просроченная."
                    ),
                    is_notification=True,
                )
            )

        db.commit()
        logger.info("SLA check: помечено просроченными заявок: %d", len(expired_tickets))
    except Exception as exc:
        db.rollback()
        logger.exception("Ошибка в фоновой проверке SLA: %s", exc)
    finally:
        db.close()


def run_seed_on_startup() -> None:
    db: Session = SessionLocal()
    try:
        sig = inspect.signature(seed_database)
        if len(sig.parameters) > 0:
            seed_database(db)
        else:
            seed_database()
        db.commit()
        logger.info("Инициализация БД (seed_database) выполнена успешно.")
    except Exception as exc:
        db.rollback()
        logger.exception("Ошибка при выполнении seed_database(): %s", exc)
    finally:
        db.close()