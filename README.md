# borg-mcp

A **read-only [MCP](https://modelcontextprotocol.io/) server** for
[BorgBackup](https://www.borgbackup.org/) operational status.

borg-mcp lets AI agents (Claude, and other MCP clients) answer questions like
*"is my backup fresh?"*, *"how big is the repo?"*, *"what would prune remove?"*
— without any ability to modify or destroy backups.

It is a companion project to [borg](https://github.com/borgbackup/borg),
born from [borg#9955](https://github.com/borgbackup/borg/issues/9955).
It is intentionally **not** part of borg core: the safety boundary for
untrusted AI agents lives in this small, auditable project.

**Status: pre-alpha, under development.** Requires borg2 (no borg 1.x support).

## Security model

The MCP client (the agent) is treated as **untrusted input** — it may be
prompt-injected or simply wrong. Therefore:

- **Command allowlist, not passthrough.** Only a fixed set of borg
  subcommands with fixed argument templates is ever executed. No
  agent-supplied flags, no shell.
- **Repository allowlist.** Repositories are configured server-side with
  aliases; the agent refers to `"home"`, never to a raw path or URL.
- **No secrets over MCP.** Passphrases come from configured passcommands on
  the server side and never appear in tool results or logs.
- **Sanitized, size-capped output.** Raw file listings are off by default
  (explicit config opt-in); all listings are paginated.
- **Read-only by construction — and by enforcement.** borg-mcp never runs
  prune/delete/compact/repair/restore. For defense in depth, run it against
  repositories accessed via an SSH key that is restricted server-side to
  read-only `borg serve`, and run borg-mcp itself as an unprivileged user.
- **Audit log.** Every tool invocation is logged.

Never in scope: executing destructive operations, key export, passphrase
handling over MCP, arbitrary borg commands.

## Requirements

- Python >= 3.11
- borg2, installed from the
  [master branch](https://github.com/borgbackup/borg) (borg-mcp drives the
  `borg` CLI; it does not import borg internals)

## Installation

There is no PyPI release; install from git:

```
pip install git+https://github.com/borgbackup/borg-mcp.git
```

or from a checkout: `pip install .`

## Configuration

TOML, at `~/.config/borg-mcp/config.toml` (or `/etc/borg-mcp.toml`).
The config file holds all security-relevant settings and must not be
writable by the agent's account — there are deliberately no CLI overrides.

```toml
[server]
allow_file_listing = false   # raw archive contents listing, off by default
timeout = 300
max_items = 1000             # pagination cap for listings

[repos.home]
location = "ssh://backup@host/./home"
description = "workstation home dirs, nightly"
passcommand = "cat /path/to/passphrase-file"
```

## Usage

```
borg-mcp serve [--config PATH]      # run the stdio MCP server
borg-mcp check [--config PATH] [ALIAS ...]
                                    # validate config; with aliases, test
                                    # repository access
```

MCP client configuration (e.g. Claude Code `.mcp.json`):

```json
{
  "mcpServers": {
    "borg": {
      "command": "borg-mcp",
      "args": ["serve", "--config", "/path/to/config.toml"]
    }
  }
}
```

## Tools

| tool | answers |
|---|---|
| `list_repositories` | which repositories can I ask about? |
| `repo_info` | repository ID, size, encryption mode |
| `list_archives` | which archives exist? (paginated, filterable) |
| `archive_info` | stats, duration, hostname for one archive |
| `latest_archive` | is my backup fresh? |
| `prune_preview` | what *would* prune remove? (always dry-run) |

## License

BSD-3-Clause, see [LICENSE](LICENSE) and [AUTHORS](AUTHORS).
