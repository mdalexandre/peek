"""The only writer of the program: the spill file of a capped run."""

from __future__ import annotations

import os
import tempfile


def write_spill(raw: bytes) -> str:
    """Write raw to gettempdir()/peek-*/out.txt (dir 0700, file 0600) and return the path."""
    directory = tempfile.mkdtemp(prefix="peek-")
    path = os.path.join(directory, "out.txt")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
    return path
