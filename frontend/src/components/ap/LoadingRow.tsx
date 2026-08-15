import { Loader2 } from "lucide-react";

export function LoadingRow() {
  return <div className="loading-row"><Loader2 size={18} className="spin" /> Loading ledger data…</div>;
}
