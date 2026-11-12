from datetime import datetime, timedelta
from database import engine, SessionLocal, Base
from models import User, Ticket, Comment, History, calculate_sla_deadline


def seed_database():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if db.query(User).count() > 0:
        db.close()
        return

    users = [
        User(username="client_ivan", full_name="Иван Петров (Клиент - Бухгалтерия)", role="client"),
        User(username="agent_alex", full_name="Алексей Смирнов (Инженер L2)", role="agent"),
        User(username="agent_dmitry", full_name="Дмитрий Волков (Сисадмин)", role="agent"),
        User(username="admin_anna", full_name="Анна Козлова (Руководитель IT)", role="admin"),
    ]
    db.add_all(users)
    db.commit()

    client, agent1, agent2, admin = users
    now = datetime.now()

    t1 = Ticket(
        title="Не работает корпоративный VPN из дома",
        description="При подключении через WireGuard висит handshake, внутренние ресурсы недоступны.",
        category="Сеть и VPN",
        priority="high",
        status="in_progress",
        creator_id=client.id,
        assignee_id=agent1.id,
        created_at=now - timedelta(hours=3),
        sla_deadline=now - timedelta(hours=1),
        is_overdue=True,
    )

    t2 = Ticket(
        title="Выдать доступ к БД PostgreSQL для нового аналитика",
        description="Нужен read-only доступ к схеме analytics на боевом сервере.",
        category="Доступы и учетные записи",
        priority="medium",
        status="new",
        creator_id=client.id,
        assignee_id=None,
        created_at=now - timedelta(minutes=40),
        sla_deadline=calculate_sla_deadline("medium", now - timedelta(minutes=40)),
        is_overdue=False,
    )

    t3 = Ticket(
        title="Замена термопасты и чистка рабочего ПК",
        description="Компьютер сильно шумит и выключается при открытии тяжелых таблиц.",
        category="Оборудование и ПК",
        priority="low",
        status="waiting_user",
        creator_id=client.id,
        assignee_id=agent2.id,
        created_at=now - timedelta(hours=5),
        sla_deadline=calculate_sla_deadline("low", now - timedelta(hours=5)),
        is_overdue=False,
    )

    t4 = Ticket(
        title="Сбой синхронизации 1С с почтовым сервером",
        description="Не уходят расчетные листки сотрудникам, ошибка SMTP 535.",
        category="Корпоративное ПО",
        priority="critical",
        status="resolved",
        creator_id=client.id,
        assignee_id=agent1.id,
        created_at=now - timedelta(hours=4),
        sla_deadline=now - timedelta(hours=3),
        resolved_at=now - timedelta(hours=3, minutes=20),
        is_overdue=False,
    )

    db.add_all([t1, t2, t3, t4])
    db.commit()

    comments = [
        Comment(ticket_id=t1.id, user_id=agent1.id, text="Проверяю ключи на VPN-шлюзе, пришлите лог подключения."),
        Comment(ticket_id=t3.id, user_id=agent2.id, text="В какое время сегодня можно забрать системный блок на 30 минут?"),
        Comment(ticket_id=t4.id, user_id=agent1.id, text="Обновил пароль приложения для SMTP-учетки, отправка восстановлена."),
    ]
    db.add_all(comments)

    histories = [
        History(ticket_id=t1.id, user_id=client.id, action="Заявка создана"),
        History(ticket_id=t1.id, user_id=agent1.id, action="Статус изменен: «Новая» → «В работе» (событие: take_in_work)"),
        History(ticket_id=t1.id, user_id=None, action="⚠️ Нарушен регламент SLA! Дедлайн истек."),
        History(ticket_id=t2.id, user_id=client.id, action="Заявка создана"),
        History(ticket_id=t3.id, user_id=agent2.id, action="Статус изменен: «В работе» → «Ожидание ответа» (событие: ask_user)"),
        History(ticket_id=t4.id, user_id=agent1.id, action="Статус изменен: «В работе» → «Решена» (событие: resolve)"),
    ]
    db.add_all(histories)
    db.commit()
    db.close()


if __name__ == "__main__":
    seed_database()
    print("База данных успешно создана и заполнена демо-данными!")