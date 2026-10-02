import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException

from app.api import auth, education, finance, lessons, system
from app.common import DB, APIError
from app.config import get_settings

log = logging.getLogger(__name__)


def create_app():
    get_settings()  # Fail fast on missing secrets or a non-PostgreSQL database.
    app = FastAPI(
        title="O'quv markaz CRM",
        version="1.0.0",
        redirect_slashes=False,
        description="FastAPI + PostgreSQL backend. Pul: butun UZS. Sanalar: Asia/Tashkent.",
    )
    for router in (auth.router, education.router, lessons.router, finance.router, system.router):
        app.include_router(router, prefix="/api/v1")

    @app.exception_handler(APIError)
    async def domain_error(request: Request, exc: APIError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
        return JSONResponse(
            {"detail": exc.detail, "code": exc.code}, status_code=exc.status, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [{"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            {
                "detail": "So'rov ma'lumotlari noto'g'ri",
                "code": "validation_error",
                "errors": errors,
            },
            status_code=422,
        )

    @app.exception_handler(IntegrityError)
    async def conflict(request: Request, exc: IntegrityError):
        return JSONResponse(
            {"detail": "Takroriy yoki bog'lanishi noto'g'ri ma'lumot", "code": "data_conflict"},
            status_code=409,
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        log.error("Database operation failed: %s", type(exc).__name__)
        return JSONResponse(
            {"detail": "Ma'lumotlar ombori vaqtincha mavjud emas", "code": "database_unavailable"},
            status_code=503,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(
            {"detail": str(exc.detail), "code": f"http_{exc.status_code}"},
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        log.error("Unexpected API error: %s", type(exc).__name__)
        return JSONResponse(
            {"detail": "Ichki server xatosi", "code": "internal_error"}, status_code=500
        )

    @app.get("/health/live", tags=["Health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"])
    def ready(db: DB):
        db.execute(text("SELECT 1 FROM alembic_version LIMIT 1"))
        return {"status": "ok", "database": "postgresql"}

    return app


app = create_app()
