"""FastAPI application: API routes, the web page and startup tasks."""
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.database import PROJECT_ROOT, Base, SessionLocal, engine
from app.routes import auth, catalog, invoices, reports, subscriptions, users
from app.seed import seed

STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
INDEX_HTML = os.path.join(PROJECT_ROOT, "templates", "index.html")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    if os.getenv("INTRINSIC_SEED", "1") != "0":
        with SessionLocal() as db:
            if seed(db):
                print("[INTRINSIC] Demo data created. Sign in with admin@intrinsic.io / Intrinsic@2026")
    yield


app = FastAPI(title="INTRINSIC", version=__version__, lifespan=lifespan,
              description="Subscription & Invoicing Management System")


@app.middleware("http")
async def timing(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
    return response


@app.exception_handler(RequestValidationError)
async def friendly_validation_errors(_request: Request, exc: RequestValidationError):
    messages = []
    for err in exc.errors():
        msg = err.get("msg", "Invalid value.")
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        else:
            field = str(err["loc"][-1]).replace("_", " ") if err.get("loc") else "value"
            msg = f"{field.capitalize()}: {msg}"
        messages.append(msg)
    return JSONResponse({"detail": " ".join(dict.fromkeys(messages))}, status_code=422)


for module in (auth, users, catalog, subscriptions, invoices, reports):
    app.include_router(module.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(INDEX_HTML)


@app.get("/api/health", tags=["System"])
def health():
    return {"status": "ok", "version": __version__}
