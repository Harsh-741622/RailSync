import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Activity, AlertOctagon, AlertTriangle, ArrowDownRight, ArrowRight, AudioLines, BadgeCheck, Bell,
  CalendarClock, Check, CheckCircle2, ChevronDown, ChevronRight, Clock3, FileCheck2, FileClock,
  Filter, Gauge, GitCompareArrows, Layers3, LayoutDashboard, ListChecks, MapPin, Menu, Mic, Pause,
  Play, Plus, RefreshCw, Search, Send, Settings2, ShieldCheck, Siren, SlidersHorizontal, TrainFront,
  Trash2, X, Zap, ArrowLeftRight, CircleHelp, ClipboardList, Volume2, LockKeyhole, WandSparkles,
} from 'lucide-react';
import { api, del, patch, post, postAudio } from './api';
import { initialSimulationMinute, isClosureActive, simulationHorizon, simulationWindow, trainMotion } from './simulation';

type Page = 'Overview' | 'Live Station' | 'Timetable' | 'Disruptions & Rescheduling' | 'Proposal Review' | 'Validation & Audit' | 'AI Voice Assistant';
type PlatformSummary = {
  id: string;
  status: 'CLOSED' | 'OCCUPIED' | 'RESERVED' | 'FREE';
  train_id: string | null;
};
const NAV: { label: Page; icon: any }[] = [
  { label: 'Overview', icon: LayoutDashboard },
  { label: 'Live Station', icon: TrainFront },
  { label: 'Timetable', icon: CalendarClock },
  { label: 'Disruptions & Rescheduling', icon: AlertTriangle },
  { label: 'Proposal Review', icon: GitCompareArrows },
  { label: 'Validation & Audit', icon: FileCheck2 },
  { label: 'AI Voice Assistant', icon: AudioLines },
];
const fmt = (m: number | null | undefined) => {
  if (m === null || m === undefined || Number.isNaN(Number(m))) return '—';
  const t = 9 * 60 + Number(m); return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
};
const errText = (e: unknown) => e instanceof Error ? e.message : 'Unexpected error';
const statusClass = (s: string) => String(s || '').toLowerCase().replaceAll(' ', '-').replaceAll('·', '').replaceAll('_', '-');

export default function App() {
  const [page, setPage] = useState<Page>('Overview');
  const [dashboard, setDashboard] = useState<any>(null);
  const [station, setStation] = useState<any>(null);
  const [platforms, setPlatforms] = useState<any[]>([]);
  const [trains, setTrains] = useState<any[]>([]);
  const [timetable, setTimetable] = useState<any>(null);
  const [effective, setEffective] = useState<any>(null);
  const [conflicts, setConflicts] = useState<any>({ items: [], hard_count: 0, warning_count: 0 });
  const [scenarios, setScenarios] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [proposals, setProposals] = useState<any[]>([]);
  const [proposalDetail, setProposalDetail] = useState<any>(null);
  const [validationHistory, setValidationHistory] = useState<any[]>([]);
  const [audit, setAudit] = useState<any[]>([]);
  const [simulation, setSimulation] = useState<any>({ clock_min: 5, clock: '09:05', paused: false, speed: 1, initial_clock_min: 5, horizon_end: 180 });
  const [simulationLoopStart, setSimulationLoopStart] = useState(5);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const notify = useCallback((text: string, type: 'success' | 'error' | 'info' = 'success') => {
    setNotice({ text, type });
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(null), 6000);
  }, []);

  const refresh = useCallback(async (showLoader = false) => {
    if (showLoader) setLoading(true);
    const requests = await Promise.allSettled([
      api('/dashboard'), api('/station'), api('/platforms'), api('/trains'), api('/timetable/current'),
      api('/timetable/effective'), api('/conflicts'), api('/scenarios'), api('/events?limit=12'),
      api('/schedules/proposals'), api('/validation/history'), api('/audit?limit=100'), api('/simulation'),
    ]);
    const get = (i: number) => requests[i].status === 'fulfilled' ? requests[i].value : null;
    if (get(0)) setDashboard(get(0));
    if (get(1)) setStation(get(1));
    if (get(2)) setPlatforms(get(2));
    if (get(3)) setTrains(get(3));
    if (get(4)) setTimetable(get(4));
    if (get(5)) setEffective(get(5));
    if (get(6)) setConflicts(get(6));
    if (get(7)) setScenarios(get(7));
    if (get(8)) setEvents(get(8));
    if (get(9)) setProposals(get(9));
    if (get(10)) setValidationHistory(get(10));
    if (get(11)) setAudit(get(11));
    if (get(12)) setSimulation(get(12));
    const failed = requests.find(r => r.status === 'rejected') as PromiseRejectedResult | undefined;
    if (failed && showLoader) notify(`Backend connection issue: ${errText(failed.reason)}. Start the FastAPI server at localhost:8000.`, 'error');
    setLoading(false);
  }, [notify]);

  useEffect(() => { refresh(true); }, []); // load the single persisted station state
  useEffect(() => {
    const onNavigate = (event: Event) => {
      const target = (event as CustomEvent<Page>).detail;
      if (NAV.some(item => item.label === target)) setPage(target);
    };
    window.addEventListener('railsync-navigate', onNavigate);
    return () => window.removeEventListener('railsync-navigate', onNavigate);
  }, []);
  useEffect(() => {
    if (page !== 'Live Station' || simulation?.paused) return;
    const timer = setInterval(async () => {
      try {
        const next = await patch('/simulation', { advance_minutes: 1, loop_start_min: simulationLoopStart });
        setSimulation(next);
        if (next.replaying) {
          notify(`Timetable replay started at ${next.initial_clock || fmt(simulationLoopStart)} after the final service completed.`, 'info');
          await refresh(false);
          setSimulation(next); // Preserve the brief, visible replay state after the refresh.
        }
      } catch { /* connection errors are surfaced by explicit refresh/actions */ }
    }, 10000);
    return () => clearInterval(timer);
  }, [page, simulation?.paused, simulation?.speed, simulationLoopStart, refresh, notify]);

  const handle = async (action: () => Promise<any>, success?: string, refreshAfter = true) => {
    setBusy(true);
    try {
      const result = await action();
      if (success) notify(success, 'success');
      if (refreshAfter) await refresh(false);
      return result;
    } catch (e) {
      notify(errText(e), 'error');
      return null;
    } finally { setBusy(false); }
  };

  const openProposal = async (id: number) => {
    const result = await handle(() => api(`/schedules/proposals/${id}`), undefined, false);
    if (result) setProposalDetail(result);
  };

  const currentProposal = proposalDetail || (proposals.length ? proposals[0] : null);
  const currentProposalState = currentProposal?.state || '';
  const approvedEntries = timetable?.entries || [];
  const projectedEntries = effective?.entries || approvedEntries;

  const pageContent = () => {
    if (loading && !dashboard) return <div className="loading-screen"><div className="loading-orbit"><TrainFront size={32} /></div><h2>Connecting to RailSync</h2><p>Loading the fictional Central Junction state…</p></div>;
    switch (page) {
      case 'Overview': return <Overview dashboard={dashboard} platforms={platforms} entries={projectedEntries} events={events} conflicts={conflicts} go={setPage} refresh={() => refresh(false)} />;
      case 'Live Station': return <LiveStation approvedEntries={projectedEntries} approvedVersionId={timetable?.version_id} scenarioClosures={effective?.closures || []} proposals={proposals} simulation={simulation} doAction={handle} notify={notify} onTimelineChange={setSimulationLoopStart} />;
      case 'Timetable': return <Timetable entries={projectedEntries} approvedEntries={approvedEntries} closures={effective?.closures || []} conflicts={conflicts} go={setPage} />;
      case 'Disruptions & Rescheduling': return <Disruptions trains={trains} platforms={platforms} scenarios={scenarios} doAction={handle} busy={busy} notify={notify} />;
      case 'Proposal Review': return <ProposalReview current={timetable} proposals={proposals} proposal={currentProposal} selectProposal={openProposal} doAction={handle} busy={busy} notify={notify} />;
      case 'Validation & Audit': return <ValidationAudit history={validationHistory} audit={audit} proposals={proposals} />;
      case 'AI Voice Assistant': return <AssistantPage notify={notify} refresh={refresh} go={setPage} trains={trains} proposals={proposals} audit={audit} />;
    }
  };

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><TrainFront size={27} strokeWidth={2.5} /></div><div><div className="brand-name">Rail<span>Sync</span></div><div className="brand-sub">Railway Disruption Simulator</div></div></div>
      <div className="station-chip"><MapPin size={16} /><span>Central Junction</span></div>
      <div className="nav-label">OPERATIONS</div>
      <nav className="nav-list">{NAV.map(item => {
        const Icon = item.icon;
        return <button key={item.label} className={`nav-item ${page === item.label ? 'active' : ''}`} onClick={() => setPage(item.label)}><Icon size={19} /><span>{item.label}</span>{item.label === 'Timetable' && conflicts?.hard_count > 0 ? <i className="nav-count">{conflicts.hard_count}</i> : null}</button>;
      })}</nav>
      <div className="sidebar-bottom"><div className="online-indicator"><span className="dot green" />Simulation engine ready</div><div className="sidebar-sub">Local fictional data · v1.0.0</div><div className="safety-mini"><ShieldCheck size={17} /><span>Not connected to railway operations</span></div></div>
    </aside>

    <main className="main-area">
      <header className="topbar">
        <div className="page-context"><div className="crumb">RAILSYNC <ChevronRight size={13} /> OPERATIONS</div><h1>{page}</h1><p>{pageSubtitle(page)}</p></div>
        <div className="topbar-right"><div className="simulation-badge"><span className="pulse-dot" />SIMULATION MODE <b>·</b> FICTIONAL DATA</div><div className="clock-block"><Clock3 size={20} /><div><strong>{simulation?.clock || dashboard?.clock || '10:12'}</strong><small>Simulated station time</small></div></div><button className="icon-button assistant-shortcut" title="Open Operations Assistant" onClick={() => setPage('AI Voice Assistant')}><Mic size={18} /></button><button className="icon-button" title="Refresh all station data" onClick={() => handle(() => refresh(false), 'Station state refreshed.', false)}><RefreshCw size={17} /></button></div>
      </header>
      {notice && <div className={`toast ${notice.type}`} role="status"><span className="toast-mark">{notice.type === 'error' ? <AlertOctagon size={17} /> : notice.type === 'success' ? <CheckCircle2 size={17} /> : <CircleHelp size={17} />}</span><span>{notice.text}</span><button onClick={() => setNotice(null)} aria-label="Dismiss notification"><X size={15} /></button></div>}
      <section className="page-body">{pageContent()}</section>
      <footer className="app-footer"><span>RailSync <b>·</b> Safer stations. Smoother journeys.</span><span><span className="dot green" /> Local simulation <b>·</b> All times are minutes within the 09:00–12:00 demo horizon</span></footer>
    </main>
  </div>;
}

function pageSubtitle(page: Page) {
  const subtitles: Record<Page, string> = {
    'Overview': 'Understand the station state at a glance.',
    'Live Station': 'Explore track occupancy and simulated train movements.',
    'Timetable': 'Inspect platform allocations, conflicts, and service intervals.',
    'Disruptions & Rescheduling': 'Apply fictional incidents and run constraint-based rescheduling.',
    'Proposal Review': 'Compare, validate, and decide on a revised timetable.',
    'Validation & Audit': 'Review independent checks and traceable operational decisions.',
    'AI Voice Assistant': 'Turn an instruction into a reviewable structured action.',
  };
  return subtitles[page];
}

function SectionHead({ icon: Icon, title, subtitle, right }: { icon: any; title: string; subtitle?: string; right?: ReactNode }) {
  return <div className="section-head"><div className="section-icon"><Icon size={19} /></div><div className="section-title"><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{right && <div className="section-right">{right}</div>}</div>;
}
function StatusPill({ status }: { status: string }) { return <span className={`status-pill ${statusClass(status)}`}>{status}</span>; }
function Empty({ title, body }: { title: string; body: string }) { return <div className="empty-state"><div className="empty-icon"><FileClock size={22} /></div><b>{title}</b><p>{body}</p></div>; }

function Overview({ dashboard, platforms, entries, events, conflicts, go, refresh }: any) {
  const kpis = [
    { label: 'Scheduled today', value: dashboard?.scheduled_today ?? '—', suffix: 'trains', icon: TrainFront, tone: 'cyan' },
    { label: 'Approaching', value: dashboard?.approaching ?? '—', suffix: 'next 20 min', icon: ArrowRight, tone: 'cyan' },
    { label: 'Delayed', value: dashboard?.delayed ?? '—', suffix: 'trains with delay inputs', icon: Clock3, tone: 'amber' },
    { label: 'Closures now', value: dashboard?.closures ?? '—', suffix: 'platforms', icon: LockKeyhole, tone: 'amber' },
    { label: 'Hard conflicts', value: conflicts?.hard_count ?? '—', suffix: 'constraint violations', icon: AlertTriangle, tone: 'red' },
    { label: 'Latest validation', value: dashboard?.validation_status ?? 'PENDING', suffix: `approved v${dashboard?.current_version ?? '—'}`, icon: ShieldCheck, tone: dashboard?.validation_status === 'PASS' ? 'green' : 'amber' },
  ];
  const upcoming = [...(entries || [])].sort((a: any, b: any) => a.arrival_min - b.arrival_min).slice(0, 7);
  const fmtDelay = (e: any) => (e.scenario_delay_min || e.additional_delay_min) ? `+${e.scenario_delay_min || e.additional_delay_min} min` : '—';
  return <div className="page-stack">
    <div className="page-intro"><div><div className="eyebrow">STATION OVERVIEW <span className="line" /></div><h2>Good operations start with <span>visibility.</span></h2><p>Monitor train movement, platform availability, and active scenario effects in one place.</p></div><button className="button secondary" onClick={refresh}><RefreshCw size={15} /> Refresh station state</button></div>
    <div className="kpi-grid">{kpis.map(k => { const Icon = k.icon; return <div key={k.label} className={`kpi-card tone-${k.tone}`}><div className="kpi-top"><span>{k.label}</span><div className="kpi-icon"><Icon size={20} /></div></div><div className="kpi-value">{k.value}</div><div className="kpi-foot">{k.suffix}</div></div>; })}</div>
    <div className="panel platform-panel"><SectionHead icon={Layers3} title="Platform availability" subtitle="Status derived from the active scenario projection and simulated clock." right={<button className="text-link" onClick={() => go('Live Station')}>Open live station <ArrowRight size={15} /></button>} /><div className="platform-strip">{platforms.map((p: PlatformSummary) => <div className={`platform-card platform-${String(p.status).toLowerCase()}`} key={p.id}><div className="platform-card-top"><span className="platform-number">{p.id}</span><StatusPill status={p.status} /></div><div className="platform-symbol">{p.status === 'CLOSED' ? <LockKeyhole size={20} /> : p.status === 'OCCUPIED' ? <TrainFront size={22} /> : p.status === 'RESERVED' ? <Clock3 size={20} /> : <span className="dot green" />}</div><div className="platform-foot">{p.train_id ? `Train ${p.train_id}` : p.status === 'CLOSED' ? 'Unavailable in interval' : 'No train currently assigned'}</div></div>)}</div><div className="legend-row"><span><i className="dot green" />Free</span><span><i className="dot cyan" />Occupied</span><span><i className="dot amber" />Reserved</span><span><i className="dot red" />Closed / conflict</span></div></div>
    <div className="overview-bottom-grid"><div className="panel"><SectionHead icon={Menu} title="Upcoming arrivals & departures" subtitle="Scenario-adjusted view; the approved timetable remains versioned separately." right={<button className="text-link" onClick={() => go('Timetable')}>View timetable <ArrowRight size={15} /></button>} /><div className="table-wrap"><table><thead><tr><th>Train No.</th><th>Train name</th><th>Arrival</th><th>Departure</th><th>Platform</th><th>Scenario delay</th></tr></thead><tbody>{upcoming.map((r: any) => <tr key={r.train_id}><td className="mono bold">{r.train_id}</td><td>{r.name}</td><td className="mono">{fmt(r.arrival_min)}</td><td className="mono">{fmt(r.departure_min)}</td><td><span className="platform-tag">{r.platform_id}</span></td><td className={(r.scenario_delay_min || 0) > 0 ? 'text-amber mono' : 'muted mono'}>{fmtDelay(r)}</td></tr>)}</tbody></table>{!upcoming.length && <Empty title="No train entries" body="Check whether the backend seed ran successfully." />}</div></div>
      <div className="panel events-panel"><SectionHead icon={Zap} title="Recent events" subtitle="Auditable changes to simulation state." right={<button className="text-link" onClick={() => go('Validation & Audit')}>All events <ArrowRight size={15} /></button>} /><div className="event-list">{events.slice(0, 7).map((e: any, index: number) => <div className="event-row" key={e.id}><span className={`event-node node-${index % 4}`}><span /></span><div className="event-time mono">{new Date(e.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div><div className="event-copy"><b>{e.title}</b><p>{e.details?.title || e.details?.reason || e.details?.message || e.actor || 'Fictional simulation event'}</p></div></div>)}{!events.length && <Empty title="No events recorded" body="Scenario changes, validation and approvals will appear here." />}</div></div></div>
  </div>;
}

const SIMULATED_MINUTE_MS = 10_000;

function LiveStation({ approvedEntries, approvedVersionId, scenarioClosures, proposals, simulation, doAction, notify, onTimelineChange }: any) {
  const proposalChoices = useMemo(() => (proposals || []).filter((proposal: any) => proposal.version_id), [proposals]);
  const [displayMode, setDisplayMode] = useState('approved'); const [proposalPreview, setProposalPreview] = useState<any>(null);
  const [selectedSpeed, setSelectedSpeed] = useState(String(simulation?.speed || 1)); const [selectedTrain, setSelectedTrain] = useState<string | null>(null); const [seekClock, setSeekClock] = useState(fmt(Number(simulation?.clock_min ?? 5)));
  useEffect(() => { if (displayMode === 'approved') { setProposalPreview(null); return; } let cancelled = false; api(`/schedules/proposals/${displayMode.slice('proposal:'.length)}`).then(result => { if (!cancelled) setProposalPreview(result); }).catch(error => { if (!cancelled) { setProposalPreview(null); notify(errText(error), 'error'); } }); return () => { cancelled = true; }; }, [displayMode, notify]);
  useEffect(() => {
    const selectedProposal = proposalChoices.find((proposal: any) => `proposal:${proposal.id}` === displayMode);
    if (displayMode.startsWith('proposal:') && !selectedProposal) {
      // Approval removes this proposal from the preview list.  Keep the train
      // selection when its stable ID still exists in the newly approved table.
      setDisplayMode('approved'); setProposalPreview(null);
    }
    if (selectedProposal?.state === 'APPROVED' && selectedProposal.version_id === approvedVersionId) {
      setDisplayMode('approved'); setProposalPreview(null);
    }
  }, [displayMode, proposalChoices, approvedVersionId]);
  const entries = displayMode === 'approved' ? (approvedEntries || []) : (proposalPreview?.entries || []);
  const closures = displayMode === 'approved' ? (scenarioClosures || []) : (proposalPreview?.simulation_context?.closures || []);
  const initialMinute = useMemo(() => initialSimulationMinute(entries, Number(simulation?.initial_clock_min ?? 5)), [entries, simulation?.initial_clock_min]);
  const horizonEnd = useMemo(() => simulationHorizon(entries, Number(simulation?.horizon_end ?? 180)), [entries, simulation?.horizon_end]);
  const window = useMemo(() => simulationWindow(entries, closures, Number(simulation?.horizon_start ?? 0), horizonEnd), [entries, closures, simulation?.horizon_start, horizonEnd]);
  const modeLabel = displayMode === 'approved' ? 'Approved timetable' : proposalPreview?.state === 'APPROVED' ? `Proposal snapshot — approved (#${proposalPreview.id})` : proposalPreview ? `Proposal preview — not approved (#${proposalPreview.id})` : 'Loading proposal preview…';
  const [visibleMinute, setVisibleMinute] = useState(Number(simulation?.clock_min ?? 5)); const trainNodes = useRef<Map<string, HTMLButtonElement>>(new Map()); const frameRef = useRef<number | null>(null); const anchorRef = useRef({ minute: Number(simulation?.clock_min ?? 5), at: 0 }); const lastMinuteRef = useRef(-1);
  const entryMap = useMemo<Map<string, any>>(() => new Map<string, any>((entries || []).map((entry: any) => [entry.train_id, entry])), [entries]);
  const collisionOffset = useMemo(() => { const offsets = new Map<string, number>(); ['P1', 'P2', 'P3', 'P4', 'P5'].forEach(platform => { const lane = entries.filter((entry: any) => entry.platform_id === platform).sort((a: any, b: any) => a.arrival_min - b.arrival_min); const active: any[] = []; lane.forEach((entry: any) => { for (let index = active.length - 1; index >= 0; index -= 1) if (active[index].departure_min <= entry.arrival_min) active.splice(index, 1); offsets.set(entry.train_id, active.length); active.push(entry); }); }); return offsets; }, [entries]);
  useEffect(() => setSelectedSpeed(String(simulation?.speed || 1)), [simulation?.speed]);
  useEffect(() => setSeekClock(fmt(Number(simulation?.clock_min ?? initialMinute))), [simulation?.clock_min, initialMinute]);
  useEffect(() => {
    // Switching a source changes only the next replay/reset point.  It must not
    // restart the persisted clock—especially after approval promotes a preview.
    if (entries.length) onTimelineChange(initialMinute);
  }, [entries.length, initialMinute, onTimelineChange]);
  useEffect(() => {
    const startMinute = Number(simulation?.clock_min ?? initialMinute); anchorRef.current = { minute: startMinute, at: performance.now() }; lastMinuteRef.current = Math.floor(startMinute); setVisibleMinute(Math.floor(startMinute));
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
    if (simulation?.paused) return;
    const animate = (now: number) => {
      const current = Math.min(horizonEnd, anchorRef.current.minute + ((now - anchorRef.current.at) / SIMULATED_MINUTE_MS) * Number(simulation?.speed || 1));
      trainNodes.current.forEach((node, trainId) => { const entry = entryMap.get(trainId); if (!entry) return; const motion = trainMotion(entry, current); node.style.left = `${motion.position}%`; node.style.opacity = motion.visible ? '1' : '0'; node.style.pointerEvents = motion.visible ? 'auto' : 'none'; });
      const minute = Math.floor(current); if (minute !== lastMinuteRef.current) { lastMinuteRef.current = minute; setVisibleMinute(minute); }
      frameRef.current = requestAnimationFrame(animate);
    };
    frameRef.current = requestAnimationFrame(animate);
    return () => { if (frameRef.current) cancelAnimationFrame(frameRef.current); };
  }, [simulation?.clock_min, simulation?.paused, simulation?.speed, entryMap, horizonEnd, initialMinute]);
  const platformState = (platformId: string) => { const closure = closures.find((item: any) => item.platform_id === platformId && isClosureActive(item, visibleMinute)); const occupied = entries.find((entry: any) => entry.platform_id === platformId && entry.arrival_min <= visibleMinute && visibleMinute < entry.departure_min); const reserved = entries.find((entry: any) => entry.platform_id === platformId && visibleMinute < entry.arrival_min && entry.arrival_min <= visibleMinute + 20); return closure ? { status: 'CLOSED', closure } : occupied ? { status: 'OCCUPIED', entry: occupied } : reserved ? { status: 'RESERVED', entry: reserved } : { status: 'FREE' }; };
  const closureConflicts = useMemo(() => closures.flatMap((closure: any) => entries.filter((entry: any) => entry.platform_id === closure.platform_id && entry.arrival_min < closure.end_min && entry.departure_min > closure.start_min).map((entry: any) => ({ entry, closure }))), [entries, closures]);
  const conflictTrainIds = useMemo(() => new Set(closureConflicts.map((item: any) => item.entry.train_id)), [closureConflicts]);
  const nextMoves = useMemo(() => [...entries].filter((entry: any) => entry.departure_min > visibleMinute).sort((a: any, b: any) => a.arrival_min - b.arrival_min).slice(0, 8), [entries, visibleMinute]);
  const selected = selectedTrain ? entryMap.get(selectedTrain) : null; const selectedMotion = selected ? trainMotion(selected, visibleMinute) : null;
  const activeClosures = closures.filter((item: any) => isClosureActive(item, visibleMinute));
  const statusText = (entry: any) => { const motion = trainMotion(entry, visibleMinute); if (conflictTrainIds.has(entry.train_id)) return `${motion.phase} · closure conflict`; if (entry.scenario_delay_min > 0) return `${motion.phase} · +${entry.scenario_delay_min} min input`; if (entry.additional_delay_min > 0) return `${motion.phase} · +${entry.additional_delay_min} min optimizer`; return motion.phase; };
  const seek = () => {
    const parts = seekClock.split(':').map(Number); const minute = parts.length === 2 && parts.every(Number.isFinite) ? parts[0] * 60 + parts[1] - 9 * 60 : Number.NaN;
    if (!Number.isInteger(minute) || minute < window.start || minute > window.end) { notify(`Choose a time from ${fmt(window.start)} to ${fmt(window.end)}.`, 'error'); return; }
    void doAction(() => patch('/simulation', { seek_min: minute }), `Simulation moved to ${fmt(minute)}.`);
  };
  return <div className="page-stack live-simulation">
    <div className="page-intro"><div><div className="eyebrow">LIVE STATION <span className="line" /></div><h2>Central Junction <span>track view</span></h2><p>Illustrative movement is calculated from the central fictional timetable clock; it is not live railway tracking.</p></div><div className="live-clock"><Clock3 size={21} /><strong>{fmt(visibleMinute)}</strong><span>SIMULATED TIME</span></div></div>
    <div className="control-bar"><div className="control-group"><button className="button secondary" onClick={() => doAction(() => patch('/simulation', { paused: true }), 'Simulation paused.')} disabled={simulation?.paused}><Pause size={15} /> Pause</button><button className="button green-button" onClick={() => doAction(() => patch('/simulation', { paused: false }), 'Simulation resumed.')} disabled={!simulation?.paused}><Play size={15} /> Resume</button><button className="button secondary" onClick={() => doAction(() => patch('/simulation', { reset: true, start_min: initialMinute }), `Simulation reset to ${fmt(initialMinute)}.`)}><RefreshCw size={15} /> Reset</button></div><label className="live-source"><span>Timetable source</span><select value={displayMode} onChange={event => { setSelectedTrain(null); setDisplayMode(event.target.value); }}><option value="approved">Approved timetable</option>{proposalChoices.map((proposal: any) => <option value={`proposal:${proposal.id}`} key={proposal.id}>#{proposal.id} · v{proposal.version_id} · {proposal.state} · {proposal.created_at ? new Date(proposal.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'saved proposal'}</option>)}</select>{!proposalChoices.length ? <small>No persisted proposals with schedules are available.</small> : null}</label><div className="seek-control"><label>Inspect time<input aria-label="Simulation time" type="time" min={fmt(window.start)} max={fmt(window.end)} value={seekClock} onChange={event => setSeekClock(event.target.value)} /></label><button className="button secondary small" onClick={seek}>Seek</button></div><div className="speed-select"><span>Speed</span>{[1, 2, 5].map(speed => <button className={Number(selectedSpeed) === speed ? 'speed active' : 'speed'} key={speed} onClick={() => doAction(() => patch('/simulation', { speed }), `Simulation speed set to ${speed}x.`).then(() => setSelectedSpeed(String(speed)))}>{speed}x</button>)}</div><span className="sim-status"><span className={`dot ${simulation?.paused ? 'amber' : simulation?.replaying ? 'cyan' : 'green'}`} />{simulation?.paused ? 'Paused · positions frozen' : simulation?.replaying ? `Replaying · ${fmt(initialMinute)} restart` : 'Running · smooth view'}</span></div>
    <div className={`timetable-source-banner ${displayMode === 'approved' ? 'approved' : 'preview'}`}><BadgeCheck size={16} /><div><b>{modeLabel}</b><span>{displayMode === 'approved' ? 'Current approved entries are projected once through active scenarios. Closures remain visible and any overlap is flagged for review.' : `Persisted proposal entries, validation, and its exact closure snapshot are shown. ${proposalPreview?.validation?.summary || 'It has not been approved into the current timetable.'}`}</span></div></div>
    {simulation?.replaying ? <div className="simulation-replay-banner"><RefreshCw size={16} /><span>Final service completed; this fictional timetable is replaying from {fmt(initialMinute)}.</span></div> : null}
    {closureConflicts.length ? <div className="closure-conflict-warning"><AlertTriangle size={18} /><div><b>{closureConflicts.length} closure conflict{closureConflicts.length === 1 ? '' : 's'} in the selected timetable</b><p>{closureConflicts.slice(0, 3).map((item: any) => `Train ${item.entry.train_id} overlaps ${item.closure.platform_id} closure ${fmt(item.closure.start_min)}–${fmt(item.closure.end_min)}`).join(' · ')}. Re-optimize or review this timetable; the display has not moved any train.</p></div></div> : null}
    <div className="station-layout"><div className="station-diagram panel"><div className="diagram-header"><span>← Arrival approach</span><span>Illustrative platform movement</span><span>Departure →</span></div><div className="track-map">
      {['P1', 'P2', 'P3', 'P4', 'P5'].map((platformId, index) => { const state = platformState(platformId); const lane = entries.filter((entry: any) => entry.platform_id === platformId); return <div className={`track-lane simulation-lane ${state.status === 'CLOSED' ? 'lane-closed' : ''}`} key={platformId}><div className="track-left"><small>A{index + 1}</small><span className={`signal signal-${state.status.toLowerCase()}`} /></div><div className="rails"><span className="rail-line" /><span className="rail-line rail-low" /><div className="platform-label">{platformId} <small>{state.status}</small></div>{closures.filter((closure: any) => closure.platform_id === platformId).map((closure: any, closureIndex: number) => <div className={`closure-band ${isClosureActive(closure, visibleMinute) ? 'active' : ''}`} key={`${closure.start_min}-${closureIndex}`} style={{ left: `${Math.max(0, closure.start_min / horizonEnd * 100)}%`, width: `${Math.max(3, (closure.end_min - closure.start_min) / horizonEnd * 100)}%` }}>CLOSED · {fmt(closure.start_min)}–{fmt(closure.end_min)}</div>)}{lane.map((entry: any) => { const motion = trainMotion(entry, visibleMinute); const conflictsClosure = conflictTrainIds.has(entry.train_id); return <button type="button" key={entry.train_id} ref={node => { if (node) trainNodes.current.set(entry.train_id, node); else trainNodes.current.delete(entry.train_id); }} className={`train-capsule moving-capsule ${motion.phase === 'APPROACHING' ? 'approaching-capsule' : ''} ${entry.platform_changed ? 'changed' : ''} ${entry.scenario_delay_min > 0 || entry.additional_delay_min > 0 ? 'delayed' : ''} ${conflictsClosure ? 'closure-affected closure-conflict' : ''} ${selectedTrain === entry.train_id ? 'selected' : ''}`} aria-label={`Show details for train ${entry.train_id}`} onClick={() => setSelectedTrain(entry.train_id)} title={`${entry.train_id} · ${entry.name} · ${fmt(entry.arrival_min)}–${fmt(entry.departure_min)} · ${statusText(entry)}`} style={{ left: `${motion.position}%`, opacity: motion.visible ? 1 : 0, '--lane-offset': `${collisionOffset.get(entry.train_id) || 0}` } as any}><TrainFront size={14} /><b>{entry.train_id}</b><i>{conflictsClosure ? '!' : motion.phase === 'AT PLATFORM' ? '●' : '→'}</i></button>; })}</div><div className="track-right">D{index + 1}</div></div>; })}
    </div><div className="diagram-scale"><span>09:00</span><span>{fmt(Math.round(horizonEnd / 2))}</span><span>{fmt(horizonEnd)}</span></div><div className="diagram-legend"><span><i className="capsule-key" />Normal service</span><span><i className="legend-delay" />Delay input</span><span><i className="legend-selected" />Selected service</span><span><i className="legend-closed" />Closure interval</span><span><i className="legend-signal" />Live platform status</span></div>{!entries.length ? <Empty title="No timetable entries available" body="No approved or selected proposal timetable could be loaded for this view." /> : !entries.some((entry: any) => entry.arrival_min <= visibleMinute && visibleMinute < entry.departure_min) ? <div className="simulation-empty-state">No trains occupying platforms at this simulated time. {nextMoves[0] ? `Next arrival: ${nextMoves[0].train_id} at ${fmt(nextMoves[0].arrival_min)}.` : `The replay begins again at ${fmt(initialMinute)} after the final departure.`}</div> : null}</div>
      <div className="station-side"><div className="panel"><SectionHead icon={ArrowLeftRight} title="Next movements" subtitle={`Ordered by arrival in the ${displayMode === 'approved' ? 'approved' : 'proposal-preview'} timetable.`} /><div className="movement-table"><div className="movement-head"><span>Time</span><span>Train</span><span>Status</span><span>Platform</span></div>{nextMoves.map((entry: any) => <button className={`movement-row movement-button ${selectedTrain === entry.train_id ? 'active' : ''}`} key={entry.train_id} onClick={() => setSelectedTrain(entry.train_id)}><span className="mono">{fmt(entry.arrival_min)}</span><b>{entry.train_id}</b><span>{statusText(entry)}</span><span>{entry.platform_id}</span></button>)}{!nextMoves.length && <Empty title="No upcoming movements" body="All scheduled services are outside the current simulation window." />}</div></div><div className="panel train-inspector"><SectionHead icon={TrainFront} title="Selected train" subtitle="Choose a moving service or a row to inspect the displayed timetable." />{selected ? <div className="inspector-content"><b className="inspector-title">{selected.train_id} · {selected.name}</b><div className="inspector-grid"><span>Status</span><b className={conflictTrainIds.has(selected.train_id) ? 'text-red' : ''}>{statusText(selected)}</b><span>Platform</span><b>{selected.platform_id || 'Unavailable'}</b>{(selected.original_platform_id && selected.original_platform_id !== selected.platform_id) ? <><span>Original platform</span><b>{selected.original_platform_id}</b></> : null}<span>Arrival</span><b className="mono">{fmt(selected.arrival_min)}</b><span>Departure</span><b className="mono">{fmt(selected.departure_min)}</b>{(selected.original_arrival_min !== selected.arrival_min || selected.original_departure_min !== selected.departure_min) ? <><span>Original times</span><b className="mono">{fmt(selected.original_arrival_min)}–{fmt(selected.original_departure_min)}</b></> : null}<span>{selected.scenario_delay_min > 0 ? 'Delay input' : 'Optimizer delay'}</span><b className={(selected.scenario_delay_min > 0 || selected.additional_delay_min > 0) ? 'text-amber' : ''}>{selected.scenario_delay_min > 0 ? `+${selected.scenario_delay_min} min` : selected.additional_delay_min > 0 ? `+${selected.additional_delay_min} min` : 'None'}</b><span>Timetable source</span><b>{displayMode === 'approved' ? 'Approved' : 'Unapproved preview'}</b></div></div> : <div className="inspector-empty">Select a visible train or an upcoming movement to see its service name, times, platform, and source timetable.</div>}</div><div className="panel station-status"><SectionHead icon={Activity} title="Station status" /><div className="status-line"><span>Platforms in service</span><b>{['P1','P2','P3','P4','P5'].filter(platformId => platformState(platformId).status !== 'CLOSED').length} / 5</b></div><div className="status-line"><span>Scheduled services</span><b>{entries.length}</b></div><div className="status-line"><span>Active closures now</span><b className="text-amber">{activeClosures.length}</b></div><div className="status-line"><span>Closure conflicts</span><b className={closureConflicts.length ? 'text-red' : 'text-green'}>{closureConflicts.length}</b></div><div className="status-line"><span>Simulation clock</span><b className="mono">{fmt(visibleMinute)}</b></div><div className="status-callout"><ShieldCheck size={16} /> Positions are calculated from this selected timetable, not live GPS.</div></div></div></div>
  </div>;
}

function Timetable({ entries, approvedEntries, closures, conflicts, go }: any) {
  const [search, setSearch] = useState(''); const [platform, setPlatform] = useState('ALL'); const [status, setStatus] = useState('ALL'); const [sort, setSort] = useState('arrival'); const [severity, setSeverity] = useState('ALL');
  const filtered = useMemo(() => [...entries].filter((e: any) => `${e.train_id} ${e.name}`.toLowerCase().includes(search.toLowerCase()) && (platform === 'ALL' || e.platform_id === platform) && (status === 'ALL' || (status === 'DELAYED' ? e.scenario_delay_min > 0 : status === 'ON TIME' ? !e.scenario_delay_min : true))).sort((a: any, b: any) => sort === 'arrival' ? a.arrival_min - b.arrival_min : sort === 'departure' ? a.departure_min - b.departure_min : String(a.train_id).localeCompare(String(b.train_id))), [entries, search, platform, status, sort]);
  const items = (conflicts?.items || []).filter((c: any) => severity === 'ALL' || c.severity === severity);
  const priorMap = new Map((approvedEntries || []).map((e: any) => [e.train_id, e]));
  return <div className="page-stack"><div className="page-intro"><div><div className="eyebrow">SCHEDULE INTELLIGENCE <span className="line" /></div><h2>Timetable <span>& conflicts</span></h2><p>The Gantt and table use the active scenario projection; compare with the immutable approved timetable using the row indicators.</p></div><button className="button primary" onClick={() => go('Disruptions & Rescheduling')}><WandSparkles size={16} /> Reschedule trains</button></div>
    <div className="filter-bar"><label className="search-field"><Search size={16} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search train number or name…" /></label><label className="filter-select"><span>Platform</span><select value={platform} onChange={e => setPlatform(e.target.value)}><option value="ALL">All</option>{['P1','P2','P3','P4','P5'].map(p => <option key={p}>{p}</option>)}</select></label><label className="filter-select"><span>Status</span><select value={status} onChange={e => setStatus(e.target.value)}><option>ALL</option><option>DELAYED</option><option>ON TIME</option></select></label><label className="filter-select"><span>Sort by</span><select value={sort} onChange={e => setSort(e.target.value)}><option value="arrival">Arrival</option><option value="departure">Departure</option><option value="train">Train number</option></select></label><button className="button secondary" onClick={() => { setSearch(''); setPlatform('ALL'); setStatus('ALL'); setSort('arrival'); }}><Filter size={15} /> Reset</button></div>
    <div className="panel gantt-panel"><SectionHead icon={CalendarClock} title="Platform occupation · 09:00–12:00" subtitle={`${filtered.length} train services match current filters.`} right={<span className="legend-inline"><i className="bar-key" />Scenario projection <i className="bar-key muted-bar" />Unchanged view</span>} /><div className="gantt-scroll"><div className="gantt-chart"><div className="gantt-time-header"><div className="gantt-platform-label">PLATFORM</div>{[0,15,30,45,60,75,90,105,120,135,150,165,180].map(m => <div className="gantt-tick" key={m}>{fmt(m)}</div>)}</div>{['P1','P2','P3','P4','P5'].map(p => <div className="gantt-lane" key={p}><div className="gantt-platform-label">{p}</div><div className="gantt-bars">{closures.filter((c: any) => c.platform_id === p).map((c: any, ci: number) => <div key={`closure-${ci}`} className="closure-gantt" style={{ left: `${c.start_min / 180 * 100}%`, width: `${Math.max(1.5, (c.end_min - c.start_min) / 180 * 100)}%` }} title={`${p} closed ${fmt(c.start_min)}–${fmt(c.end_min)}`}>CLOSED</div>)}{filtered.filter((e: any) => e.platform_id === p).map((e: any) => { const prior: any = priorMap.get(e.train_id); const changed = prior && (prior.arrival_min !== e.arrival_min || prior.platform_id !== e.platform_id); return <div key={e.train_id} className={`gantt-bar ${changed ? 'bar-changed' : ''} ${e.scenario_delay_min > 0 ? 'bar-delayed' : ''}`} style={{ left: `${e.arrival_min / 180 * 100}%`, width: `${Math.max(2.7, (e.departure_min - e.arrival_min) / 180 * 100)}%` }} title={`${e.train_id} ${fmt(e.arrival_min)}-${fmt(e.departure_min)}`}>{e.train_id}</div>; })}</div></div>)}</div></div></div>
    <div className="panel"><SectionHead icon={ListChecks} title="Train service table" subtitle="Filter and sort controls above apply to this table and Gantt." right={<span className="muted small-text">{filtered.length} shown</span>} /><div className="table-wrap"><table><thead><tr><th>Train No.</th><th>Name</th><th>Arrival</th><th>Departure</th><th>Platform</th><th>Delay input</th><th>Assignment</th><th>Check</th></tr></thead><tbody>{filtered.map((e: any) => { const prior: any = priorMap.get(e.train_id); const moved = prior && prior.platform_id !== e.platform_id; const shifted = prior && (prior.arrival_min !== e.arrival_min || prior.departure_min !== e.departure_min); return <tr key={e.train_id}><td className="mono bold">{e.train_id}</td><td>{e.name}</td><td className={`mono ${shifted ? 'text-amber' : ''}`}>{fmt(e.arrival_min)}</td><td className="mono">{fmt(e.departure_min)}</td><td><span className="platform-tag">{e.platform_id}</span></td><td className="mono">{e.scenario_delay_min ? `+${e.scenario_delay_min} min` : '—'}</td><td>{moved ? <span className="mini-badge info">Changed</span> : <span className="mini-badge muted">Same</span>}</td><td>{(conflicts?.items || []).some((c: any) => c.train_ids?.includes(e.train_id)) ? <span className="mini-badge danger">Conflict</span> : shifted ? <span className="mini-badge warning">Review</span> : <span className="mini-badge success">OK</span>}</td></tr>; })}</tbody></table>{!filtered.length && <Empty title="No matching trains" body="Try a different search or reset the filters." />}</div></div>
    <div className="panel conflict-panel"><SectionHead icon={AlertTriangle} title="Conflict list" subtitle="Hard violations block approval. Warnings are visible and should be reviewed." right={<select className="compact-select" value={severity} onChange={e => setSeverity(e.target.value)}><option value="ALL">All severities</option><option value="HARD">Hard</option><option value="WARNING">Warnings</option></select>} /><div className="conflict-list">{items.map((c: any) => <div className={`conflict-row severity-${String(c.severity).toLowerCase()}`} key={c.id}><span className="severity-label">{c.severity}</span><div><b>{c.type.replaceAll('_', ' ')}</b><p>{c.title}</p><small>{c.platform_id || 'Station-wide'}{c.start_min !== null && c.start_min !== undefined ? ` · ${fmt(c.start_min)}–${fmt(c.end_min)}` : ''}</small></div><ChevronRight size={17} /></div>)}{!items.length && <div className="all-clear"><CheckCircle2 size={21} /><div><b>No items at this severity</b><p>The independent checks found no matching constraints to list in the current scenario projection.</p></div></div>}</div></div>
  </div>;
}

const TEMPLATES = [
  { id: 'minor', title: 'Minor delay', description: 'One train held 15 minutes by a signal issue.', accent: 'blue', disruptions: [{ kind: 'train_delay', train_id: '12951', delay_min: 15, reason: 'Signal issue' }] },
  { id: 'express', title: 'Express train delay', description: 'Priority express service delayed 30 minutes.', accent: 'cyan', disruptions: [{ kind: 'train_delay', train_id: '12951', delay_min: 30, reason: 'Express train signal delay' }] },
  { id: 'maintenance', title: 'Platform maintenance', description: 'Close P2 from 10:00 to 10:45.', accent: 'amber', disruptions: [{ kind: 'platform_closure', platform_id: 'P2', start_min: 60, end_min: 105, reason: 'Scheduled maintenance' }] },
  { id: 'multiple', title: 'Multiple train delays', description: 'Two trains receive simultaneous delay inputs.', accent: 'violet', disruptions: [{ kind: 'train_delay', train_id: '12951', delay_min: 15, reason: 'Signal issue' }, { kind: 'train_delay', train_id: '12139', delay_min: 10, reason: 'Congestion upstream' }] },
  { id: 'peak', title: 'Peak-hour disruption', description: 'Several services receive short delays.', accent: 'orange', disruptions: [{ kind: 'train_delay', train_id: '12951', delay_min: 10, reason: 'Peak-hour congestion' }, { kind: 'train_delay', train_id: '22691', delay_min: 12, reason: 'Peak-hour congestion' }, { kind: 'train_delay', train_id: '59201', delay_min: 8, reason: 'Peak-hour congestion' }] },
  { id: 'severe', title: 'Severe disruption', description: 'A closure plus delays; feasible outcome is not guaranteed.', accent: 'red', disruptions: [{ kind: 'platform_closure', platform_id: 'P2', start_min: 60, end_min: 105, reason: 'Severe incident response' }, { kind: 'train_delay', train_id: '12951', delay_min: 35, reason: 'Severe disruption' }, { kind: 'train_delay', train_id: '12139', delay_min: 20, reason: 'Severe disruption' }] },
];

function Disruptions({ trains, platforms, scenarios, doAction, busy, notify }: any) {
  const [selectedTemplate, setSelectedTemplate] = useState<any>(null);
  const [kind, setKind] = useState<'train_delay' | 'platform_closure'>('train_delay');
  const [trainId, setTrainId] = useState('12951'); const [delayMin, setDelayMin] = useState(15); const [reason, setReason] = useState('Signal issue');
  const [platformId, setPlatformId] = useState('P2'); const [from, setFrom] = useState('10:00'); const [to, setTo] = useState('10:45');
  const [instructionTrain, setInstructionTrain] = useState('12951'); const [instructionPlatform, setInstructionPlatform] = useState('P3'); const [instructionType, setInstructionType] = useState('SOFT_PLATFORM'); const [instructionText, setInstructionText] = useState('Keep Train 12951 on Platform 3 if possible.');
  const [scenarioTitle, setScenarioTitle] = useState('Signal issue');
  const toMinute = (s: string) => { const [h,m] = s.split(':').map(Number); return h * 60 + m - 540; };
  const pickTemplate = (t: any) => { setSelectedTemplate(t); setScenarioTitle(t.title); const d = t.disruptions[0]; setKind(d.kind); if (d.kind === 'train_delay') { setTrainId(d.train_id); setDelayMin(d.delay_min); setReason(d.reason); } else { setPlatformId(d.platform_id); setFrom(fmt(d.start_min)); setTo(fmt(d.end_min)); setReason(d.reason); } notify(`“${t.title}” loaded into the scenario editor. Review then apply it.`, 'info'); };
  const applyTemplate = () => {
    if (!selectedTemplate) return;
    const editorDisruption: any = kind === 'train_delay'
      ? { kind: 'train_delay', train_id: trainId, delay_min: Number(delayMin), reason }
      : { kind: 'platform_closure', platform_id: platformId, start_min: toMinute(from), end_min: toMinute(to), reason };
    if (editorDisruption.kind === 'platform_closure' && (editorDisruption.start_min < 0 || editorDisruption.end_min > 180 || editorDisruption.start_min >= editorDisruption.end_min)) {
      notify('Closure must have increasing times within the 09:00–12:00 demo horizon.', 'error'); return;
    }
    // Preserve the multi-item template, but apply edits made in the visible editor
    // to its first item so the form never appears editable while being ignored.
    const disruptions = selectedTemplate.disruptions.map((d: any, i: number) => i === 0 ? editorDisruption : d);
    doAction(() => post('/scenarios', { title: scenarioTitle || selectedTemplate.title, description: `Scenario template: ${selectedTemplate.title}`, disruptions, instructions: [] }), `Scenario “${selectedTemplate.title}” applied. Related views now reflect its disruptions.`);
    setSelectedTemplate(null);
  };
  const applyCustom = (chosenKind: 'train_delay' | 'platform_closure' = kind, titleOverride?: string) => {
    const disruption = chosenKind === 'train_delay'
      ? { kind: chosenKind, train_id: trainId, delay_min: Number(delayMin), reason }
      : { kind: chosenKind, platform_id: platformId, start_min: toMinute(from), end_min: toMinute(to), reason };
    if (chosenKind === 'platform_closure' && (toMinute(from) < 0 || toMinute(to) > 180 || toMinute(from) >= toMinute(to))) { notify('Closure must have increasing times within the 09:00–12:00 demo horizon.', 'error'); return; }
    doAction(() => post('/scenarios', { title: titleOverride || scenarioTitle || (chosenKind === 'train_delay' ? `Train ${trainId} delay` : `${platformId} closure`), description: reason, disruptions: [disruption], instructions: [] }), 'Disruption applied to the shared station state. The approved timetable remains unchanged.');
    setSelectedTemplate(null);
  };
  const applyInstruction = () => doAction(() => post('/scenarios', { title: 'Station-master instruction', description: instructionText, disruptions: [], instructions: [{ kind: instructionType, train_id: instructionTrain, platform_id: instructionPlatform, instruction_text: instructionText }] }), 'Station-master instruction saved. It will be considered on the next optimization run.');
  const active = scenarios.filter((s: any) => s.active);
  const recentlyDeactivated = scenarios.filter((s: any) => !s.active).slice(0, 4);
  return <div className="page-stack"><div className="page-intro"><div><div className="eyebrow">SCENARIO LAB <span className="line" /></div><h2>Disruptions <span>& rescheduling</span></h2><p>Disruptions create a scenario projection. The approved timetable changes only after a validated proposal is approved.</p></div><div className="active-pill"><span className="dot amber" />{active.length} active scenario{active.length === 1 ? '' : 's'}</div></div>
    <div className="disruption-layout"><div className="editor-column">
      <div className="panel form-panel"><SectionHead icon={TrainFront} title="Train delay" subtitle="Shift expected arrival and departure before optimization." /><label className="field-label">Train<select value={trainId} onChange={e => setTrainId(e.target.value)}>{trains.map((t: any) => <option key={t.train_id} value={t.train_id}>{t.train_id} — {t.name}</option>)}</select></label><div className="form-inline"><label className="field-label grow">Delay (minutes)<input type="number" min={1} max={180} value={delayMin} onChange={e => setDelayMin(Number(e.target.value))} /></label><label className="field-label grow">Reason<input value={reason} onChange={e => setReason(e.target.value)} maxLength={240} /></label></div><label className="field-label">Scenario name<input value={scenarioTitle} onChange={e => setScenarioTitle(e.target.value)} maxLength={160} /></label><button className="button primary full" disabled={busy || delayMin < 1} onClick={() => applyCustom()}><Plus size={16} /> Apply train delay</button></div>
      <div className="panel form-panel"><SectionHead icon={LockKeyhole} title="Platform closure" subtitle="Unavailable only during the specified interval." /><div className="form-inline"><label className="field-label grow">Platform<select value={platformId} onChange={e => setPlatformId(e.target.value)}>{platforms.map((p: any) => <option key={p.id}>{p.id}</option>)}</select></label><label className="field-label grow">Reason<input value={reason} onChange={e => setReason(e.target.value)} maxLength={240} /></label></div><div className="form-inline"><label className="field-label grow">From<input type="time" value={from} min="09:00" max="11:59" onChange={e => setFrom(e.target.value)} /></label><label className="field-label grow">To<input type="time" value={to} min="09:01" max="12:00" onChange={e => setTo(e.target.value)} /></label></div><button className="button secondary full" disabled={busy} onClick={() => { setKind('platform_closure'); setScenarioTitle(`${platformId} maintenance`); applyCustom('platform_closure', `${platformId} maintenance`); }}><Plus size={16} /> Apply platform closure</button></div>
      <div className="panel form-panel"><SectionHead icon={ClipboardList} title="Station-master instruction" subtitle="Hard requirements block the model if infeasible; preferences can be relaxed." /><div className="form-inline"><label className="field-label grow">Instruction type<select value={instructionType} onChange={e => setInstructionType(e.target.value)}><option value="SOFT_PLATFORM">Soft preference</option><option value="HARD_PLATFORM">Mandatory platform</option></select></label><label className="field-label grow">Train<select value={instructionTrain} onChange={e => setInstructionTrain(e.target.value)}>{trains.map((t: any) => <option key={t.train_id} value={t.train_id}>{t.train_id} — {t.name}</option>)}</select></label><label className="field-label grow">Platform<select value={instructionPlatform} onChange={e => setInstructionPlatform(e.target.value)}>{platforms.map((p: any) => <option key={p.id}>{p.id}</option>)}</select></label></div><label className="field-label">Instruction text<textarea rows={2} value={instructionText} onChange={e => setInstructionText(e.target.value)} maxLength={500} /></label><button className="button secondary full" disabled={busy} onClick={applyInstruction}><Plus size={16} /> Apply instruction</button></div>
    </div>
    <div className="template-column"><div className="template-heading"><div><h3><WandSparkles size={19} /> Scenario templates</h3><p>Choose a common disruption to populate the editor, then apply it.</p></div></div><div className="template-grid">{TEMPLATES.map(t => <button key={t.id} onClick={() => pickTemplate(t)} className={`template-card ${t.accent} ${selectedTemplate?.id === t.id ? 'selected' : ''}`}><div className="template-icon">{t.id === 'maintenance' ? <LockKeyhole size={21} /> : t.id === 'severe' ? <Siren size={21} /> : t.id === 'multiple' ? <TrainFront size={21} /> : t.id === 'peak' ? <Activity size={21} /> : <Clock3 size={21} />}</div><div className="template-copy"><b>{t.title}</b><p>{t.description}</p></div><ChevronRight size={18} /></button>)}</div>{selectedTemplate && <div className="selected-template panel"><div><span className="mini-badge info">SELECTED TEMPLATE</span><h3>{selectedTemplate.title}</h3><p>{selectedTemplate.disruptions.length} disruption item(s) will be applied as a single active scenario.</p><ul>{selectedTemplate.disruptions.map((d: any, i: number) => <li key={i}>{d.kind === 'train_delay' ? `Train ${d.train_id} delayed by ${d.delay_min} min — ${d.reason}` : `${d.platform_id} closed ${fmt(d.start_min)}–${fmt(d.end_min)} — ${d.reason}`}</li>)}</ul><label className="field-label">Scenario title<input value={scenarioTitle} onChange={e => setScenarioTitle(e.target.value)} /></label><button className="button primary full" disabled={busy} onClick={applyTemplate}><Check size={16} /> Apply selected template</button></div></div>}
      <div className="panel active-scenarios"><SectionHead icon={Bell} title="Active disruptions & instructions" subtitle="Each change is persisted and affects all scenario-aware views." right={<span className="mini-badge warning">{active.length} ACTIVE</span>} />{active.length ? active.map((s: any) => <div className="scenario-card" key={s.id}>
        <div className="scenario-card-header"><div><b>{s.title}</b><p>{s.description || 'Fictional scenario input'}</p></div><button className="icon-button danger-icon" title="Deactivate this scenario" aria-label={`Deactivate scenario ${s.title}`} onClick={() => doAction(() => del(`/scenarios/${s.id}`), `Scenario “${s.title}” deactivated. Use Undo below to restore it.`)}><Trash2 size={16} /></button></div>
        {s.disruptions.map((d: any) => <div className={`scenario-detail ${d.active ? '' : 'inactive-detail'}`} key={`d-${d.id}`}>
          <span className={`detail-marker ${d.kind === 'platform_closure' ? 'amber' : 'cyan'}`} />
          <div className="scenario-detail-copy">{d.kind === 'train_delay' ? `Train ${d.train_id} +${d.delay_min} min` : `${d.platform_id} closed ${fmt(d.start_min)}–${fmt(d.end_min)}`}<small>{d.reason}{!d.active ? ' · Removed' : ''}</small></div>
          <button className={`detail-action ${d.active ? 'remove' : 'restore'}`} title={d.active ? 'Remove disruption' : 'Undo removal'} aria-label={d.active ? 'Remove disruption' : 'Restore disruption'} onClick={() => doAction(() => d.active ? del(`/scenarios/${s.id}/disruptions/${d.id}`) : post(`/scenarios/${s.id}/disruptions/${d.id}/restore`, {}), d.active ? 'Disruption removed from the active scenario.' : 'Disruption restored to the active scenario.')}>
            {d.active ? <X size={13} /> : <RefreshCw size={13} />}
          </button>
        </div>)}
        {s.instructions.map((i: any) => <div className={`scenario-detail ${i.active ? '' : 'inactive-detail'}`} key={`i-${i.id}`}>
          <span className={`detail-marker ${i.kind === 'HARD_PLATFORM' ? 'red' : 'blue'}`} />
          <div className="scenario-detail-copy">{i.kind === 'HARD_PLATFORM' ? 'Mandatory' : 'Preference'}: Train {i.train_id} → {i.platform_id}<small>{i.instruction_text}{!i.active ? ' · Removed' : ''}</small></div>
          <button className={`detail-action ${i.active ? 'remove' : 'restore'}`} title={i.active ? 'Remove instruction' : 'Undo removal'} aria-label={i.active ? 'Remove instruction' : 'Restore instruction'} onClick={() => doAction(() => i.active ? del(`/scenarios/${s.id}/instructions/${i.id}`) : post(`/scenarios/${s.id}/instructions/${i.id}/restore`, {}), i.active ? 'Station-master instruction removed.' : 'Station-master instruction restored.')}>
            {i.active ? <X size={13} /> : <RefreshCw size={13} />}
          </button>
        </div>)}
        <div className="scenario-card-footer"><span>Scenario #{s.id}</span><button className="text-link" onClick={() => doAction(() => del(`/scenarios/${s.id}`), 'Scenario deactivated; approved timetable unchanged.')}>Deactivate <X size={14} /></button></div>
      </div>) : <Empty title="No active disruptions" body="Apply a train delay, closure, instruction or scenario template to start." />}</div>
      {recentlyDeactivated.length > 0 && <div className="panel inactive-scenarios"><SectionHead icon={RefreshCw} title="Recently deactivated · Undo" subtitle="Restore a cleared scenario without editing the approved timetable." />{recentlyDeactivated.map((s: any) => <div className="inactive-scenario-row" key={s.id}><div><b>{s.title}</b><small>{s.description || 'No description'} · Scenario #{s.id}</small></div><button className="button secondary small" onClick={() => doAction(() => post(`/scenarios/${s.id}/restore`, {}), `Scenario “${s.title}” restored.`)}><RefreshCw size={13} /> Undo</button></div>)}</div>}
    <div className="reschedule-cta"><div className="cta-symbol"><Settings2 size={22} /></div><div><b>{busy ? 'Preparing input · optimizing · validating…' : 'Ready to reschedule?'}</b><p>{busy ? 'The API request is running. This button stays busy until CP-SAT and post-solve validation return.' : 'Generate a real CP-SAT proposal, run independent validation, then open the proposal for review.'}</p></div><button className="button primary" disabled={busy} onClick={async () => { const result = await doAction(() => post('/schedules/optimize', { aggregate: true, minimum_gap: 5, max_time_seconds: 5 }), undefined); if (result) { notify(result.is_valid ? `Proposal #${result.id} generated and independently validated.` : `Proposal #${result.id} returned ${result.solver_status}; inspect diagnostics.`, result.is_valid ? 'success' : 'info'); window.dispatchEvent(new CustomEvent('railsync-navigate', { detail: 'Proposal Review' })); } }}><WandSparkles size={16} /> {busy ? 'Running CP-SAT…' : 'Generate revised timetable'}</button></div>
    </div></div>
  </div>;
}

function ProposalReview({ current, proposals, proposal, selectProposal, doAction, busy, notify }: any) {
  const [altTrain, setAltTrain] = useState('12951'); const [altPlatform, setAltPlatform] = useState('P3'); const [altKind, setAltKind] = useState('SOFT_PLATFORM'); const [altText, setAltText] = useState('Prefer Train 12951 on Platform 3 if feasible.'); const [altReason, setAltReason] = useState('Please preserve the original platform preference where feasible.');
  const [rejectOpen, setRejectOpen] = useState(false); const [rejectReason, setRejectReason] = useState('');
  useEffect(() => { if (proposal?.id) selectProposal(proposal.id); }, [proposal?.id]);
  const latest = proposal;
  const currentRows = current?.entries || [];
  const proposedRows = latest?.entries || [];
  const proposedMap = new Map(proposedRows.map((e: any) => [e.train_id, e]));
  const changeByTrain = new Map((latest?.changes || []).map((c: any) => [c.train_id, c]));
  const runOptimization = () => doAction(async () => { const result = await post('/schedules/optimize', { aggregate: true, minimum_gap: 5, max_time_seconds: 5 }); await selectProposal(result.id); return result; }, undefined).then((result: any) => { if (result) notify(result.is_valid ? result.changes?.length ? `Proposal #${result.id} generated with ${result.changes.length} timetable change(s); independent validation passed.` : `Proposal #${result.id} generated. No timetable changes were necessary for the submitted constraints; independent validation passed.` : `Proposal #${result.id} result: ${result.solver_status}. Review diagnostics.`, result.is_valid ? 'success' : 'info'); });
  const validate = () => doAction(async () => { const result = await post(`/schedules/proposals/${latest.id}/validate`); await selectProposal(latest.id); return result; }, 'Independent timetable validation completed.');
  const approve = () => doAction(async () => { const result = await post(`/schedules/proposals/${latest.id}/approve`); await selectProposal(latest.id); return result; }, 'Proposal approved. The approved timetable version has advanced.');
  const reject = async () => {
    if (!latest?.id || rejectReason.trim().length < 3) { notify('Enter a rejection reason with at least 3 characters.', 'error'); return; }
    const result = await doAction(async () => { const r = await post(`/schedules/proposals/${latest.id}/reject`, { reason: rejectReason.trim() }); await selectProposal(latest.id); return r; }, 'Proposal rejected; current approved timetable unchanged.');
    if (result) { setRejectOpen(false); setRejectReason(''); }
  };
  const alternative = () => doAction(async () => {
    if (latest.state !== 'REJECTED') {
      const rejection = await post(`/schedules/proposals/${latest.id}/reject`, { reason: altReason || 'Station master requests an alternative.' });
    }
    const result = await post(`/schedules/proposals/${latest.id}/alternative`, { reason: altReason, instruction: { kind: altKind, train_id: altTrain, platform_id: altPlatform, instruction_text: altText }, minimum_gap: 5, max_time_seconds: 5 });
    await selectProposal(result.id); return result;
  }, 'New alternative generated by the optimizer from the updated instruction.');
  return <div className="page-stack"><div className="page-intro"><div><div className="eyebrow">STATION-MASTER DECISION <span className="line" /></div><h2>Proposal <span>review</span></h2><p>Compare immutable current version to a computed proposal, inspect independent validation, then decide.</p></div><button className="button primary" onClick={runOptimization} disabled={busy}><WandSparkles size={16} /> Generate revised timetable</button></div>
    <div className="proposal-status-row"><div className="version-chip current"><CheckCircle2 size={16} /><span>CURRENT · Approved v{current?.version_number ?? '—'}</span></div>{latest && <><div className="version-chip proposed"><FileClock size={16} /><span>PROPOSAL #{latest.id} · {latest.solver_status}</span></div><div className={`version-chip ${latest.is_valid ? 'validated' : 'invalid'}`}>{latest.is_valid ? <ShieldCheck size={16} /> : <AlertTriangle size={16} />}<span>{latest.is_valid ? `VALIDATED · ${latest.validation?.hard_violation_count || 0} hard violations` : `${latest.state || 'NOT VALIDATED'}`}</span></div><div className={`version-chip ${latest.state === 'AWAITING_APPROVAL' ? 'awaiting' : latest.state === 'APPROVED' ? 'validated' : 'neutral'}`}><Clock3 size={16} /><span>{latest.state?.replaceAll('_', ' ')}</span></div></>}</div>
    {proposals.length > 1 && <div className="proposal-select-row"><label>Choose proposal history<select value={latest?.id || ''} onChange={e => selectProposal(Number(e.target.value))}>{proposals.map((p: any) => <option key={p.id} value={p.id}>#{p.id} · {p.solver_status} · {p.state}</option>)}</select></label><span className="muted small-text">{proposals.length} saved proposal(s)</span></div>}
    {!latest ? <div className="panel no-proposal"><Empty title="No proposal yet" body="Apply a disruption from the scenario lab, then select Generate revised timetable. This invokes the real CP-SAT backend." /><button className="button primary" onClick={() => window.dispatchEvent(new CustomEvent('railsync-navigate', { detail: 'Disruptions & Rescheduling' }))}>Open scenario lab <ArrowRight size={15} /></button></div> : <>
      {!latest.entries?.length && <div className="callout danger"><AlertOctagon size={18} /><div><b>{latest.solver_status === 'INFEASIBLE' ? 'No feasible timetable has been returned' : `Solver result: ${latest.solver_status || 'UNRESOLVED'}`}</b><p>{latest.diagnostics?.reason || 'The solver did not return a schedule. No fabricated timetable is shown.'}</p>{latest.diagnostics?.constraint_conflicts?.length ? <p>{latest.diagnostics.constraint_conflicts.map((conflict: any) => `${conflict.train_id}: ${fmt(conflict.arrival_min)}–${fmt(conflict.departure_min)} is outside the ${fmt(conflict.horizon_start)}–${fmt(conflict.horizon_end)} operating horizon`).join(' · ')}</p> : null}<p>{(latest.diagnostics?.constraints_to_review || []).join(' · ')}</p></div></div>}
      <div className="comparison-grid"><div className="panel"><SectionHead icon={CheckCircle2} title="Current approved timetable" subtitle={`Version ${current?.version_number ?? '—'} · immutable until approval`} /><TimetableCompare rows={currentRows} otherMap={proposedMap} changes={changeByTrain} side="current" /></div><div className="panel"><SectionHead icon={GitCompareArrows} title="Proposed timetable" subtitle={latest.version_id ? `Proposal #${latest.id} · version record ${latest.version_id}` : 'No schedule generated'} /><TimetableCompare rows={proposedRows} otherMap={new Map(currentRows.map((e: any) => [e.train_id, e]))} changes={changeByTrain} side="proposal" /></div></div>
      {latest.objective && Object.keys(latest.objective).length > 0 && <div className="metric-grid"><Metric value={latest.objective.total_additional_delay_min ?? 0} label="Additional optimizer delay" unit="min" /><Metric value={latest.objective.platform_changes ?? 0} label="Platform changes" unit="trains" /><Metric value={latest.objective.soft_preference_violations ?? 0} label="Soft preference misses" unit="rules" /><Metric value={latest.objective.weighted_objective ?? '—'} label="Weighted objective" unit="CP-SAT cost" /></div>}
      <div className="review-bottom-grid"><div className="panel"><SectionHead icon={ClipboardList} title="Reasons for changes" subtitle="Derived from the persisted solution diff." />{latest.changes?.length ? <div className="reason-list">{latest.changes.map((c: any, i: number) => <div className="reason-row" key={c.train_id}><span className="reason-index">{i + 1}</span><div><b>{c.train_id} · {c.name}</b><p>{c.changes.map((d: any) => `${d.field}: ${d.before} → ${d.after}`).join(' · ')}</p><small>{c.reason}</small></div></div>)}</div> : <Empty title="No changes recorded" body="The solver found no differences or returned no feasible schedule for comparison." />}</div><div className="panel validation-report"><SectionHead icon={ShieldCheck} title="Independent validation" subtitle="Plain-Python checks run after the solver result." right={<button className="button small secondary" disabled={!latest.version_id || busy} onClick={validate}><RefreshCw size={13} /> Revalidate</button>} />{latest.validation?.valid ? <div className="validation-pass"><CheckCircle2 size={26} /><div><b>All hard checks passed</b><p>{latest.validation.summary}</p></div></div> : <div className="validation-fail"><AlertTriangle size={23} /><div><b>{latest.validation?.hard_violation_count ?? 'No'} hard violation(s)</b><p>{latest.validation?.summary || latest.diagnostics?.reason || 'No independently validated timetable available.'}</p></div></div>}<ul className="check-list">{['One assignment per train','Allowed platform compatibility','No overlapping platform occupancy','Minimum five-minute separation','Time-specific platform closures','Valid times within operating horizon','Station-master hard requirements'].map((r, i) => <li key={r}><span className={(latest.validation?.valid && latest.version_id) ? 'check-good' : 'check-pending'}>{latest.validation?.valid && latest.version_id ? <Check size={13} /> : <Clock3 size={13} />}</span>{r}</li>)}</ul></div></div>
      <div className="decision-bar"><div className="decision-note"><LockKeyhole size={17} /><div><b>Not operational until approved by station master.</b><p>Only approval promotes this proposal to the current timetable. Rejection never changes the approved version.</p></div></div><div className="decision-buttons"><button className="button green-button" disabled={busy || !latest.is_valid || latest.state !== 'AWAITING_APPROVAL'} onClick={approve}><Check size={16} /> Approve timetable</button><button className="button danger-button" disabled={busy || ['APPROVED','REJECTED','INFEASIBLE'].includes(latest.state)} onClick={() => { setRejectReason(''); setRejectOpen(true); }}><X size={16} /> Reject</button></div></div>
      <div className="panel alternative-panel"><SectionHead icon={RefreshCw} title="Request alternative" subtitle="Add a changed structured instruction. The system reruns CP-SAT; it will not randomly rotate platforms." /><div className="alternative-form"><label className="field-label">Constraint type<select value={altKind} onChange={e => setAltKind(e.target.value)}><option value="SOFT_PLATFORM">Soft preference</option><option value="HARD_PLATFORM">Hard requirement</option></select></label><label className="field-label">Train<select value={altTrain} onChange={e => setAltTrain(e.target.value)}>{trainsOptionList(currentRows).map((t: any) => <option value={t.train_id} key={t.train_id}>{t.train_id} — {t.name}</option>)}</select></label><label className="field-label">Platform<select value={altPlatform} onChange={e => setAltPlatform(e.target.value)}>{['P1','P2','P3','P4','P5'].map(p => <option key={p}>{p}</option>)}</select></label><label className="field-label wide-field">Instruction<input value={altText} onChange={e => setAltText(e.target.value)} /></label><label className="field-label wide-field">Station-master reason<input value={altReason} onChange={e => setAltReason(e.target.value)} /></label><button className="button outline-cyan" disabled={busy || !latest.id || ['APPROVED','INFEASIBLE'].includes(latest.state)} onClick={alternative}><RefreshCw size={15} /> Request alternative and optimize</button></div><p className="small-note">If the extra instruction makes the model infeasible, the result is recorded as infeasible and not shown as a validated timetable.</p></div>
    </>}
    {rejectOpen && latest && <div className="modal-backdrop" role="presentation" onMouseDown={() => setRejectOpen(false)}><div className="reason-dialog panel" role="dialog" aria-modal="true" aria-labelledby="reject-dialog-title" onMouseDown={e => e.stopPropagation()}><div className="reason-dialog-icon"><AlertTriangle size={21} /></div><h3 id="reject-dialog-title">Reject proposal #{latest.id}</h3><p>The approved timetable will remain unchanged. This reason will be written to the audit trail.</p><label className="field-label">Rejection reason<textarea autoFocus rows={4} maxLength={1000} value={rejectReason} onChange={e => setRejectReason(e.target.value)} placeholder="Explain which operational requirement is not satisfied…" /></label><div className="reason-dialog-actions"><button className="button secondary" onClick={() => setRejectOpen(false)}>Cancel</button><button className="button danger-button" disabled={busy || rejectReason.trim().length < 3} onClick={reject}><X size={15} /> Confirm rejection</button></div></div></div>}
  </div>;
}
function trainsOptionList(entries: any[]) { return entries.length ? entries : [{ train_id: '12951', name: 'Coastal Superfast' }, { train_id: '12139', name: 'Harbour Mail' }, { train_id: '17031', name: 'Hill Fort Express' }]; }
function TimetableCompare({ rows, otherMap, changes, side }: any) {
  return <div className="table-wrap compare-table"><table><thead><tr><th>Train</th><th>Arr</th><th>Dep</th><th>Platform</th><th>State</th></tr></thead><tbody>{rows.slice(0, 18).map((r: any) => { const changed = changes.has(r.train_id); const item = changes.get(r.train_id); return <tr key={r.train_id} className={changed ? `changed-row ${side}` : ''}><td><b className="mono">{r.train_id}</b><small>{r.name}</small></td><td className={`mono ${changed && item?.changes.some((c: any) => c.field === 'time') ? 'changed-cell' : ''}`}>{fmt(r.arrival_min)}</td><td className="mono">{fmt(r.departure_min)}</td><td className={changed && item?.changes.some((c: any) => c.field === 'platform') ? 'changed-cell' : ''}><span className="platform-tag">{r.platform_id}</span></td><td>{changed ? <span className="mini-badge warning">Changed</span> : <span className="mini-badge muted">Same</span>}</td></tr>; })}</tbody></table>{!rows.length && <div className="compare-empty">No timetable rows to display.</div>}</div>;
}
function Metric({ value, label, unit }: any) { return <div className="metric-card"><div className="metric-value">{value}<small>{unit}</small></div><p>{label}</p></div>; }

function ValidationAudit({ history, audit, proposals }: any) {
  const [filter, setFilter] = useState('ALL');
  const filtered = audit.filter((e: any) => filter === 'ALL' || e.event_type.includes(filter));
  const byProposal = new Map(proposals.map((p: any) => [p.id, p]));
  return <div className="page-stack"><div className="page-intro"><div><div className="eyebrow">TRUST & TRACEABILITY <span className="line" /></div><h2>Validation <span>& audit</span></h2><p>Every solver proposal, independent validation and station-master decision leaves a local audit trail.</p></div><div className="audit-summary"><div><strong>{history.length}</strong><span>Validation runs</span></div><div><strong>{audit.length}</strong><span>Audit events</span></div></div></div>
    <div className="audit-kpi-grid"><div className="audit-kpi"><span className="kpi-icon"><ShieldCheck size={20} /></span><div><b>{history.filter((x: any) => x.status === 'PASS').length}</b><span>Passed validation</span></div></div><div className="audit-kpi"><span className="kpi-icon amber-icon"><AlertTriangle size={20} /></span><div><b>{history.filter((x: any) => x.status === 'FAIL').length}</b><span>Failed validation</span></div></div><div className="audit-kpi"><span className="kpi-icon cyan-icon"><GitCompareArrows size={20} /></span><div><b>{proposals.length}</b><span>Saved proposals</span></div></div><div className="audit-kpi"><span className="kpi-icon green-icon"><BadgeCheck size={20} /></span><div><b>{proposals.filter((x: any) => x.state === 'APPROVED').length}</b><span>Approved proposals</span></div></div></div>
    <div className="panel"><SectionHead icon={FileCheck2} title="Independent validation history" subtitle="Stored validation reports contain individual codes, affected trains, platforms and intervals." />{history.length ? <div className="table-wrap"><table><thead><tr><th>Run</th><th>Proposal</th><th>Created</th><th>Result</th><th>Hard violations</th><th>Summary</th></tr></thead><tbody>{history.map((r: any) => <tr key={r.id}><td className="mono">VAL-{String(r.id).padStart(4,'0')}</td><td>{`#${r.proposal_id}`}</td><td>{new Date(r.created_at).toLocaleString()}</td><td><StatusPill status={r.status} /></td><td className={r.hard_violation_count ? 'text-red bold' : 'text-green bold'}>{r.hard_violation_count}</td><td>{r.report?.summary || 'Validation report saved.'}</td></tr>)}</tbody></table></div> : <Empty title="No validation runs yet" body="Generate a proposal to run the independent validator." />}</div>
    <div className="panel"><SectionHead icon={FileClock} title="Audit timeline" subtitle="Local demo actor names are illustrative, not authenticated identity claims." right={<label className="audit-filter">Filter<select value={filter} onChange={e => setFilter(e.target.value)}><option value="ALL">All events</option><option value="SCENARIO">Scenario</option><option value="SCHEDULE">Scheduling</option><option value="PROPOSAL">Proposal</option><option value="TIMETABLE">Approval</option><option value="SIMULATION">Simulation</option></select></label>} />{filtered.length ? <div className="audit-timeline">{filtered.map((e: any) => <div className="audit-event" key={e.id}><div className={`audit-event-dot ${e.event_type.includes('APPROVED') ? 'green' : e.event_type.includes('REJECTED') || e.event_type.includes('INFEASIBLE') ? 'red' : e.event_type.includes('VALIDAT') ? 'cyan' : 'amber'}`} /><div className="audit-event-main"><div className="audit-event-head"><b>{e.event_type.replaceAll('_', ' ')}</b><time>{new Date(e.created_at).toLocaleString()}</time></div><p>{e.details?.title || e.details?.reason || e.details?.message || JSON.stringify(e.details)}</p><small>Actor: {e.actor} · {e.entity_type}{e.entity_id ? ` #${e.entity_id}` : ''}{e.details?.solver_status ? ` · solver ${e.details.solver_status}` : ''}</small></div></div>)}</div> : <Empty title="No audit events match this filter" body="Choose a different event category." />}</div>
    <div className="panel"><SectionHead icon={GitCompareArrows} title="Proposal register" subtitle="Current state of saved timetable proposals." />{proposals.length ? <div className="table-wrap"><table><thead><tr><th>Proposal</th><th>Created</th><th>Solver</th><th>State</th><th>Validated</th><th>Base version</th></tr></thead><tbody>{proposals.map((p: any) => <tr key={p.id}><td className="mono">#{p.id}</td><td>{p.created_at ? new Date(p.created_at).toLocaleString() : '—'}</td><td>{p.solver_status}</td><td><StatusPill status={p.state} /></td><td>{p.is_valid ? <span className="text-green">PASS</span> : <span className="text-amber">Not passed</span>}</td><td>v{p.base_version_number ?? '—'}</td></tr>)}</tbody></table></div> : <Empty title="No proposals yet" body="The proposal register will populate after a scheduler run." />}</div>
  </div>;
}

function VoiceBriefing({ notify, trains, audit }: any) {
  const [status, setStatus] = useState<any>({ text_available: true, speech_enabled: false, status: 'loading' });
  const [suggestions, setSuggestions] = useState<any>({ actions: [], questions: [] });
  const [explanation, setExplanation] = useState<any>(null); const [explanationRequest, setExplanationRequest] = useState<any>(null);
  const [question, setQuestion] = useState(''); const [selectedTrain, setSelectedTrain] = useState('');
  const [voiceListening, setVoiceListening] = useState(false); const [requesting, setRequesting] = useState(false); const [audioLoading, setAudioLoading] = useState(false);
  const [playback, setPlayback] = useState<'idle' | 'playing' | 'paused' | 'complete' | 'error'>('idle'); const [spokenUpdates, setSpokenUpdates] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null); const audioUrlRef = useRef<string | null>(null); const announcedRef = useRef<Set<number>>(new Set()); const autoReadyRef = useRef(false);
  const clearAudio = () => { if (audioRef.current) { audioRef.current.pause(); audioRef.current = null; } if (audioUrlRef.current) { URL.revokeObjectURL(audioUrlRef.current); audioUrlRef.current = null; } };
  useEffect(() => { Promise.all([api('/voice/status'), api('/voice/suggestions')]).then(([nextStatus, nextSuggestions]) => { setStatus(nextStatus); setSuggestions(nextSuggestions); }).catch(e => notify(errText(e), 'error')); return clearAudio; }, []);
  const speak = async (item = explanation, request = explanationRequest) => {
    if (!item?.text) return;
    if (!status.speech_enabled) { notify('ElevenLabs speech is unavailable. You can still read the explanation.', 'info'); return; }
    setAudioLoading(true); setPlayback('idle'); clearAudio();
    try { const blob = await postAudio('/voice/speak', request); const url = URL.createObjectURL(blob); audioUrlRef.current = url; const audio = new Audio(url); audioRef.current = audio; audio.onplay = () => setPlayback('playing'); audio.onpause = () => { if (!audio.ended) setPlayback('paused'); }; audio.onended = () => { setPlayback('complete'); if (audioRef.current === audio) audioRef.current = null; }; audio.onerror = () => { setPlayback('error'); if (audioRef.current === audio) audioRef.current = null; notify('The browser could not play this audio response.', 'error'); }; await audio.play(); }
    catch (e) { setPlayback('error'); notify(errText(e), 'error'); }
    finally { setAudioLoading(false); }
  };
  const explain = async (kind: string, overrides: any = {}, autoPlay = false) => { const request = { kind, ...overrides }; setRequesting(true); try { const result = await post('/voice/explain', request); setExplanation(result); setExplanationRequest(request); if (autoPlay) await speak(result, request); return result; } catch (e) { notify(errText(e), 'error'); return null; } finally { setRequesting(false); } };
  const startQuestionVoice = () => { const Recognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition; if (!Recognition) { notify('Speech recognition is not supported in this browser. Type a supported question instead.', 'info'); return; } const recognition = new Recognition(); recognition.lang = 'en-IN'; recognition.interimResults = true; recognition.continuous = false; recognition.onstart = () => setVoiceListening(true); recognition.onresult = (event: any) => setQuestion(Array.from(event.results).map((result: any) => result[0]?.transcript || '').join(' ')); recognition.onerror = (event: any) => notify(`Microphone error: ${event.error || 'unavailable'}. You can type your question.`, 'error'); recognition.onend = () => setVoiceListening(false); try { recognition.start(); } catch (e) { setVoiceListening(false); notify(errText(e), 'error'); } };
  useEffect(() => { const relevant = (audit || []).filter((event: any) => /SCENARIO_APPLIED|SCHEDULE_OPTIMIZED|SCHEDULE_INFEASIBLE|PROPOSAL_VALIDATED|TIMETABLE_APPROVED|PROPOSAL_REJECTED/.test(event.event_type)); if (!spokenUpdates) { announcedRef.current = new Set(relevant.map((event: any) => event.id)); autoReadyRef.current = false; return; } if (!autoReadyRef.current) { announcedRef.current = new Set(relevant.map((event: any) => event.id)); autoReadyRef.current = true; return; } const next = relevant.find((event: any) => !announcedRef.current.has(event.id)); relevant.forEach((event: any) => announcedRef.current.add(event.id)); if (!next || !status.speech_enabled || audioRef.current || audioLoading) return; (async () => { try { const request = { kind: 'current_status' }; const result = await post('/voice/explain', request); setExplanation(result); setExplanationRequest(request); await speak(result, request); } catch { /* Automatic announcements do not retry. */ } })(); }, [audit, spokenUpdates, status.speech_enabled]);
  return <div className="panel voice-briefing"><SectionHead icon={Volume2} title="Railway voice briefing" subtitle="Factual explanations are generated from persisted RailSync data; speech is optional." right={<span className={`mini-badge ${status.speech_enabled ? 'success' : 'warning'}`}>{status.speech_enabled ? 'ELEVENLABS READY' : 'TEXT ONLY'}</span>} /><div className="voice-availability"><span><i className="dot green" />Text explanations available</span><span><i className={`dot ${status.speech_enabled ? 'green' : 'amber'}`} />{status.speech_enabled ? 'ElevenLabs speech enabled' : status.status === 'missing_configuration' ? 'Speech needs backend configuration' : 'Speech disabled'}</span><span><i className={`dot ${playback === 'playing' ? 'cyan' : 'green'}`} />{audioLoading ? 'Generating audio…' : playback === 'playing' ? 'Audio playing' : playback === 'paused' ? 'Audio paused' : playback === 'complete' ? 'Playback complete' : 'Ready'}</span></div><div className="voice-action-grid">{suggestions.actions.map((action: any) => <button key={action.kind} className="button secondary" disabled={requesting} onClick={() => explain(action.kind)}>{action.label}</button>)}</div><div className="voice-question-row"><select value={selectedTrain} onChange={event => setSelectedTrain(event.target.value)}><option value="">Explain a specific train…</option>{(trains || []).map((train: any) => <option key={train.train_id} value={train.train_id}>{train.train_id} · {train.name}</option>)}</select><button className="button secondary" disabled={!selectedTrain || requesting} onClick={() => explain('train_summary', { train_id: selectedTrain })}>Explain train</button></div><div className="voice-question-row"><input value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') explain('question', { question: question.trim() }); }} placeholder="Ask a supported railway question" /><button className={`button ${voiceListening ? 'danger-button' : 'secondary'}`} onClick={startQuestionVoice} disabled={voiceListening}><Mic size={15} /> {voiceListening ? 'Listening…' : 'Ask by voice'}</button><button className="button primary" disabled={!question.trim() || requesting} onClick={() => explain('question', { question: question.trim() })}><Send size={15} /> Ask</button></div><div className="example-chips">{suggestions.questions.map((item: string) => <button key={item} onClick={() => setQuestion(item)}>{item}</button>)}</div>{explanation ? <div className="voice-explanation"><div className="voice-explanation-head"><div><span className="mini-badge info">{explanation.source_context?.proposal_id ? `PROPOSAL #${explanation.source_context.proposal_id}` : 'LIVE CONTEXT'}</span><h3>{explanation.title}</h3></div><time>{explanation.generated_at ? new Date(explanation.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</time></div><p>{explanation.text}</p>{explanation.train_ids?.length ? <div className="voice-train-tags">{explanation.train_ids.map((id: string) => <span key={id}>Train {id}</span>)}</div> : null}<div className="voice-controls"><button className="button primary" onClick={() => speak()} disabled={audioLoading || requesting || !status.speech_enabled}><Play size={15} /> Listen</button><button className="button secondary" onClick={() => audioRef.current?.pause()} disabled={playback !== 'playing'}><Pause size={15} /> Pause</button><button className="button secondary" onClick={async () => { try { await audioRef.current?.play(); } catch (e) { notify(errText(e), 'error'); } }} disabled={playback !== 'paused'}><Play size={15} /> Resume</button><button className="button secondary" onClick={() => { clearAudio(); setPlayback('idle'); }} disabled={playback === 'idle'}><X size={15} /> Stop</button><button className="button secondary" onClick={() => speak()} disabled={audioLoading || !status.speech_enabled}><RefreshCw size={15} /> Replay</button></div></div> : <div className="voice-empty">Choose a quick action, select a train, or ask a supported question. The answer remains readable even without an ElevenLabs API key.</div>}<label className="spoken-updates"><input type="checkbox" checked={spokenUpdates} onChange={event => setSpokenUpdates(event.target.checked)} disabled={!status.speech_enabled} /> Enable spoken railway updates <small>Off by default; new confirmed events are announced once while this page is open.</small></label></div>;
}

function AssistantPage({ notify, refresh, go, trains, audit }: any) {
  const [input, setInput] = useState(''); const [interpreted, setInterpreted] = useState<any>(null); const [context, setContext] = useState<any>(null);
  const [listening, setListening] = useState(false); const [voiceAvailable, setVoiceAvailable] = useState(false); const [transcript, setTranscript] = useState(''); const [busy, setBusy] = useState(false); const recognitionRef = useRef<any>(null);
  useEffect(() => { api('/assistant/context').then(setContext).catch(e => notify(errText(e), 'error')); const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition; setVoiceAvailable(Boolean(SR)); return () => { try { recognitionRef.current?.stop(); } catch { /* ignored */ } }; }, []);
  const startVoice = () => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) { notify('Speech recognition is not supported in this browser. Type an instruction in the text box instead.', 'info'); return; }
    const rec = new SR(); recognitionRef.current = rec; rec.lang = 'en-IN'; rec.interimResults = true; rec.continuous = false;
    rec.onstart = () => { setListening(true); setTranscript('Listening…'); };
    rec.onresult = (event: any) => { const value = Array.from(event.results).map((r: any) => r[0]?.transcript || '').join(' '); setTranscript(value); setInput(value); };
    rec.onerror = (event: any) => { setListening(false); setTranscript(`Microphone error: ${event.error || 'unavailable'}. You can type below.`); };
    rec.onend = () => setListening(false);
    try { rec.start(); } catch (e) { setListening(false); notify(errText(e), 'error'); }
  };
  const interpret = async () => {
    if (!input.trim()) return;
    setBusy(true); setInterpreted(null);
    try { const result = await post('/assistant/interpret', { text: input }); setInterpreted(result); setTranscript(result.summary); if (!result.supported) notify(result.summary, 'info'); }
    catch (e) { notify(errText(e), 'error'); }
    finally { setBusy(false); }
  };
  const confirm = async () => {
    if (!interpreted?.interpreted) return;
    setBusy(true);
    try {
      const it = interpreted.interpreted;
      const payload = interpreted.kind === 'disruption' ? { title: 'Assistant-confirmed disruption', disruption: it } : { title: 'Assistant-confirmed instruction', instruction: it.instruction };
      await post('/assistant/confirm', payload); setInterpreted(null); setInput(''); notify('Confirmed instruction saved to shared scenario state. You can now review disruptions or generate a timetable proposal.'); await refresh(false); const c = await api('/assistant/context'); setContext(c);
    } catch (e) { notify(errText(e), 'error'); }
    finally { setBusy(false); }
  };
  return <div className="page-stack"><div className="page-intro"><div><div className="eyebrow">OPERATIONS ASSISTANT <span className="line" /></div><h2>Ask <span>RailSync</span></h2><p>Interpretation is a local rule-based demo adapter. It never selects platforms or changes data without your confirmation.</p></div><div className="assistant-status"><span className="dot green" />RULE-BASED DEMO ADAPTER</div></div>
    <VoiceBriefing notify={notify} trains={trains} audit={audit} />
    <div className="assistant-layout"><div className="assistant-left panel"><div className={`assistant-mic ${listening ? 'listening' : ''}`}><Mic size={35} /></div><h3>{listening ? 'Listening…' : 'Operations voice input'}</h3><p>Speak or type a structured operational instruction. Confirm the interpreted action before it becomes active.</p><button className={`button ${listening ? 'danger-button' : 'primary'} full`} onClick={startVoice} disabled={listening}><Mic size={16} /> {listening ? 'Listening' : 'Start microphone'}</button><div className="voice-support"><span className={`dot ${voiceAvailable ? 'green' : 'amber'}`} />{voiceAvailable ? 'Browser speech recognition available' : 'Voice API unavailable · typing remains supported'}</div>{transcript && <div className="transcript-preview"><b>Transcript / state</b><p>{transcript}</p></div>}<div className="assistant-disclaimer"><ShieldCheck size={16} /><span>Speech recognition uses the browser when supported. Spoken timetable explanations use ElevenLabs only when the backend is configured.</span></div></div>
      <div className="assistant-middle"><div className="panel assistant-compose"><SectionHead icon={AudioLines} title="Instruction console" subtitle="Example commands help the parser produce a reviewable structured instruction." /><label className="field-label">Type or edit the instruction<textarea rows={5} placeholder="e.g. delay train 12951 by 15 minutes" value={input} onChange={e => setInput(e.target.value)} /></label><div className="example-chips">{['delay train 12951 by 15 minutes','close platform 2 from 10:00 to 10:45','keep train 12951 on platform 3 if possible'].map(v => <button key={v} onClick={() => setInput(v)}>{v}</button>)}</div><div className="compose-footer"><span className="muted small-text">Nothing changes until a structured action is confirmed.</span><button className="button primary" disabled={busy || !input.trim()} onClick={interpret}><Send size={15} /> Interpret instruction</button></div></div>
        <div className="panel interpreted-panel"><SectionHead icon={ListChecks} title="Interpreted instruction" subtitle="Check the fields before confirmation." />{interpreted?.requires_confirmation ? <div className="instruction-card"><div className="instruction-card-head"><span className="mini-badge info">CONFIRMATION REQUIRED</span><span className="mini-badge warning">NOT APPLIED</span></div><h3>{interpreted.summary}</h3>{interpreted.kind === 'disruption' && <div className="parsed-fields">{interpreted.interpreted.kind === 'train_delay' ? <><div><span>Action</span><b>Train delay</b></div><div><span>Train</span><b>{interpreted.interpreted.train_id}</b></div><div><span>Delay</span><b>+{interpreted.interpreted.delay_min} min</b></div></> : <><div><span>Action</span><b>Platform closure</b></div><div><span>Platform</span><b>{interpreted.interpreted.platform_id}</b></div><div><span>Interval</span><b>{fmt(interpreted.interpreted.start_min)}–{fmt(interpreted.interpreted.end_min)}</b></div></>}</div>}{interpreted.kind === 'instruction' && <div className="parsed-fields"><div><span>Instruction</span><b>{interpreted.interpreted.kind}</b></div><div><span>Train</span><b>{interpreted.interpreted.train_id}</b></div><div><span>Platform</span><b>{interpreted.interpreted.platform_id}</b></div><div className="parsed-wide"><span>Text</span><b>{interpreted.interpreted.instruction_text}</b></div></div>}<div className="confirm-actions"><button className="button green-button" onClick={confirm} disabled={busy}><Check size={16} /> Confirm and apply</button><button className="button secondary" onClick={() => setInterpreted(null)}><X size={15} /> Reject interpretation</button></div></div> : interpreted ? <div className="assistant-unsupported"><AlertTriangle size={21} /><div><b>Unable to safely interpret</b><p>{interpreted.summary}</p></div></div> : <Empty title="No instruction awaiting review" body="Type an example command and select Interpret instruction. The assistant does not independently assign platforms." />}</div></div>
      <div className="assistant-right"><div className="panel context-panel"><SectionHead icon={Activity} title="Current station context" subtitle="Fetched from backend state." /><div className="context-clock"><span>SIMULATED CLOCK</span><b>{context?.clock || '—'}</b></div><div className="context-item"><span>Station</span><b>{context?.station || 'Central Junction'}</b></div><div className="context-item"><span>Approved version</span><b>v{context?.current_version ?? '—'}</b></div><div className="context-item"><span>Services</span><b>{context?.train_count ?? '—'}</b></div><div className="context-summary">{context?.summary || 'Station context will load when the backend is available.'}</div><button className="button secondary full" onClick={() => go('Disruptions & Rescheduling')}><SlidersHorizontal size={15} /> Review active scenarios</button><button className="button secondary full" onClick={() => go('Proposal Review')}><GitCompareArrows size={15} /> Review proposal workflow</button></div><div className="panel safety-panel"><ShieldCheck size={21} /><div><b>Safe decision flow</b><p>Interpret → Confirm → Persist scenario → Run optimizer → Independently validate → Station-master approval.</p></div></div></div>
    </div>
  </div>;
}
