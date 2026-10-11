export type TimetableMoment = { arrival_min?: number | null; departure_min?: number | null };
export type TrainMotion = { phase: 'APPROACHING' | 'AT PLATFORM' | 'DEPARTING' | 'OUT OF VIEW'; position: number; visible: boolean };

/** Keep pre-arrival movement in the approach region; platform occupancy starts at arrival. */
export function trainMotion(entry: Required<Pick<TimetableMoment, 'arrival_min' | 'departure_min'>>, minute: number): TrainMotion {
  const arrival = Number(entry.arrival_min);
  const departure = Number(entry.departure_min);
  if (minute < arrival - 20) return { phase: 'OUT OF VIEW', position: -16, visible: false };
  if (minute < arrival) return { phase: 'APPROACHING', position: 8 + ((minute - (arrival - 20)) / 20) * 26, visible: true };
  // Occupancy uses [arrival, departure), matching validator and closure checks.
  if (minute < departure) return { phase: 'AT PLATFORM', position: 44, visible: true };
  if (minute <= departure + 20) return { phase: 'DEPARTING', position: 44 + ((minute - departure) / 20) * 28, visible: true };
  return { phase: 'OUT OF VIEW', position: 108, visible: false };
}

/**
 * Begin beside the first real arrival, aligned to a five-minute display tick.
 * A fallback keeps the empty-data state deterministic without inventing trains.
 */
export function initialSimulationMinute(entries: TimetableMoment[], fallback = 0): number {
  const arrivals = entries
    .map(entry => Number(entry.arrival_min))
    .filter(minute => Number.isFinite(minute) && minute >= 0);
  if (!arrivals.length) return fallback;
  return Math.floor(Math.min(...arrivals) / 5) * 5;
}

/** The renderer keeps a final service visible through its departure animation. */
export function simulationHorizon(entries: TimetableMoment[], fallback = 180): number {
  const departures = entries
    .map(entry => Number(entry.departure_min))
    .filter(minute => Number.isFinite(minute) && minute >= 0);
  return Math.max(fallback, ...(departures.length ? departures.map(minute => minute + 20) : []));
}

export function simulationWindow(entries: TimetableMoment[], closures: Array<{ start_min?: number; end_min?: number }>, fallbackStart = 0, fallbackEnd = 180): { start: number; end: number } {
  const closureEnds = closures.map(closure => Number(closure.end_min)).filter(minute => Number.isFinite(minute) && minute >= fallbackStart);
  return { start: fallbackStart, end: Math.max(simulationHorizon(entries, fallbackEnd), ...closureEnds) };
}

export function isClosureActive(closure: { start_min: number; end_min: number }, minute: number): boolean {
  return closure.start_min <= minute && minute < closure.end_min;
}
