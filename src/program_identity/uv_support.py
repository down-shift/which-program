"""Small helper for stable uv subprocess execution in restricted environments."""
import os, tempfile
from pathlib import Path

def uv_environment(base=None):
    env=(base or os.environ).copy()
    env.setdefault("UV_CACHE_DIR",str(Path(tempfile.gettempdir())/"program-identity-uv-cache"))
    env.setdefault("UV_NO_CONFIG", "1")
    return env
