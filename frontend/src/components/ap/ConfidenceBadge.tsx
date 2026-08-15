export function ConfidenceBadge({ confidence }: { confidence?: number | null }) {
  if (confidence === undefined || confidence === null) {
    return <small className="confidence-missing">Missing confidence</small>;
  }
  const percentage = Math.round(confidence * 100);
  const tone = confidence >= 0.85 ? "confidence-high" : confidence >= 0.65 ? "confidence-medium" : "confidence-low";
  return <small className={tone}>{percentage}% confidence</small>;
}
