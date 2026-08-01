import argparse
import logging

import pytest

from borg_mcp.cli import build_parser, main, setup_logging


def write_config(tmp_path, borg, location="/path/to/repo"):
    p = tmp_path / "config.toml"
    p.write_text(f'[server]\nborg_binary = "{borg}"\n\n[repos.test]\nlocation = "{location}"\n')
    return str(p)


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("borg-mcp ")


def test_subcommand_required():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([])
    assert exc.value.code == 2


def test_parse_serve_and_check():
    args = build_parser().parse_args(["serve", "--config", "/x.toml", "--log-level", "debug"])
    assert args.command == "serve"
    assert args.config == "/x.toml"
    assert args.log_level == "debug"
    args = build_parser().parse_args(["check", "home", "media"])
    assert args.command == "check"
    assert args.aliases == ["home", "media"]


def test_missing_config(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["check", "--config", str(tmp_path / "nope.toml")])
    assert exc.value.code == 2
    assert "not found" in capsys.readouterr().err


def test_check_config_only(tmp_path, fake_borg, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["check", "--config", write_config(tmp_path, fake_borg)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "config OK: 1 repositories: test" in out
    assert "borg OK" in out
    assert "2.0.0b23" in out


def test_check_repo_access(tmp_path, fake_borg, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["check", "--config", write_config(tmp_path, fake_borg), "test"])
    assert exc.value.code == 0
    assert "test: OK (repository id beef" in capsys.readouterr().out


def test_check_unknown_alias(tmp_path, fake_borg, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["check", "--config", write_config(tmp_path, fake_borg), "nope"])
    assert exc.value.code == 2
    assert "nope: FAILED: not a configured alias" in capsys.readouterr().out


def test_check_borg1_rejected(tmp_path, make_fake_borg, capsys):
    borg1 = make_fake_borg('print("borg 1.4.4")\n')
    with pytest.raises(SystemExit) as exc:
        main(["check", "--config", write_config(tmp_path, borg1)])
    assert exc.value.code == 2
    assert "needs borg2" in capsys.readouterr().out


def test_audit_log_always_enabled():
    # the audit trail (borg_mcp.runner at INFO) must be on even at the default warning level
    setup_logging(argparse.Namespace(log_level="warning", log_file=None))
    assert logging.getLogger("borg_mcp.runner").isEnabledFor(logging.INFO)
    assert not logging.getLogger().isEnabledFor(logging.INFO)
    setup_logging(argparse.Namespace(log_level="debug", log_file=None))
    assert logging.getLogger("borg_mcp.runner").isEnabledFor(logging.DEBUG)


def test_check_emits_audit_line(tmp_path, fake_borg, capsys):
    # at the default log level (warning), the audit line must still reach stderr
    with pytest.raises(SystemExit):
        main(["check", "--config", write_config(tmp_path, fake_borg), "test"])
    assert "audit: repo=test cmd=repo-info --json rc=0" in capsys.readouterr().err


def test_serve_borg_failure_exits(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["serve", "--config", write_config(tmp_path, "/nonexistent/borg")])
    assert exc.value.code == 2
    assert "cannot execute" in capsys.readouterr().err
