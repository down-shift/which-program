"""Cooperative source provenance for explicitly monitored filesystem modules."""
from __future__ import annotations

import atexit
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
import sys
import time
from pathlib import Path

_MARKER = "_program_identity_finder"


def _append(row: dict) -> None:
    path = os.environ.get("PI_PROVENANCE_FILE")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception:
        # Runner detects a missing heartbeat and treats the command as unknown.
        pass


def _common(event: str) -> dict:
    return {
        "schema_version": 2,
        "event": event,
        "run_id": os.environ.get("PI_RUN_ID"),
        "command_id": os.environ.get("PI_COMMAND_ID"),
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "interpreter": sys.executable,
        "cwd": os.getcwd(),
        "timestamp": time.time(),
    }


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_read(path: Path) -> bytes:
    before = path.stat()
    source = path.read_bytes()
    after = path.stat()
    signature_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    signature_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if signature_before != signature_after or len(source) != after.st_size:
        raise RuntimeError("source changed while provenance bytes were captured")
    return source


class _SourceLoader:
    """Compile the captured source bytes directly, bypassing stale bytecode."""

    def __init__(self, fullname: str, origin: Path, package: bool):
        self.fullname, self.origin, self.package = fullname, origin, package

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        common = _common("module")
        row = {
            **common,
            "module": self.fullname,
            "origin": str(self.origin),
            "source_path": str(self.origin),
            "loader": "SourceFileLoader (captured source compiled directly)",
            "instrumentation": "unknown",
            "capture_seconds": 0.0,
        }
        started = time.perf_counter()
        try:
            if self.origin.suffix != ".py" or not self.origin.is_file():
                raise ValueError("only existing filesystem-backed .py source is supported")
            source = _stable_read(self.origin)
            row["loaded_sha256"] = _sha(source)
            mapping = json.loads(os.environ.get("PI_TARGET_MODULE_PATHS", "{}"))
            target = Path(mapping[self.fullname]).resolve()
            row["target_path"] = str(target)
            row["target_sha256"] = (row["loaded_sha256"] if target == self.origin else
                                     _sha(_stable_read(target))) if target.is_file() else None
            row["path_match"] = self.origin.resolve() == target
            row["content_match"] = row["target_sha256"] == row["loaded_sha256"] if row["target_sha256"] else None
            row["identity_status"] = (
                "unknown" if row["content_match"] is None else
                "exact_source_match" if row["path_match"] and row["content_match"] else
                "equivalent_copy" if row["content_match"] else "confirmed_content_mismatch"
            )
            # This custom loader compiles the captured bytes, so an existing .pyc is ignored.
            module.__file__ = str(self.origin)
            module.__cached__ = None
            code = compile(source, str(self.origin), "exec")
            row["instrumentation"] = "ok"
            row["bytecode_cache_ignored"] = True
            exec(code, module.__dict__)
        except BaseException as exc:
            row["load_error"] = f"{type(exc).__name__}: {exc}"
            if row.get("instrumentation") == "unknown":
                row["identity_status"] = "unknown"
            raise
        finally:
            row["capture_seconds"] = time.perf_counter() - started
            _append(row)


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        relevant = set(filter(None, os.environ.get("PI_RELEVANT_MODULES", "").split(",")))
        if fullname not in relevant:
            return None
        # Run after existing custom finders and directly before PathFinder. A custom
        # loader is therefore not redirected; absence of a module record stays unknown.
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or not spec.origin or not spec.loader:
            return None
        if not isinstance(spec.loader, importlib.machinery.SourceFileLoader) or not spec.origin.endswith(".py"):
            return None
        spec.loader = _SourceLoader(fullname, Path(spec.origin).resolve(), spec.submodule_search_locations is not None)
        return spec


def install() -> None:
    if not os.environ.get("PI_PROVENANCE_FILE") or getattr(sys, _MARKER, False):
        return
    finder = _Finder()
    path_finder_index = next((i for i, x in enumerate(sys.meta_path) if x is importlib.machinery.PathFinder), len(sys.meta_path))
    sys.meta_path.insert(path_finder_index, finder)
    setattr(sys, _MARKER, True)
    _append(_common("process_start"))
    atexit.register(lambda: _append(_common("process_end")))
