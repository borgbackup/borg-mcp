# Contributing to borg-mcp

First of all, thank you for considering contributing to borg-mcp!

## How to Contribute

1.  **Discuss Changes:** Before starting major work, please discuss your proposed changes on the [GitHub issue tracker](https://github.com/borgbackup/borg-mcp/issues). Smaller changes can also be discussed in the comments of the pull request.
2.  **Branching Model:** Pull Requests should be made against the `master` branch.
3.  **Pull Requests:**
    - Create a feature branch for your changes.
    - Keep changesets clean and focused on a single topic.
    - Reference any related issues in your commit messages.
    - Ensure your PR includes tests and documentation for new features.
    - Proof read your PR yourself, fix typos and other obvious issues.

## Scope

borg-mcp is deliberately small and read-only. Please read the security model
in the [README](README.md) before proposing new features: anything that
executes destructive borg operations, passes agent-supplied flags through to
borg, or handles secrets over MCP is out of scope and will not be merged.

## Responsible AI Usage

You are welcome to use AI tools, but we require that a human is always "in the loop".

AI-generated content must not be submitted without active critical review, modification, and integration by the human contributor. We require that the final contribution is a product of human creative control and that AI is only used as a supportive tool to assist the human author.

As the contributor, you are responsible for the entire content of your pull request.

This includes:
- Verifying the correctness and security of any AI-generated code.
- Ensuring that new or modified code is covered by correct tests.
- Proofreading and refining any AI-generated documentation or comments.
- Being able to explain, debug, and maintain the code you submit.

Always be aware of the limitations and the ecological footprint of AI tools and act accordingly:
- Do not just believe what AI tells you, but verify it critically. AI is known to hallucinate, to be over-confident and to always tell you that you are right, even when you are not.
- Do not use AI tools for tasks that can be done more efficiently manually or by simpler tools.
- Learn how to use AI tools efficiently.

## Development Setup

borg-mcp is pure Python (>= 3.11). To set up a development environment:

1.  Create and activate a virtual environment.
2.  Install borg-mcp in editable mode: `pip install -e .`
3.  Install borg2 from the [master branch](https://github.com/borgbackup/borg) if you want to run the integration tests.

## Code Style

We use [Black](https://black.readthedocs.io/) for automated code formatting, with the same settings as borg (line length 120).
- Check formatting: `black --check .`
- Apply formatting: `black .`

## Running Tests

We use `tox` and `pytest` for testing.
- Run all tests: `tox`
- Integration tests need a working borg2 binary and are skipped otherwise.
  Point them at a specific one with `BORG_MCP_TEST_BORG=/path/to/borg`.
- `tox -e bandit` runs a static security check over the sources.

## Security

If you discover a security vulnerability, please report it privately following the [BorgBackup security policy](https://github.com/borgbackup/borg/blob/master/SECURITY.md).
