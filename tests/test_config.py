import pytest

from borg_mcp.config import ConfigError, RepoConfig, base_env, find_config, load_config, repo_env

GOOD = """\
[server]
borg_binary = "/usr/local/bin/borg2"
allow_file_listing = false
timeout = 60
max_items = 500

[repos.home]
location = "ssh://backup@host/./home"
description = "home dirs"
passcommand = "cat /path/to/pp"
extra_env = { BORG_REMOTE_PATH = "borg2" }

[repos.media]
location = "/backup/media"
"""


def write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_good_config(tmp_path):
    cfg = load_config(write(tmp_path, GOOD))
    assert cfg.borg_binary == "/usr/local/bin/borg2"
    assert cfg.allow_file_listing is False
    assert cfg.timeout == 60
    assert cfg.max_items == 500
    assert set(cfg.repos) == {"home", "media"}
    home = cfg.repos["home"]
    assert home.name == "home"
    assert home.location == "ssh://backup@host/./home"
    assert home.passcommand == "cat /path/to/pp"
    assert home.extra_env == {"BORG_REMOTE_PATH": "borg2"}
    media = cfg.repos["media"]
    assert media.passcommand is None
    assert media.extra_env == {}


def test_defaults(tmp_path):
    cfg = load_config(write(tmp_path, '[repos.r]\nlocation = "/r"\n'))
    assert cfg.borg_binary == "borg"
    assert cfg.allow_file_listing is False
    assert cfg.timeout == 300
    assert cfg.max_items == 1000


@pytest.mark.parametrize(
    "text,message",
    [
        ("", "at least one repository"),
        ("[server]\ntimeout = 60\n", "at least one repository"),
        ('[repos.r]\ndescription = "x"\n', "location is required"),
        ('[repos."../evil"]\nlocation = "/r"\n', "invalid repository alias"),
        ('[repos."-evil"]\nlocation = "/r"\n', "invalid repository alias"),
        ('[repos.r]\nlocation = "/r"\nfrobnicate = 1\n', "unknown key"),
        ('[typo]\n[repos.r]\nlocation = "/r"\n', "unknown key"),
        ('[server]\nfrobnicate = 1\n[repos.r]\nlocation = "/r"\n', "unknown key"),
        ('[server]\ntimeout = 0\n[repos.r]\nlocation = "/r"\n', "timeout must be in"),
        ('[server]\ntimeout = true\n[repos.r]\nlocation = "/r"\n', "timeout must be of type int"),
        ('[server]\nmax_items = 0\n[repos.r]\nlocation = "/r"\n', "max_items must be in"),
        ('[server]\nborg_binary = ""\n[repos.r]\nlocation = "/r"\n', "non-empty"),
        ('[server]\nallow_file_listing = 1\n[repos.r]\nlocation = "/r"\n', "must be of type bool"),
        ('[repos.r]\nlocation = "/r"\npasscommand = ""\n', "passcommand must be a non-empty string"),
        ('[repos.r]\nlocation = "/r"\nextra_env = { PATH = "/evil" }\n', "only allows BORG_"),
        ('[repos.r]\nlocation = "/r"\nextra_env = { BORG_PASSPHRASE = "s" }\n', "use passcommand"),
        ('[repos.r]\nlocation = "/r"\nextra_env = { BORG_PASSCOMMAND = "s" }\n', "use passcommand"),
        ('[repos.r]\nlocation = "/r"\nextra_env = { BORG_REPO = "/other" }\n', "use passcommand"),
        ('[repos.r]\nlocation = "/r"\nextra_env = { BORG_X = 1 }\n', "must be a string"),
        ("not valid toml [", "invalid TOML"),
    ],
)
def test_bad_config(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, text))


def test_find_config_explicit_missing(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        find_config(str(tmp_path / "nope.toml"))


def test_find_config_explicit(tmp_path):
    p = write(tmp_path, GOOD)
    assert find_config(str(p)) == p


def test_world_writable_warns(tmp_path, caplog):
    p = write(tmp_path, GOOD)
    p.chmod(0o666)
    with caplog.at_level("WARNING"):
        load_config(p)
    assert "writable" in caplog.text


def test_env_scrubbing(monkeypatch):
    monkeypatch.setenv("BORG_PASSPHRASE", "supersecret")
    monkeypatch.setenv("MY_SECRET_TOKEN", "supersecret")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = base_env()
    assert "BORG_PASSPHRASE" not in env
    assert "MY_SECRET_TOKEN" not in env
    assert env["PATH"] == "/usr/bin"


def test_repo_env(monkeypatch):
    monkeypatch.setenv("BORG_PASSPHRASE", "supersecret")
    repo = RepoConfig(name="r", location="/r", passcommand="cat pp", extra_env={"BORG_REMOTE_PATH": "borg2"})
    env = repo_env(repo)
    assert env["BORG_PASSCOMMAND"] == "cat pp"
    assert env["BORG_REMOTE_PATH"] == "borg2"
    assert "BORG_PASSPHRASE" not in env
