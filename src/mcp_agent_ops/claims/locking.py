# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Provides repository-domain file locking across POSIX and Windows processes.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import portalocker


@contextmanager
def exclusive_text_file(path: Path) -> Iterator[IO[str]]:
    """Open and exclusively lock one persistent repository text file.

    Args:
        path: File whose stable identity is the cross-process lock authority.

    Yields:
        One readable and writable text stream positioned by the caller.

    Raises:
        OSError: The file cannot be created, opened, locked, or closed.
        portalocker.LockException: The host cannot acquire the exclusive OS lock.

    The lock blocks until available and is released before the stream closes. Callers
    must update the yielded stream in place so competing processes keep locking the
    same file identity.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(file_descriptor, "r+", encoding="utf-8") as descriptor:
        while True:
            try:
                portalocker.lock(
                    descriptor,
                    portalocker.LOCK_EX | portalocker.LOCK_NB,
                )
                break
            except portalocker.AlreadyLocked:
                time.sleep(0.05)
        try:
            yield descriptor
        finally:
            portalocker.unlock(descriptor)
