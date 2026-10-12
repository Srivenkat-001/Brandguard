"""Brand Guard. Loads API keys from a `.env` file in the project root (if present)."""
import os
from pathlib import Path


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:      # real environment variables win
            os.environ[k] = v


_load_env(Path(__file__).resolve().parent.parent / ".env")
