"""MCP server and tool definitions.

All tools are read-only and carry the corresponding MCP tool annotations.
Repositories are addressed by their configured alias only.
"""

import logging
from datetime import datetime
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from borg_mcp import __version__, commands
from borg_mcp.config import RepoConfig, ServerConfig
from borg_mcp.runner import BorgRunner

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
Read-only access to BorgBackup repositories for operational monitoring.
Repositories are addressed by their configured alias - use list_repositories
to see them. No tool can modify, prune, or delete anything.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def _age_seconds(timestamp: str | None) -> float | None:
    """Age of a borg JSON timestamp (ISO format, local time), in seconds."""
    if not timestamp:
        return None
    try:
        then = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    now = datetime.now(tz=then.tzinfo)
    return max(0.0, (now - then).total_seconds())


def _age_human(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    if seconds < 120:
        return f"{seconds:.0f} seconds"
    if seconds < 2 * 3600:
        return f"{seconds / 60:.0f} minutes"
    if seconds < 2 * 86400:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / 86400:.1f} days"


def _capped_limit(limit: int | None, cap: int) -> int:
    if limit is None:
        return cap
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if limit > cap:
        raise ValueError(f"limit is capped at {cap} on this server")
    return limit


def _prune_entry(archive: dict[str, Any]) -> dict[str, Any]:
    entry = {"name": archive.get("name"), "time": archive.get("time"), "id": archive.get("id")}
    if archive.get("keep_rule"):
        entry["keep_rule"] = archive["keep_rule"]
    return entry


def _sanitized(result: Any) -> Any:
    """Drop server-local paths from borg's JSON (cache/security dirs) - noise for the agent."""
    if isinstance(result, dict):
        result.pop("cache", None)
        result.pop("security_dir", None)
    return result


def create_server(config: ServerConfig) -> MCPServer:
    server = MCPServer(name="borg-mcp", instructions=INSTRUCTIONS, version=__version__)
    runner = BorgRunner(config)

    def get_repo(alias: str) -> RepoConfig:
        if not isinstance(alias, str) or alias not in config.repos:
            raise ValueError(f"unknown repository alias {alias!r} - use list_repositories to see configured aliases")
        return config.repos[alias]

    @server.tool(annotations=READ_ONLY)
    async def list_repositories() -> list[dict[str, Any]]:
        """List the configured BorgBackup repositories (aliases usable with the other tools)."""
        return [{"repo": r.name, "description": r.description, "location": r.location} for r in config.repos.values()]

    @server.tool(annotations=READ_ONLY)
    async def repo_info(repo: str) -> dict[str, Any]:
        """Show repository information: ID, location, encryption mode, space usage."""
        return _sanitized(await runner.run_json(get_repo(repo), commands.repo_info_cmd()))

    @server.tool(annotations=READ_ONLY)
    async def list_archives(
        repo: str, match: str | None = None, first: int | None = None, last: int | None = None
    ) -> dict[str, Any]:
        """List archives in a repository (newest last).

        match: only archives matching this pattern (shell glob, e.g. "sh:home-*"; re: patterns are not accepted).
        first/last: only the N oldest/newest matching archives (mutually exclusive).
        """
        r = get_repo(repo)
        cap = config.max_items
        for n in (first, last):
            if n is not None and n > cap:
                raise ValueError(f"first/last is limited to {cap} on this server")
        capped = first is None and last is None
        if capped:
            last = cap
        result = await runner.run_json(r, commands.repo_list_cmd(match=match, first=first, last=last))
        archives = result.get("archives", []) if isinstance(result, dict) else result
        out: dict[str, Any] = {"repo": r.name, "count": len(archives), "archives": archives}
        if capped and len(archives) == cap:
            out["note"] = f"showing only the newest {cap} archives - use match/first/last to narrow down"
        return out

    @server.tool(annotations=READ_ONLY)
    async def archive_info(repo: str, archive: str) -> dict[str, Any]:
        """Show details for one archive: stats, duration, hostname, command line."""
        return _sanitized(await runner.run_json(get_repo(repo), commands.archive_info_cmd(archive)))

    @server.tool(annotations=READ_ONLY)
    async def latest_archive(repo: str) -> dict[str, Any]:
        """Show the newest archive and its age - answers "is my backup fresh?"."""
        r = get_repo(repo)
        result = await runner.run_json(r, commands.latest_archive_cmd())
        archives = result.get("archives", []) if isinstance(result, dict) else []
        if not archives:
            return {"repo": r.name, "latest": None, "note": "repository contains no archives"}
        latest = archives[0]
        age = _age_seconds(latest.get("end") or latest.get("start"))
        return {"repo": r.name, "latest": latest, "age_seconds": age, "age": _age_human(age)}

    @server.tool(annotations=READ_ONLY)
    async def prune_preview(
        repo: str,
        keep_secondly: int | None = None,
        keep_minutely: int | None = None,
        keep_hourly: int | None = None,
        keep_daily: int | None = None,
        keep_weekly: int | None = None,
        keep_monthly: int | None = None,
        keep_yearly: int | None = None,
    ) -> dict[str, Any]:
        """Show which archives a prune with these retention rules would remove.

        This is always a dry run: borg-mcp cannot delete anything. At least one keep rule is required.
        """
        r = get_repo(repo)
        given = {
            "secondly": keep_secondly,
            "minutely": keep_minutely,
            "hourly": keep_hourly,
            "daily": keep_daily,
            "weekly": keep_weekly,
            "monthly": keep_monthly,
            "yearly": keep_yearly,
        }
        keep = {rule: value for rule, value in given.items() if value is not None}
        result = await runner.run_json(r, commands.prune_preview_cmd(keep))
        archives = result.get("archives", []) if isinstance(result, dict) else []
        cap = config.max_items
        kept = [a for a in archives if a.get("kept")]
        pruned = [a for a in archives if not a.get("kept")]
        out: dict[str, Any] = {
            "repo": r.name,
            "keep_rules": {f"keep_{k}": v for k, v in keep.items()},
            "dry_run": True,
            "would_keep_count": len(kept),
            "would_prune_count": len(pruned),
            "would_keep": [_prune_entry(a) for a in kept[:cap]],
            "would_prune": [_prune_entry(a) for a in pruned[:cap]],
            "note": "preview only - borg-mcp never deletes archives",
        }
        return out

    # File-level tools disclose the names of the backed up files, so they are not
    # registered at all unless the operator opted in - an agent cannot even see them.
    if config.allow_file_listing:

        @server.tool(annotations=READ_ONLY)
        async def list_archive_contents(
            repo: str, archive: str, path_prefix: str | None = None, limit: int | None = None
        ) -> dict[str, Any]:
            """List the files and directories stored in an archive.

            path_prefix: only items at or below this path inside the archive (literal path, not a pattern).
            limit: maximum number of items to return (default and maximum: the server's max_items).
            """
            r = get_repo(repo)
            n = _capped_limit(limit, config.max_items)
            cmd = commands.list_archive_cmd(archive, path_prefix)
            items, truncated = await runner.run_json_lines(r, cmd, n)
            out: dict[str, Any] = {"repo": r.name, "archive": archive, "count": len(items), "items": items}
            if truncated:
                out["note"] = f"stopped after {n} items - use path_prefix or a larger limit to see more"
            return out

        @server.tool(annotations=READ_ONLY)
        async def diff_archives(
            repo: str, archive1: str, archive2: str, path_prefix: str | None = None, limit: int | None = None
        ) -> dict[str, Any]:
            """Show which files differ between two archives (archive1 -> archive2).

            path_prefix: only items at or below this path inside the archives (literal path, not a pattern).
            limit: maximum number of changes to return (default and maximum: the server's max_items).
            """
            r = get_repo(repo)
            n = _capped_limit(limit, config.max_items)
            cmd = commands.diff_archives_cmd(archive1, archive2, path_prefix)
            changes, truncated = await runner.run_json_lines(r, cmd, n)
            out: dict[str, Any] = {
                "repo": r.name,
                "archive1": archive1,
                "archive2": archive2,
                "count": len(changes),
                "changes": changes,
            }
            if truncated:
                out["note"] = f"stopped after {n} changes - use path_prefix or a larger limit to see more"
            return out

    return server
