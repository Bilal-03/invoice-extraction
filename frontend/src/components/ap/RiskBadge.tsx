import { Badge } from "../ui/badge";

export function RiskBadge({ level, score }: { level: string; score?: number }) {
  return (
    <Badge variant="outline" className={`risk-pill risk-${level}`}>
      {score !== undefined ? `${score} · ` : ""}{level} risk
    </Badge>
  );
}
