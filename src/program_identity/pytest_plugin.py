"""Cooperative pytest nodeid recorder for command-level test scope."""
import json
import os
import time
from pathlib import Path

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    # item.path is the collected test file, independent of rootdir, decorators,
    # test names, and nodeid prefixes. Never normalize by matching a suffix.
    source = Path(item.path).resolve()
    report.pi_source_path = str(source)
    report.pi_pytest_root = str(item.config.rootpath)
    report.pi_workspace_nodeid = None
    report.pi_mapping_status = "unknown"
    workspace = os.environ.get("PI_TEST_WORKSPACE")
    if workspace and "::" in item.nodeid and source.is_file():
        try:
            relative = source.relative_to(Path(workspace).resolve())
        except ValueError:
            report.pi_mapping_status = "outside_workspace"
        else:
            report.pi_workspace_nodeid = relative.as_posix() + "::" + item.nodeid.split("::", 1)[1]
            report.pi_mapping_status = "mapped"


def pytest_runtest_logreport(report):
    path = os.environ.get("PI_TEST_REPORT_FILE")
    if not path:
        return
    row = {
        "schema_version": 2,
        "run_id": os.environ.get("PI_TEST_RUN_ID"),
        "command_id": os.environ.get("PI_TEST_COMMAND_ID"),
        "pid": os.getpid(),
        "timestamp": time.time(),
        "nodeid": report.nodeid,
        "workspace_nodeid": getattr(report, "pi_workspace_nodeid", None),
        "source_path": getattr(report, "pi_source_path", None),
        "pytest_root": getattr(report, "pi_pytest_root", None),
        "mapping_status": getattr(report, "pi_mapping_status", "unknown"),
        "when": report.when,
        "outcome": report.outcome,
    }
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
