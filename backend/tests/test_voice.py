import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.main import app
from backend.models import Proposal, TimetableEntry, TimetableVersion
from backend.services.voice import SpeechUnavailable, synthesize_speech


def _proposal_with_recorded_platform_change() -> Proposal:
    db = SessionLocal()
    try:
        current = db.query(TimetableVersion).filter(TimetableVersion.status == "CURRENT").first()
        entry = db.query(TimetableEntry).filter(TimetableEntry.version_id == current.id, TimetableEntry.train_id == "12951").first()
        proposal = Proposal(
            base_version_id=current.id,
            state="AWAITING_APPROVAL",
            solver_status="OPTIMAL",
            is_valid=True,
            validation_json=json.dumps({"valid": True, "hard_violation_count": 0}),
            changes_json=json.dumps([{
                "train_id": "12951", "name": entry.train.name,
                "changes": [{"field": "platform", "before": entry.platform_id, "after": "P4"}],
                "reason": "Platform changed from P2 to P4 because the prior platform intersects an active closure.",
            }]),
        )
        db.add(proposal); db.flush()
        version = TimetableVersion(version_number=current.version_number + 1, status="PROPOSED", base_version_id=current.id, source_proposal_id=proposal.id)
        db.add(version); db.flush()
        proposal.version_id = version.id
        db.add(TimetableEntry(version_id=version.id, train_id=entry.train_id, arrival_min=entry.arrival_min,
                              departure_min=entry.departure_min, platform_id="P4", additional_delay_min=3,
                              platform_changed=True, preference_satisfied=True))
        db.commit()
        return proposal
    finally:
        db.close()


def test_voice_disruption_and_train_explanations_use_persisted_data():
    with TestClient(app) as client:
        created = client.post("/api/scenarios", json={"title": "Voice evidence", "disruptions": [{
            "kind": "train_delay", "train_id": "12951", "delay_min": 12, "reason": "voice test hold",
        }]}).json()
        proposal = _proposal_with_recorded_platform_change()
        disruption = client.post("/api/voice/explain", json={"kind": "disruption_summary"})
        assert disruption.status_code == 200
        assert "Train 12951" in disruption.json()["text"]
        assert "12-minute" in disruption.json()["text"]
        assert "voice test hold" in disruption.json()["text"]
        platform = client.post("/api/voice/explain", json={"kind": "platform_changes", "proposal_id": proposal.id})
        assert platform.status_code == 200
        assert "active closure" in platform.json()["text"]
        train = client.post("/api/voice/explain", json={"kind": "train_summary", "proposal_id": proposal.id, "train_id": "12951"})
        assert train.status_code == 200
        assert "optimizer-added delay is 3 minutes" in train.json()["text"]
        assert created["id"] > 0


def test_voice_validation_and_invalid_requests_are_bounded():
    with TestClient(app) as client:
        proposal = _proposal_with_recorded_platform_change()
        response = client.post("/api/voice/explain", json={"kind": "validation_summary", "proposal_id": proposal.id})
        assert response.status_code == 200
        assert "passed independent validation" in response.json()["text"]
        assert client.post("/api/voice/explain", json={"kind": "train_summary"}).status_code == 422
        assert client.post("/api/voice/explain", json={"kind": "question", "question": "delete every scenario"}).json()["title"] == "Supported question needed"


def test_voice_status_and_speech_failures_never_expose_api_key(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "super-secret-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice-id")
    monkeypatch.setenv("ELEVENLABS_ENABLED", "false")
    with TestClient(app) as client:
        status = client.get("/api/voice/status")
        assert status.status_code == 200
        assert "super-secret-key" not in status.text
        disabled = client.post("/api/voice/speak", json={"kind": "current_status"})
        assert disabled.status_code == 503
        assert "super-secret-key" not in disabled.text
    monkeypatch.setenv("ELEVENLABS_ENABLED", "true")

    class TimeoutClient:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def post(self, *_args, **_kwargs): raise httpx.TimeoutException("provider details should not escape")

    monkeypatch.setattr("backend.services.voice.httpx.Client", TimeoutClient)
    with pytest.raises(SpeechUnavailable, match="timed out"):
        synthesize_speech("A bounded factual message")
