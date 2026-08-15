"""Generate small synthetic invoice images plus a labeled manifest.

This is intentionally lightweight: it creates deterministic fictional invoices
and optional distortions for local extraction regression tests.

Example:
    python -m eval.generate_synthetic --output-dir eval/datasets/synthetic --count 20
"""

from __future__ import annotations

import argparse
import json
import random
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


def render_invoice(index: int, distorted: bool) -> tuple[Image.Image, dict]:
    rng = random.Random(index)
    vendor = ["ABC Technologies Pvt Ltd", "Zenix Office Systems", "Ravi Enterprises"][index % 3]
    number = f"SYN-{2026 + index // 12:04d}-{index + 1:04d}"
    subtotal = 12000 + index * 875
    tax = round(subtotal * 0.18)
    total = subtotal + tax
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    draw.text((90, 80), vendor, fill="#1d211c")
    draw.text((90, 125), "GSTIN: 27ABCDE1234F1Z5", fill="#62685f")
    draw.text((850, 80), "TAX INVOICE", fill="#1d211c")
    draw.text((850, 125), f"Invoice No: {number}", fill="#62685f")
    draw.line((90, 210, 1110, 210), fill="#c8ccc4", width=2)
    draw.text((90, 255), "Description", fill="#62685f")
    draw.text((650, 255), "Qty", fill="#62685f")
    draw.text((760, 255), "Rate", fill="#62685f")
    draw.text((950, 255), "Amount", fill="#62685f")
    item_amount = subtotal
    draw.text((90, 325), "Business services and equipment", fill="#1d211c")
    draw.text((650, 325), "1", fill="#1d211c")
    draw.text((760, 325), f"₹{item_amount:,}", fill="#1d211c")
    draw.text((950, 325), f"₹{item_amount:,}", fill="#1d211c")
    draw.line((90, 420, 1110, 420), fill="#e0e2dc", width=2)
    draw.text((760, 510), "Subtotal", fill="#62685f")
    draw.text((950, 510), f"₹{subtotal:,}", fill="#1d211c")
    draw.text((760, 570), "GST 18%", fill="#62685f")
    draw.text((950, 570), f"₹{tax:,}", fill="#1d211c")
    draw.text((760, 650), "Grand total", fill="#1d211c")
    draw.text((950, 650), f"₹{total:,}", fill="#1d211c")
    draw.text((90, 760), "Payment terms: 30 days", fill="#62685f")
    if distorted:
        variant = index % 5
        if variant == 0:
            image = image.rotate(rng.uniform(-2.5, 2.5), expand=False, fillcolor="white")
        if variant == 1:
            image = ImageEnhance.Contrast(image).enhance(0.68).filter(ImageFilter.GaussianBlur(0.7))
        if variant == 2:
            array = np.asarray(image).astype(np.int16)
            noise = np.random.default_rng(index).normal(0, 8, array.shape)
            image = Image.fromarray(np.uint8(np.clip(array + noise, 0, 255)))
        if variant == 3:
            shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.polygon(
                [(0, 0), (image.width, 0), (image.width, image.height // 3), (0, 0)],
                fill=(0, 0, 0, 38),
            )
            image = Image.alpha_composite(image.convert("RGBA"), shadow).convert("RGB")
        if variant == 4:
            compressed = BytesIO()
            image.save(compressed, format="JPEG", quality=35, optimize=True)
            compressed.seek(0)
            image = Image.open(compressed).convert("RGB")
    expected = {
        "invoice_number": {"value": number},
        "vendor": {
            "name": {"value": vendor},
            "gstin": {"value": "27ABCDE1234F1Z5"},
        },
        "line_items": [
            {
                "description": "Business services and equipment",
                "quantity": 1,
                "unit_price": subtotal,
                "discount": 0,
                "line_total": subtotal,
            }
        ],
        "subtotal": subtotal,
        "tax_total": tax,
        "grand_total": total,
        "currency": "INR",
    }
    return image, expected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--distorted", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index in range(args.count):
        image, expected = render_invoice(index, args.distorted)
        filename = f"invoice-{index + 1:04d}.png"
        image.save(args.output_dir / filename)
        manifest.append({"file": filename, "expected": expected})
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated {len(manifest)} synthetic invoices in {args.output_dir}")


if __name__ == "__main__":
    main()
