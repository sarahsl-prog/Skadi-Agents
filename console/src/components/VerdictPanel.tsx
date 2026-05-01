import { approveCase, closeBenign, continueHunt, escalateCase } from "../api";
import type { VerdictPacket } from "../types";

interface Props {
  caseId: string;
  verdict: VerdictPacket | null;
  onAction: () => void;
}

const decisionLabel: Record<string, string> = {
  MALICIOUS: "Malicious",
  BENIGN: "Benign",
  INCONCLUSIVE: "Inconclusive",
  NEEDS_MORE_INFO: "Needs More Info",
};

export default function VerdictPanel({ caseId, verdict, onAction }: Props) {
  if (!verdict) return null;

  const handle = async (fn: (id: string) => Promise<void>) => {
    await fn(caseId);
    onAction();
  };

  return (
    <div className="verdict-panel">
      <h3>Verdict</h3>
      <div className="verdict-header">
        <span
          className={`verdict-badge ${verdict.decision.toLowerCase()}`}
        >
          {decisionLabel[verdict.decision] || verdict.decision}
        </span>
        <span className="confidence">Confidence: {verdict.confidence}</span>
      </div>
      <p className="reasoning">{verdict.reasoning_summary}</p>
      {verdict.policy_applicable.length > 0 && (
        <div className="policies">
          <strong>Policies:</strong>
          <ul>
            {verdict.policy_applicable.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="actions">
        <button onClick={() => handle(approveCase)}>Approve Learning</button>
        <button onClick={() => handle(escalateCase)}>Escalate</button>
        <button onClick={() => handle(closeBenign)}>Close Benign</button>
        <button onClick={() => handle(continueHunt)}>Continue Hunt</button>
      </div>
    </div>
  );
}
