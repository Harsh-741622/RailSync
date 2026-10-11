from fastapi.testclient import TestClient
from backend.main import app


def test_health_and_seeded_dashboard():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["mode"] == "simulation"
        dashboard = client.get("/api/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["scheduled_today"] == 18
        assert dashboard.json()["station"] == "Central Junction"


def test_scenario_flows_into_effective_timetable_and_closure_state():
    with TestClient(app) as client:
        created = client.post("/api/scenarios", json={
            "title": "API test delay and closure",
            "description": "test-only fictional scenario",
            "disruptions": [
                {"kind": "train_delay", "train_id": "12951", "delay_min": 15, "reason": "test signal issue"},
                {"kind": "platform_closure", "platform_id": "P2", "start_min": 60, "end_min": 105, "reason": "test maintenance"}
            ]
        })
        assert created.status_code == 201, created.text
        effective = client.get("/api/timetable/effective").json()
        row = next(r for r in effective["entries"] if r["train_id"] == "12951")
        assert row["arrival_min"] == row["approved_arrival_min"] + 15
        assert any(c["platform_id"] == "P2" for c in effective["closures"])
        overview = client.get("/api/dashboard").json()
        assert overview["delayed"] >= 1
        current = client.get("/api/timetable/current").json()
        current_row = next(r for r in current["entries"] if r["train_id"] == "12951")
        assert current_row["arrival_min"] == row["approved_arrival_min"]  # approved timetable stays immutable

        # Individual scenario items can be removed and restored without touching
        # the approved schedule, and scenario clearing has an explicit undo path.
        scenario_id = created.json()["id"]
        delay_id = created.json()["disruptions"][0]["id"]
        removed = client.delete(f"/api/scenarios/{scenario_id}/disruptions/{delay_id}")
        assert removed.status_code == 200
        after_remove = client.get("/api/timetable/effective").json()
        row_after_remove = next(r for r in after_remove["entries"] if r["train_id"] == "12951")
        assert row_after_remove["arrival_min"] == row_after_remove["approved_arrival_min"]
        restored_item = client.post(f"/api/scenarios/{scenario_id}/disruptions/{delay_id}/restore", json={})
        assert restored_item.status_code == 200
        after_restore = client.get("/api/timetable/effective").json()
        row_after_restore = next(r for r in after_restore["entries"] if r["train_id"] == "12951")
        assert row_after_restore["arrival_min"] == row_after_restore["approved_arrival_min"] + 15
        assert client.delete(f"/api/scenarios/{scenario_id}").status_code == 200
        assert client.get(f"/api/scenarios/{scenario_id}").json()["active"] is False
        undone = client.post(f"/api/scenarios/{scenario_id}/restore", json={})
        assert undone.status_code == 200 and undone.json()["active"] is True


def test_platform_closure_interval_is_closed_at_start_and_open_at_end():
    with TestClient(app) as client:
        created = client.post("/api/scenarios", json={
            "title": "API closure boundary",
            "description": "test-only interval boundary",
            "disruptions": [{"kind": "platform_closure", "platform_id": "P2", "start_min": 60, "end_min": 70, "reason": "test maintenance"}],
        })
        assert created.status_code == 201, created.text
        client.patch("/api/simulation", json={"reset": True, "start_min": 60})
        at_start = next(platform for platform in client.get("/api/platforms").json() if platform["id"] == "P2")
        assert at_start["status"] == "CLOSED"
        client.patch("/api/simulation", json={"reset": True, "start_min": 70})
        at_end = next(platform for platform in client.get("/api/platforms").json() if platform["id"] == "P2")
        assert at_end["status"] != "CLOSED"


def test_solver_endpoint_never_returns_fabricated_success_when_ortools_missing():
    with TestClient(app) as client:
        response = client.post("/api/schedules/optimize", json={"aggregate": True, "minimum_gap": 5, "max_time_seconds": 1})
        # In an installed environment, CP-SAT returns a real proposal (201). This
        # locked workspace has no package-index access; missing solver is explicit.
        if response.status_code == 503:
            assert "OR-Tools is not installed" in response.json()["detail"]
        else:
            assert response.status_code == 201
            assert response.json()["solver_status"] in {"OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN"}


def test_assistant_soft_preference_requires_review_and_is_not_hard():
    with TestClient(app) as client:
        result = client.post("/api/assistant/interpret", json={"text": "keep train 12951 on platform 3 if possible"})
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["requires_confirmation"] is True
        assert body["kind"] == "instruction"
        assert body["interpreted"]["kind"] == "SOFT_PLATFORM"
        assert body["interpreted"]["platform_id"] == "P3"


def test_custom_train_delay_contract_persists_and_rejects_invalid_input():
    with TestClient(app) as client:
        payload = {
            "title": "Custom delay API test",
            "description": "test-only custom delay",
            "disruptions": [{
                "kind": "train_delay",
                "train_id": "12951",
                "delay_min": 12,
                "reason": "test signal hold",
            }],
            "instructions": [],
        }
        created = client.post("/api/scenarios", json=payload)
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["title"] == payload["title"]
        assert body["disruptions"] == [{
            "id": body["disruptions"][0]["id"],
            "kind": "train_delay",
            "train_id": "12951",
            "platform_id": None,
            "delay_min": 12,
            "start_min": None,
            "end_min": None,
            "reason": "test signal hold",
            "active": True,
        }]

        persisted = client.get(f"/api/scenarios/{body['id']}")
        assert persisted.status_code == 200
        assert persisted.json()["disruptions"][0]["delay_min"] == 12

        invalid_delay = client.post("/api/scenarios", json={
            **payload,
            "title": "Invalid negative delay",
            "disruptions": [{**payload["disruptions"][0], "delay_min": -1}],
        })
        assert invalid_delay.status_code == 422

        invalid_kind = client.post("/api/scenarios", json={
            **payload,
            "title": "Invalid disruption kind",
            "disruptions": [{**payload["disruptions"][0], "kind": "mouse_event"}],
        })
        assert invalid_kind.status_code == 422
