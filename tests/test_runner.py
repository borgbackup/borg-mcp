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
