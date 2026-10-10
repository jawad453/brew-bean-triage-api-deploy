import json
import logging
import os
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.triage import classify_email

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("brew_bean_api")
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Brew & Bean Email Triage API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class TriageRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=10000)


class TriageResponse(BaseModel):
    category: str
    confidence: float


def require_auth(x_auth_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("AUTH_TOKEN")
    if not expected:
        logger.error("AUTH_TOKEN is not configured")
        raise HTTPException(
            status_code=503, detail="API authentication is not configured"
        )
    if not x_auth_token or x_auth_token != expected:
        raise HTTPException(
            status_code=401, detail="Invalid or missing authentication token"
        )


@app.middleware("http")
async def request_logging(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "client": get_remote_address(request),
            }
        )
    )
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post(
    "/triage", response_model=TriageResponse, dependencies=[Depends(require_auth)]
)
@limiter.limit("10/minute")
def triage(request: Request, body: TriageRequest):
    return classify_email(body.email)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled API error")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
