import dataclasses

import pytest

from borg_mcp.server import create_server
from conftest import read_argv_log

TOOLS = {"list_repositories", "repo_info", "list_archives", "archive_info", "latest_archive"}


async def test_tools_registered_read_only(server_config):
    server = create_server(server_config)
    tools = await server.list_tools()
    assert {t.name for t in tools} == TOOLS
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


async def test_list_repositories(server_config, call):
    result = await call(create_server(server_config), "list_repositories", {})
    assert result == [{"repo": "test", "description": "demo repo", "location": "/path/to/repo"}]


async def test_repo_info(server_config, call):
    result = await call(create_server(server_config), "repo_info", {"repo": "test"})
    assert result["repository"]["id"] == "beef" * 16
    # server-local paths are stripped from results
    assert "cache" not in result
    assert "security_dir" not in result


async def test_list_archives(server_config, call):
    result = await call(create_server(server_config), "list_archives", {"repo": "test"})
    assert result["repo"] == "test"
    assert result["count"] == 2
    assert [a["name"] for a in result["archives"]] == ["archive1", "archive2"]


async def test_list_archives_default_cap(fake_borg_logged, server_config, call):
    borg, log = fake_borg_logged
    config = dataclasses.replace(server_config, borg_binary=borg, max_items=50)
    await call(create_server(config), "list_archives", {"repo": "test"})
    (argv,) = read_argv_log(log)
    assert "--last=50" in argv


async def test_list_archives_over_cap(server_config, call):
    with pytest.raises(Exception, match="limited to 50"):
        await create_server(server_config).call_tool("list_archives", {"repo": "test", "last": 51})


async def test_archive_info(server_config, call):
    result = await call(create_server(server_config), "archive_info", {"repo": "test", "archive": "archive2"})
    assert result["archives"][0]["name"] == "archive2"
    assert "cache" not in result
    assert "security_dir" not in result


async def test_latest_archive(server_config, call):
    result = await call(create_server(server_config), "latest_archive", {"repo": "test"})
    assert result["latest"]["name"] == "archive2"
    assert result["age_seconds"] is not None
    assert 0 <= result["age_seconds"] < 3600
    assert result["age"].endswith("seconds")


async def test_latest_archive_empty(make_fake_borg, server_config, call):
    borg = make_fake_borg('import json\nprint(json.dumps({"archives": []}))\n')
    config = dataclasses.replace(server_config, borg_binary=borg)
    result = await call(create_server(config), "latest_archive", {"repo": "test"})
    assert result["latest"] is None
    assert "no archives" in result["note"]


async def test_unknown_alias(server_config):
    server = create_server(server_config)
    for tool, args in [
        ("repo_info", {"repo": "nope"}),
        ("list_archives", {"repo": "../etc"}),
        ("archive_info", {"repo": "nope", "archive": "a"}),
        ("latest_archive", {"repo": "nope"}),
    ]:
        with pytest.raises(Exception, match="unknown repository alias"):
            await server.call_tool(tool, args)


async def test_flag_smuggling_rejected(fake_borg_logged, server_config):
    borg, log = fake_borg_logged
    config = dataclasses.replace(server_config, borg_binary=borg)
    server = create_server(config)
    for tool, args in [
        ("archive_info", {"repo": "test", "archive": "--delete"}),
        ("archive_info", {"repo": "test", "archive": "a\nb"}),
        ("list_archives", {"repo": "test", "match": "-evil"}),
    ]:
        with pytest.raises(Exception, match="must not"):
            await server.call_tool(tool, args)
    assert not log.exists(), "borg must never have been executed for rejected values"
