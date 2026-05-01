import { useState } from "react";
import { showRaw } from "../api";

interface Props {
  caseId: string;
  fields: string[];
}

export default function BreakGlass({ caseId, fields }: Props) {
  const [rawMap, setRawMap] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState(false);
  const [confirmField, setConfirmField] = useState<string | null>(null);

  const reveal = async (field: string) => {
    const res = await showRaw(caseId, field);
    setRawMap((prev) => ({ ...prev, [field]: res.raw }));
    setBanner(true);
    setConfirmField(null);
  };

  return (
    <div className="breakglass">
      {banner && (
        <div className="audit-banner">
          Raw data view active — every access is audit-logged.
        </div>
      )}
      <h4>Break-Glass</h4>
      {fields.map((f) => (
        <div key={f} className="breakglass-row">
          <code>{f}</code>
          {rawMap[f] ? (
            <span className="raw-value">{rawMap[f]}</span>
          ) : confirmField === f ? (
            <div className="confirm">
              <span>Audit-logged — continue?</span>
              <button onClick={() => reveal(f)}>Yes</button>
              <button onClick={() => setConfirmField(null)}>Cancel</button>
            </div>
          ) : (
            <button onClick={() => setConfirmField(f)}>Show Raw</button>
          )}
        </div>
      ))}
    </div>
  );
}
