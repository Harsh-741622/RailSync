# RailSync — Railway Disruption & Platform Conflict Simulator

RailSync is a **local hackathon prototype** for exploring fictional train delays, platform closures, timetable conflicts, constraint-based rescheduling, independent validation, and station-master approval. It is not connected to Indian Railways or any live railway operating system, and it is not safety-certified.

The UI follows the supplied dark navy/cyan/amber/red/green visual language and uses one fictional station dataset: **Central Junction**, five platforms (P1–P5), 18 services, and a simulated 09:00–12:00 horizon. Times are stored as integer minutes after 09:00. A platform reservation/closure or train delay is a local simulation input, not a live incident.

## Stack

- **Frontend:** React + TypeScript + Vite, responsive CSS, Lucide icons.
- **API:** Python + FastAPI + Pydantic.
- **Optimization:** Google OR-Tools CP-SAT. The application does not fall back to a mock scheduler; if OR-Tools is missing, optimization returns a clear HTTP 503 error.
- **Persistence:** SQLAlchemy + SQLite.
- **Validation/tests:** independent plain-Python timetable validator + Pytest and FastAPI TestClient.

## Voice assistant

The **AI Voice Assistant** page explains real persisted RailSync state: active disruptions, affected trains, approved-versus-proposed timetable changes, recorded platform-change reasons, disruption delay versus optimizer-added delay, validation, approval/rejection state, and available infeasibility diagnostics. It is explanatory only: it cannot assign platforms, approve a proposal, or change the timetable.

Text briefings, quick actions, a train selector, and supported typed questions work without any external credential. Browser speech recognition is optional and has a typed fallback. It uses the browser implementation when available (commonly Chromium browsers); it may be unavailable in Firefox, blocked by browser policy, or denied by microphone permissions.

ElevenLabs is optional. The frontend never receives its API key. To enable MP3 speech, add these values to your local backend `.env` (leave `.env.example` unchanged as a template), then restart the backend:

```text
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
ELEVENLABS_ENABLED=true
```

Choose `ELEVENLABS_VOICE_ID` from a voice available in your ElevenLabs account. The assistant reports speech as ready only when enabled and configured; failed provider calls keep the readable briefing available. Spoken railway updates are off by default, announce only new confirmed events once while the assistant page is open, and can be stopped or muted from that page.

Supported questions include: “What happened to the timetable?”, “Which trains were affected?”, “Why was this train moved to another platform?”, “How much additional delay did the optimizer introduce?”, “Did the proposed timetable pass validation?”, “What changed in the proposed timetable?”, “Is this proposal approved?”, and “Summarize the latest disruption.” Unsupported questions receive a bounded explanation of the available actions.

## Requirements

- Python 3.11 or newer (Python 3.12 is a safe default for broad wheel availability).
- Node.js 20 or newer and npm.
- Internet access during initial dependency installation, unless packages are already cached. OR-Tools is a native package and may not be available in offline environments.

## Run on Windows

Open PowerShell in the extracted `RailSync` folder.

### 1. Install and start the backend

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

On the first start, RailSync creates `railsync.db` in the project working directory and seeds the fictional station if the database is empty. Do not delete the database unless you intend to reset local demo state. API documentation is available at `http://127.0.0.1:8000/docs` and health status at `http://127.0.0.1:8000/api/health`.

### 2. Install and start the frontend

Open a **second** PowerShell terminal in the `RailSync` folder:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL printed by npm, normally `http://localhost:5173`.

The frontend uses `http://localhost:8000/api` by default. To change it, create `frontend/.env.local` with:

```text
VITE_API_ROOT=http://localhost:8000/api
```

## Authentication and operational access

RailSync is a simulator, not a production railway control system. Its local setup deliberately runs in the explicit `demo` mode in [`.env.example`](.env.example), where mutation requests are attributed to **Demo Station Master**. Demo mode is for a local single-user exercise only and must never be used for deployment.

Production mode is fail-closed. Set both values outside source control before starting the API:

```text
RAILSYNC_AUTH_MODE=production
RAILSYNC_AUTH_SECRET=<a unique random secret of at least 32 characters>
```

The server rejects startup without a valid production secret. All `POST`, `PATCH`, and `DELETE` operational endpoints then require a signed `Authorization: Bearer <token>` header. Tokens carry a server-verified subject, role (`operator` or `approver`), and expiry; approval requires the `approver` role. The API never accepts an actor supplied by the client, and audit records use the authenticated subject. Token creation is intentionally not exposed as an HTTP endpoint: integrate `backend.auth.create_access_token` only from a trusted identity-provisioning service. For a development-only browser client, a separately provisioned short-lived token may be supplied through `VITE_RAILSYNC_AUTH_TOKEN`; do not put a production token in source control or a public frontend bundle.

## Scenario scope and lifecycle

`POST /api/schedules/optimize` has two mutually exclusive modes:

- **Selected scenario:** send `{ "scenario_id": 123 }`. Only that active scenario's active disruptions and instructions are used. A missing scenario returns `404`; an inactive scenario returns `409`.
- **Aggregate operations view:** send `{ "aggregate": true }`. Every active scenario is included deliberately. This is the mode used by the existing aggregate UI controls.

Requests that name neither mode, or both, are rejected with `422`. Each proposal stores its mode, scenario IDs, item IDs, and complete optimization input snapshot. Independent validation reads that same snapshot.

Approval is transactional: the proposal must still be independently valid, be based on the current approved version, and retain exactly the scenario items recorded in its snapshot. The approval transaction promotes its timetable version, archives the former current version, consumes only those captured active items, and then deactivates a scenario only when it has no active items left. This prevents already-incorporated inputs from being projected a second time. Rejection never consumes inputs or changes the approved timetable. A proposal can only be claimed once for approval; a second or concurrent request receives `409`.

## Run tests

From the project root with the virtual environment activated:

```powershell
python -m pytest -q
```

Tests cover the independent validator, API startup, seed data, selected-versus-aggregate scenario isolation, approval/rejection lifecycle behavior, snapshot preservation, signed-auth enforcement, and file-backed SQLite approval claims. CP-SAT engine tests are skipped explicitly when OR-Tools is unavailable. **Do not count skipped solver tests as proof that optimization was executed.**

## Functional walkthrough

1. Open **Disruptions & Rescheduling** and apply a train delay or a time-specific platform closure; scenario templates first populate the editor, then apply the edited first item plus any remaining items in the selected multi-item template.
2. Verify that Overview KPIs/events, Platform Availability, Live Station, the timetable projection, and conflict list update from the API. Remove an individual scenario item, restore it with Undo, or deactivate and restore an entire scenario. The approved timetable stays separate and unchanged.
3. Open **Proposal Review** and select **Generate revised timetable**. The backend applies delay inputs, runs CP-SAT, persists the solver status/objective, and independently validates any returned schedule.
4. Inspect the current-vs-proposed table, reasons, objective metrics and validation findings.
5. Approve only an independently validated proposal with zero hard violations. Rejection records a reason and leaves the current approved version intact. An alternative request must include a structured instruction/preference; it is run through CP-SAT again.
6. Open **Validation & Audit** to review stored validation reports and the event timeline.
7. Use **AI Voice Assistant** to test typed instruction examples. Browser speech recognition is optional; the local rule-based adapter must be reviewed/confirmed before saving, and it never assigns a platform itself.

## State and approval semantics

- `TimetableVersion.status = CURRENT` is the source of truth for the approved timetable. A proposal gets its own immutable version record with status `PROPOSED`, `INVALID`, `REJECTED`, or eventually `CURRENT`.
- Applying a scenario creates persisted disruptions/instructions and updates the **scenario projection** shown around the app. It does **not** edit the current approved schedule.
- CP-SAT generates a proposal against either one explicitly selected scenario or an explicitly requested aggregate set of active inputs. The complete input snapshot and objective are saved with the proposal.
- The independent validator re-checks assignment completeness, allowed platforms, overlaps, minimum separation, closures, horizon bounds, valid times, and mandatory instructions. The approval API enforces validation and rejects stale proposals if the current version changed.
- The SQLite transaction that approves a proposal archives the previous version, promotes the proposal version, marks the proposal approved, and records an audit event together.
- Simulation time advances locally while resumed. The control buttons can pause/resume, reset to 10:12, manually advance five minutes, and change the simulated speed. At 12:00 it pauses.

## API overview

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | API and simulation health |
| GET | `/api/station`, `/api/dashboard` | Station and overview state |
| GET | `/api/trains`, `/api/platforms` | Seeded train/platform catalogue and platform status |
| GET | `/api/timetable/current` | Approved timetable version |
| GET | `/api/timetable/effective` | Approved timetable projected through active disruption inputs |
| GET | `/api/timetable/proposals`, `/api/schedules/proposals` | Proposal register |
| GET | `/api/schedules/proposals/{id}` | Proposal detail and persisted validation |
| GET | `/api/conflicts`, `/api/events`, `/api/audit` | Conflicts and event/audit views |
| GET | `/api/scenarios`, `/api/scenarios/{id}` | Scenario state |
| POST | `/api/scenarios` | Create and apply disruptions/instructions |
| DELETE | `/api/scenarios/{id}` | Deactivate scenario; approved schedule remains unchanged |
| POST | `/api/scenarios/{id}/restore` | Undo a scenario deactivation |
| DELETE/POST | `/api/scenarios/{id}/disruptions/{disruption_id}` and `/restore` | Remove or restore an individual disruption |
| DELETE/POST | `/api/scenarios/{id}/instructions/{instruction_id}` and `/restore` | Remove or restore an individual instruction |
| POST | `/api/schedules/optimize` | Run OR-Tools CP-SAT and independent validation |
| POST | `/api/schedules/proposals/{id}/validate` | Re-run independent validation against the stored input snapshot |
| POST | `/api/schedules/proposals/{id}/approve` | Promote validated, current-base proposal atomically |
| POST | `/api/schedules/proposals/{id}/reject` | Reject with reason; preserve current version |
| POST | `/api/schedules/proposals/{id}/alternative` | Add structured station-master requirement and run CP-SAT again |
| GET/PATCH | `/api/simulation` | Read/update simulated clock state |
| GET | `/api/validation/history` | Persisted validation-run history |
| GET | `/api/assistant/context` | Current scenario/timetable context |
| POST | `/api/assistant/interpret`, `/api/assistant/confirm` | Rule-based parse followed by explicit confirmation |

FastAPI generates the detailed request/response schemas in `/docs`.

## Reference images

The five supplied image references and UX concept are included under `reference-ui/` so a team can compare the implementation against the initial concepts. The original screenshots may show the old prototype name; the application UI is branded **RailSync**.

## Known limitations

- OR-Tools was not installed in the authoring workspace because package-index networking was unavailable. The CP-SAT implementation is included and the dependency is declared, but the solver itself could not be executed here. Install `requirements.txt`, run the solver tests, and verify `/api/schedules/optimize` before presenting it as a tested optimization result.
- The provided station, trains, closure/delay events and timetable are fictional. No live GPS, railway signalling, live timetable, production identity or external LLM service is connected.
- The local rule-based assistant understands a small set of explicit patterns and returns a safe unsupported response for other instructions. It is not a general language model.
- `create_all` initializes the local schema for this hackathon build. If the schema changes during development, back up or remove the local demo database and restart to reseed; this is not a production migration strategy.
- P1 did not add columns, so no database migration is required for this release. Future schema changes require an explicit SQLite migration; `create_all()` does not upgrade an existing database.
