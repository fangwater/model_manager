#!/usr/bin/env python3
from __future__ import annotations

import argparse

import grpc

from model_manager.backend.config import load_settings
from model_manager.backend.proto_loader import ensure_proto_modules


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo gRPC client for model_manager")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50061)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--group-key", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    settings = load_settings()
    pb2, pb2_grpc = ensure_proto_modules(
        proto_dir=settings.proto_dir,
        generated_dir=settings.generated_proto_dir,
    )

    endpoint = f"{args.host}:{args.port}"
    with grpc.insecure_channel(endpoint) as channel:
        stub = pb2_grpc.ModelServiceStub(channel)
        resp = stub.GetModel(
            pb2.GetModelRequest(
                model_name=args.model_name,
                symbol=args.symbol,
                group_key=args.group_key,
            )
        )

    if not resp.ok:
        print("ERROR:", resp.message)
        return 2

    print("OK")
    print("model_name:", resp.payload.metadata.model_name)
    print("symbol:", resp.payload.metadata.symbol)
    print("group_key:", resp.payload.metadata.group_key)
    print("feature_dim:", resp.payload.metadata.feature_dim)
    print("train_start:", resp.payload.metadata.train_start_date)
    print("train_end:", resp.payload.metadata.train_end_date)
    print("dim_factor_count:", len(resp.payload.dim_factors))
    print("model_json_bytes:", len(resp.payload.model_json.encode("utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
