"""Test-run wide settings."""

import os
import sys


def pytest_sessionfinish(session, exitstatus):
    """On the CI runner, Qt crashes (segfault) while Python shuts down after every test has passed, which turns a green run red.
    Leave straight away with the real result instead of running that teardown."""
    if os.environ.get("CI"):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(int(exitstatus))
