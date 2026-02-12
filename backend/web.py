from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import AuthManager, InvalidPassword, InvalidToken, PasswordNotInitialized
from .config import Settings
from .registry import ModelNotFound, ModelRegistry, ModelRegistryError, SymbolNotFound


class BootstrapPasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class AddModelRequest(BaseModel):
    model_name: str = Field(min_length=1, max_length=128)
    root_path: str = Field(min_length=1, max_length=2048)


class ApiSession(BaseModel):
    token: str
    permission: str
    expires_at: int



def create_app(settings: Settings, registry: ModelRegistry, auth_manager: AuthManager) -> FastAPI:
    app = FastAPI(title="Model Manager", version="0.1.0")

    app.state.settings = settings
    app.state.registry = registry
    app.state.auth_manager = auth_manager

    frontend_dir = settings.frontend_dir
    assets_dir = frontend_dir

    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    def _extract_session(authorization: str | None) -> ApiSession:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing bearer token",
            )

        token = authorization[len("Bearer ") :].strip()
        try:
            session = auth_manager.verify_token(token)
        except InvalidToken as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc

        return ApiSession(
            token=session.token,
            permission=session.permission,
            expires_at=session.expires_at,
        )

    def _require_session(
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> ApiSession:
        return _extract_session(authorization)

    @app.get("/")
    async def index() -> FileResponse:
        index_file = frontend_dir / "index.html"
        return FileResponse(index_file)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/auth/status")
    async def auth_status() -> dict[str, bool]:
        return {"initialized": auth_manager.is_password_initialized()}

    @app.post("/api/auth/bootstrap")
    async def bootstrap_password(payload: BootstrapPasswordRequest) -> dict[str, str]:
        created = auth_manager.bootstrap_password(payload.password)
        if not created:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="password already initialized",
            )
        return {"message": "password initialized"}

    @app.post("/api/auth/login")
    async def login(payload: LoginRequest) -> ApiSession:
        try:
            session = auth_manager.login(payload.password)
        except PasswordNotInitialized as exc:
            raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED, detail=str(exc)) from exc
        except InvalidPassword as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

        return ApiSession(
            token=session.token,
            permission=session.permission,
            expires_at=session.expires_at,
        )

    @app.get("/api/me")
    async def me(session: ApiSession = Depends(_require_session)) -> dict[str, str | int]:
        return {
            "permission": session.permission,
            "expires_at": session.expires_at,
        }

    @app.post("/api/models")
    async def add_model(
        payload: AddModelRequest,
        session: ApiSession = Depends(_require_session),
    ) -> dict[str, object]:
        _ = session
        try:
            snapshot = registry.add_or_refresh_model(payload.model_name, payload.root_path)
        except ModelRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

        return {
            "model_name": snapshot.model_name,
            "root_path": snapshot.root_path,
            "scanned_at": snapshot.scanned_at,
            "symbol_count": snapshot.symbol_count,
            "group_count": snapshot.group_count,
            "symbols": sorted({item.symbol for item in snapshot.symbols}),
            "warnings": snapshot.warnings,
        }

    @app.post("/api/models/{model_name}/refresh")
    async def refresh_model(model_name: str, session: ApiSession = Depends(_require_session)) -> dict[str, object]:
        _ = session
        try:
            snapshot = registry.refresh_model(model_name)
        except ModelNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

        return {
            "model_name": snapshot.model_name,
            "root_path": snapshot.root_path,
            "scanned_at": snapshot.scanned_at,
            "symbol_count": snapshot.symbol_count,
            "group_count": snapshot.group_count,
            "warnings": snapshot.warnings,
        }

    @app.get("/api/models")
    async def list_models(session: ApiSession = Depends(_require_session)) -> dict[str, object]:
        _ = session
        return {"items": registry.list_models()}

    @app.get("/api/models/{model_name}/symbols")
    async def list_symbols(
        model_name: str,
        session: ApiSession = Depends(_require_session),
    ) -> dict[str, object]:
        _ = session
        try:
            symbols = registry.list_symbols(model_name)
        except ModelNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return {"items": symbols}

    @app.get("/api/models/{model_name}/symbols/{symbol}")
    async def get_symbol_detail(
        model_name: str,
        symbol: str,
        request: Request,
        session: ApiSession = Depends(_require_session),
    ) -> dict[str, object]:
        _ = session
        group_key = request.query_params.get("group_key")
        try:
            detail = registry.get_symbol_detail(model_name, symbol, group_key=group_key)
        except ModelNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except SymbolNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return detail

    return app
