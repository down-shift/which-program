"""Cooperative pytest nodeid recorder for command-level test scope."""
import json
import os
import time


def pytest_runtest_logreport(report):
    path = os.environ.get("PI_TEST_REPORT_FILE")
    if not path:
        return
    row = {
        "schema_version": 1,
        "run_id": os.environ.get("PI_TEST_RUN_ID"),
        "command_id": os.environ.get("PI_TEST_COMMAND_ID"),
        "pid": os.getpid(),
        "timestamp": time.time(),
        "nodeid": report.nodeid,
        "when": report.when,
        "outcome": report.outcome,
    }
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
