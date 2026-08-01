# Security Policy

## Supported Versions

borg-mcp is pre-release software; there are no supported release versions yet.
Security fixes land on the `master` branch.

| Version | Supported          |
|---------|--------------------|
| master  | :white_check_mark: |

## Reporting a Vulnerability

Please report vulnerabilities privately via the BorgBackup security contact:

https://borgbackup.readthedocs.io/en/latest/support.html#security-contact

Please do not open public issues for security problems.

## Scope notes

borg-mcp's security model treats the MCP client (the AI agent) as untrusted
input; anything that lets an agent execute non-allowlisted borg commands,
modify repositories, or obtain passphrases through borg-mcp is a
vulnerability. The configuration file is trusted admin input - attacks
requiring control of the config file or the borg binary are out of scope.
