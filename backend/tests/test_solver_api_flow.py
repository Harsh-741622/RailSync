"""End-to-end API checks for the actual CP-SAT scheduler, using test SQLite only."""
from fastapi.testclient import TestClient

from backend.main import app


def _scenario(client: TestClient, title: str, disruption: dict) -> dict:
    response = client.post("/api/scenarios", json={"title": title, "disruptions": [disruption]})
    assert response.status_code == 201, response.text
    return response.json()


def _optimize(client: TestClient, payload: dict) -> dict:
    response = client.post("/api/schedules/optimize", json={**payload, "max_time_seconds": 10})
    assert response.status_code == 201, response.text
    proposal = response.json()
    assert proposal["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert proposal["is_valid"] is True
    assert proposal["validation"]["valid"] is True
    assert proposal["validation"]["hard_violation_count"] == 0
    return proposal


def test_cp_sat_api_normal_timetable_is_independently_valid():
    with TestClient(app) as client:
        proposal = _optimize(client, {"aggregate": True})
        assert len(proposal["entries"]) == 18


def test_cp_sat_api_delay_can_be_approved_without_double_projection():
    with TestClient(app) as client:
        scenario = _scenario(client, "Solver API delay", {
            "kind": "train_delay", "train_id": "12008", "delay_min": 5, "reason": "test hold",
        })
        before = client.get("/api/timetable/current").json()
        proposal = _optimize(client, {"scenario_id": scenario["id"]})
        delayed = next(row for row in proposal["entries"] if row["train_id"] == "12008")
        assert delayed["arrival_min"] >= 10  # approved arrival 5 + submitted five-minute delay
        approved = client.post(f"/api/schedules/proposals/{proposal['id']}/approve", json={})
        assert approved.status_code == 200, approved.text
        current = client.get("/api/timetable/current").json()
        assert current["version_id"] != before["version_id"]
        current_delay = next(row for row in current["entries"] if row["train_id"] == "12008")
        effective = client.get("/api/timetable/effective").json()
        effective_delay = next(row for row in effective["entries"] if row["train_id"] == "12008")
        assert effective_delay["arrival_min"] == current_delay["arrival_min"]
        assert client.post(f"/api/schedules/proposals/{proposal['id']}/approve", json={}).status_code == 409


def test_cp_sat_api_platform_closure_reassigns_or_reports_valid_result():
    with TestClient(app) as client:
        scenario = _scenario(client, "Solver API closure", {
            "kind": "platform_closure", "platform_id": "P2", "start_min": 0, "end_min": 180, "reason": "test maintenance",
        })
        proposal = _optimize(client, {"scenario_id": scenario["id"]})
        assert all(entry["platform_id"] != "P2" for entry in proposal["entries"])


def test_cp_sat_api_mid_horizon_closure_persists_a_real_revised_timetable():
    with TestClient(app) as client:
        scenario = _scenario(client, "Solver API P4 closure", {
            "kind": "platform_closure", "platform_id": "P4", "start_min": 60, "end_min": 105, "reason": "test maintenance",
        })
        proposal = _optimize(client, {"scenario_id": scenario["id"]})
        displaced = next(entry for entry in proposal["entries"] if entry["train_id"] == "44712")
        assert displaced["platform_id"] != "P4"
        assert proposal["changes"]


def test_delay_beyond_horizon_is_infeasible_without_rows_or_approved_schedule_change():
    with TestClient(app) as client:
        before = client.get("/api/timetable/current").json()
        scenario = _scenario(client, "Solver API horizon overflow", {
            "kind": "train_delay", "train_id": "12951", "delay_min": 171, "reason": "test extended signal hold",
        })
        response = client.post("/api/schedules/optimize", json={"scenario_id": scenario["id"], "max_time_seconds": 10})
        assert response.status_code == 201, response.text
        proposal = response.json()
        assert proposal["solver_status"] == "INFEASIBLE"
        assert proposal["state"] == "INFEASIBLE"
        assert proposal["version_id"] is None
        assert proposal["entries"] == []
        assert proposal["validation"] == {}
        assert proposal["diagnostics"]["affected_train_ids"] == ["12951"]
        conflict = proposal["diagnostics"]["constraint_conflicts"][0]
        assert conflict["departure_min"] == 191
        assert conflict["horizon_end"] == 180
        after = client.get("/api/timetable/current").json()
        assert after["version_id"] == before["version_id"]
        assert after["entries"] == before["entries"]
