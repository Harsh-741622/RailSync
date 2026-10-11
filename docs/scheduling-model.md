# RailSync CP-SAT model and validation rules

## Variables and time domain

Times are integer minutes after 09:00 in the inclusive three-hour demo horizon. Each train has a base arrival/departure taken from the current approved timetable. Active train-delay disruptions shift both by the specified scenario delay before optimization. Planned dwell duration is fixed.

For each train `i` and platform `p`, the model creates a Boolean variable `x[i,p]`, true when the train uses that platform. Variables for incompatible platforms are constrained to zero; each train must use exactly one member of its allowed set. `arrival[i]` is the modelled start time and `extra_delay[i] >= 0` records optimizer-added delay separately from scenario delay. `departure[i] = arrival[i] + planned_dwell[i]` is implicit in the interval end.

## Hard constraints

1. **Exactly one allowed platform:** sum of assignment Booleans over each train's allowed platforms equals one.
2. **Time horizon:** modelled occupancy lies inside 09:00–12:00. If a shifted base arrival cannot fit, the model becomes infeasible rather than fabricating an out-of-horizon time.
3. **No overlapping occupancy:** optional occupancy intervals are placed on each assigned platform and `NoOverlap` is applied.
4. **Minimum clearance:** separate optional intervals extended by the configured gap enforce `departure + gap <= next arrival` for any two consecutive trains on a platform. The default gap is five minutes.
5. **Closures:** fixed closure intervals are added to occupancy no-overlap constraints. Overlapping closure records are merged per platform first, and closures apply only during their specified interval.
6. **Mandatory station-master platform requirements:** the selected platform Boolean is forced true. An incompatible, unknown, closed, or conflicting mandatory requirement can make the full model infeasible; it is not silently downgraded.

Soft preferences use Boolean miss variables. They affect the objective only and never outweigh hard constraints.

## Objective

The model minimizes a weighted integer objective:

`total_extra_delay * delay_weight + platform_changes * platform_weight + soft_preference_misses`

Let `n` be train count and `m` soft-preference count. `platform_weight = m + 1`; `delay_weight = (n + 1) * (m + 1)`. One minute of extra delay therefore costs more than the maximum possible combination of lower-priority platform-change and preference penalties. Hard constraints are model constraints and cannot be traded away by objective weights.

The solver uses a configurable interactive time limit, a single worker, and a fixed seed for reproducibility. Result status is returned honestly as `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, or `UNKNOWN`. A `FEASIBLE` result is not described as proven optimal.

## Independent validator

`backend/services/validator.py` does not inspect the solver model or trust solver status. It inspects the returned timetable using ordinary Python collections and checks missing/duplicate/unknown train rows, unknown or incompatible platforms, invalid/out-of-horizon times, closure overlaps, overlapping occupancies, minimum separation and mandatory platform requirements. It returns `PASS` only when hard-violation count is zero. The approval endpoint additionally requires the proposal to be in `AWAITING_APPROVAL`, a valid validation snapshot, and the same current base timetable version used to optimize.

## Infeasibility and station-master review

When CP-SAT proves infeasibility, no entries are persisted as a valid schedule. The proposal records the solver status and diagnostics, with likely affected trains/platforms where the hard instruction or closure overlap makes them identifiable. The station master can edit/deactivate a scenario or add a structured hard instruction/soft preference and request another run. The alternate is a fresh optimization, not a post-hoc platform-number rotation.
