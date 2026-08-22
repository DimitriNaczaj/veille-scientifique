import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_open(path, mode, encoding=None, newline=None):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    options = {
        "mode": mode,
        "dir": str(destination.parent),
        "prefix": "." + destination.name + ".",
        "suffix": ".tmp",
        "delete": False,
    }
    if "b" not in mode:
        options["encoding"] = encoding or "utf-8"
        options["newline"] = newline
    try:
        with tempfile.NamedTemporaryFile(**options) as stream:
            temporary_path = Path(stream.name)
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary_path), str(destination))
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
        raise
