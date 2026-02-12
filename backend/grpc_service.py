from __future__ import annotations

from typing import Any

import grpc

from .registry import ModelNotFound, ModelRegistry, SymbolNotFound


class ModelServiceServicer:
    def __init__(self, registry: ModelRegistry, pb2: Any) -> None:
        self.registry = registry
        self.pb2 = pb2

    async def GetModel(self, request, context):  # noqa: N802
        try:
            payload = self.registry.build_grpc_payload(
                model_name=request.model_name,
                symbol=request.symbol,
                group_key=request.group_key or None,
            )
        except (ModelNotFound, SymbolNotFound) as exc:
            return self.pb2.GetModelResponse(ok=False, message=str(exc))
        except Exception as exc:  # Defensive catch to keep grpc call response stable.
            return self.pb2.GetModelResponse(ok=False, message=f"internal error: {exc}")

        dim_factors = [
            self.pb2.DimFactor(
                dim=int(item["dim"]),
                factor_name=str(item.get("factor_name") or ""),
                kendall_tau=float(item["kendall_tau"] if item["kendall_tau"] is not None else 0.0),
            )
            for item in payload["dim_factors"]
        ]

        metadata = self.pb2.ModelMetadata(
            model_name=payload["model_name"],
            symbol=payload["symbol"],
            group_key=payload["group_key"],
            return_name=payload["return_name"],
            feature_dim=int(payload["feature_dim"]),
            train_window_start_ts=int(payload["train_window_start_ts"] or 0),
            train_window_end_ts=int(payload["train_window_end_ts"] or 0),
            train_start_date=str(payload["train_start_date"] or ""),
            train_end_date=str(payload["train_end_date"] or ""),
            train_samples=int(payload["train_samples"] or 0),
            train_time_sec=float(payload["train_time_sec"] or 0.0),
            model_json_path=payload["model_json_path"],
            source_root_path=payload["root_path"],
            scanned_at=payload["scanned_at"],
        )

        return self.pb2.GetModelResponse(
            ok=True,
            message="ok",
            payload=self.pb2.ModelPayload(
                model_json=payload["model_json"],
                metadata=metadata,
                dim_factors=dim_factors,
            ),
        )

    async def ListSymbols(self, request, context):  # noqa: N802
        try:
            symbols = self.registry.list_symbols(request.model_name)
        except ModelNotFound as exc:
            return self.pb2.ListSymbolsResponse(ok=False, message=str(exc))
        except Exception as exc:
            return self.pb2.ListSymbolsResponse(ok=False, message=f"internal error: {exc}")

        entries = [
            self.pb2.SymbolEntry(
                symbol=item["symbol"],
                group_key=item["group_key"],
                return_name=item["return_name"],
                feature_dim=int(item["feature_dim"] or 0),
                grpc_ready=bool(item["grpc_ready"]),
            )
            for item in symbols
        ]

        return self.pb2.ListSymbolsResponse(ok=True, message="ok", symbols=entries)


async def start_grpc_server(
    registry: ModelRegistry,
    pb2: Any,
    pb2_grpc: Any,
    host: str,
    port: int,
) -> grpc.aio.Server:
    server = grpc.aio.server()
    servicer = ModelServiceServicer(registry=registry, pb2=pb2)
    pb2_grpc.add_ModelServiceServicer_to_server(servicer, server)
    bind = f"{host}:{port}"
    server.add_insecure_port(bind)
    await server.start()
    return server
