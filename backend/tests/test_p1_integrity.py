"""P1 contracts exercised against the test-only SQLite database from conftest."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.database import SessionLocal
from backend.main import _effective_entries, _scenario_inputs, _validate_inputs, app
from backend.models import AuditEvent, Disruption, Proposal, StationInstruction, TimetableEntry, TimetableVersion, ValidationRun
from backend.database import Base
from backend.seed import seed_database


def _scenario(client: TestClient, title: str, disruptions: list[dict], instructions: list[dict] | None = None) -> dict:
    response = client.post("/api/scenarios", json={"title": title, "disruptions": disruptions, "instructions": instructions or []})
    assert response.status_code == 201, response.text
    return response.json()


def _validated_delay_proposal(scenario_id: int) -> Proposal:
    """Persist a validator-approved schedule without pretending CP-SAT ran.

    The locked test environment intentionally lacks OR-Tools. This helper tests
    approval's transaction and snapshot rules with a schedule independently
    validated by the production validator; CP-SAT has its own explicitly skipped
    tests when its optional package is unavailable.
    """
    db = SessionLocal()
    try:
        inputs = _scenario_inputs(db, scenario_id, False)
        rows = _effective_entries(inputs)
        report = _validate_inputs(inputs, rows)
        assert report["valid"], report
        snapshot = {
            "scenario_mode": inputs["scenario_mode"],
            "scenario_ids": [s.id for s in inputs["active_scenarios"]],
            "disruption_ids": [d.id for d in inputs["active_disruptions"]],
            "instruction_ids": [i.id for i in inputs["active_instructions"]],
            "trains": inputs["trains"], "platforms": inputs["platforms"],
            "closures": inputs["closures"], "hard_instructions": inputs["hard_instructions"],
            "minimum_gap": inputs["station"].minimum_gap,
            "horizon_start": inputs["station"].horizon_start,
            "horizon_end": inputs["station"].horizon_end,
        }
        base = inputs["current_version"]
        proposal = Proposal(base_version_id=base.id, scenario_id=scenario_id, state="AWAITING_APPROVAL", solver_status="TEST_VALIDATED",
                            is_valid=True, inputs_json=json.dumps(snapshot), validation_json=json.dumps(report), created_by="test")
        db.add(proposal); db.flush()
        version = TimetableVersion(version_number=max(v.version_number for v in db.query(TimetableVersion).all()) + 1,
                                   status="PROPOSED", base_version_id=base.id, source_proposal_id=proposal.id, created_by="test")
        db.add(version); db.flush(); proposal.version_id = version.id
        for row in rows:
            db.add(TimetableEntry(version_id=version.id, train_id=row["train_id"], arrival_min=row["arrival_min"],
                                  departure_min=row["departure_min"], platform_id=row["platform_id"],
                                  additional_delay_min=0, platform_changed=False, preference_satisfied=True))
        db.add(ValidationRun(proposal_id=proposal.id, status=report["status"], hard_violation_count=0, report_json=json.dumps(report)))
        db.commit(); db.refresh(proposal)
        return proposal
    finally:
        db.close()


def test_selected_and_aggregate_scenario_inputs_are_explicit_and_isolated():
    with TestClient(app) as client:
        delay = _scenario(client, "P1 selected delay", [{"kind": "train_delay", "train_id": "12008", "delay_min": 5}])
        closure = _scenario(client, "P1 selected closure", [{"kind": "platform_closure", "platform_id": "P2", "start_min": 60, "end_min": 105}])
        db = SessionLocal()
        try:
            selected_delay = _scenario_inputs(db, delay["id"], False)
            selected_closure = _scenario_inputs(db, closure["id"], False)
            aggregate = _scenario_inputs(db, None, True)
            assert [s.id for s in selected_delay["active_scenarios"]] == [delay["id"]]
            assert selected_delay["closures"] == []
            assert next(row for row in selected_delay["entries"] if row["train_id"] == "12008")["scenario_delay_min"] == 5
            assert [s.id for s in selected_closure["active_scenarios"]] == [closure["id"]]
            assert selected_closure["closures"][0]["scenario_id"] == closure["id"]
            assert any(s.id == delay["id"] for s in aggregate["active_scenarios"])
            assert any(s.id == closure["id"] for s in aggregate["active_scenarios"])
        finally:
            db.close()
        assert client.post("/api/schedules/optimize", json={}).status_code == 422
        assert client.post("/api/schedules/optimize", json={"scenario_id": 999999}).status_code == 404
        assert client.delete(f"/api/scenarios/{closure['id']}").status_code == 200
        assert client.post("/api/schedules/optimize", json={"scenario_id": closure["id"]}).status_code == 409


def test_approval_consumes_snapshot_once_and_rejection_preserves_inputs():
    with TestClient(app) as client:
        created = _scenario(client, "P1 approval delay", [{"kind": "train_delay", "train_id": "12008", "delay_min": 5}])
        delay_id = created["disruptions"][0]["id"]
        # Approval promotes only the proposal version.  It must not reset or
        # otherwise alter the independent simulation playback state.
        simulation_before = client.patch("/api/simulation", json={"reset": True, "start_min": 77, "paused": True, "speed": 2}).json()
        before = client.get("/api/timetable/current").json()
        effective_before = client.get("/api/timetable/effective").json()
        assert next(row for row in effective_before["entries"] if row["train_id"] == "12008")["arrival_min"] == 10
        proposal = _validated_delay_proposal(created["id"])
        snapshot_before = proposal.inputs_json
        approved = client.post(f"/api/schedules/proposals/{proposal.id}/approve", json={})
        assert approved.status_code == 200, approved.text
        after = client.get("/api/timetable/current").json()
        assert after["version_id"] != before["version_id"]
        approved_delay = next(row for row in after["entries"] if row["train_id"] == "12008")
        assert approved_delay["arrival_min"] == 10
        assert approved_delay["original_arrival_min"] == 5
        effective_after = client.get("/api/timetable/effective").json()
        assert next(row for row in effective_after["entries"] if row["train_id"] == "12008")["arrival_min"] == 10
        simulation_after = client.get("/api/simulation").json()
        assert simulation_after["clock_min"] == simulation_before["clock_min"] == 77
        assert simulation_after["paused"] is True and simulation_after["speed"] == 2
        assert client.get(f"/api/scenarios/{created['id']}").json()["active"] is False
        assert client.post(f"/api/schedules/proposals/{proposal.id}/approve", json={}).status_code == 409
        db = SessionLocal()
        try:
            assert db.get(Proposal, proposal.id).inputs_json == snapshot_before
            assert db.get(Disruption, delay_id).active is False
        finally:
            db.close()

        rejected_scenario = _scenario(client, "P1 rejected delay", [{"kind": "train_delay", "train_id": "81506", "delay_min": 5}])
        rejected = _validated_delay_proposal(rejected_scenario["id"])
        current_id = client.get("/api/timetable/current").json()["version_id"]
        assert client.post(f"/api/schedules/proposals/{rejected.id}/reject", json={"reason": "Operator declined"}).status_code == 200
        assert client.get("/api/timetable/current").json()["version_id"] == current_id
        assert client.get(f"/api/scenarios/{rejected_scenario['id']}").json()["disruptions"][0]["active"] is True


def test_proposal_preview_payload_exposes_only_its_closure_snapshot():
    with TestClient(app) as client:
        scenario = _scenario(client, "P1 preview context", [{"kind": "train_delay", "train_id": "12008", "delay_min": 5}])
        proposal = _validated_delay_proposal(scenario["id"])
        expected_closure = {"platform_id": "P4", "start_min": 75, "end_min": 95, "reason": "Preview-only test closure"}
        db = SessionLocal()
        try:
            stored = db.get(Proposal, proposal.id)
            snapshot = json.loads(stored.inputs_json)
            snapshot["closures"] = [expected_closure]
            stored.inputs_json = json.dumps(snapshot)
            db.commit()
        finally:
            db.close()
        payload = client.get(f"/api/schedules/proposals/{proposal.id}").json()
        assert payload["entries"]
        assert payload["simulation_context"] == {"closures": [expected_closure]}
        assert "inputs_json" not in payload


def test_proposal_list_and_detail_return_the_same_persisted_schedule():
    with TestClient(app) as client:
        scenario = _scenario(client, "P1 proposal selector", [{"kind": "train_delay", "train_id": "12008", "delay_min": 5}])
        proposal = _validated_delay_proposal(scenario["id"])
        listing = client.get("/api/schedules/proposals")
        assert listing.status_code == 200
        summary = next(item for item in listing.json() if item["id"] == proposal.id)
        assert summary["version_id"] == proposal.version_id
        assert summary["state"] == "AWAITING_APPROVAL"
        detail = client.get(f"/api/schedules/proposals/{proposal.id}")
        assert detail.status_code == 200
        assert detail.json()["id"] == summary["id"]
        assert detail.json()["version_id"] == summary["version_id"]
        assert any(entry["train_id"] == "12008" and entry["arrival_min"] == 10 for entry in detail.json()["entries"])


def test_stale_or_changed_snapshot_cannot_be_approved():
    with TestClient(app) as client:
        created = _scenario(client, "P1 stale snapshot", [{"kind": "train_delay", "train_id": "12008", "delay_min": 5}])
        proposal = _validated_delay_proposal(created["id"])
        disruption_id = created["disruptions"][0]["id"]
        assert client.delete(f"/api/scenarios/{created['id']}/disruptions/{disruption_id}").status_code == 200
        current_id = client.get("/api/timetable/current").json()["version_id"]
        response = client.post(f"/api/schedules/proposals/{proposal.id}/approve", json={})
        assert response.status_code == 409
        assert client.get("/api/timetable/current").json()["version_id"] == current_id
        assert client.get(f"/api/schedules/proposals/{proposal.id}").json()["state"] == "AWAITING_APPROVAL"


def test_approval_consumes_only_snapshot_items_and_preserves_unapplied_records():
    with TestClient(app) as client:
        created = _scenario(client, "P1 partial scenario", [{"kind": "train_delay", "train_id": "12008", "delay_min": 5}], [{
            "kind": "SOFT_PLATFORM", "train_id": "12008", "platform_id": "P5", "instruction_text": "Preserve for a later run"
        }])
        instruction_id = created["instructions"][0]["id"]
        # Operators may withdraw an item before optimization. It remains historical
        # scenario data and is intentionally absent from the proposal snapshot.
        assert client.delete(f"/api/scenarios/{created['id']}/instructions/{instruction_id}").status_code == 200
        proposal = _validated_delay_proposal(created["id"])
        assert client.post(f"/api/schedules/proposals/{proposal.id}/approve", json={}).status_code == 200
        db = SessionLocal()
        try:
            instruction = db.get(StationInstruction, instruction_id)
            assert instruction is not None and instruction.active is False
            assert instruction.id not in json.loads(db.get(Proposal, proposal.id).inputs_json)["instruction_ids"]
        finally:
            db.close()


def test_file_backed_sqlite_conditional_claim_allows_exactly_one_approver(tmp_path):
    """Exercise the same SQL claim guard on separate file-backed SQLite sessions."""
    url = f"sqlite:///{(tmp_path / 'approval-race.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 10}, future=True)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    Base.metadata.create_all(bind=engine)
    db = sessions()
    try:
        seed_database(db)
        current = db.query(TimetableVersion).filter(TimetableVersion.status == "CURRENT").one()
        proposal = Proposal(base_version_id=current.id, state="AWAITING_APPROVAL", is_valid=True, solver_status="TEST")
        db.add(proposal); db.commit(); proposal_id = proposal.id
    finally:
        db.close()
    barrier = Barrier(2)
    def claim_once() -> int:
        session = sessions()
        try:
            barrier.wait()
            result = session.execute(update(Proposal).where(Proposal.id == proposal_id, Proposal.state == "AWAITING_APPROVAL", Proposal.is_valid.is_(True)).values(state="APPROVING"))
            session.commit()
            return result.rowcount
        finally:
            session.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: claim_once(), range(2)))
    assert sorted(outcomes) == [0, 1]
    engine.dispose()


def test_production_authentication_uses_signed_identity_not_client_actor(monkeypatch):
    secret = "test-only-strong-secret-value-0123456789"
    monkeypatch.setenv("RAILSYNC_AUTH_MODE", "production")
    monkeypatch.setenv("RAILSYNC_AUTH_SECRET", secret)
    with TestClient(app) as client:
        assert client.post("/api/scenarios", json={"title": "No auth", "disruptions": [{"kind": "train_delay", "train_id": "12008", "delay_min": 5}]}).status_code == 401
        assert client.post("/api/scenarios", headers={"Authorization": "Bearer garbage"}, json={"title": "Bad auth", "disruptions": [{"kind": "train_delay", "train_id": "12008", "delay_min": 5}]}).status_code == 401
        expired = auth.create_access_token("expired", "operator", -1, secret=secret)
        assert client.post("/api/scenarios", headers={"Authorization": f"Bearer {expired}"}, json={"title": "Expired", "disruptions": [{"kind": "train_delay", "train_id": "12008", "delay_min": 5}]}).status_code == 401
        operator = auth.create_access_token("operator-7", "operator", secret=secret)
        response = client.post("/api/scenarios", headers={"Authorization": f"Bearer {operator}"}, json={"title": "Authenticated", "description": "forged actor: chief", "disruptions": [{"kind": "train_delay", "train_id": "12008", "delay_min": 5}]})
        assert response.status_code == 201, response.text
        assert client.post("/api/schedules/proposals/999999/approve", headers={"Authorization": f"Bearer {operator}"}, json={}).status_code == 403
        db = SessionLocal()
        try:
            assert db.query(AuditEvent).order_by(AuditEvent.id.desc()).first().actor == "operator-7"
        finally:
            db.close()


def test_production_configuration_rejects_insecure_defaults(monkeypatch):
    monkeypatch.setenv("RAILSYNC_AUTH_MODE", "production")
    monkeypatch.delenv("RAILSYNC_AUTH_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="RAILSYNC_AUTH_SECRET"):
        auth.validate_auth_configuration()
    monkeypatch.setenv("RAILSYNC_AUTH_MODE", "demo")
    assert auth.authenticate(None).subject == "Demo Station Master"
