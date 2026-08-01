import pytest

import itertools

from borg_mcp.commands import (
    KEEP_RULES,
    MAX_KEEP,
    ValidationError,
    archive_info_cmd,
    diff_archives_cmd,
    latest_archive_cmd,
    list_archive_cmd,
    prune_preview_cmd,
    repo_info_cmd,
    repo_list_cmd,
    version_cmd,
)


def test_fixed_commands():
    assert version_cmd() == ["--version"]
    assert repo_info_cmd() == ["repo-info", "--json"]
    assert latest_archive_cmd() == ["info", "--json", "--last=1"]


def test_repo_list_plain():
    assert repo_list_cmd() == ["repo-list", "--json"]


def test_repo_list_filters():
    assert repo_list_cmd(match="sh:home-*") == ["repo-list", "--json", "--match-archives=sh:home-*"]
    assert repo_list_cmd(first=3) == ["repo-list", "--json", "--first=3"]
    assert repo_list_cmd(last=5) == ["repo-list", "--json", "--last=5"]


def test_repo_list_first_and_last():
    with pytest.raises(ValidationError, match="not both"):
        repo_list_cmd(first=1, last=1)


def test_archive_info():
    assert archive_info_cmd("my-archive.2026-08-01") == ["info", "--json", "my-archive.2026-08-01"]


@pytest.mark.parametrize(
    "value,message",
    [
        ("-evil", "must not start with '-'"),
        ("--delete", "must not start with '-'"),
        ("a\nb", "control characters"),
        ("a\x00b", "control characters"),
        ("a\x7fb", "control characters"),
        ("", "1..200"),
        ("x" * 201, "1..200"),
        (42, "must be a string"),
    ],
)
def test_bad_string_values(value, message):
    with pytest.raises(ValidationError, match=message):
        archive_info_cmd(value)
    with pytest.raises(ValidationError, match=message):
        repo_list_cmd(match=value)


@pytest.mark.parametrize("value", ["re:(a+)+b", "re:.*", "name:re:x"])
def test_regex_match_rejected(value):
    # re: patterns would run agent-supplied regexes on the server (ReDoS)
    with pytest.raises(ValidationError, match="not allowed"):
        repo_list_cmd(match=value)


@pytest.mark.parametrize("value", ["home", "sh:home-*", "aid:0fae632d", "host:MacBook-Pro-4"])
def test_safe_match_accepted(value):
    assert repo_list_cmd(match=value) == ["repo-list", "--json", f"--match-archives={value}"]


def test_archive_name_none_rejected():
    # None means "not given" for the optional match filter, but never for a required archive name
    with pytest.raises(ValidationError, match="must be a string"):
        archive_info_cmd(None)


@pytest.mark.parametrize("value", [0, -1, 100001, True, "5", 1.5])
def test_bad_int_values(value):
    with pytest.raises(ValidationError):
        repo_list_cmd(first=value)
    with pytest.raises(ValidationError):
        repo_list_cmd(last=value)


def test_list_archive():
    assert list_archive_cmd("arch") == ["list", "--json-lines", "arch"]
    assert list_archive_cmd("arch", "home/tw") == ["list", "--json-lines", "arch", "pp:home/tw"]


def test_diff_archives():
    assert diff_archives_cmd("a1", "a2") == ["diff", "--json-lines", "a1", "a2"]
    assert diff_archives_cmd("a1", "a2", "home") == ["diff", "--json-lines", "a1", "a2", "pp:home"]


@pytest.mark.parametrize("prefix", ["re:(a+)+b", "sh:**", "fm:*", "pp:other"])
def test_path_prefix_selectors_neutralized(prefix):
    # a smuggled selector must end up inside the literal pp: path, not as its own selector
    (arg,) = list_archive_cmd("arch", prefix)[3:]
    assert arg == f"pp:{prefix}"


@pytest.mark.parametrize("value", ["-x", "a\nb", "", "x" * 201])
def test_bad_path_prefix_rejected(value):
    with pytest.raises(ValidationError):
        list_archive_cmd("arch", value)
    with pytest.raises(ValidationError):
        diff_archives_cmd("a1", "a2", value)


@pytest.mark.parametrize("bad", ["--delete", "-x", "a\nb"])
def test_diff_archive_names_validated(bad):
    with pytest.raises(ValidationError):
        diff_archives_cmd(bad, "a2")
    with pytest.raises(ValidationError):
        diff_archives_cmd("a1", bad)


def test_prune_preview():
    assert prune_preview_cmd({"daily": 7}) == ["prune", "--dry-run", "--list", "--json", "--keep-daily=7"]
    assert prune_preview_cmd({"weekly": 4, "daily": 7}) == [
        "prune",
        "--dry-run",
        "--list",
        "--json",
        "--keep-daily=7",
        "--keep-weekly=4",  # fixed order, independent of input order
    ]


def test_prune_always_dry_run():
    """The safety net: no combination of accepted input may produce a real prune."""
    for count in range(1, len(KEEP_RULES) + 1):
        for rules in itertools.combinations(KEEP_RULES, count):
            cmd = prune_preview_cmd(dict.fromkeys(rules, 1))
            assert cmd[0] == "prune"
            assert "--dry-run" in cmd
    # ... and every value a client can get past validation keeps the dry run
    for value in (0, 1, MAX_KEEP):
        assert "--dry-run" in prune_preview_cmd({"daily": value})


def test_prune_needs_a_keep_rule():
    with pytest.raises(ValidationError, match="at least one keep rule"):
        prune_preview_cmd({})


def test_prune_unknown_rule():
    with pytest.raises(ValidationError, match="unknown keep rule"):
        prune_preview_cmd({"daily": 7, "fortnightly": 2})


@pytest.mark.parametrize("value", [-1, MAX_KEEP + 1, "7", 7.0, True, None])
def test_prune_bad_keep_value(value):
    with pytest.raises(ValidationError):
        prune_preview_cmd({"daily": value})


def test_no_option_smuggling_via_match():
    # agent-influenced values always end up in --opt=value form, never as separate argv items
    cmd = repo_list_cmd(match="sh:*")
    assert all(arg.startswith(("repo-list", "--json", "--match-archives=")) for arg in cmd)
