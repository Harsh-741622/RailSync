# RailSync — UI/UX Concept (for team review)

All data is fictional and illustrative. Screens are concept mockups, not a working product.

## Navigation
Left sidebar, fixed: Overview · Live Station · Timetable · Disruptions · Rescheduling · Validation & Audit · AI Voice Assistant.
Top bar on every screen: RailSync + subtitle, Central Junction, SIMULATION MODE · FICTIONAL STATION DATA badge, simulated clock.

## Screens
1. **Overview** (01-dashboard) — 6 KPI tiles, platform strip P1–P5, upcoming trains, event feed. Goal: station state in under 5 seconds.
2. **Live Station** (02-live-station) — schematic tracks, approach left / departure right, trains as labelled capsules, closures hatched red, conflicts outlined red, reservations dashed. Simulation controls on top.
3. **Timetable & Conflicts** (03-timetable-conflicts) — Gantt 09:00–12:00 above, sortable table below, conflict list on the right split into Hard / Warning / Preference.
4. **Disruptions & Rescheduling** (04-disruptions-rescheduling) — forms on the left, scenario cards in the middle, active disruptions on the right; GENERATE REVISED TIMETABLE with a 3-step progress bar (collect → schedule → validate).
5. **Proposal Review** (05-proposal-comparison) — current vs proposed tables side by side, changed cells highlighted, reasons, before/after metrics, validator checklist, Approve / Reject / Request Alternative.
6. **Operations Assistant** (06-voice-assistant) — mic and voice states on the left, transcript with structured "interpreted instruction" confirm cards in the middle, summary + alerts on the right, rejection-reason dialog.

## Timetable states (one visual language everywhere)
| State | Treatment |
|---|---|
| Current / Approved | Solid green outline chip "CURRENT · Approved vN" |
| Proposed | Blue dashed outline "PROPOSAL #N" |
| Validated | Solid green chip "VALIDATED · 0 hard violations" (only after the validator passes) |
| Awaiting approval | Amber chip |
| Invalid / No feasible schedule | Red chip, approve button disabled |

## Key design decisions
- The assistant never shows platform assignments as its own decision: it shows a structured instruction card that must be confirmed, and proposal cards come from the scheduler + validator.
- "Not operational until approved by station master" sits next to the decision buttons.
- Colors: navy/charcoal base; cyan = live or selected; amber = warning/delay; red = hard conflict/closure; green = validated/approved.
- Typography: clean sans-serif for labels, monospace for all times and train numbers so columns line up.

## Fix before build (mockup inconsistencies from image generation)
- Train names, dates and station labels vary between screens; standardize on one dataset (Central Junction, 18 trains, 09:00–12:00).
- Screen 6 has a different sidebar; use the 7-item sidebar from Screen 1.
- Screen 3 shows "Live" and IST; replace with "Simulated time".
