"""Ratings Lab API: contract keys, predeclared parameters only, and no writes to any stored rating."""
import hashlib
import pathlib

import pytest
from starlette.testclient import TestClient

from runrank import api
from test_api import keys_match

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples" / "synthetic"


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "p.sqlite"
    app = api.create_app(str(db), demo_mode=False, database="personal", allowed_hosts=("testserver",))
    with TestClient(app) as c:
        yield c, db


def test_lab_contract_and_explanation(client):
    c, _ = client
    m = c.get("/api/lab/meta").json()
    keys_match(m, "LabMeta")
    assert [x["key"] for x in m["methods"]] == ["A", "B", "C", "D"]
    r = c.get("/api/lab/runners/beginner", params={"method": "B", "speed_weight": "0.25"}).json()
    keys_match(r, "LabRunner")
    keys_match(r["result"], "LabResult")
    keys_match(r["activities"][0], "LabActivity")
    eight = next(a["key"] for a in r["activities"] if a["distance_m"] == 8000)
    ex = c.get("/api/lab/runners/beginner/activities/%s" % eight, params={"method": "B"}).json()
    keys_match(ex, "LabExplanation")
    assert ex["deltas"]["endurance"] > 0 and ex["deltas"]["speed"] == 0
    cmp_ = c.get("/api/lab/compare").json()
    keys_match(cmp_, "LabCompare")
    keys_match(cmp_["rows"][0]["cells"][0], "LabCell")
    assert len(cmp_["rows"]) == 7 and len(cmp_["rows"][0]["cells"]) == 9


def test_only_predeclared_parameters(client):
    c, _ = client
    assert c.get("/api/lab/runners/beginner", params={"method": "B", "speed_weight": "0.9"}).status_code == 400
    assert c.get("/api/lab/runners/beginner", params={"method": "Z"}).status_code == 400
    assert c.get("/api/lab/runners/nobody").status_code == 404


def test_lab_controls_never_change_stored_ratings(client):
    c, db = client
    pid = c.post("/api/participants", json={"label": "Real (synthetic stand-in)", "data_kind": "synthetic"}).json()["id"]
    c.post("/api/participants/%d/imports" % pid, files={"file": ("a.csv", (EXAMPLES / "mmr" / "recreational.csv")
                                                                  .read_bytes())})
    before = (c.get("/api/mmr/participants/%d?as_of=2025-12-31" % pid).json()["estimate"],
              hashlib.sha256(db.read_bytes()).hexdigest())
    for m, extra in (("A", {}), ("B", {"speed_weight": "0.25", "k_best": "2"}), ("C", {"aggregation": "balanced"}),
                     ("D", {"alpha": "0.6", "init": "anchor"})):
        c.get("/api/lab/runners/ultra", params=dict(method=m, **extra))
    c.get("/api/lab/compare")
    after = (c.get("/api/mmr/participants/%d?as_of=2025-12-31" % pid).json()["estimate"],
             hashlib.sha256(db.read_bytes()).hexdigest())
    assert before == after                        # identical estimates and database bytes


def test_lab_exclusion_is_explicit_and_validated(client):
    c, db = client
    assert not db.exists()                         # nothing has opened the database yet
    r = c.get("/api/lab/runners/speed", params={"method": "B"}).json()
    setter = next(x for x in r["result"]["selected"] if x["component"] == "speed")["activity"]
    ex = c.get("/api/lab/runners/speed", params={"method": "B", "exclude": setter}).json()
    assert ex["excluded"] == [setter] and setter not in [a["key"] for a in ex["activities"]]
    assert ex["result"]["components"]["speed"] < r["result"]["components"]["speed"]
    assert c.get("/api/lab/runners/speed", params={"method": "B", "exclude": "nope"}).status_code == 400
    assert not db.exists()                         # Lab requests never create or open the database


def test_lab_confirmation_and_states_are_explicit(client):
    c, db = client
    r = c.get("/api/lab/runners/ultra", params={"method": "B"}).json()
    states = {a["state"] for a in r["activities"]}
    assert states <= {"counted", "flagged", "held", "dropped", "after as-of"} and r["confirmed"] == []
    assert c.get("/api/lab/runners/ultra", params={"method": "B", "confirm": "nope"}).status_code == 400
    key = next(a["key"] for a in r["activities"] if a["state"] in ("counted", "flagged"))
    rc = c.get("/api/lab/runners/ultra", params={"method": "B", "confirm": key}).json()
    assert rc["confirmed"] == [key]
    assert any("confirmed by the user (not independent validation)" in f
               for a in rc["activities"] if a["key"] == key for f in a["flags"])
    assert not db.exists()


def test_lab_explanation_range_provenance_and_keep_separate(client):
    c, db = client
    m = c.get("/api/lab/meta").json()
    assert m["supported_range_km"] == [3.0, 250.0] and m["curve_range_km"] == [5.0, 250.0]
    assert all("synthetic assumption" in x["provenance"] for x in m["anchors"])
    q = {"method": "B", "long_performance": "bridged"}
    r = c.get("/api/lab/runners/marathon", params=q).json()
    perf = next(x for x in r["explanation"]["components"] if x["component"] == "performance")
    assert perf["activity"] == "930265" and any("ambiguous overlap" in w for w in perf["warnings"])
    assert "experimental exchange rate" in r["explanation"]["weighting"]
    excl = c.get("/api/lab/runners/marathon", params=dict(q, exclude="930265")).json()
    assert excl["result"]["combined"] < r["result"]["combined"]
    assert c.get("/api/lab/runners/marathon", params=q).json()["result"] == r["result"]          # restore
    assert c.get("/api/lab/runners/marathon", params=dict(q, keep_separate="nope")).status_code == 400
    assert not db.exists()
