import { Badge } from "../ui/badge";

const labels: Record<string, string> = {
  review_required: "Review required",
  awaiting_payment: "Awaiting payment",
  approved: "Approved",
  paid: "Paid",
  rejected: "Rejected",
  duplicate: "Duplicate",
  on_hold: "On hold",
  pending: "Uploaded",
  preprocessing: "Processing",
  ocr: "OCR",
  extracting: "Extracted",
  validating: "Validating",
  completed: "Processed",
  failed: "Processing failed",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={`status-pill status-${status}`}>
      <i />{labels[status] || status.replaceAll("_", " ")}
    </Badge>
  );
}
