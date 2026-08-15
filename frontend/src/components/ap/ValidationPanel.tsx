import { AlertTriangle, Check } from "lucide-react";
import type { Invoice } from "../../lib/api-client";

export function ValidationPanel({ invoice }: { invoice: Invoice }) {
  return (
    <section className="panel">
      <div className="panel-heading"><div><span className="eyebrow">Automated controls</span><h2>Validation results</h2></div><span className="muted-text">{invoice.validations.filter((item) => item.passed).length}/{invoice.validations.length} passed</span></div>
      <div className="validation-list">
        {invoice.validations.map((item) => (
          <div className={`validation-row ${item.passed ? "passed" : "failed"}`} key={item.id}>
            <span>{item.passed ? <Check size={14} /> : <AlertTriangle size={14} />}</span>
            <div><strong>{item.rule.replaceAll("_", " ")}</strong><small>{item.message}</small></div>
            <em>{item.severity}</em>
          </div>
        ))}
      </div>
    </section>
  );
}
