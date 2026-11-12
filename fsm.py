from datetime import datetime
from statemachine import StateMachine, State
from statemachine.exceptions import TransitionNotAllowed
from models import History, STATUS_LABELS

EVENT_BUTTONS = {
    "take_in_work": {"label": "Взять в работу", "style": "primary"},
    "ask_user": {"label": "Запросить уточнение у клиента", "style": "secondary"},
    "return_to_work": {"label": "Вернуть в работу", "style": "primary"},
    "resolve": {"label": "Отметить решенной", "style": "contrast"},
    "reopen": {"label": "Переоткрыть заявку", "style": "secondary"},
    "close_ticket": {"label": "Подтвердить и закрыть", "style": "primary"},
}


class TicketStateMachine(StateMachine):
    new = State("Новая", initial=True, value="new")
    in_progress = State("В работе", value="in_progress")
    waiting_user = State("Ожидание ответа", value="waiting_user")
    resolved = State("Решена", value="resolved")
    closed = State("Закрыта", final=True, value="closed")

    take_in_work = new.to(in_progress, cond="has_assignee")
    ask_user = in_progress.to(waiting_user)
    return_to_work = waiting_user.to(in_progress)
    resolve = in_progress.to(resolved) | waiting_user.to(resolved)
    reopen = resolved.to(in_progress)
    close_ticket = resolved.to(closed)

    def __init__(self, ticket, db=None, actor_id=None):
        self.ticket = ticket
        self.db = db
        self.actor_id = actor_id
        super().__init__(model=ticket, state_field="status")

    def has_assignee(self) -> bool:
        return self.ticket.assignee_id is not None

    def after_transition(self, event: str, source: State, target: State):
        if event == "__initial__" or source == target:
            return

        if target.value == "resolved":
            self.ticket.resolved_at = datetime.now()
        elif target.value == "in_progress" and source.value == "resolved":
            self.ticket.resolved_at = None

        self.ticket.updated_at = datetime.now()

        if self.db is not None:
            old_name = STATUS_LABELS.get(source.value, source.value)
            new_name = STATUS_LABELS.get(target.value, target.value)
            log_entry = History(
                ticket_id=self.ticket.id,
                user_id=self.actor_id,
                action=f"Статус изменен: «{old_name}» → «{new_name}» (событие: {event})",
                is_notification=True,
            )
            self.db.add(log_entry)
            self.db.commit()

    def get_available_actions(self):
        actions = []
        seen_events = set()
        for transition in self.current_state.transitions:
            ev = transition.event
            if ev not in seen_events and ev in EVENT_BUTTONS:
                seen_events.add(ev)
                actions.append({
                    "event": ev,
                    "label": EVENT_BUTTONS[ev]["label"],
                    "style": EVENT_BUTTONS[ev]["style"],
                    "requires_assignee": ev == "take_in_work" and not self.has_assignee(),
                })
        return actions


def trigger_ticket_event(ticket, event_name: str, db, actor_id: int):
    sm = TicketStateMachine(ticket, db=db, actor_id=actor_id)
    try:
        sm.send(event_name)
        return True, "Статус успешно обновлен"
    except TransitionNotAllowed:
        if event_name == "take_in_work" and not ticket.assignee_id:
            return False, "Ошибка State Machine: нельзя перевести в работу без назначенного исполнителя!"
        return False, f"Переход «{event_name}» недоступен из текущего статуса."