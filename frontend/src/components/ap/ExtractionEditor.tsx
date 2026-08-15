import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import type { Invoice } from "../../lib/api-client";
import { apiClient } from "../../lib/api-client";
import { ConfidenceBadge } from "./ConfidenceBadge";

export function ExtractionEditor({ label, path, value, confidence, invoiceId, onSaved }: { label: string; path: string; value: string; confidence?: number; invoiceId: string; onSaved: (invoice: Invoice) => void }) {
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  useEffect(() => setDraft(value), [value]);
  const save = async () => {
    if (draft === value) return;
    setSaving(true);
    try {
      const response = await apiClient.patch<Invoice>(`/invoices/${invoiceId}/fields`, { field_path: path, old_value: value || null, new_value: draft, corrected_by: "local_user" });
      onSaved(response.data);
    } finally { setSaving(false); }
  };
  return <label className="editable-field"><span>{label}</span><div><input value={draft} onChange={(event) => setDraft(event.target.value)} onBlur={() => void save()} />{saving ? <Loader2 size={13} className="spin" /> : confidence === undefined ? <small className={value ? "" : "confidence-missing"}>{value ? "field evidence" : "missing"}</small> : <ConfidenceBadge confidence={confidence} />}</div></label>;
}
