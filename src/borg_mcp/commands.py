"""borg2 command templates - the complete allowlist of what borg-mcp may execute.

Values originating from the MCP client (the agent) are validated here and only
ever placed in ``--option=value`` form or as strictly checked positionals, so
borg's argument parser can never mistake them for additional options.
"""

MAX_VALUE_LEN = 200
MAX_LIST_LIMIT = 100000


class ValidationError(Exception):
    """An agent-supplied value was rejected."""


def _checked_str(value, what: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{what} must be a string")
    if not 0 < len(value) <= MAX_VALUE_LEN:
        raise ValidationError(f"{what} must be 1..{MAX_VALUE_LEN} characters")
    if value.startswith("-"):
        raise ValidationError(f"{what} must not start with '-'")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValidationError(f"{what} must not contain control characters")
    return value


def _checked_int(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{what} must be an integer")
    if not 1 <= value <= MAX_LIST_LIMIT:
        raise ValidationError(f"{what} must be in 1..{MAX_LIST_LIMIT}")
    return value


def version_cmd() -> list[str]:
    return ["--version"]


def repo_info_cmd() -> list[str]:
    return ["repo-info", "--json"]


def _checked_match(value, what: str) -> str:
    value = _checked_str(value, what)
    # borg's re: patterns run Python regexes on the server - a crafted pattern with
    # catastrophic backtracking would let the agent burn CPU (ReDoS). Globs suffice.
    if value.startswith("re:") or ":re:" in value:
        raise ValidationError(f"{what}: regular expression patterns (re:) are not allowed, use sh: globs")
    return value


def repo_list_cmd(match: str | None = None, first: int | None = None, last: int | None = None) -> list[str]:
    if first is not None and last is not None:
        raise ValidationError("give either first or last, not both")
    cmd = ["repo-list", "--json"]
    if match is not None:
        cmd.append(f"--match-archives={_checked_match(match, 'match')}")
    if first is not None:
        cmd.append(f"--first={_checked_int(first, 'first')}")
    if last is not None:
        cmd.append(f"--last={_checked_int(last, 'last')}")
    return cmd


def archive_info_cmd(archive: str) -> list[str]:
    return ["info", "--json", _checked_str(archive, "archive")]


def latest_archive_cmd() -> list[str]:
    return ["info", "--json", "--last=1"]
