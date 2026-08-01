import pytest

from borg_mcp.commands import (
    ValidationError,
    archive_info_cmd,
    latest_archive_cmd,
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


def test_no_option_smuggling_via_match():
    # agent-influenced values always end up in --opt=value form, never as separate argv items
    cmd = repo_list_cmd(match="sh:*")
    assert all(arg.startswith(("repo-list", "--json", "--match-archives=")) for arg in cmd)
