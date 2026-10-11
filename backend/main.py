from __future__ import annotations
import json, re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, update
from .database import get_db, init_db
from .models import (Station, Platform, Train, TimetableVersion, TimetableEntry, Scenario, Disruption,
                     StationInstruction, Proposal, ValidationRun, AuditEvent, OptimizationRun, SimulationState)
from .schemas import (ScenarioIn, OptimizeIn, RejectIn, AlternativeIn, SimulationPatch,
                      AssistantInterpretIn, AssistantConfirmIn, VoiceExplainIn, VoiceSpeakIn)
from .seed import seed_database
from .services.scheduler import optimize_timetable, SchedulerUnavailable
from .services.validator import validate_timetable
from .services.timeutils import minute_to_clock, clock_to_minute
from .services.voice import SpeechUnavailable, explain as explain_voice, speech_status, synthesize_speech
from .auth import authenticate, require_approver, validate_auth_configuration, current_actor

@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_configuration()
    init_db()
    db = next(get_db())
    try:
        seed_database(db)
    finally:
        db.close()
    yield

app = FastAPI(title="RailSync API", version="1.0.0", description="Fictional local railway disruption and platform-conflict simulator. No live railway systems are connected.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def authorize_mutations(request: Request, call_next):
    if request.method in {"POST", "PATCH", "DELETE"} and request.url.path.startswith("/api/") and request.url.path != "/api/assistant/interpret":
        try:
            principal = authenticate(request.headers.get("Authorization"))
            if request.url.path.endswith("/approve"):
                require_approver(principal)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        request.state.actor = principal.subject
        token = current_actor.set(principal.subject)
        try: return await call_next(request)
        finally: current_actor.reset(token)
    return await call_next(request)

def _json(value: Any, fallback):
    try: return json.loads(value) if value else fallback
    except (ValueError, TypeError): return fallback

def _audit(db: Session, event_type: str, entity_type: str, entity_id: Any = None, details: dict | None = None, actor: str | None = None):
    db.add(AuditEvent(event_type=event_type, actor=actor or current_actor.get() or "System", entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None, details_json=json.dumps(details or {})))

def _station(db: Session) -> Station:
    station = db.query(Station).first()
    if not station: raise HTTPException(500, "Station seed data is missing. Restart the backend to initialize the database.")
    return station

def _current_version(db: Session) -> TimetableVersion:
    version = db.query(TimetableVersion).filter(TimetableVersion.status == "CURRENT").order_by(desc(TimetableVersion.version_number)).first()
    if not version: raise HTTPException(500, "No approved timetable is available.")
    return version

def _simulation_start_minute(db: Session) -> int:
    """Choose a stable, human-readable replay point from the current timetable."""
    station = _station(db)
    first = db.query(TimetableEntry.arrival_min).filter(
        TimetableEntry.version_id == _current_version(db).id
    ).order_by(TimetableEntry.arrival_min).first()
    if not first:
        return station.horizon_start
    return max(station.horizon_start, (int(first[0]) // 5) * 5)

def _simulation_horizon_minute(db: Session) -> int:
    """Leave room for the final service to complete its visual departure."""
    station = _station(db)
    latest = db.query(TimetableEntry.departure_min).filter(
        TimetableEntry.version_id == _current_version(db).id
    ).order_by(desc(TimetableEntry.departure_min)).first()
    return max(station.horizon_end, int(latest[0]) + 20 if latest else station.horizon_end)

def _simulation_payload(db: Session, state: SimulationState, replaying: bool = False) -> dict:
    start = _simulation_start_minute(db)
    horizon = _simulation_horizon_minute(db)
    station = _station(db)
    return {"clock_min": state.clock_min, "clock": minute_to_clock(state.clock_min),
            "paused": state.paused, "speed": state.speed, "horizon_start": station.horizon_start,
            "horizon_end": horizon, "initial_clock_min": start,
            "initial_clock": minute_to_clock(start), "replaying": replaying}

def _entry_dict(entry: TimetableEntry, scenario_delay: int = 0, original: TimetableEntry | None = None) -> dict:
    original = original or entry
    return {"train_id": entry.train_id, "name": entry.train.name, "arrival_min": entry.arrival_min + scenario_delay,
            "departure_min": entry.departure_min + scenario_delay, "approved_arrival_min": entry.arrival_min,
            "approved_departure_min": entry.departure_min, "platform_id": entry.platform_id,
            "original_arrival_min": original.arrival_min, "original_departure_min": original.departure_min,
            "original_platform_id": original.platform_id,
            "additional_delay_min": entry.additional_delay_min, "scenario_delay_min": scenario_delay,
            "platform_changed": entry.platform_changed, "preference_satisfied": entry.preference_satisfied,
            "arrival": minute_to_clock(entry.arrival_min + scenario_delay), "departure": minute_to_clock(entry.departure_min + scenario_delay),
            "approved_arrival": minute_to_clock(entry.arrival_min), "approved_departure": minute_to_clock(entry.departure_min),
            "original_arrival": minute_to_clock(original.arrival_min), "original_departure": minute_to_clock(original.departure_min)}

def _version_entry_map(db: Session, version_id: int | None) -> dict[str, TimetableEntry]:
    if not version_id:
        return {}
    return {entry.train_id: entry for entry in db.query(TimetableEntry).options(joinedload(TimetableEntry.train)).filter(
        TimetableEntry.version_id == version_id
    ).all()}

def _scenario_inputs(db: Session, scenario_id: int | None = None, aggregate: bool = True) -> dict:
    station = _station(db); current = _current_version(db)
    version_entries = db.query(TimetableEntry).options(joinedload(TimetableEntry.train)).filter(TimetableEntry.version_id == current.id).all()
    if scenario_id is not None:
        chosen = db.query(Scenario).filter(Scenario.id == scenario_id).first()
        if not chosen: raise HTTPException(404, "Scenario not found")
        if not chosen.active: raise HTTPException(409, "The selected scenario is inactive. Activate it or choose an active scenario.")
        scenarios = [chosen]
        scenario_mode = "SELECTED"
    elif aggregate:
        scenarios = db.query(Scenario).filter(Scenario.active.is_(True)).all()
        scenario_mode = "AGGREGATE"
    else:
        raise HTTPException(422, "Select one scenario or explicitly request aggregate optimization.")
    scenario_ids = {s.id for s in scenarios}
    disruptions = db.query(Disruption).filter(Disruption.active.is_(True), Disruption.scenario_id.in_(scenario_ids)).all() if scenario_ids else []
    instructions = db.query(StationInstruction).filter(StationInstruction.active.is_(True), StationInstruction.scenario_id.in_(scenario_ids)).all() if scenario_ids else []
    delays: dict[str, int] = {}
    closures = []
    for d in disruptions:
        if d.kind == "train_delay" and d.train_id:
            delays[d.train_id] = delays.get(d.train_id, 0) + d.delay_min
        elif d.kind == "platform_closure" and d.platform_id is not None and d.start_min is not None and d.end_min is not None:
            closures.append({"platform_id": d.platform_id, "start_min": d.start_min, "end_min": d.end_min, "reason": d.reason, "disruption_id": d.id, "scenario_id": d.scenario_id})
    trains = []
    for t in db.query(Train).order_by(Train.id).all():
        trains.append({"train_id": t.id, "name": t.name, "allowed_platforms": _json(t.allowed_platforms_json, ["P1", "P2", "P3", "P4", "P5"]), "direction": t.direction, "priority": t.priority})
    platforms = [p.id for p in db.query(Platform).filter(Platform.enabled.is_(True)).order_by(Platform.number).all()]
    original_map = _version_entry_map(db, current.base_version_id) if current.source_proposal_id else {}
    entries = []
    for e in version_entries:
        r = _entry_dict(e, original=original_map.get(e.train_id))
        r["scenario_delay_min"] = delays.get(e.train_id, 0)
        entries.append(r)
    hard = [{"kind": i.kind, "train_id": i.train_id, "platform_id": i.platform_id, "instruction_text": i.instruction_text, "instruction_id": i.id} for i in instructions if i.kind == "HARD_PLATFORM"]
    soft = [{"kind": i.kind, "train_id": i.train_id, "platform_id": i.platform_id, "instruction_text": i.instruction_text, "instruction_id": i.id} for i in instructions if i.kind == "SOFT_PLATFORM"]
    return {"station": station, "current_version": current, "trains": trains, "platforms": platforms,
            "entries": entries, "closures": closures, "hard_instructions": hard, "soft_preferences": soft,
            "active_scenarios": scenarios, "active_disruptions": disruptions, "active_instructions": instructions, "scenario_mode": scenario_mode}

def _effective_entries(inputs: dict) -> list[dict]:
    result = []
    for row in inputs["entries"]:
        r = dict(row)
        shift = int(r.get("scenario_delay_min", 0))
        r["arrival_min"] = int(r["approved_arrival_min"]) + shift
        r["departure_min"] = int(r["approved_departure_min"]) + shift
        r["arrival"] = minute_to_clock(r["arrival_min"])
        r["departure"] = minute_to_clock(r["departure_min"])
        result.append(r)
    return result

def _validate_inputs(inputs: dict, rows: list[dict], gap: int | None = None) -> dict:
    return validate_timetable(rows, inputs["trains"], inputs["platforms"], inputs["closures"], inputs["hard_instructions"],
                              gap if gap is not None else inputs["station"].minimum_gap,
                              inputs["station"].horizon_start, inputs["station"].horizon_end)

def _proposal_entries(db: Session, proposal: Proposal) -> list[dict]:
    if not proposal.version_id: return []
    ents = db.query(TimetableEntry).options(joinedload(TimetableEntry.train)).filter(TimetableEntry.version_id == proposal.version_id).all()
    original_map = _version_entry_map(db, proposal.base_version_id)
    return [_entry_dict(e, original=original_map.get(e.train_id)) for e in ents]

def _proposal_payload(db: Session, proposal: Proposal, include_entries: bool = True) -> dict:
    validations = _json(proposal.validation_json, {})
    objective = _json(proposal.objective_json, {})
    changes = _json(proposal.changes_json, [])
    inputs = _json(proposal.inputs_json, {})
    output = {"id": proposal.id, "state": proposal.state, "solver_status": proposal.solver_status, "is_valid": proposal.is_valid,
              "base_version_id": proposal.base_version_id, "base_version_number": db.query(TimetableVersion).filter(TimetableVersion.id == proposal.base_version_id).first().version_number if db.query(TimetableVersion).filter(TimetableVersion.id == proposal.base_version_id).first() else None,
              "version_id": proposal.version_id, "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
              "created_by": proposal.created_by, "rejection_reason": proposal.rejection_reason,
              "objective": objective, "validation": validations, "changes": changes,
              "diagnostics": _json(proposal.infeasibility_json, {}),
              # The UI needs only the snapshot closures to render this proposal safely;
              # do not expose the complete optimization-input snapshot to the browser.
              "simulation_context": {"closures": inputs.get("closures", [])}}
    if include_entries: output["entries"] = _proposal_entries(db, proposal)
    return output

def _active_scenario_payload(s: Scenario) -> dict:
    return {"id": s.id, "title": s.title, "description": s.description, "active": s.active,
            "created_at": s.created_at.isoformat() if s.created_at else None, "created_by": s.created_by,
            "disruptions": [{"id": d.id, "kind": d.kind, "train_id": d.train_id, "platform_id": d.platform_id,
                            "delay_min": d.delay_min, "start_min": d.start_min, "end_min": d.end_min, "reason": d.reason, "active": d.active} for d in s.disruptions],
            "instructions": [{"id": i.id, "kind": i.kind, "train_id": i.train_id, "platform_id": i.platform_id, "instruction_text": i.instruction_text, "active": i.active} for i in s.instructions]}

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "RailSync API", "mode": "simulation", "data": "fictional", "solver": "OR-Tools CP-SAT when installed"}

@app.get("/api/station")
def station(db: Session = Depends(get_db)):
    s = _station(db); state = db.query(SimulationState).filter(SimulationState.id == 1).first()
    current = _current_version(db)
    return {"name": s.name, "horizon_start": s.horizon_start, "horizon_end": s.horizon_end,
            "horizon_label": f"{minute_to_clock(s.horizon_start)}–{minute_to_clock(s.horizon_end)}", "minimum_gap": s.minimum_gap,
            "current_version": current.version_number, "simulation": {"clock_min": state.clock_min, "clock": minute_to_clock(state.clock_min), "paused": state.paused, "speed": state.speed}}

@app.get("/api/trains")
def trains(db: Session = Depends(get_db)):
    return [{"train_id": t.id, "name": t.name, "allowed_platforms": _json(t.allowed_platforms_json, []), "direction": t.direction, "priority": t.priority}
            for t in db.query(Train).order_by(Train.id).all()]

@app.get("/api/platforms")
def platforms(db: Session = Depends(get_db)):
    inputs = _scenario_inputs(db); state = db.query(SimulationState).filter(SimulationState.id == 1).first(); effective = _effective_entries(inputs)
    result = []
    for p in db.query(Platform).order_by(Platform.number).all():
        closure = next((c for c in inputs["closures"] if c["platform_id"] == p.id and c["start_min"] <= state.clock_min < c["end_min"]), None)
        occupied = next((e for e in effective if e["platform_id"] == p.id and e["arrival_min"] <= state.clock_min < e["departure_min"]), None)
        reserved = next((e for e in sorted(effective, key=lambda x: x["arrival_min"]) if e["platform_id"] == p.id and state.clock_min < e["arrival_min"] <= state.clock_min + 20), None)
        status = "CLOSED" if closure else "OCCUPIED" if occupied else "RESERVED" if reserved else "FREE"
        result.append({"id": p.id, "number": p.number, "name": p.name, "status": status,
                       "train_id": occupied["train_id"] if occupied else reserved["train_id"] if reserved else None,
                       "train_name": occupied["name"] if occupied else reserved["name"] if reserved else None,
                       "closure": closure, "enabled": p.enabled})
    return result

@app.get("/api/timetable/current")
def timetable_current(db: Session = Depends(get_db)):
    version = _current_version(db)
    rows = db.query(TimetableEntry).options(joinedload(TimetableEntry.train)).filter(TimetableEntry.version_id == version.id).order_by(TimetableEntry.arrival_min).all()
    original_map = _version_entry_map(db, version.base_version_id) if version.source_proposal_id else {}
    return {"version_id": version.id, "version_number": version.version_number, "status": "CURRENT · Approved", "created_at": version.created_at.isoformat() if version.created_at else None,
            "entries": [_entry_dict(e, original=original_map.get(e.train_id)) for e in rows]}

@app.get("/api/timetable/effective")
def timetable_effective(db: Session = Depends(get_db)):
    inputs = _scenario_inputs(db)
    return {"version_id": inputs["current_version"].id, "version_number": inputs["current_version"].version_number,
            "status": "SCENARIO PROJECTION · Not yet approved", "active_scenario_ids": [s.id for s in inputs["active_scenarios"]],
            "entries": _effective_entries(inputs), "closures": inputs["closures"]}

@app.get("/api/conflicts")
def conflicts(db: Session = Depends(get_db)):
    inputs = _scenario_inputs(db); rows = _effective_entries(inputs); report = _validate_inputs(inputs, rows)
    items = []
    for i, v in enumerate(report["violations"], 1):
        items.append({"id": i, "severity": "HARD", "type": v["code"], "title": v["message"], "train_ids": v["train_ids"],
                      "platform_id": v["platform_id"], "start_min": v["start_min"], "end_min": v["end_min"]})
    # Near-separation warnings are visible but do not count as hard violations.
    for p in inputs["platforms"]:
        lane = sorted([r for r in rows if r["platform_id"] == p], key=lambda r: r["arrival_min"])
        for a, b in zip(lane, lane[1:]):
            gap = b["arrival_min"] - a["departure_min"]
            if gap >= inputs["station"].minimum_gap and gap < inputs["station"].minimum_gap + 3:
                items.append({"id": f"w-{p}-{a['train_id']}-{b['train_id']}", "severity": "WARNING", "type": "TIGHT_GAP", "title": f"Only {gap} minutes between {a['train_id']} and {b['train_id']} on {p}.", "train_ids": [a["train_id"], b["train_id"]], "platform_id": p, "start_min": a["departure_min"], "end_min": b["arrival_min"]})
    return {"items": items, "hard_count": sum(1 for x in items if x["severity"] == "HARD"), "warning_count": sum(1 for x in items if x["severity"] == "WARNING"), "independent_validation": report}

@app.get("/api/scenarios")
def scenarios(db: Session = Depends(get_db)):
    return [_active_scenario_payload(s) for s in db.query(Scenario).options(joinedload(Scenario.disruptions), joinedload(Scenario.instructions)).order_by(desc(Scenario.created_at)).all()]

@app.get("/api/scenarios/{scenario_id}")
def scenario_get(scenario_id: int, db: Session = Depends(get_db)):
    s = db.query(Scenario).options(joinedload(Scenario.disruptions), joinedload(Scenario.instructions)).filter(Scenario.id == scenario_id).first()
    if not s: raise HTTPException(404, "Scenario not found")
    return _active_scenario_payload(s)

@app.post("/api/scenarios", status_code=201)
def scenario_create(payload: ScenarioIn, db: Session = Depends(get_db)):
    known_trains = {t.id for t in db.query(Train).all()}; known_platforms = {p.id for p in db.query(Platform).all()}
    for d in payload.disruptions:
        if d.train_id and d.train_id not in known_trains: raise HTTPException(422, f"Unknown train {d.train_id}")
        if d.platform_id and d.platform_id not in known_platforms: raise HTTPException(422, f"Unknown platform {d.platform_id}")
    for i in payload.instructions:
        if i.train_id not in known_trains or i.platform_id not in known_platforms: raise HTTPException(422, "Instruction references unknown train or platform")
    if not payload.disruptions and not payload.instructions: raise HTTPException(422, "A scenario must include at least one disruption or instruction")
    s = Scenario(title=payload.title, description=payload.description, active=payload.activate)
    db.add(s); db.flush()
    for d in payload.disruptions:
        db.add(Disruption(scenario_id=s.id, kind=d.kind, train_id=d.train_id, platform_id=d.platform_id, delay_min=d.delay_min,
                          start_min=d.start_min, end_min=d.end_min, reason=d.reason, active=True))
    for i in payload.instructions:
        db.add(StationInstruction(scenario_id=s.id, kind=i.kind, train_id=i.train_id, platform_id=i.platform_id, instruction_text=i.instruction_text, active=True))
    _audit(db, "SCENARIO_APPLIED" if payload.activate else "SCENARIO_CREATED_INACTIVE", "scenario", s.id,
           {"title": s.title, "disruptions": [d.model_dump() for d in payload.disruptions], "instructions": [i.model_dump() for i in payload.instructions]})
    db.commit(); db.refresh(s)
    # Query relationships afresh so new child rows are returned consistently.
    s = db.query(Scenario).options(joinedload(Scenario.disruptions), joinedload(Scenario.instructions)).filter(Scenario.id == s.id).first()
    return _active_scenario_payload(s)

@app.delete("/api/scenarios/{scenario_id}")
def scenario_deactivate(scenario_id: int, db: Session = Depends(get_db)):
    s = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not s: raise HTTPException(404, "Scenario not found")
    s.active = False
    _audit(db, "SCENARIO_DEACTIVATED", "scenario", s.id, {"title": s.title})
    db.commit()
    return {"success": True, "scenario_id": scenario_id, "active": False, "message": "Scenario deactivated; approved timetable was not changed."}

@app.delete("/api/scenarios/{scenario_id}/disruptions/{disruption_id}")
def disruption_deactivate(scenario_id: int, disruption_id: int, db: Session = Depends(get_db)):
    d = db.query(Disruption).filter(Disruption.id == disruption_id, Disruption.scenario_id == scenario_id).first()
    if not d: raise HTTPException(404, "Disruption not found in this scenario")
    d.active = False
    _audit(db, "DISRUPTION_REMOVED", "disruption", d.id, {"scenario_id": scenario_id, "kind": d.kind, "reason": d.reason})
    db.commit(); return {"success": True, "disruption_id": d.id, "active": False}

@app.post("/api/scenarios/{scenario_id}/restore")
def scenario_restore(scenario_id: int, db: Session = Depends(get_db)):
    s = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not s: raise HTTPException(404, "Scenario not found")
    s.active = True
    _audit(db, "SCENARIO_RESTORED", "scenario", s.id, {"title": s.title})
    db.commit(); db.refresh(s)
    s = db.query(Scenario).options(joinedload(Scenario.disruptions), joinedload(Scenario.instructions)).filter(Scenario.id == s.id).first()
    return _active_scenario_payload(s)

@app.post("/api/scenarios/{scenario_id}/disruptions/{disruption_id}/restore")
def disruption_restore(scenario_id: int, disruption_id: int, db: Session = Depends(get_db)):
    s = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    d = db.query(Disruption).filter(Disruption.id == disruption_id, Disruption.scenario_id == scenario_id).first()
    if not s or not d: raise HTTPException(404, "Scenario or disruption not found")
    if not s.active: raise HTTPException(409, "Restore the parent scenario before restoring an individual disruption")
    d.active = True
    _audit(db, "DISRUPTION_RESTORED", "disruption", d.id, {"scenario_id": scenario_id, "kind": d.kind, "reason": d.reason})
    db.commit()
    return {"success": True, "disruption_id": d.id, "active": True}

@app.delete("/api/scenarios/{scenario_id}/instructions/{instruction_id}")
def instruction_deactivate(scenario_id: int, instruction_id: int, db: Session = Depends(get_db)):
    i = db.query(StationInstruction).filter(StationInstruction.id == instruction_id, StationInstruction.scenario_id == scenario_id).first()
    if not i: raise HTTPException(404, "Instruction not found in this scenario")
    i.active = False
    _audit(db, "INSTRUCTION_REMOVED", "instruction", i.id, {"scenario_id": scenario_id, "kind": i.kind, "instruction_text": i.instruction_text})
    db.commit()
    return {"success": True, "instruction_id": i.id, "active": False}

@app.post("/api/scenarios/{scenario_id}/instructions/{instruction_id}/restore")
def instruction_restore(scenario_id: int, instruction_id: int, db: Session = Depends(get_db)):
    s = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    i = db.query(StationInstruction).filter(StationInstruction.id == instruction_id, StationInstruction.scenario_id == scenario_id).first()
    if not s or not i: raise HTTPException(404, "Scenario or instruction not found")
    if not s.active: raise HTTPException(409, "Restore the parent scenario before restoring an individual instruction")
    i.active = True
    _audit(db, "INSTRUCTION_RESTORED", "instruction", i.id, {"scenario_id": scenario_id, "kind": i.kind, "instruction_text": i.instruction_text})
    db.commit()
    return {"success": True, "instruction_id": i.id, "active": True}

@app.get("/api/timetable/proposals")
def timetable_proposals_alias(db: Session = Depends(get_db)):
    return [_proposal_payload(db, p, include_entries=False) for p in db.query(Proposal).order_by(desc(Proposal.created_at)).all()]

@app.get("/api/schedules/proposals")
def proposals(db: Session = Depends(get_db)):
    return [_proposal_payload(db, p, include_entries=False) for p in db.query(Proposal).order_by(desc(Proposal.created_at)).all()]

@app.post("/api/schedules/optimize", status_code=201)
def optimize(payload: OptimizeIn, db: Session = Depends(get_db)):
    inputs = _scenario_inputs(db, payload.scenario_id, payload.aggregate)
    base_rows = []
    for row in inputs["entries"]:
        r = {k: row[k] for k in ("train_id", "name", "approved_arrival_min", "approved_departure_min", "platform_id")}
        r["arrival_min"] = row["approved_arrival_min"] + row["scenario_delay_min"]
        r["departure_min"] = row["approved_departure_min"] + row["scenario_delay_min"]
        r["scenario_delay_min"] = row["scenario_delay_min"]
        base_rows.append(r)
    try:
        result = optimize_timetable(inputs["trains"], base_rows, inputs["platforms"], inputs["closures"], inputs["hard_instructions"], inputs["soft_preferences"],
                                    minimum_gap=payload.minimum_gap, horizon_start=inputs["station"].horizon_start,
                                    horizon_end=inputs["station"].horizon_end, max_time_seconds=payload.max_time_seconds)
    except SchedulerUnavailable as exc:
        raise HTTPException(503, str(exc))
    actor = current_actor.get() or "System"
    proposal = Proposal(base_version_id=inputs["current_version"].id, scenario_id=payload.scenario_id or (inputs["active_scenarios"][-1].id if inputs["active_scenarios"] else None),
                        state="INFEASIBLE" if result["solver_status"] == "INFEASIBLE" else "UNRESOLVED" if not result["has_schedule"] else "PROPOSED", solver_status=result["solver_status"], is_valid=False,
                        objective_json=json.dumps(result.get("objective", {})), validation_json=json.dumps({}), changes_json=json.dumps([]),
                        inputs_json=json.dumps({"scenario_mode": inputs["scenario_mode"], "scenario_ids": [s.id for s in inputs["active_scenarios"]], "disruption_ids": [d.id for d in inputs["active_disruptions"]], "instruction_ids": [i.id for i in inputs["active_instructions"]], "trains": inputs["trains"], "platforms": inputs["platforms"], "closures": inputs["closures"],
                                                "hard_instructions": inputs["hard_instructions"], "soft_preferences": inputs["soft_preferences"],
                                                "minimum_gap": payload.minimum_gap, "horizon_start": inputs["station"].horizon_start, "horizon_end": inputs["station"].horizon_end,
                                                "effective_base": base_rows}), infeasibility_json=json.dumps(result.get("diagnostics", {})), created_by=actor)
    db.add(proposal); db.flush()
    if result["has_schedule"]:
        report = validate_timetable(result["entries"], inputs["trains"], inputs["platforms"], inputs["closures"], inputs["hard_instructions"], payload.minimum_gap,
                                    inputs["station"].horizon_start, inputs["station"].horizon_end)
        proposal.validation_json = json.dumps(report)
        proposal.is_valid = bool(report["valid"])
        proposal.state = "AWAITING_APPROVAL" if report["valid"] else "INVALID"
        next_num = max([v.version_number for v in db.query(TimetableVersion).all()] + [0]) + 1
        version = TimetableVersion(version_number=next_num, status="PROPOSED" if report["valid"] else "INVALID", base_version_id=inputs["current_version"].id,
                                  source_proposal_id=proposal.id, created_by=actor, note=f"Proposal #{proposal.id} generated by CP-SAT")
        db.add(version); db.flush()
        proposal.version_id = version.id
        # The comparison shown to the station master must be against the approved
        # timetable, not the scenario-shifted working input. Keep the shifted input
        # separately for explanations about closures and optimizer-added delay.
        approved_map = {r["train_id"]: r for r in inputs["entries"]}
        solver_base_map = {r["train_id"]: r for r in base_rows}
        changes = []
        for r in result["entries"]:
            prior = approved_map[r["train_id"]]
            working_prior = solver_base_map[r["train_id"]]
            diffs = []
            if r["platform_id"] != prior["platform_id"]:
                diffs.append({"field": "platform", "before": prior["platform_id"], "after": r["platform_id"]})
            if r["arrival_min"] != prior["approved_arrival_min"] or r["departure_min"] != prior["approved_departure_min"]:
                diffs.append({"field": "time", "before": f"{minute_to_clock(prior['approved_arrival_min'])}–{minute_to_clock(prior['approved_departure_min'])}", "after": f"{minute_to_clock(r['arrival_min'])}–{minute_to_clock(r['departure_min'])}"})
            reason_parts = []
            if r.get("scenario_delay_min", 0):
                reason_parts.append(f"The active disruption adds {r['scenario_delay_min']} minute(s) to the approved timetable for this train.")
            if r["platform_changed"]:
                closed_old = any(c["platform_id"] == working_prior["platform_id"] and working_prior["arrival_min"] < c["end_min"] and working_prior["departure_min"] > c["start_min"] for c in inputs["closures"])
                reason_parts.append(f"Platform changed from {prior['platform_id']} to {r['platform_id']} in the solver's feasible solution" + (" because the prior platform intersects an active closure." if closed_old else " while satisfying the submitted constraints."))
            if r["additional_delay_min"]:
                reason_parts.append(f"The optimizer added {r['additional_delay_min']} minute(s) to satisfy the modeled occupancy, closure and separation constraints.")
            if not reason_parts and diffs:
                reason_parts.append("Timetable fields changed in the computed solution to satisfy the submitted constraints and objective.")
            if diffs:
                changes.append({"train_id": r["train_id"], "name": r["name"], "changes": diffs, "reason": " ".join(reason_parts) or "Computed change from the approved timetable."})
            db.add(TimetableEntry(version_id=version.id, train_id=r["train_id"], arrival_min=r["arrival_min"], departure_min=r["departure_min"],
                                  platform_id=r["platform_id"], additional_delay_min=r["additional_delay_min"], platform_changed=r["platform_changed"], preference_satisfied=r["preference_satisfied"]))
        proposal.changes_json = json.dumps(changes)
        db.add(ValidationRun(proposal_id=proposal.id, status=report["status"], hard_violation_count=report["hard_violation_count"], report_json=json.dumps(report)))
        db.add(OptimizationRun(proposal_id=proposal.id, status=result["solver_status"], wall_time_seconds=result["wall_time_seconds"],
                               objective_value=result.get("objective", {}).get("weighted_objective"), best_bound=int(result["objective"].get("best_bound", 0)) if result.get("objective") else None,
                               metadata_json=json.dumps({"objective": result.get("objective", {}), "diagnostics": result.get("diagnostics", {})})))
    _audit(db, "SCHEDULE_OPTIMIZED" if result["has_schedule"] else "SCHEDULE_INFEASIBLE", "proposal", proposal.id,
           {"solver_status": result["solver_status"], "state": proposal.state, "objective": result.get("objective", {}), "diagnostics": result.get("diagnostics", {})})
    db.commit(); db.refresh(proposal)
    return _proposal_payload(db, proposal)

@app.get("/api/schedules/proposals/{proposal_id}")
def proposal_get(proposal_id: int, db: Session = Depends(get_db)):
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not p: raise HTTPException(404, "Proposal not found")
    return _proposal_payload(db, p)

@app.post("/api/schedules/proposals/{proposal_id}/validate")
def proposal_validate(proposal_id: int, db: Session = Depends(get_db)):
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not p: raise HTTPException(404, "Proposal not found")
    if not p.version_id: raise HTTPException(409, "This proposal has no schedule to validate because the solver did not find a feasible result.")
    snap = _json(p.inputs_json, {})
    entries = _proposal_entries(db, p)
    report = validate_timetable(entries, snap.get("trains", []), snap.get("platforms", []), snap.get("closures", []), snap.get("hard_instructions", []),
                                int(snap.get("minimum_gap", 5)), int(snap.get("horizon_start", 0)), int(snap.get("horizon_end", 180)))
    p.validation_json = json.dumps(report); p.is_valid = bool(report["valid"])
    p.state = "AWAITING_APPROVAL" if report["valid"] and p.state not in {"APPROVED", "REJECTED"} else "INVALID" if not report["valid"] else p.state
    version = db.query(TimetableVersion).filter(TimetableVersion.id == p.version_id).first()
    if version and p.state == "INVALID": version.status = "INVALID"
    db.add(ValidationRun(proposal_id=p.id, status=report["status"], hard_violation_count=report["hard_violation_count"], report_json=json.dumps(report)))
    _audit(db, "PROPOSAL_VALIDATED", "proposal", p.id, {"status": report["status"], "hard_violations": report["hard_violation_count"]})
    db.commit(); db.refresh(p); return _proposal_payload(db, p)

@app.post("/api/schedules/proposals/{proposal_id}/approve")
def proposal_approve(proposal_id: int, db: Session = Depends(get_db)):
    # SQLite ignores SELECT ... FOR UPDATE. Claim the state with one conditional
    # UPDATE instead, so only one transaction can promote a proposal.
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not p: raise HTTPException(404, "Proposal not found")
    if p.state != "AWAITING_APPROVAL" or not p.is_valid:
        raise HTTPException(409, "Only an independently validated proposal with zero hard violations can be approved.")
    claimed = db.execute(update(Proposal).where(
        Proposal.id == proposal_id,
        Proposal.state == "AWAITING_APPROVAL",
        Proposal.is_valid.is_(True),
    ).values(state="APPROVING"))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "This proposal is already being processed or is no longer eligible for approval.")
    db.flush()
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    current = _current_version(db)
    if current.id != p.base_version_id:
        db.rollback()
        raise HTTPException(409, "This proposal is stale because the approved timetable changed. Generate a new proposal against the current version.")
    report = _json(p.validation_json, {})
    if report.get("valid") is not True or int(report.get("hard_violation_count", -1)) != 0:
        db.rollback()
        raise HTTPException(409, "Independent validation is missing or failed; approval is blocked.")
    if not p.version_id:
        db.rollback()
        raise HTTPException(409, "Proposal timetable is missing")
    new_version = db.query(TimetableVersion).filter(TimetableVersion.id == p.version_id).first()
    if not new_version:
        db.rollback()
        raise HTTPException(409, "Proposal version is missing")
    # Single DB transaction: the prior version is archived and proposal becomes current atomically.
    current.status = "ARCHIVED"
    new_version.status = "CURRENT"
    p.state = "APPROVED"
    # A proposal is a snapshot. Consume only the active scenario items recorded
    # in that snapshot so its already-incorporated effects are not projected again.
    snap = _json(p.inputs_json, {})
    disruption_ids = [int(x) for x in snap.get("disruption_ids", [])]
    instruction_ids = [int(x) for x in snap.get("instruction_ids", [])]
    active_disruptions = db.query(Disruption).filter(Disruption.id.in_(disruption_ids), Disruption.active.is_(True)).all() if disruption_ids else []
    active_instructions = db.query(StationInstruction).filter(StationInstruction.id.in_(instruction_ids), StationInstruction.active.is_(True)).all() if instruction_ids else []
    if {d.id for d in active_disruptions} != set(disruption_ids) or {i.id for i in active_instructions} != set(instruction_ids):
        db.rollback()
        raise HTTPException(409, "Scenario inputs changed after optimization; generate a new proposal.")
    for disruption in active_disruptions: disruption.active = False
    for instruction in active_instructions: instruction.active = False
    for scenario_id in snap.get("scenario_ids", []):
        scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
        if scenario and not any(d.active for d in scenario.disruptions) and not any(i.active for i in scenario.instructions):
            scenario.active = False
    _audit(db, "TIMETABLE_APPROVED", "proposal", p.id, {"old_version": current.version_number, "new_version": new_version.version_number})
    db.commit()
    return {"success": True, "message": "Proposal approved and promoted to current timetable.", "current_version_id": new_version.id, "current_version_number": new_version.version_number, "proposal": _proposal_payload(db, p)}

@app.post("/api/schedules/proposals/{proposal_id}/reject")
def proposal_reject(proposal_id: int, payload: RejectIn, db: Session = Depends(get_db)):
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not p: raise HTTPException(404, "Proposal not found")
    if p.state in {"APPROVED", "REJECTED"}: raise HTTPException(409, f"Cannot reject a proposal already {p.state.lower()}.")
    p.state = "REJECTED"; p.rejection_reason = payload.reason
    version = db.query(TimetableVersion).filter(TimetableVersion.id == p.version_id).first() if p.version_id else None
    if version: version.status = "REJECTED"
    _audit(db, "PROPOSAL_REJECTED", "proposal", p.id, {"reason": payload.reason, "approved_timetable_unchanged": True})
    db.commit(); db.refresh(p)
    return {"success": True, "message": "Proposal rejected. The approved timetable and active disruptions remain unchanged.", "proposal": _proposal_payload(db, p, include_entries=False)}

@app.post("/api/schedules/proposals/{proposal_id}/alternative", status_code=201)
def proposal_alternative(proposal_id: int, payload: AlternativeIn, db: Session = Depends(get_db)):
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not p: raise HTTPException(404, "Proposal not found")
    if p.state != "REJECTED": raise HTTPException(409, "Reject the proposal before requesting an alternative.")
    if payload.instruction is None:
        raise HTTPException(422, "Provide a structured station-master instruction or preference so the optimizer has a changed requirement for the alternative.")
    instruction = payload.instruction
    if not db.query(Train).filter(Train.id == instruction.train_id).first() or not db.query(Platform).filter(Platform.id == instruction.platform_id).first():
        raise HTTPException(422, "Instruction references an unknown train or platform")
    active = db.query(Scenario).filter(Scenario.active.is_(True)).order_by(desc(Scenario.created_at)).first()
    if not active:
        active = Scenario(title="Station-master alternative constraints", description=payload.reason, active=True); db.add(active); db.flush()
    db.add(StationInstruction(scenario_id=active.id, kind=instruction.kind, train_id=instruction.train_id, platform_id=instruction.platform_id, instruction_text=instruction.instruction_text, active=True))
    _audit(db, "ALTERNATIVE_REQUESTED", "proposal", p.id, {"reason": payload.reason, "instruction": instruction.model_dump(), "new_scenario_id": active.id})
    db.commit()
    # Re-run the real optimizer with changed structured constraints.
    return optimize(OptimizeIn(scenario_id=active.id, minimum_gap=payload.minimum_gap, max_time_seconds=payload.max_time_seconds), db)

@app.get("/api/validation/history")
def validation_history(db: Session = Depends(get_db)):
    rows = db.query(ValidationRun).order_by(desc(ValidationRun.created_at)).limit(100).all()
    return [{"id": r.id, "proposal_id": r.proposal_id, "status": r.status, "hard_violation_count": r.hard_violation_count,
             "report": _json(r.report_json, {}), "created_at": r.created_at.isoformat()} for r in rows]

@app.get("/api/audit")
def audit_events(limit: int = Query(default=100, ge=1, le=500), event_type: str | None = None, db: Session = Depends(get_db)):
    q = db.query(AuditEvent)
    if event_type: q = q.filter(AuditEvent.event_type == event_type)
    rows = q.order_by(desc(AuditEvent.created_at)).limit(limit).all()
    return [{"id": r.id, "event_type": r.event_type, "actor": r.actor, "entity_type": r.entity_type, "entity_id": r.entity_id,
             "details": _json(r.details_json, {}), "created_at": r.created_at.isoformat()} for r in rows]

@app.get("/api/events")
def events(limit: int = Query(default=10, ge=1, le=100), db: Session = Depends(get_db)):
    rows = db.query(AuditEvent).order_by(desc(AuditEvent.created_at)).limit(limit).all()
    return [{"id": r.id, "event_type": r.event_type, "title": r.event_type.replace("_", " ").title(), "actor": r.actor,
             "details": _json(r.details_json, {}), "created_at": r.created_at.isoformat()} for r in rows]

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    inputs = _scenario_inputs(db); effective = _effective_entries(inputs); state = db.query(SimulationState).filter(SimulationState.id == 1).first()
    report = _validate_inputs(inputs, effective)
    approaching = [r for r in effective if state.clock_min <= r["arrival_min"] <= state.clock_min + 20]
    delayed = [r for r in effective if r["scenario_delay_min"] > 0]
    open_closures = [c for c in inputs["closures"] if c["start_min"] <= state.clock_min < c["end_min"]]
    conflicts = db.query(Proposal).filter(Proposal.state == "AWAITING_APPROVAL").count()
    return {"station": inputs["station"].name, "mode": "SIMULATION MODE · FICTIONAL STATION DATA", "current_version": inputs["current_version"].version_number,
            "clock_min": state.clock_min, "clock": minute_to_clock(state.clock_min), "paused": state.paused, "speed": state.speed,
            "scheduled_today": len(inputs["trains"]), "approaching": len(approaching), "delayed": len(delayed), "closures": len({c["platform_id"] for c in open_closures}),
            "hard_conflicts": report["hard_violation_count"], "proposals_awaiting_approval": conflicts, "validation_status": "PASS" if report["valid"] else "ISSUES",
            "upcoming": sorted(effective, key=lambda r: r["arrival_min"])[:8], "active_scenario_count": len(inputs["active_scenarios"])}

@app.get("/api/simulation")
def simulation_get(db: Session = Depends(get_db)):
    state = db.query(SimulationState).filter(SimulationState.id == 1).first()
    return _simulation_payload(db, state)

@app.patch("/api/simulation")
def simulation_patch(payload: SimulationPatch, db: Session = Depends(get_db)):
    state = db.query(SimulationState).filter(SimulationState.id == 1).first()
    replaying = False
    if payload.reset:
        start = payload.start_min if payload.start_min is not None else _simulation_start_minute(db)
        state.clock_min = min(_simulation_horizon_minute(db), start); state.paused = False; state.speed = 1
        _audit(db, "SIMULATION_RESET", "simulation", 1, {"clock": minute_to_clock(state.clock_min)})
    if payload.paused is not None: state.paused = payload.paused
    if payload.speed is not None: state.speed = payload.speed
    if payload.seek_min is not None:
        station = _station(db); horizon = _simulation_horizon_minute(db)
        if not station.horizon_start <= payload.seek_min <= horizon:
            raise HTTPException(422, f"Simulation time must be between {minute_to_clock(station.horizon_start)} and {minute_to_clock(horizon)}.")
        # Seeking is an operator action, not timetable mutation.  In particular,
        # keep pause/play and speed unchanged so playback resumes predictably.
        state.clock_min = payload.seek_min
        _audit(db, "SIMULATION_SEEKED", "simulation", 1, {"clock": minute_to_clock(state.clock_min)})
    if payload.advance_minutes and not state.paused:
        horizon = _simulation_horizon_minute(db)
        next_minute = state.clock_min + payload.advance_minutes * state.speed
        if next_minute >= horizon:
            # The finite fictional timetable has completed.  Replay explicitly
            # from the selected timetable's start instead of leaving an empty,
            # permanently-paused station at the end of the horizon.
            requested_start = payload.loop_start_min if payload.loop_start_min is not None else _simulation_start_minute(db)
            state.clock_min = min(horizon, max(0, requested_start))
            replaying = True
            _audit(db, "SIMULATION_REPLAYED", "simulation", 1,
                   {"from": minute_to_clock(horizon), "to": minute_to_clock(state.clock_min)})
        else:
            state.clock_min = max(0, next_minute)
    db.commit()
    return _simulation_payload(db, state, replaying=replaying)

@app.get("/api/assistant/context")
def assistant_context(db: Session = Depends(get_db)):
    dash = dashboard(db)
    active = [_active_scenario_payload(s) for s in db.query(Scenario).options(joinedload(Scenario.disruptions), joinedload(Scenario.instructions)).filter(Scenario.active.is_(True)).all()]
    return {"station": dash["station"], "clock": dash["clock"], "current_version": dash["current_version"], "train_count": dash["scheduled_today"],
            "active_scenarios": active, "summary": f"{dash['station']} has {dash['scheduled_today']} scheduled fictional services. {dash['delayed']} have active delay inputs, {dash['closures']} platforms are closed at the simulated clock, and the current scenario projection has {dash['hard_conflicts']} hard conflict(s)."}

@app.get("/api/voice/status")
def voice_status():
    return speech_status()

@app.get("/api/voice/suggestions")
def voice_suggestions():
    return {"actions": [
        {"kind": "current_status", "label": "Explain the current railway situation"},
        {"kind": "disruption_summary", "label": "Summarize active disruptions"},
        {"kind": "platform_changes", "label": "Explain platform changes"},
        {"kind": "proposal_summary", "label": "Explain the proposed timetable"},
        {"kind": "validation_summary", "label": "Read validation results"},
        {"kind": "delay_analysis", "label": "Summarize additional delay"},
        {"kind": "approval_summary", "label": "Explain approval status"},
        {"kind": "rejection_summary", "label": "Explain the last rejection"},
    ], "questions": [
        "What happened to the timetable?", "Which trains were affected?", "Why was this train moved to another platform?",
        "How much additional delay did the optimizer introduce?", "Did the proposed timetable pass validation?",
        "What changed in the proposed timetable?", "Is this proposal approved?", "Summarize the latest disruption.",
    ]}

@app.post("/api/voice/explain")
def voice_explain(payload: VoiceExplainIn, db: Session = Depends(get_db)):
    try:
        return explain_voice(db, payload.kind, payload.proposal_id, payload.train_id, payload.question)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

@app.post("/api/voice/speak")
def voice_speak(payload: VoiceSpeakIn, db: Session = Depends(get_db)):
    try:
        explanation = explain_voice(db, payload.kind, payload.proposal_id, payload.train_id, payload.question)
        audio = synthesize_speech(explanation["text"])
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except SpeechUnavailable as exc:
        raise HTTPException(503, str(exc))
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

@app.post("/api/assistant/interpret")
def assistant_interpret(payload: AssistantInterpretIn, db: Session = Depends(get_db)):
    text = payload.text.strip()
    # This is an explicit local rule-based demo adapter, not an LLM service.
    instruction_match = re.search(r"(?:train\s+)?(\d{4,6}).*?(?:on|at)\s+(?:platform\s*)?(P?\d)\b", text, re.I)
    delay = re.search(r"(?:delay|hold)\s+(?:train\s+)?(\d{4,6})\s+(?:by\s+)?(\d{1,3})\s*(?:minutes?|mins?)", text, re.I)
    closure = re.search(r"(?:close|closure|shut)\s+(?:platform\s*)?(\d|P\d).*?(\d{1,2}:\d{2}).*?(?:to|until|-)\s*(\d{1,2}:\d{2})", text, re.I)
    known_trains = {t.id for t in db.query(Train).all()}; known_platforms = {p.id for p in db.query(Platform).all()}
    if delay:
        tid, minutes = delay.group(1), int(delay.group(2))
        if tid not in known_trains: raise HTTPException(422, f"Unknown train {tid}")
        parsed = {"kind": "train_delay", "train_id": tid, "delay_min": minutes, "reason": "Confirmed through Operations Assistant"}
        return {"supported": True, "requires_confirmation": True, "kind": "disruption", "interpreted": parsed, "summary": f"Add a {minutes}-minute delay to Train {tid}. Nothing has been changed yet."}
    if closure:
        p_raw, start, end = closure.groups(); pid = f"P{p_raw[-1]}"
        a, b = clock_to_minute(start), clock_to_minute(end)
        if pid not in known_platforms or a < 0 or b > 180 or a >= b: raise HTTPException(422, "Platform or closure time is outside the 09:00–12:00 demo horizon")
        parsed = {"kind": "platform_closure", "platform_id": pid, "start_min": a, "end_min": b, "reason": "Confirmed through Operations Assistant"}
        return {"supported": True, "requires_confirmation": True, "kind": "disruption", "interpreted": parsed, "summary": f"Close {pid} from {start} to {end}. Nothing has been changed yet."}
    match = instruction_match
    if match:
        tid, p_raw = match.group(1), match.group(2); pid = p_raw if p_raw.upper().startswith("P") else f"P{p_raw}"
        if tid not in known_trains or pid not in known_platforms: raise HTTPException(422, "Unknown train or platform")
        is_soft = bool(re.search(r"if possible|prefer|try to keep|preferably|soft preference", text, re.I))
        is_hard = bool(re.search(r"\bmust\b|\bmandatory\b|\brequired\b|\bremain\b|\bstay\b", text, re.I))
        kind = "SOFT_PLATFORM" if is_soft or not is_hard else "HARD_PLATFORM"
        parsed = {"kind": kind, "train_id": tid, "platform_id": pid,
                  "instruction_text": text, "instruction": {"kind": kind, "train_id": tid, "platform_id": pid, "instruction_text": text}}
        action_label = "mandatory requirement" if kind == "HARD_PLATFORM" else "soft preference"
        return {"supported": True, "requires_confirmation": True, "kind": "instruction", "interpreted": parsed, "summary": f"Create a {action_label} for Train {tid} on {pid}. Nothing has been changed yet."}
    return {"supported": False, "requires_confirmation": False, "kind": "unsupported", "interpreted": None,
            "summary": "I could not safely convert that text into a structured demo instruction. Try: ‘delay train 12951 by 15 minutes’, ‘close platform 2 from 10:00 to 10:45’, or ‘keep train 12951 on platform 3 if possible’. No data was changed."}

@app.post("/api/assistant/confirm", status_code=201)
def assistant_confirm(payload: AssistantConfirmIn, db: Session = Depends(get_db)):
    disruptions = [payload.disruption] if payload.disruption else []
    instructions = [payload.instruction] if payload.instruction else []
    if not disruptions and not instructions: raise HTTPException(422, "Confirmation needs a structured disruption or instruction")
    scenario_payload = ScenarioIn(title=payload.title, description="Confirmed Operations Assistant instruction.", disruptions=disruptions, instructions=instructions, activate=True)
    return scenario_create(scenario_payload, db)

@app.get("/api/overview")
def overview_alias(db: Session = Depends(get_db)):
    return dashboard(db)
