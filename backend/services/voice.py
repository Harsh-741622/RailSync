"""Factual voice-explanation and optional ElevenLabs speech helpers."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from ..models import Disruption, Proposal, Scenario, Station, TimetableEntry, TimetableVersion, Train
from .timeutils import minute_to_clock


class SpeechUnavailable(Exception):
    """A safe, user-facing speech service failure."""


@dataclass(frozen=True)
class VoiceConfiguration:
    enabled: bool
    configured: bool
    voice_id: str
    model_id: str


def _as_json(value: str | None, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def speech_configuration() -> VoiceConfiguration:
    enabled = os.getenv("ELEVENLABS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    return VoiceConfiguration(
        enabled=enabled,
        configured=bool(api_key and voice_id),
        voice_id=voice_id,
        model_id=os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip() or "eleven_multilingual_v2",
    )


def speech_status() -> dict:
    config = speech_configuration()
    ready = config.enabled and config.configured
    return {
        "text_available": True,
        "speech_enabled": ready,
        "configured": config.configured,
        "status": "ready" if ready else "disabled" if not config.enabled else "missing_configuration",
        "provider": "ElevenLabs" if ready else None,
        "model_id": config.model_id if ready else None,
    }


def synthesize_speech(text: str) -> bytes:
    """Generate bounded MP3 bytes without exposing provider details or credentials."""
    config = speech_configuration()
    if not config.enabled:
        raise SpeechUnavailable("Speech is disabled. Text explanations remain available.")
    if not config.configured:
        raise SpeechUnavailable("Speech is not configured. Add a voice ID and API key on the backend to enable it.")
    safe_text = text.strip()
    if not safe_text:
        raise SpeechUnavailable("There is no explanation available to read aloud.")
    if len(safe_text) > 4000:
        raise SpeechUnavailable("The explanation is too long to read aloud in one request.")
    timeout = min(max(float(os.getenv("ELEVENLABS_TIMEOUT_SECONDS", "15")), 1), 30)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{config.voice_id}"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                url,
                headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Accept": "audio/mpeg"},
                json={"text": safe_text, "model_id": config.model_id, "output_format": "mp3_44100_128"},
            )
    except httpx.TimeoutException as exc:
        raise SpeechUnavailable("Speech generation timed out. Please try again.") from exc
    except httpx.HTTPError as exc:
        raise SpeechUnavailable("Speech generation is temporarily unavailable. Please try again.") from exc
    if response.status_code in {401, 403}:
        raise SpeechUnavailable("The speech service rejected the configured credentials or voice.")
    if response.status_code in {402, 429}:
        raise SpeechUnavailable("The speech service quota or rate limit was reached.")
    if response.status_code >= 400 or not response.content:
        raise SpeechUnavailable("Speech generation could not be completed. Text explanations remain available.")
    return response.content


def _latest_proposal(db: Session, proposal_id: int | None) -> Proposal | None:
    query = db.query(Proposal)
    if proposal_id is not None:
        return query.filter(Proposal.id == proposal_id).first()
    return query.order_by(desc(Proposal.created_at)).first()


def _proposal_entries(db: Session, proposal: Proposal | None) -> dict[str, TimetableEntry]:
    if not proposal or not proposal.version_id:
        return {}
    rows = db.query(TimetableEntry).options(joinedload(TimetableEntry.train)).filter(TimetableEntry.version_id == proposal.version_id).all()
    return {row.train_id: row for row in rows}


def _current_entries(db: Session) -> dict[str, TimetableEntry]:
    version = db.query(TimetableVersion).filter(TimetableVersion.status == "CURRENT").order_by(desc(TimetableVersion.version_number)).first()
    if not version:
        return {}
    rows = db.query(TimetableEntry).options(joinedload(TimetableEntry.train)).filter(TimetableEntry.version_id == version.id).all()
    return {row.train_id: row for row in rows}


def _active_disruptions(db: Session) -> list[Disruption]:
    return db.query(Disruption).join(Scenario).filter(Scenario.active.is_(True), Disruption.active.is_(True)).all()


def _disruption_text(disruption: Disruption) -> str:
    if disruption.kind == "train_delay" and disruption.train_id:
        return f"Train {disruption.train_id} has an active {disruption.delay_min}-minute delay input" + (f" due to {disruption.reason}" if disruption.reason else "") + "."
    if disruption.kind == "platform_closure" and disruption.platform_id is not None:
        interval = ""
        if disruption.start_min is not None and disruption.end_min is not None:
            interval = f" from {minute_to_clock(disruption.start_min)} to {minute_to_clock(disruption.end_min)}"
        return f"{disruption.platform_id} has an active closure{interval}" + (f" due to {disruption.reason}" if disruption.reason else "") + "."
    return "An active disruption has incomplete details."


def _proposal_state_text(proposal: Proposal) -> str:
    if proposal.state == "APPROVED":
        return f"Proposal {proposal.id} is approved and its timetable is current."
    if proposal.state == "AWAITING_APPROVAL":
        return f"Proposal {proposal.id} is independently validated and awaiting station-master approval."
    if proposal.state == "REJECTED":
        return f"Proposal {proposal.id} was rejected; the approved timetable remains unchanged."
    if proposal.state == "INFEASIBLE":
        return f"Proposal {proposal.id} is infeasible, so the solver did not produce a timetable."
    if proposal.state == "INVALID":
        return f"Proposal {proposal.id} did not pass independent validation and cannot be approved."
    return f"Proposal {proposal.id} is in state {proposal.state}."


def _question_kind(question: str) -> str | None:
    text = question.lower()
    if any(word in text for word in ("validate", "validation", "pass validation")):
        return "validation_summary"
    if "additional delay" in text or "how much" in text and "delay" in text:
        return "delay_analysis"
    if "platform" in text or "moved" in text:
        return "platform_changes"
    if "approved" in text or "approval" in text:
        return "approval_summary"
    if "proposal" in text or "changed" in text:
        return "proposal_summary"
    if "disruption" in text or "what happened" in text or "affected" in text:
        return "disruption_summary"
    if "situation" in text or "status" in text or "summary" in text:
        return "current_status"
    return None


def explain(db: Session, kind: str, proposal_id: int | None = None, train_id: str | None = None, question: str | None = None) -> dict:
    """Return a short explanation using only persisted RailSync records."""
    if kind == "question":
        kind = _question_kind(question or "") or "unsupported"
    proposal = _latest_proposal(db, proposal_id)
    if proposal_id is not None and proposal is None:
        raise LookupError("The requested proposal was not found.")
    station = db.query(Station).first()
    disruptions = _active_disruptions(db)
    current_entries = _current_entries(db)
    proposed_entries = _proposal_entries(db, proposal)
    changes = _as_json(proposal.changes_json if proposal else None, [])
    validation = _as_json(proposal.validation_json if proposal else None, {})
    diagnostics = _as_json(proposal.infeasibility_json if proposal else None, {})
    source = {"station": station.name if station else "RailSync station", "proposal_id": proposal.id if proposal else None}
    related_ids: list[str] = [train_id] if train_id else []

    if kind == "unsupported":
        return _response("Supported question needed", "I can summarize the current situation, disruptions, proposal changes, platform changes, delays, validation, approval state, or a specific train. Please choose one of those actions.", related_ids, source)
    if kind == "current_status":
        segments = [f"{station.name if station else 'The station'} has {len(current_entries)} services in the current approved timetable."]
        segments.append(f"There {'is' if len(disruptions) == 1 else 'are'} {len(disruptions)} active disruption input{'s' if len(disruptions) != 1 else ''}.")
        if proposal:
            segments.append(_proposal_state_text(proposal))
        else:
            segments.append("There is no saved timetable proposal to review.")
        return _response("Current railway situation", " ".join(segments), related_ids, source)
    if kind == "disruption_summary":
        text = "There are no active disruption inputs." if not disruptions else " ".join(_disruption_text(item) for item in disruptions)
        affected = [item.train_id for item in disruptions if item.train_id]
        return _response("Active disruption summary", text, affected, source)
    if kind == "proposal_summary":
        if not proposal:
            return _response("Proposal summary", "There is no saved timetable proposal to summarize.", related_ids, source)
        text = _proposal_state_text(proposal)
        if changes:
            text += f" It records {len(changes)} train change{'s' if len(changes) != 1 else ''} against the approved timetable."
        else:
            text += " It records no train changes against the approved timetable."
        return _response("Proposed timetable", text, [item.get("train_id") for item in changes if item.get("train_id")], source)
    if kind == "platform_changes":
        selected = [item for item in changes if any(change.get("field") == "platform" for change in item.get("changes", [])) and (not train_id or item.get("train_id") == train_id)]
        if not selected:
            text = f"No recorded platform change is available{' for train ' + train_id if train_id else ''}."
        else:
            details = []
            for item in selected[:5]:
                platform = next(change for change in item["changes"] if change.get("field") == "platform")
                details.append(f"Train {item['train_id']}, {item.get('name', 'service')}, changed from {platform.get('before')} to {platform.get('after')}. {item.get('reason', 'No recorded reason is available.')}")
            text = " ".join(details)
        return _response("Platform changes", text, [item.get("train_id") for item in selected], source)
    if kind == "delay_analysis":
        disruption_delay = sum(item.delay_min for item in disruptions if item.kind == "train_delay")
        added_delay = sum(entry.additional_delay_min for entry in proposed_entries.values()) if proposed_entries else 0
        text = f"Active train-delay inputs total {disruption_delay} minute{'s' if disruption_delay != 1 else ''} across affected services."
        if proposal and proposed_entries:
            text += f" The optimizer-added delay in proposal {proposal.id} totals {added_delay} minute{'s' if added_delay != 1 else ''}; this is separate from disruption delay inputs."
        else:
            text += " No proposed timetable is available to calculate optimizer-added delay."
        return _response("Delay analysis", text, related_ids, source)
    if kind == "validation_summary":
        if not proposal:
            text = "There is no proposal with an independent validation result."
        elif validation.get("valid") is True:
            text = f"Proposal {proposal.id} passed independent validation with {validation.get('hard_violation_count', 0)} hard violations."
        elif validation:
            text = f"Proposal {proposal.id} did not pass independent validation. The recorded hard-violation count is {validation.get('hard_violation_count', 'unknown')}."
        else:
            text = f"Proposal {proposal.id} has no recorded independent validation result."
        return _response("Independent validation", text, related_ids, source)
    if kind == "approval_summary":
        text = "There is no proposal awaiting an approval decision." if not proposal else _proposal_state_text(proposal) + " Approval is a separate station-master action after validation and review."
        return _response("Approval status", text, related_ids, source)
    if kind == "rejection_summary":
        rejected = db.query(Proposal).filter(Proposal.state == "REJECTED").order_by(desc(Proposal.created_at)).first()
        if not rejected:
            text = "No rejected proposal is recorded."
        else:
            text = f"Proposal {rejected.id} was rejected. The approved timetable remained unchanged." + (f" Recorded reason: {rejected.rejection_reason}." if rejected.rejection_reason else " No rejection reason was recorded.")
            source["proposal_id"] = rejected.id
        return _response("Latest rejection", text, related_ids, source)
    if kind == "infeasibility_summary":
        if not proposal or proposal.state != "INFEASIBLE":
            text = "No selected proposal is recorded as infeasible."
        else:
            detail = diagnostics.get("summary") or diagnostics.get("reason") or diagnostics.get("message")
            text = f"Proposal {proposal.id} is infeasible; the solver did not return a timetable." + (f" Recorded diagnostic: {detail}." if detail else " No additional diagnostic was recorded.")
        return _response("Infeasibility summary", text, related_ids, source)
    if kind == "train_summary":
        train = db.query(Train).filter(Train.id == train_id).first() if train_id else None
        if not train:
            return _response("Train explanation", "Select a train from the timetable to receive a factual explanation.", related_ids, source)
        current = current_entries.get(train.id)
        proposed = proposed_entries.get(train.id)
        parts = [f"Train {train.id}, {train.name}."]
        if current:
            parts.append(f"The approved timetable is {minute_to_clock(current.arrival_min)} to {minute_to_clock(current.departure_min)} on {current.platform_id}.")
        else:
            parts.append("No approved timetable entry is recorded for this train.")
        if proposed:
            parts.append(f"The proposed timetable is {minute_to_clock(proposed.arrival_min)} to {minute_to_clock(proposed.departure_min)} on {proposed.platform_id}.")
            parts.append(f"The optimizer-added delay is {proposed.additional_delay_min} minute{'s' if proposed.additional_delay_min != 1 else ''}.")
        affected = [item for item in disruptions if item.train_id == train.id]
        if affected:
            parts.extend(_disruption_text(item) for item in affected)
        change = next((item for item in changes if item.get("train_id") == train.id), None)
        if change:
            parts.append(change.get("reason") or "A change was recorded without a detailed reason.")
        elif proposed and current and (proposed.platform_id != current.platform_id or proposed.arrival_min != current.arrival_min or proposed.departure_min != current.departure_min):
            parts.append("The timetable changed, but no detailed recorded reason is available.")
        if proposal:
            parts.append(_proposal_state_text(proposal))
        return _response("Train explanation", " ".join(parts), [train.id], source)
    return _response("Voice assistant", "That explanation type is not supported.", related_ids, source)


def _response(title: str, text: str, train_ids: list[str | None], source: dict) -> dict:
    return {
        "title": title,
        "text": text[:4000],
        "train_ids": [item for item in train_ids if item],
        "source_context": source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
