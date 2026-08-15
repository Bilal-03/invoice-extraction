import { formatINR } from "../../lib/api-client";
import type { DashboardSummary } from "../../lib/api-client";

export function AgingBars({ buckets }: { buckets: DashboardSummary["aging"] }) {
  const max = Math.max(...buckets.map((bucket) => bucket.amount), 1);
  const fallback = ["Current", "1–30 days", "31–60 days", "61–90 days", "90+ days"]
    .map((label) => ({ label, amount: 0, count: 0 }));
  return (
    <div className="aging-bars">
      {(buckets.length ? buckets : fallback).map((bucket) => (
        <div className="aging-row" key={bucket.label}>
          <div><span>{bucket.label}</span><strong>{formatINR(bucket.amount)}</strong></div>
          <div className="bar-track"><i style={{ width: `${Math.max(2, (bucket.amount / max) * 100)}%` }} /></div>
          <small>{bucket.count} invoices</small>
        </div>
      ))}
    </div>
  );
}
