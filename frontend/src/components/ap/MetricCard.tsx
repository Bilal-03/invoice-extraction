import type { LucideIcon } from "lucide-react";

export function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  tone?: string;
}) {
  return (
    <div className={`metric-card ${tone}`}>
      <div className="metric-top"><span>{label}</span><Icon size={17} /></div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}
