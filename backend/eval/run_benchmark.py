"""Run the extraction pipeline against a labeled manifest and report quality metrics.

Manifest format:
[
  {"id": "sample-1", "file": "images/sample-1.png", "expected": { ...InvoiceExtraction fields... }}
]
"""

import argparse
import asyncio
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.api.v1.deps import build_ocr_engine, build_vlm_client
from app.core.config import get_settings
from app.services.extraction_service import ExtractionService

CORE_FIELDS = (
    "invoice_number",
    "invoice_date",
    "due_date",
    "vendor_name",
    "grand_total",
    "currency",
)


def normalize(value: Any) -> str:
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    return "" if value is None else " ".join(str(value).casefold().split())


def edit_distance(left: list[str] | str, right: list[str] | str) -> int:
    previous = list(range(len(right) + 1))
    for index, left_item in enumerate(left, 1):
        current = [index]
        for other_index, right_item in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[other_index] + 1,
                    previous[other_index - 1] + int(left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def field_value(record: dict[str, Any], field: str) -> Any:
    if field == "vendor_name":
        return ((record.get("vendor") or {}).get("name") or {}).get("value")
    return record.get(field)


def score_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    field_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    exact_documents = 0
    row_true_positive = row_predicted = row_expected = 0
    cell_matches = cell_total = 0
    latencies = []
    sources: dict[str, int] = defaultdict(int)
    ocr_errors = {
        "before": {"characters": 0, "character_total": 0, "words": 0, "word_total": 0},
        "after": {"characters": 0, "character_total": 0, "words": 0, "word_total": 0},
    }

    for record in records:
        expected = record["expected"]
        predicted = record["predicted"]
        all_match = True
        for field in CORE_FIELDS:
            truth = normalize(field_value(expected, field))
            guess = normalize(field_value(predicted, field))
            if truth and guess == truth:
                field_counts[field]["tp"] += 1
            elif guess:
                field_counts[field]["fp"] += 1
            if truth and guess != truth:
                field_counts[field]["fn"] += 1
            all_match = all_match and truth == guess
        exact_documents += int(all_match)

        expected_items = expected.get("line_items") or []
        predicted_items = predicted.get("line_items") or []
        row_expected += len(expected_items)
        row_predicted += len(predicted_items)
        paired = min(len(expected_items), len(predicted_items))
        row_true_positive += paired
        for index in range(paired):
            for cell in ("description", "quantity", "unit_price", "discount", "line_total"):
                cell_total += 1
                cell_matches += int(
                    normalize(expected_items[index].get(cell))
                    == normalize(predicted_items[index].get(cell))
                )
        latency = predicted.get("processing_time_ms")
        if latency is not None:
            latencies.append(float(latency))
        sources[str(predicted.get("extraction_source", "unknown"))] += 1
        expected_ocr = record.get("expected_ocr_text")
        if expected_ocr is not None:
            expected_text = str(expected_ocr)
            expected_words = expected_text.split()
            for stage, record_key in (
                ("before", "predicted_ocr_text_before"),
                ("after", "predicted_ocr_text"),
            ):
                if record.get(record_key) is None:
                    continue
                predicted_text = str(record[record_key])
                ocr_errors[stage]["characters"] += edit_distance(expected_text, predicted_text)
                ocr_errors[stage]["character_total"] += len(expected_text)
                ocr_errors[stage]["words"] += edit_distance(expected_words, predicted_text.split())
                ocr_errors[stage]["word_total"] += len(expected_words)

    def prf(counts: dict[str, int]) -> dict[str, float]:
        precision = counts["tp"] / max(1, counts["tp"] + counts["fp"])
        recall = counts["tp"] / max(1, counts["tp"] + counts["fn"])
        f1 = 2 * precision * recall / max(1e-12, precision + recall)
        return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}

    row_precision = row_true_positive / max(1, row_predicted)
    row_recall = row_true_positive / max(1, row_expected)
    ordered_latencies = sorted(latencies)
    p95_index = max(0, min(len(ordered_latencies) - 1, int(len(ordered_latencies) * 0.95) - 1))
    total = len(records)
    return {
        "documents": total,
        "exact_match_accuracy": round(exact_documents / max(1, total), 4),
        "fields": {field: prf(field_counts[field]) for field in CORE_FIELDS},
        "line_items": {
            "row_precision": round(row_precision, 4),
            "row_recall": round(row_recall, 4),
            "row_f1": round(
                2 * row_precision * row_recall / max(1e-12, row_precision + row_recall), 4
            ),
            "cell_accuracy": round(cell_matches / max(1, cell_total), 4),
        },
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2) if latencies else 0,
            "p95": round(ordered_latencies[p95_index], 2) if latencies else 0,
        },
        "sources": dict(sources),
        "vlm_fallback_rate": round(sources.get("vlm_fallback", 0) / max(1, total), 4),
        "ocr": {
            stage: {
                "cer": round(values["characters"] / max(1, values["character_total"]), 4),
                "wer": round(values["words"] / max(1, values["word_total"]), 4),
            }
            for stage, values in ocr_errors.items()
        }
        | {
            "samples": sum(1 for record in records if record.get("expected_ocr_text") is not None),
        },
    }


async def run_pipeline(manifest_path: Path, manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.adapters.preprocessing.pipeline import load_image_from_bytes, load_pdf_pages

    settings = get_settings()
    service = ExtractionService(build_ocr_engine(settings), build_vlm_client(settings))
    records = []
    for sample in manifest:
        file_path = (manifest_path.parent / sample["file"]).resolve()
        data = file_path.read_bytes()
        images = (
            load_pdf_pages(data)
            if file_path.suffix.lower() == ".pdf"
            else [load_image_from_bytes(data)]
        )
        raw_results = []
        for page_index, image in enumerate(images):
            result = await service.ocr_engine.extract(image)
            for word in result.words:
                word.page = page_index
            raw_results.append(result)
        raw_ocr = service._combine_ocr_results(raw_results)
        prediction = await service.extract_from_images(images)
        records.append(
            {
                "id": sample.get("id", file_path.stem),
                "expected": sample["expected"],
                "predicted": prediction.model_dump(mode="json"),
                "expected_ocr_text": sample.get("ocr_text"),
                "predicted_ocr_text_before": raw_ocr.raw_text,
                "predicted_ocr_text": service.last_ocr_result.raw_text,
            }
        )
    return records


def markdown_report(metrics: dict[str, Any]) -> str:
    latency = metrics["latency_ms"]
    ocr = metrics["ocr"]
    lines = [
        "# Invoice extraction benchmark",
        "",
        f"Documents: {metrics['documents']}",
        f"Exact-match accuracy: {metrics['exact_match_accuracy']:.2%}",
        f"Line-item row F1: {metrics['line_items']['row_f1']:.2%}",
        f"Line-item cell accuracy: {metrics['line_items']['cell_accuracy']:.2%}",
        f"Latency p50/p95: {latency['p50']:.0f} / {latency['p95']:.0f} ms",
        f"OCR CER before/after: {ocr['before']['cer']:.2%} / {ocr['after']['cer']:.2%}",
        f"OCR WER before/after: {ocr['before']['wer']:.2%} / {ocr['after']['wer']:.2%}",
        "",
        "| Field | Precision | Recall | F1 |",
        "|---|---:|---:|---:|",
    ]
    for field, values in metrics["fields"].items():
        lines.append(
            f"| {field} | {values['precision']:.3f} | {values['recall']:.3f} | {values['f1']:.3f} |"
        )
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, help="Labeled benchmark manifest JSON")
    parser.add_argument(
        "--predictions", type=Path, help="Precomputed records with expected/predicted keys"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("eval/results"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    records = (
        json.loads(args.predictions.read_text())
        if args.predictions
        else await run_pipeline(args.manifest, manifest)
    )
    metrics = score_records(records)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (args.output_dir / "report.md").write_text(markdown_report(metrics))
    print(markdown_report(metrics))


if __name__ == "__main__":
    asyncio.run(main())
