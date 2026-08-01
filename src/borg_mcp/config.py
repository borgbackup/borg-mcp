"""Configuration loading and validation.

The config file holds all security-relevant settings (repository allowlist,
passcommands, feature toggles). It is trusted admin input, but it is still
validated strictly: a typo must fail loudly at startup, not silently relax a
restriction at tool-call time.
"""

import logging
import os
import re
import stat
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATHS = (Path("~/.config/borg-mcp/config.toml"), Path("/etc/borg-mcp.toml"))

ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ENV_NAME_RE = re.compile(r"^BORG_[A-Z0-9_]+$")
# secrets belong in passcommand, nothing may inject them as plain env values
ENV_DENYLIST = frozenset({"BORG_PASSPHRASE", "BORG_PASSCOMMAND", "BORG_REPO"})

MIN_TIMEOUT, MAX_TIMEOUT = 1, 86400
MIN_MAX_ITEMS, MAX_MAX_ITEMS = 1, 100000


class ConfigError(Exception):
    """Invalid or missing configuration."""


@dataclass(frozen=True)
class RepoConfig:
    name: str
    location: str
    description: str = ""
    passcommand: str | None = None
    extra_env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ServerConfig:
    repos: dict[str, RepoConfig]
    borg_binary: str = "borg"
    allow_file_listing: bool = False
    timeout: int = 300
    max_items: int = 1000


def find_config(path: str | None) -> Path:
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise ConfigError(f"config file not found: {p}")
        return p
    for candidate in DEFAULT_CONFIG_PATHS:
        p = candidate.expanduser()
        if p.is_file():
            return p
    raise ConfigError("no config file found (tried: %s)" % ", ".join(str(p) for p in DEFAULT_CONFIG_PATHS))


def _check_keys(what: str, table: dict, allowed: set[str]) -> None:
    unknown = set(table) - allowed
    if unknown:
        raise ConfigError(f"{what}: unknown key(s): {', '.join(sorted(unknown))}")


def _typed(what: str, table: dict, key: str, typ: type, default):
    value = table.get(key, default)
    if not isinstance(value, typ) or (typ is int and isinstance(value, bool)):
        raise ConfigError(f"{what}: {key} must be of type {typ.__name__}")
    return value


def _load_repo(name: str, table: object) -> RepoConfig:
    what = f"repos.{name}"
    if not ALIAS_RE.match(name):
        raise ConfigError(f"invalid repository alias {name!r} (allowed: letters, digits, '.', '_', '-')")
    if not isinstance(table, dict):
        raise ConfigError(f"{what}: must be a table")
    _check_keys(what, table, {"location", "description", "passcommand", "extra_env"})
    location = _typed(what, table, "location", str, "")
    if not location:
        raise ConfigError(f"{what}: location is required")
    description = _typed(what, table, "description", str, "")
    passcommand = table.get("passcommand")
    if passcommand is not None and (not isinstance(passcommand, str) or not passcommand):
        raise ConfigError(f"{what}: passcommand must be a non-empty string")
    extra_env = _typed(what, table, "extra_env", dict, {})
    for env_name, env_value in extra_env.items():
        if not isinstance(env_value, str):
            raise ConfigError(f"{what}: extra_env.{env_name} must be a string")
        if env_name in ENV_DENYLIST:
            raise ConfigError(f"{what}: extra_env must not set {env_name} (use passcommand for secrets)")
        if not ENV_NAME_RE.match(env_name):
            raise ConfigError(f"{what}: extra_env only allows BORG_* variables, got {env_name!r}")
    return RepoConfig(
        name=name, location=location, description=description, passcommand=passcommand, extra_env=dict(extra_env)
    )


def _check_permissions(path: Path) -> None:
    mode = path.stat().st_mode
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        logger.warning("config file %s is group/world-writable - it should only be writable by its owner", path)
    if mode & stat.S_IROTH:
        logger.warning("config file %s is world-readable - it may reveal repository locations", path)


def load_config(path: Path) -> ServerConfig:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"cannot read config file {path}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from e
    _check_permissions(path)
    _check_keys(str(path), data, {"server", "repos"})
    server = data.get("server", {})
    if not isinstance(server, dict):
        raise ConfigError("server: must be a table")
    _check_keys("server", server, {"borg_binary", "allow_file_listing", "timeout", "max_items"})
    borg_binary = _typed("server", server, "borg_binary", str, "borg")
    if not borg_binary:
        raise ConfigError("server: borg_binary must be a non-empty string")
    allow_file_listing = _typed("server", server, "allow_file_listing", bool, False)
    timeout = _typed("server", server, "timeout", int, 300)
    if not MIN_TIMEOUT <= timeout <= MAX_TIMEOUT:
        raise ConfigError(f"server: timeout must be in [{MIN_TIMEOUT}, {MAX_TIMEOUT}]")
    max_items = _typed("server", server, "max_items", int, 1000)
    if not MIN_MAX_ITEMS <= max_items <= MAX_MAX_ITEMS:
        raise ConfigError(f"server: max_items must be in [{MIN_MAX_ITEMS}, {MAX_MAX_ITEMS}]")
    repos_table = data.get("repos", {})
    if not isinstance(repos_table, dict) or not repos_table:
        raise ConfigError("config must define at least one repository in [repos.<alias>]")
    repos = {name: _load_repo(name, table) for name, table in repos_table.items()}
    return ServerConfig(
        repos=repos,
        borg_binary=borg_binary,
        allow_file_listing=allow_file_listing,
        timeout=timeout,
        max_items=max_items,
    )


def base_env() -> dict[str, str]:
    """Minimal environment for borg subprocesses.

    Nothing from the parent environment leaks through except what borg needs
    to run (PATH, HOME, ...) - especially no BORG_* variables the operator may
    have set in their own shell.
    """
    keep = ("PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "SSH_AUTH_SOCK")
    return {k: os.environ[k] for k in keep if k in os.environ}


def repo_env(repo: RepoConfig) -> dict[str, str]:
    env = base_env()
    env.update(repo.extra_env)
    if repo.passcommand:
        env["BORG_PASSCOMMAND"] = repo.passcommand
    return env
