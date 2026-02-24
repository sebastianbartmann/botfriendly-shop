from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.database import init_db
from web_app.routes import router

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Ecom LLM Readiness Checker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Shared template loader used by routes.
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.state.templates = templates

app.include_router(router)
