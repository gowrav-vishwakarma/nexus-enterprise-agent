"""Start and supervise media model servers."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any

import grpc
import yaml

from nexus.server.config import LauncherConfig, ModelServerSpec, ServersConfig
from nexus.server.pool import EnginePool, get_pool
from nexus.server.registry import ServerRegistry
from nexus.server.services.base import serve_grpc
from nexus.server.services.lid_server import build_lid_server
from nexus.server.services.stt_server import build_stt_server
from nexus.server.services.tts_server import build_tts_server
from nexus.server.services.vad_server import build_vad_server

logger = logging.getLogger(__name__)

_BUILDERS = {
    "stt": build_stt_server,
    "tts": build_tts_server,
    "vad": build_vad_server,
    "lid": build_lid_server,
}


def load_servers_config(path: str | Path) -> ServersConfig:
    data = yaml.safe_load(Path(path).read_text()) or {}
    if "servers" in data:
        return ServersConfig.model_validate(data)
    return ServersConfig(servers={k: ModelServerSpec.model_validate(v) for k, v in data.items()})


async def start_server(name: str, spec: ModelServerSpec, pool: EnginePool) -> grpc.aio.Server:
    builder = _BUILDERS[spec.kind]
    if spec.kind == "tts":
        parts = builder(
            spec.engine,
            host=spec.host,
            port=spec.port,
            replicas=spec.replicas,
            extra=_engine_kwargs(spec),
        )
    else:
        parts = builder(
            spec.engine,
            pool,
            host=spec.host,
            port=spec.port,
            extra=_engine_kwargs(spec),
        )
    add_svc, servicer, add_health, health, host, port = parts
    return await serve_grpc(
        [(add_svc, servicer), (add_health, health)],
        host=host,
        port=port,
    )


def _engine_kwargs(spec: ModelServerSpec) -> dict[str, Any]:
    kw = dict(spec.extra)
    if spec.device:
        kw.setdefault("device", spec.device)
    return kw


async def up(config_path: str, *, only: str | None = None) -> None:
    cfg = load_servers_config(config_path)
    pool = get_pool()
    servers: list[grpc.aio.Server] = []
    for name, spec in cfg.servers.items():
        if only and name != only:
            continue
        logger.info("Starting %s (%s/%s) on %s", name, spec.kind, spec.engine, spec.endpoint)
        servers.append(await start_server(name, spec, pool))

    stop = asyncio.Event()

    def _handle(*_):
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle)
        except NotImplementedError:
            pass

    await stop.wait()
    for s in servers:
        await s.stop(grace=5)


async def health(config_path: str) -> int:
    cfg = load_servers_config(config_path)
    registry = ServerRegistry(cfg)
    results = await registry.check_all()
    await registry.close()
    for name, ok in results.items():
        status = "ok" if ok else "FAIL"
        print(f"{name}: {status}")
    return 0 if all(results.values()) else 1


async def status(config_path: str) -> None:
    cfg = load_servers_config(config_path)
    registry = ServerRegistry(cfg)
    await registry.check_all()
    for row in registry.list_servers():
        print(f"{row['name']}: {row['kind']}/{row['engine']} @ {row['endpoint']} healthy={row['healthy']}")
    await registry.close()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Nexus media model server launcher")
    parser.add_argument("command", choices=["up", "health", "status"])
    parser.add_argument("--config", "-c", default="servers.yaml")
    parser.add_argument("--only", help="Start only this named server")
    args = parser.parse_args(argv)

    if args.command == "up":
        asyncio.run(up(args.config, only=args.only))
    elif args.command == "health":
        raise SystemExit(asyncio.run(health(args.config)))
    else:
        asyncio.run(status(args.config))


if __name__ == "__main__":
    main()
