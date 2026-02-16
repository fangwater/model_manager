from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .registry import ModelNotFound, ModelRegistry, ModelRegistryError, SymbolNotFound


class AddModelRequest(BaseModel):
    model_name: str = Field(min_length=1, max_length=128)
    root_path: str = Field(min_length=1, max_length=2048)


def create_app(settings: Settings, registry: ModelRegistry) -> FastAPI:
    app = FastAPI(title="Model Manager", version="0.1.0")
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    app.state.settings = settings
    app.state.registry = registry

    frontend_dir = settings.frontend_dir
    assets_dir = frontend_dir

    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    async def index() -> FileResponse:
        index_file = frontend_dir / "index.html"
        return FileResponse(index_file)

    @app.get("/config")
    async def config_page() -> FileResponse:
        config_file = frontend_dir / "config.html"
        return FileResponse(config_file)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        favicon_file = frontend_dir / "favicon.ico"
        if favicon_file.exists():
            return FileResponse(favicon_file)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/models")
    async def add_model(
        payload: AddModelRequest,
    ) -> dict[str, object]:
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
    async def refresh_model(model_name: str) -> dict[str, object]:
        try:
            snapshot = registry.refresh_model(model_name)
        except ModelNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
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
            "warnings": snapshot.warnings,
        }

    @app.get("/api/models")
    async def list_models() -> dict[str, object]:
        return {"items": registry.list_models()}

    @app.get("/api/models/{model_name}/symbols")
    async def list_symbols(
        model_name: str,
    ) -> dict[str, object]:
        try:
            symbols = registry.list_symbols(model_name)
        except ModelNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return {"items": symbols}

    @app.get("/api/models/{model_name}/factors")
    async def list_model_factors(
        model_name: str,
    ) -> dict[str, object]:
        try:
            factors = registry.list_model_factors(model_name)
        except ModelNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return factors

    @app.get("/api/models/{model_name}/symbols/{symbol}")
    async def get_symbol_detail(
        model_name: str,
        symbol: str,
        request: Request,
    ) -> dict[str, object]:
        group_key = request.query_params.get("group_key")
        try:
            detail = registry.get_symbol_detail(model_name, symbol, group_key=group_key)
        except ModelNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except SymbolNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return detail

    @app.get("/api/models/{model_name}/symbols/{symbol}/factor-stats")
    async def get_symbol_factor_stats(
        model_name: str,
        symbol: str,
        request: Request,
    ) -> dict[str, object]:
        group_key = request.query_params.get("group_key")
        try:
            data = registry.get_symbol_factor_stats(model_name, symbol, group_key=group_key)
        except ModelNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except SymbolNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModelRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return data

    @app.put("/api/models/{model_name}/symbols/{symbol}/factor-stats")
    async def update_symbol_factor_stats(
        model_name: str,
        symbol: str,
        request: Request,
    ) -> dict[str, object]:
        group_key = request.query_params.get("group_key")
        try:
            raw_payload = await request.json()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="request body must be valid JSON",
            ) from exc

        if not isinstance(raw_payload, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="request body must be an object with symbol key",
            )

        symbol_entry = raw_payload.get(symbol)
        if symbol_entry is None:
            symbol_entry = raw_payload.get(symbol.strip().upper())
        if symbol_entry is None and len(raw_payload) == 1:
            symbol_entry = next(iter(raw_payload.values()))

        if not isinstance(symbol_entry, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"request body must include symbol key '{symbol}' with object value",
            )

        mean_values = symbol_entry.get("mean_values")
        variance_values = symbol_entry.get("variance_values")
        if not isinstance(mean_values, list) or not isinstance(variance_values, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="symbol config must include mean_values and variance_values arrays",
            )
        factor_names = symbol_entry.get("factor_names")
        if factor_names is not None and not isinstance(factor_names, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="factor_names must be an array when provided",
            )

        try:
            data = registry.set_symbol_factor_stats(
                model_name=model_name,
                symbol=symbol,
                mean_values=list(mean_values),
                variance_values=list(variance_values),
                factor_names=list(factor_names) if factor_names is not None else None,
                group_key=group_key,
            )
        except ModelNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except SymbolNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModelRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return data

    @app.get("/api/models/{model_name}/model/{symbol}")
    async def get_model_payload(
        model_name: str,
        symbol: str,
    ) -> dict[str, object]:
        try:
            payload = registry.build_model_payload(model_name=model_name, symbol=symbol)
        except ModelNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except SymbolNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return {
            "ok": True,
            "message": "ok",
            "payload": {
                "model_json": payload["model_json"],
                "metadata": {
                    "model_name": payload["model_name"],
                    "symbol": payload["symbol"],
                    "return_name": payload["return_name"],
                    "feature_dim": payload["feature_dim"],
                    "train_window_start_ts": payload["train_window_start_ts"],
                    "train_window_end_ts": payload["train_window_end_ts"],
                    "train_start_date": payload["train_start_date"],
                    "train_end_date": payload["train_end_date"],
                    "train_samples": payload["train_samples"],
                    "train_time_sec": payload["train_time_sec"],
                    "model_json_path": payload["model_json_path"],
                    "source_root_path": payload["root_path"],
                    "scanned_at": payload["scanned_at"],
                    "factor_stats_updated_at": payload["factor_stats_updated_at"],
                },
                "dim_factors": payload["dim_factors"],
                "symbol_stats": payload["symbol_stats"],
            },
        }

    return app
