from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

CATEGORIES = [
    "Сеть и VPN",
    "Оборудование и ПК",
    "Доступы и учетные записи",
    "Корпоративное ПО",
    "Серверы и БД",
]

PRIORITIES = {
    "low": {"label": "Низкий", "sla_hours": 24},
    "medium": {"label": "Средний", "sla_hours": 8},
    "high": {"label": "Высокий", "sla_hours": 2},
    "critical": {"label": "Критический", "sla_hours": 1},
}

STATUS_LABELS = {
    "new": "Новая",
    "in_progress": "В работе",
    "waiting_user": "Ожидание ответа",
    "resolved": "Решена",
    "closed": "Закрыта",
}


def calculate_sla_deadline(priority: str, from_time: datetime = None) -> datetime:
    base_time = from_time or datetime.now()
    hours = PRIORITIES.get(priority, {"sla_hours": 8})["sla_hours"]
    return base_time + timedelta(hours=hours)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="client")  # client, agent, admin

    created_tickets = relationship(
        "Ticket", back_populates="creator", foreign_keys="Ticket.creator_id"
    )
    assigned_tickets = relationship(
        "Ticket", back_populates="assignee", foreign_keys="Ticket.assignee_id"
    )


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(100), nullable=False)
    priority = Column(String(20), nullable=False, default="medium")
    status = Column(String(30), nullable=False, default="new")

    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    sla_deadline = Column(DateTime, nullable=False)
    is_overdue = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    resolved_at = Column(DateTime, nullable=True)

    creator = relationship("User", back_populates="created_tickets", foreign_keys=[creator_id])
    assignee = relationship("User", back_populates="assigned_tickets", foreign_keys=[assignee_id])
    comments = relationship(
        "Comment", back_populates="ticket", cascade="all, delete-orphan", order_by="Comment.created_at"
    )
    attachments = relationship(
        "Attachment", back_populates="ticket", cascade="all, delete-orphan"
    )
    history = relationship(
        "History", back_populates="ticket", cascade="all, delete-orphan", order_by="History.created_at.desc()"
    )


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    ticket = relationship("Ticket", back_populates="comments")
    user = relationship("User")


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    filepath = Column(String(500), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.now)

    ticket = relationship("Ticket", back_populates="attachments")


class History(Base):
    __tablename__ = "history"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(500), nullable=False)
    is_notification = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    ticket = relationship("Ticket", back_populates="history")
    user = relationship("User")