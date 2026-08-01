"""Command line interface.

Deliberately a thin launcher: all security-relevant settings live only in the
config file, so they cannot be overridden per-invocation.
"""

import argparse
import asyncio
import logging
import sys

from borg_mcp import __version__
from borg_mcp.config import ConfigError, ServerConfig, find_config, load_config
from borg_mcp.runner import BorgError, BorgRunner
from borg_mcp.server import create_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="borg-mcp", description="Read-only MCP server for BorgBackup status.")
    parser.add_argument("--version", action="version", version=f"borg-mcp {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_ in (
        ("serve", "run the stdio MCP server"),
        ("check", "validate the configuration and optionally test repository access"),
    ):
        sub = subparsers.add_parser(name, help=help_)
        sub.add_argument("--config", metavar="PATH", help="config file (default: ~/.config/borg-mcp/config.toml)")
        sub.add_argument("--log-level", default="warning", choices=["debug", "info", "warning", "error"])
        sub.add_argument("--log-file", metavar="PATH", help="log to this file instead of stderr")
    subparsers.choices["check"].add_argument(
        "aliases", nargs="*", metavar="ALIAS", help="test access to these repositories (default: config check only)"
    )
    return parser


def setup_logging(args: argparse.Namespace) -> None:
    # stdout is the MCP protocol channel and must stay clean - log to stderr or a file.
    kwargs: dict = {"filename": args.log_file} if args.log_file else {"stream": sys.stderr}
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s", **kwargs
    )


async def run_check(config: ServerConfig, aliases: list[str]) -> int:
    runner = BorgRunner(config)
    print(f"config OK: {len(config.repos)} repositories: {', '.join(config.repos)}")
    try:
        print(f"borg OK: {config.borg_binary} is borg {await runner.check_borg2()}")
    except BorgError as e:
        print(f"borg FAILED: {e}")
        return 2
    failed = False
    for alias in aliases:
        if alias not in config.repos:
            print(f"{alias}: FAILED: not a configured alias")
            failed = True
            continue
        try:
            info = await runner.run_json(config.repos[alias], ["repo-info", "--json"])
            repo_id = info.get("repository", {}).get("id", "?")
            print(f"{alias}: OK (repository id {repo_id})")
        except BorgError as e:
            print(f"{alias}: FAILED: {e}")
            failed = True
    return 2 if failed else 0


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    setup_logging(args)
    try:
        config = load_config(find_config(args.config))
    except ConfigError as e:
        print(f"borg-mcp: {e}", file=sys.stderr)
        raise SystemExit(2)
    if args.command == "check":
        raise SystemExit(asyncio.run(run_check(config, args.aliases)))
    try:
        asyncio.run(BorgRunner(config).check_borg2())
    except BorgError as e:
        print(f"borg-mcp: {e}", file=sys.stderr)
        raise SystemExit(2)
    create_server(config).run(transport="stdio")
