"""FastAPI application factory for the WolfPack Analyst Console API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from wolfpack.api.routes import breakglass, cases, review, ws


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Application lifespan handler."""
    yield


def create_app() -> FastAPI:
    """Factory that returns a configured FastAPI application."""
    app = FastAPI(
        title="WolfPack Analyst Console API",
        version="0.1.0",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-API-Token"],
    )

    app.include_router(cases.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(breakglass.router, prefix="/api")
    app.include_router(ws.router, prefix="/ws")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
