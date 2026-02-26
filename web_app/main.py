from pathlib import Path
from contextlib import asynccontextmanager
import logging
from uuid import uuid4

from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded

from core.database import init_db
from core.logging_config import reset_request_id, set_request_id, setup_logging
from web_app.admin_routes import admin_router
from web_app.routes import limiter, router

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


setup_logging()
app = FastAPI(title="botfriendly.shop AI Readiness Checker", lifespan=lifespan)
app.state.limiter = limiter
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Shared template loader used by routes.
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.state.templates = templates


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning("Rate limit exceeded", extra={"path": request.url.path, "client": request.client.host if request.client else None})
    return JSONResponse(
        status_code=429,
        content={"error": "Rate limit exceeded. Please wait a moment and try again."},
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception):
    templates = request.app.state.templates
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = str(uuid4())
    token = set_request_id(request_id)
    try:
        response = await call_next(request)
        reset_request_id(token)
    except Exception:
        reset_request_id(token)
        raise
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


app.include_router(router)
app.include_router(admin_router)
