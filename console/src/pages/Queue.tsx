import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listCases, reviewQueue } from "../api";
import type { CaseSummary } from "../types";
import "./Queue.css";

export default function QueuePage() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [filter, setFilter] = useState("review");

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const data =
          filter === "review"
            ? await reviewQueue()
            : await listCases(filter === "all" ? undefined : filter);
        if (active) setCases(data.cases || []);
      } catch (e) {
        console.error(e);
      }
    })();
    return () => {
      active = false;
    };
  }, [filter]);

  return (
    <div>
      <h2>Review Queue</h2>
      <div className="filters">
        {["review", "all", "closed", "escalation"].map((f) => (
          <button
            key={f}
            className={filter === f ? "active" : ""}
            onClick={() => setFilter(f)}
          >
            {f === "all" ? "All Cases" : f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>
      <table className="queue-table">
        <thead>
          <tr>
            <th>Case ID</th>
            <th>Status</th>
            <th>Version</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.case_id}>
              <td>
                <Link to={`/cases/${encodeURIComponent(c.case_id)}`}>
                  {c.case_id}
                </Link>
              </td>
              <td>
                <span className={`status-badge ${c.status}`}>{c.status}</span>
              </td>
              <td>{c.version}</td>
              <td>{new Date(c.updated_at).toLocaleString()}</td>
            </tr>
          ))}
          {cases.length === 0 && (
            <tr>
              <td colSpan={4} className="empty">No cases found.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
