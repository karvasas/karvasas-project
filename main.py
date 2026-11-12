import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from database import Base, engine
from routers import files, stats, tickets, users
from tasks import check_sla_overdues, run_seed_on_startup, scheduler
from web import STATIC_DIR, UPLOAD_DIR, parse_optional_int

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("servicedesk")


@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    run_seed_on_startup()

    scheduler.add_job(
        check_sla_overdues,
        trigger="interval",
        seconds=30,
        id="sla_overdue_monitor",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Фоновый планировщик APScheduler запущен (интервал проверки SLA: 30 сек).")

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Фоновый планировщик APScheduler остановлен.")


app = FastAPI(title="IT Service Desk", lifespan=lifespan)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def user_switch_cookie_middleware(request: Request, call_next):
    response = await call_next(request)
    raw_user_id = request.query_params.get("user_id") or request.query_params.get("switch_user")
    parsed_id = parse_optional_int(raw_user_id)
    if parsed_id is not None:
        response.set_cookie(
            key="current_user_id",
            value=str(parsed_id),
            httponly=True,
            max_age=60 * 60 * 24 * 30,
            samesite="lax",
        )
    return response


app.include_router(users.router)
app.include_router(tickets.router)
app.include_router(files.router)
app.include_router(stats.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)