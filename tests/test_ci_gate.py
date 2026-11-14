from pathlib import Path

CONFTEST = Path(__file__).with_name("conftest.py").read_text()
TESTS = """
import pytest

@pytest.mark.integration
@pytest.mark.skipif(True, reason="extractor missing")
def test_integration():
    pass

@pytest.mark.skipif(True, reason="optional dependency")
def test_optional():
    pass
"""


def _run(pytester, monkeypatch, required):
    pytester.makeconftest(CONFTEST.replace('pytest_plugins = ("pytester",)\n', ""))
    pytester.makeini("[pytest]\nmarkers =\n    integration: integration test\n")
    pytester.makepyfile(TESTS)
    if required:
        monkeypatch.setenv("ARCHIE_REQUIRE_INTEGRATION", "1")
    else:
        monkeypatch.delenv("ARCHIE_REQUIRE_INTEGRATION", raising=False)
    return pytester.runpytest()


def test_integration_skips_are_allowed_locally(pytester, monkeypatch):
    _run(pytester, monkeypatch, False).assert_outcomes(skipped=2)


def test_integration_skips_fail_when_required(pytester, monkeypatch):
    result = _run(pytester, monkeypatch, True)
    result.assert_outcomes(errors=1, skipped=1)
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*Integration test skipped while ARCHIE_REQUIRE_INTEGRATION=1*extractor missing*"])
