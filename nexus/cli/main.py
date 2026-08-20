"""Nexus command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nexus", description="Nexus agent framework CLI")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run an orchestration manifest")
    run_p.add_argument("manifest", type=Path, help="Path to YAML manifest")
    run_p.add_argument("message", nargs="?", default="Hello", help="User message")

    sub.add_parser("doctor", help="Check environment and optional extras")

    val_p = sub.add_parser("manifest", help="Manifest utilities")
    val_sub = val_p.add_subparsers(dest="manifest_cmd")
    validate_p = val_sub.add_parser("validate", help="Validate a manifest file")
    validate_p.add_argument("manifest", type=Path)

    eval_p = sub.add_parser("eval", help="Run dataset eval (requires nexus[eval])")
    eval_p.add_argument("dataset", type=Path, nargs="?", default=None)

    serve_p = sub.add_parser("serve", help="Start example API server (requires nexus[serve])")
    serve_p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)

    if args.command == "doctor":
        _doctor()
    elif args.command == "run":
        asyncio.run(_run_manifest(args.manifest, args.message))
    elif args.command == "manifest" and args.manifest_cmd == "validate":
        _validate_manifest(args.manifest)
    elif args.command == "eval":
        _run_eval(args.dataset)
    elif args.command == "serve":
        _serve(args.port)
    else:
        parser.print_help()
        sys.exit(1)


def _doctor() -> None:
    print("Nexus doctor")
    for extra in ("litellm", "fastapi", "otel"):
        try:
            if extra == "litellm":
                import litellm  # noqa: F401
            elif extra == "fastapi":
                import fastapi  # noqa: F401
            elif extra == "otel":
                import opentelemetry  # noqa: F401
            print(f"  [ok] {extra}")
        except ImportError:
            print(f"  [missing] {extra} (optional extra)")


def _validate_manifest(path: Path) -> None:
    from nexus.orchestration import OrchestrationManifest

    manifest = OrchestrationManifest.load(path)
    print(f"Valid manifest: root={manifest.schema.root}")


async def _run_manifest(path: Path, message: str) -> None:
    from nexus.orchestration import OrchestrationManifest, OrchestrationRuntime
    from nexus.tools.context import RunContext

    manifest = OrchestrationManifest.load(path)
    run_context = RunContext()
    runtime = OrchestrationRuntime.from_manifest(manifest, run_context=run_context)
    result = await runtime.run(message)
    print(result)


def _run_eval(dataset: Path | None) -> None:
    from nexus.eval.runner import run_eval_cli

    run_eval_cli(dataset)


def _serve(port: int) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Install nexus-enterprise-agent[serve] for nexus serve") from exc
    uvicorn.run("examples.nexus_saas_api:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
