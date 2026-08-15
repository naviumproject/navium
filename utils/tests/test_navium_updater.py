import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.navium_updater import parse_version, should_update


def test_parse_version_basic():
    assert parse_version('0.0.3') == (0, 0, 3)
    assert parse_version('v0.0.4') == (0, 0, 4)


def test_should_update_when_release_is_newer():
    assert should_update('0.0.3', '0.0.4') is True


def test_should_update_ignore_prerelease():
    assert should_update('0.0.3', '0.0.4-beta.1') is False
    assert should_update('0.0.3', '1.0.0-rc.1') is False


def test_should_update_when_same_version():
    assert should_update('0.0.3', '0.0.3') is False
