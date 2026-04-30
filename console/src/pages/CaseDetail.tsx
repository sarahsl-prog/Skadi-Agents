import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getCase, getTimeline, getVerdict } from "../api";
import BreakGlass from "../components/BreakGlass";
import VerdictPanel from "../components/VerdictPanel";
import type { CaseDetail, TimelineEvent, VerdictPacket } from "../types";
import "./CaseDetail.css";

export default function CaseDetailPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const navigate = useNavigate();
  const [caseData, setCaseData] = useState<CaseDetail | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [verdict, setVerdict] = useState<VerdictPacket | null>(null);

  const refresh = useCallback(async () => {
    if (!caseId) return;
    const [c, t, v] = await Promise.all([
      getCase(caseId),
      getTimeline(caseId),
      getVerdict(caseId).catch(() => null),
    ]);
    setCaseData(c);
    setEvents(t.events || []);
    if (v) setVerdict(v.verdict);
  }, [caseId]);

  useEffect(() => {
    let active = true;
    (async () => {
      if (!active) return;
      await refresh();
    })();
    return () => {
      active = false;
    };
  }, [refresh]);

  const pseudonymizedFields = useMemo(() => {
    return ["user_a42", "host_b17", "ip_c99"];
  }, []);

  if (!caseData) return <p>Loading case…</p>;

  return (
    <div className="case-detail">
      <header>
        <h2>Case {caseData.case_id}</h2>
        <button onClick={() => navigate(-1)}>← Back</button>
      </header>

      <div className="case-meta">
        <span className="meta-pill">Status: {caseData.status}</span>
        <span className="meta-pill">Version: {caseData.version}</span>
        {caseData.tracker_confidence != null && (
          <span className="meta-pill">
            Tracker Confidence: {caseData.tracker_confidence}
          </span>
        )}
      </div>

      <VerdictPanel
        caseId={caseData.case_id}
        verdict={verdict}
        onAction={refresh}
      />

      <div className="timeline">
        <h3>Timeline</h3>
        {events.map((ev, i) => (
          <div key={i} className="timeline-event">
            <strong>{ev.entry_type}</strong> — {ev.timestamp}
          </div>
        ))}
        {events.length === 0 && (
          <p className="empty">No timeline events.</p>
        )}
      </div>

      <BreakGlass caseId={caseData.case_id} fields={pseudonymizedFields} />
    </div>
  );
}
