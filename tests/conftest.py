import json
import textwrap

import pytest

from borg_mcp.config import RepoConfig, ServerConfig

# fake borg: emits canned JSON shaped like borg2 --json output, no repo needed
CANNED_BODY = """\
import datetime, json, sys

args = sys.argv[1:]
if args == ["--version"]:
    print("borg 2.0.0b23")
    sys.exit(0)
sub = args[0]
now = datetime.datetime.now().isoformat()


def arch(name):
    return {
        "name": name,
        "id": "aid_" + name,
        "start": now,
        "end": now,
        "hostname": "testhost",
        "username": "tw",
        "command_line": ["borg", "create"],
        "stats": {"nfiles": 3, "original_size": 1000, "compressed_size": 500, "deduplicated_size": 100},
    }


local = {"cache": {"path": "/home/user/.cache/borg/beef"}, "security_dir": "/home/user/.config/borg/security"}
if sub == "repo-info":
    print(json.dumps({"repository": {"id": "beef" * 16, "location": "somewhere"}, **local}))
elif sub == "repo-list":
    print(json.dumps({"archives": [arch("archive1"), arch("archive2")], "repository": {"id": "beef" * 16}}))
elif sub == "info":
    print(json.dumps({"archives": [arch("archive2")], "repository": {"id": "beef" * 16}, **local}))
elif sub == "prune":
    if "--dry-run" not in args:
        sys.stderr.write("FAKE BORG: refusing a real prune" + chr(10))
        sys.exit(99)
    print(json.dumps({"archives": [
        dict(arch("archive2"), kept=True, keep_rule="daily"),
        dict(arch("archive1"), kept=False),
    ]}))
elif sub == "list":
    for i in range(5):
        print(json.dumps({"path": "data/file%d.txt" % i, "type": "-", "size": 100 + i, "mtime": now}))
elif sub == "diff":
    print(json.dumps({"path": "data/file1.txt", "changes": [{"type": "modified", "added": 5, "removed": 2}]}))
    print(json.dumps({"path": "data/new.txt", "changes": [{"type": "added"}]}))
else:
    sys.exit(2)
"""


@pytest.fixture
def make_fake_borg(tmp_path):
    """Factory writing an executable fake borg script; returns its path as str."""

    counter = iter(range(100))

    def make(body: str) -> str:
        script = tmp_path / f"fakeborg{next(counter)}"
        script.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(body))
        script.chmod(0o755)
        return str(script)

    return make


@pytest.fixture
def fake_borg(make_fake_borg):
    return make_fake_borg(CANNED_BODY)


@pytest.fixture
def fake_borg_logged(make_fake_borg, tmp_path):
    """Canned fake borg that also logs each invocation's argv; returns (path, argv_log_path)."""
    log = tmp_path / "argv.log"
    body = f"""\
import json, sys
with open({str(log)!r}, "a") as f:
    f.write(json.dumps(sys.argv[1:]) + chr(10))
""" + CANNED_BODY
    return make_fake_borg(body), log


def read_argv_log(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


@pytest.fixture
def repo_config():
    return RepoConfig(name="test", location="/path/to/repo", description="demo repo")


@pytest.fixture
def server_config(fake_borg, repo_config):
    return ServerConfig(repos={"test": repo_config}, borg_binary=fake_borg, timeout=30, max_items=50)


@pytest.fixture
def file_listing_config(fake_borg, repo_config):
    return ServerConfig(
        repos={"test": repo_config}, borg_binary=fake_borg, timeout=30, max_items=50, allow_file_listing=True
    )


@pytest.fixture
def call():
    """Call an MCP tool and return its structured result (asserts success)."""

    async def _call(server, name, arguments):
        result = await server.call_tool(name, arguments)
        assert not result.is_error, f"tool {name} failed: {result.content}"
        sc = result.structured_content
        if isinstance(sc, dict) and set(sc) == {"result"}:
            return sc["result"]
        return sc

    return _call
