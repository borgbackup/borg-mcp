"""Executes allowlisted borg commands as subprocesses.

The environment for borg is built from scratch (see config.repo_env), stdout
must be valid JSON, and every invocation is audit-logged. Concurrent calls
against the same repository are serialized.
"""

import asyncio
import json
import logging
import subprocess
import time
from typing import Any

from borg_mcp.config import RepoConfig, ServerConfig, base_env, repo_env

logger = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 128 * 1024 * 1024
STDERR_TAIL_CHARS = 2000


class BorgError(Exception):
    """borg could not be executed or returned an error."""


class BorgRunner:
    def __init__(self, config: ServerConfig):
        self.config = config
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def _semaphore(self, key: str) -> asyncio.Semaphore:
        return self._semaphores.setdefault(key, asyncio.Semaphore(1))

    async def _execute(self, argv: list[str], env: dict[str, str]) -> tuple[bytes, bytes, int]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
            )
        except OSError as e:
            raise BorgError(f"cannot execute {argv[0]!r}: {e}") from e
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.config.timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise BorgError(f"borg did not finish within {self.config.timeout}s and was killed")
        return stdout, stderr, proc.returncode or 0

    async def run_json(self, repo: RepoConfig, cmd: list[str]) -> Any:
        """Run one allowlisted borg command against a configured repository."""
        argv = [self.config.borg_binary, *cmd, f"--repo={repo.location}"]
        async with self._semaphore(repo.name):
            start = time.monotonic()
            stdout, stderr, rc = await self._execute(argv, repo_env(repo))
            duration = time.monotonic() - start
        logger.info("audit: repo=%s cmd=%s rc=%d duration=%.2fs", repo.name, " ".join(cmd), rc, duration)
        if rc != 0:
            tail = stderr.decode("utf-8", errors="replace").strip()[-STDERR_TAIL_CHARS:]
            raise BorgError(f"borg {cmd[0]} failed for repository {repo.name!r} (rc={rc}): {tail}")
        if len(stdout) > MAX_OUTPUT_BYTES:
            raise BorgError(f"borg {cmd[0]} produced too much output ({len(stdout)} bytes)")
        try:
            return json.loads(stdout)
        except ValueError as e:
            raise BorgError(f"borg {cmd[0]} produced unparseable output: {e}") from e

    async def version(self) -> str:
        """Return the borg version string, e.g. "2.0.0b23"."""
        stdout, stderr, rc = await self._execute([self.config.borg_binary, "--version"], base_env())
        if rc != 0:
            tail = stderr.decode("utf-8", errors="replace").strip()[-STDERR_TAIL_CHARS:]
            raise BorgError(f"borg --version failed (rc={rc}): {tail}")
        words = stdout.decode("utf-8", errors="replace").split()
        if len(words) != 2 or words[0] != "borg":
            raise BorgError(f"unexpected borg --version output: {stdout.decode('utf-8', errors='replace')!r}")
        return words[1]

    async def check_borg2(self) -> str:
        version = await self.version()
        if not version.startswith("2."):
            raise BorgError(f"borg-mcp needs borg2, but {self.config.borg_binary!r} is borg {version}")
        return version
