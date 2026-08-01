"""End-to-end test over the real stdio transport.

Starts `python -m borg_mcp serve` as a subprocess and talks to it with the
MCP SDK client - the exact path an agent takes. Uses the fake borg, so no
real repository is needed.
"""

import sys

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client


@pytest.fixture
def config_file(tmp_path, fake_borg):
    p = tmp_path / "config.toml"
    p.write_text(f'[server]\nborg_binary = "{fake_borg}"\n\n[repos.test]\nlocation = "/path/to/repo"\n')
    return str(p)


async def test_stdio_roundtrip(config_file):
    params = StdioServerParameters(command=sys.executable, args=["-m", "borg_mcp", "serve", "--config", config_file])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.server_info.name == "borg-mcp"

            tools = await session.list_tools()
            assert {t.name for t in tools.tools} >= {"list_repositories", "repo_info", "latest_archive"}

            result = await session.call_tool("repo_info", {"repo": "test"})
            assert not result.is_error
            assert result.structured_content["repository"]["id"] == "beef" * 16

            result = await session.call_tool("latest_archive", {"repo": "test"})
            assert not result.is_error
            assert result.structured_content["latest"]["name"] == "archive2"

            # over the wire, rejected values come back as error results, not crashes
            result = await session.call_tool("archive_info", {"repo": "test", "archive": "--delete"})
            assert result.is_error

            result = await session.call_tool("repo_info", {"repo": "nope"})
            assert result.is_error
