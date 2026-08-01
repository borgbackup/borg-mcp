import time

import pytest

from borg_mcp.config import RepoConfig, ServerConfig
from borg_mcp.runner import BorgError, BorgRunner
from conftest import read_argv_log


def make_runner(borg, **kwargs):
    repo = RepoConfig(name="test", location="/path/to/repo", extra_env=kwargs.pop("extra_env", {}))
    config = ServerConfig(repos={"test": repo}, borg_binary=borg, **kwargs)
    return BorgRunner(config), repo


async def test_run_json_success(fake_borg):
    runner, repo = make_runner(fake_borg)
    result = await runner.run_json(repo, ["repo-info", "--json"])
    assert result["repository"]["id"] == "beef" * 16


async def test_argv_construction(fake_borg_logged):
    borg, log = fake_borg_logged
    runner, repo = make_runner(borg)
    await runner.run_json(repo, ["repo-list", "--json", "--last=5"])
    (argv,) = read_argv_log(log)
    assert argv == ["repo-list", "--json", "--last=5", "--repo=/path/to/repo"]


async def test_nonzero_exit(make_fake_borg):
    borg = make_fake_borg('import sys\nprint("borg: some error", file=sys.stderr)\nsys.exit(2)\n')
    runner, repo = make_runner(borg)
    with pytest.raises(BorgError, match="rc=2.*some error"):
        await runner.run_json(repo, ["repo-info", "--json"])


async def test_unparseable_output(make_fake_borg):
    borg = make_fake_borg('print("this is not json")\n')
    runner, repo = make_runner(borg)
    with pytest.raises(BorgError, match="unparseable"):
        await runner.run_json(repo, ["repo-info", "--json"])


async def test_timeout_kills(make_fake_borg):
    borg = make_fake_borg("import time\ntime.sleep(30)\n")
    runner, repo = make_runner(borg, timeout=1)
    start = time.monotonic()
    with pytest.raises(BorgError, match="did not finish within 1s"):
        await runner.run_json(repo, ["repo-info", "--json"])
    assert time.monotonic() - start < 10


async def test_missing_binary():
    runner, repo = make_runner("/nonexistent/borg")
    with pytest.raises(BorgError, match="cannot execute"):
        await runner.run_json(repo, ["repo-info", "--json"])


async def test_env_scrubbing(make_fake_borg, monkeypatch):
    monkeypatch.setenv("BORG_PASSPHRASE", "supersecret")
    monkeypatch.setenv("MY_SECRET_TOKEN", "alsosecret")
    borg = make_fake_borg("import json, os\nprint(json.dumps(dict(os.environ)))\n")
    runner, repo = make_runner(borg, extra_env={"BORG_REMOTE_PATH": "borg2"})
    env = await runner.run_json(repo, ["repo-info", "--json"])
    assert "BORG_PASSPHRASE" not in env
    assert "MY_SECRET_TOKEN" not in env
    assert env["BORG_REMOTE_PATH"] == "borg2"


async def test_passcommand_goes_to_env(make_fake_borg):
    borg = make_fake_borg("import json, os\nprint(json.dumps(dict(os.environ)))\n")
    repo = RepoConfig(name="test", location="/r", passcommand="cat /pp")
    config = ServerConfig(repos={"test": repo}, borg_binary=borg)
    env = await BorgRunner(config).run_json(repo, ["repo-info", "--json"])
    assert env["BORG_PASSCOMMAND"] == "cat /pp"


async def test_version(fake_borg):
    runner, _ = make_runner(fake_borg)
    assert await runner.version() == "2.0.0b23"
    assert await runner.check_borg2() == "2.0.0b23"


async def test_check_borg2_rejects_borg1(make_fake_borg):
    borg = make_fake_borg('print("borg 1.4.4")\n')
    runner, _ = make_runner(borg)
    with pytest.raises(BorgError, match="needs borg2"):
        await runner.check_borg2()


async def test_output_size_cap(make_fake_borg, monkeypatch):
    monkeypatch.setattr("borg_mcp.runner.MAX_OUTPUT_BYTES", 100)
    borg = make_fake_borg('print("[" + ",".join(["1"] * 200) + "]")\n')
    runner, repo = make_runner(borg)
    with pytest.raises(BorgError, match="too much output"):
        await runner.run_json(repo, ["repo-list", "--json"])


async def test_endless_output_killed_promptly(make_fake_borg, monkeypatch):
    # the cap must kill the process while it streams, not buffer until timeout/OOM
    monkeypatch.setattr("borg_mcp.runner.MAX_OUTPUT_BYTES", 100_000)
    borg = make_fake_borg('import sys\nwhile True:\n    sys.stdout.write("x" * 65536)\n    sys.stdout.flush()\n')
    runner, repo = make_runner(borg, timeout=60)
    start = time.monotonic()
    with pytest.raises(BorgError, match="too much output"):
        await runner.run_json(repo, ["repo-list", "--json"])
    assert time.monotonic() - start < 10


async def test_traceback_not_forwarded(make_fake_borg, caplog):
    body = (
        "import sys\n"
        'sys.stderr.write("Traceback (most recent call last):\\n")\n'
        "sys.stderr.write('  File \"/Users/someone/borg/repository.py\", line 42, in get\\n')\n"
        'sys.stderr.write("ValueError: something broke\\n")\n'
        "sys.exit(2)\n"
    )
    runner, repo = make_runner(make_fake_borg(body))
    with caplog.at_level("WARNING", logger="borg_mcp.runner"):
        with pytest.raises(BorgError) as exc:
            await runner.run_json(repo, ["repo-info", "--json"])
    # the agent sees the conclusion only, no server internals
    message = str(exc.value)
    assert "ValueError: something broke" in message
    assert "see the server log" in message
    assert "Traceback" not in message
    assert "repository.py" not in message
    # the full traceback went to the server log
    assert any("repository.py" in r.getMessage() for r in caplog.records)


async def test_passcommand_redacted_in_errors(make_fake_borg):
    body = (
        "import sys\n"
        'sys.stderr.write("Passcommand supplied in BORG_PASSCOMMAND failed: Command "\n'
        "    \"\\\"['echo', 'supersecret123']\\\" returned non-zero exit status 1.\\n\")\n"
        "sys.exit(2)\n"
    )
    borg = make_fake_borg(body)
    repo = RepoConfig(name="test", location="/r", passcommand="echo supersecret123")
    config = ServerConfig(repos={"test": repo}, borg_binary=borg)
    with pytest.raises(BorgError) as exc:
        await BorgRunner(config).run_json(repo, ["repo-info", "--json"])
    assert "supersecret123" not in str(exc.value)
    assert "***" in str(exc.value)


async def test_stderr_control_chars_stripped(make_fake_borg):
    body = 'import sys\nsys.stderr.write("\\x1b[31mred error\\x1b[0m\\rdone\\x07")\nsys.exit(2)\n'
    runner, repo = make_runner(make_fake_borg(body))
    with pytest.raises(BorgError) as exc:
        await runner.run_json(repo, ["repo-info", "--json"])
    message = str(exc.value)
    assert "red error" in message
    assert "\x1b" not in message
    assert "\r" not in message
    assert "\x07" not in message


async def test_json_lines_parsing(fake_borg):
    runner, repo = make_runner(fake_borg)
    items, truncated = await runner.run_json_lines(repo, ["list", "--json-lines", "a"], 10)
    assert [i["path"] for i in items] == ["data/file%d.txt" % i for i in range(5)]
    assert truncated is False


async def test_json_lines_limit(fake_borg):
    runner, repo = make_runner(fake_borg)
    items, truncated = await runner.run_json_lines(repo, ["list", "--json-lines", "a"], 3)
    assert len(items) == 3
    assert truncated is True


async def test_json_lines_endless_output_killed_promptly(make_fake_borg):
    # an archive with millions of files must not be read to the end
    body = (
        "import json, sys\n"
        "i = 0\n"
        "while True:\n"
        '    sys.stdout.write(json.dumps({"path": "f%d" % i}) + chr(10))\n'
        "    sys.stdout.flush()\n"
        "    i += 1\n"
    )
    runner, repo = make_runner(make_fake_borg(body), timeout=60)
    start = time.monotonic()
    items, truncated = await runner.run_json_lines(repo, ["list", "--json-lines", "a"], 100)
    assert len(items) == 100
    assert truncated is True
    assert time.monotonic() - start < 10


async def test_json_lines_error_exit(make_fake_borg):
    borg = make_fake_borg('import sys\nprint("borg: archive not found", file=sys.stderr)\nsys.exit(2)\n')
    runner, repo = make_runner(borg)
    with pytest.raises(BorgError, match="archive not found"):
        await runner.run_json_lines(repo, ["list", "--json-lines", "a"], 10)


async def test_json_lines_unparseable(make_fake_borg):
    borg = make_fake_borg('print("not json at all")\n')
    runner, repo = make_runner(borg)
    with pytest.raises(BorgError, match="unparseable"):
        await runner.run_json_lines(repo, ["list", "--json-lines", "a"], 10)


async def test_json_lines_timeout(make_fake_borg):
    borg = make_fake_borg("import time\ntime.sleep(30)\n")
    runner, repo = make_runner(borg, timeout=1)
    with pytest.raises(BorgError, match="did not finish within 1s"):
        await runner.run_json_lines(repo, ["list", "--json-lines", "a"], 10)


async def test_large_stderr_no_deadlock(make_fake_borg):
    # both pipes are drained concurrently - stderr larger than the OS pipe buffer must not deadlock
    body = 'import json, sys\nsys.stderr.write("e" * 262144)\nsys.stderr.flush()\nprint(json.dumps({"ok": 1}))\n'
    runner, repo = make_runner(make_fake_borg(body))
    result = await runner.run_json(repo, ["repo-info", "--json"])
    assert result == {"ok": 1}
