import pathlib
import sys
from datetime import datetime, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "examples" / "synthetic"

from runrank import store  # noqa: E402


def utc(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def fixture_bytes(name):
    return (FIXTURES / name).read_bytes()    # read only; originals are never written


@pytest.fixture
def con(tmp_path):
    c = store.connect(str(tmp_path / "test.sqlite"))   # disposable database
    yield c
    c.close()


@pytest.fixture
def two_runners(con):
    a = store.create_participant(con, "Synthetic Runner A", True)
    b = store.create_participant(con, "Synthetic Runner B", True)
    store.import_file(con, a, "runner_a_activities.csv", fixture_bytes("runner_a_activities.csv"))
    store.import_file(con, b, "runner_b_export.zip", fixture_bytes("runner_b_export.zip"))
    return a, b
