"""End-to-end tests against a real borg2 binary and repository.

Uses `borg` from PATH if it is borg2, or the binary named by BORG_MCP_TEST_BORG.
Skipped entirely when no borg2 is available.
"""

import os
import shutil
import subprocess

import pytest

from borg_mcp.cli import main
from borg_mcp.config import RepoConfig, ServerConfig
from borg_mcp.server import create_server

PASSPHRASE = "test"


def find_borg2() -> str | None:
    binary = os.environ.get("BORG_MCP_TEST_BORG") or shutil.which("borg")
    if not binary:
        return None
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    words = out.split()
    if len(words) == 2 and words[0] == "borg" and words[1].startswith("2."):
        return binary
    return None


BORG2 = find_borg2()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(BORG2 is None, reason="no borg2 binary found (set BORG_MCP_TEST_BORG)"),
]


def borg(repo_path, *args, **env_overrides):
    env = {**os.environ, "BORG_PASSPHRASE": PASSPHRASE, "BORG_TESTONLY_WEAKEN_KDF": "1", **env_overrides}
    subprocess.run([BORG2, *args, f"--repo={repo_path}"], check=True, env=env, capture_output=True, timeout=120)


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    base = tmp_path_factory.mktemp("borg-mcp-it")
    repo_path = str(base / "repo")
    data = base / "data"
    data.mkdir()
    (data / "file1.txt").write_text("hello borg-mcp\n" * 100)
    borg(repo_path, "repo-create", "--encryption=aes256-ocb")
    borg(repo_path, "create", "archive1", str(data))
    (data / "file2.txt").write_text("more data\n" * 100)
    borg(repo_path, "create", "archive2", str(data))
    return repo_path


@pytest.fixture
def config(repo):
    return ServerConfig(
        repos={
            "it": RepoConfig(
                name="it",
                location=repo,
                description="integration test repo",
                passcommand=f"echo {PASSPHRASE}",
                extra_env={"BORG_TESTONLY_WEAKEN_KDF": "1"},
            )
        },
        borg_binary=BORG2,
        max_items=100,
    )


@pytest.fixture
def server(config):
    return create_server(config)


async def test_repo_info(server, call):
    result = await call(server, "repo_info", {"repo": "it"})
    repo_id = result["repository"]["id"]
    assert len(repo_id) == 64
    int(repo_id, 16)
    assert "cache" not in result
    assert "security_dir" not in result


async def test_list_archives(server, call):
    result = await call(server, "list_archives", {"repo": "it"})
    assert result["count"] == 2
    assert [a["name"] for a in result["archives"]] == ["archive1", "archive2"]


async def test_list_archives_match(server, call):
    result = await call(server, "list_archives", {"repo": "it", "match": "sh:*2"})
    assert [a["name"] for a in result["archives"]] == ["archive2"]


async def test_list_archives_last(server, call):
    result = await call(server, "list_archives", {"repo": "it", "last": 1})
    assert [a["name"] for a in result["archives"]] == ["archive2"]


async def test_archive_info(server, call):
    result = await call(server, "archive_info", {"repo": "it", "archive": "archive1"})
    (archive,) = result["archives"]
    assert archive["name"] == "archive1"
    assert archive["stats"]["nfiles"] >= 1
    assert archive["duration"] >= 0


async def test_latest_archive(server, call):
    result = await call(server, "latest_archive", {"repo": "it"})
    assert result["latest"]["name"] == "archive2"
    assert result["age_seconds"] is not None
    assert 0 <= result["age_seconds"] < 3600


async def test_wrong_passphrase_fails_cleanly(config, call):
    import dataclasses

    bad_repo = dataclasses.replace(config.repos["it"], passcommand="echo wrong")
    bad_config = dataclasses.replace(config, repos={"it": bad_repo})
    server = create_server(bad_config)
    with pytest.raises(Exception, match="failed for repository 'it'"):
        await server.call_tool("repo_info", {"repo": "it"})


def test_check_cli(repo, tmp_path, capsys):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f'[server]\nborg_binary = "{BORG2}"\n\n'
        f'[repos.it]\nlocation = "{repo}"\npasscommand = "echo {PASSPHRASE}"\n'
        f'extra_env = {{ BORG_TESTONLY_WEAKEN_KDF = "1" }}\n'
    )
    with pytest.raises(SystemExit) as exc:
        main(["check", "--config", str(config_file), "it"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config OK" in out
    assert "borg OK" in out
    assert "it: OK (repository id " in out
