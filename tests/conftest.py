"""Shared test configuration.

Set ARCHIE_REQUIRE_INTEGRATION=1 (as CI does) to turn a skipped integration test into a failure,
so a missing extractor or fixture build cannot pass silently.
"""
import os

import pytest

pytest_plugins = ("pytester",)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if (report.skipped and os.environ.get("ARCHIE_REQUIRE_INTEGRATION") == "1"
            and item.get_closest_marker("integration") is not None):
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        report.outcome = "failed"
        report.longrepr = f"Integration test skipped while ARCHIE_REQUIRE_INTEGRATION=1: {reason}"
