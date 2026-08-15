"""
Image preprocessing pipeline.

This is the single biggest lever on OCR accuracy in practice — more
impactful than swapping OCR engines. Each step is independently
toggleable and logged so you can benchmark before/after impact.

Pipeline stages:
  1. Resize to an OCR-friendly working resolution
  2. Grayscale conversion
  3. Orientation correction via Tesseract OSD (best-effort)
  4. Deskew via Hough transform
  5. Denoising (conditional — skipped for clean digital PDFs)
  6. Local contrast enhancement
  7. Adaptive thresholding
"""

import asyncio
import re
from dataclasses import dataclass, field
from functools import partial

import cv2
import numpy as np

from app.adapters.ocr.base import OCRResult, OCRWord
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PreprocessingResult:
    """Output of the preprocessing pipeline with metadata."""

    image: np.ndarray
    original_shape: tuple[int, ...]
    steps_applied: list[str] = field(default_factory=list)
    deskew_angle: float = 0.0
    orientation_correction: int = 0  # degrees rotated
    estimated_dpi: int | None = None


class PreprocessingPipeline:
    """
    OpenCV preprocessing pipeline with toggleable stages.

    Each stage improves OCR accuracy for scanned/photographed invoices.
    Clean digital PDFs skip denoising (detected via DPI/quality heuristic).
    """

    def __init__(
        self,
        deskew: bool = True,
        denoise: bool = True,
        orient: bool = True,
    ):
        self.deskew = deskew
        self.denoise = denoise
        self.orient = orient

    async def process(self, image: np.ndarray) -> PreprocessingResult:
        """Run the full preprocessing pipeline asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._process_sync, image))

    def _process_sync(self, image: np.ndarray) -> PreprocessingResult:
        """Synchronous preprocessing pipeline."""
        result = PreprocessingResult(
            image=image,
            original_shape=image.shape,
        )

        # 1. Resize very small scans up for OCR, and cap very large camera
        # images so preprocessing remains bounded on the worker.  The review
        # layer uses normalized coordinates, so this does not lose evidence.
        working = self._resize_for_ocr(image, result)

        # 2. Grayscale conversion
        if len(working.shape) == 3:
            gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
            result.steps_applied.append("grayscale")
        else:
            gray = working.copy()

        # 3. Correct whole-page rotations before line-based deskewing. OSD is
        # deliberately best-effort: an unavailable/uncertain orientation must
        # never make an otherwise usable invoice fail.
        if self.orient:
            gray, orientation = self._correct_orientation(gray)
            result.orientation_correction = orientation
            if orientation:
                result.steps_applied.append(f"orientation({orientation}°)")

        # 2. Estimate quality to decide on denoising
        estimated_dpi = self._estimate_dpi(gray)
        result.estimated_dpi = estimated_dpi
        is_clean = estimated_dpi is not None and estimated_dpi >= 200

        # 4. Deskew via Hough transform
        if self.deskew:
            gray, angle = self._deskew_image(gray)
            result.deskew_angle = angle
            if abs(angle) > 0.1:
                result.steps_applied.append(f"deskew({angle:.1f}°)")

        # 5. Denoising (skip for clean digital documents)
        if self.denoise and not is_clean:
            gray = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)
            result.steps_applied.append("denoise")
        elif is_clean:
            result.steps_applied.append("denoise_skipped(clean_doc)")

        # 6. Contrast enhancement makes faint ink and photographed invoices
        # more legible without hard-coding a global brightness threshold.
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        result.steps_applied.append("contrast_clahe")

        # 7. Adaptive thresholding (kept from original — it works well)
        processed = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        result.steps_applied.append("adaptive_threshold")

        result.image = processed

        logger.info(
            "preprocessing_complete",
            steps=result.steps_applied,
            original_shape=result.original_shape,
            output_shape=processed.shape,
            deskew_angle=result.deskew_angle,
            estimated_dpi=result.estimated_dpi,
        )

        return result

    @staticmethod
    def _resize_for_ocr(image: np.ndarray, result: PreprocessingResult) -> np.ndarray:
        """Normalize working resolution while preserving the original source."""

        height, width = image.shape[:2]
        if min(height, width) <= 0:
            raise ValueError("Image has invalid dimensions")
        min_dimension = 1200
        max_dimension = 2400
        scale = max(1.0, min_dimension / min(height, width))
        if max(height, width) * scale > max_dimension:
            scale = max_dimension / max(height, width)
        if abs(scale - 1.0) < 0.01:
            return image.copy()
        interpolation = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        resized = cv2.resize(image, None, fx=scale, fy=scale, interpolation=interpolation)
        result.steps_applied.append(
            f"resize({width}x{height}->{resized.shape[1]}x{resized.shape[0]})"
        )
        return resized

    @staticmethod
    def _correct_orientation(image: np.ndarray) -> tuple[np.ndarray, int]:
        """Use Tesseract OSD when available; return the unchanged image otherwise."""

        try:
            import pytesseract

            osd = pytesseract.image_to_osd(image, config="--psm 0")
            match = re.search(r"Rotate:\s*(\d+)", osd)
            rotation = int(match.group(1)) % 360 if match else 0
        except Exception:
            return image, 0

        if rotation == 90:
            return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE), rotation
        if rotation == 180:
            return cv2.rotate(image, cv2.ROTATE_180), rotation
        if rotation == 270:
            return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE), rotation
        return image, 0

    def _deskew_image(self, image: np.ndarray) -> tuple[np.ndarray, float]:
        """
        Detect and correct document skew using Hough line transform.

        Returns the corrected image and the detected angle.
        """
        # Edge detection for line finding
        edges = cv2.Canny(image, 50, 150, apertureSize=3)

        # Hough line detection
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=100,
            minLineLength=image.shape[1] // 4,
            maxLineGap=10,
        )

        if lines is None or len(lines) == 0:
            return image, 0.0

        # Calculate dominant angle from detected lines
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line.flatten()[:4]
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            # Only consider near-horizontal lines (±30°)
            if abs(angle) < 30:
                angles.append(angle)

        if not angles:
            return image, 0.0

        # Use median angle (robust to outliers)
        median_angle = float(np.median(angles))

        # Don't correct tiny angles (noise)
        if abs(median_angle) < 0.5:
            return image, median_angle

        # Rotate to correct skew
        h, w = image.shape[:2]
        center = (w // 2, h // 2)
        rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        corrected = cv2.warpAffine(
            image,
            rotation_matrix,
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )

        return corrected, median_angle

    def _estimate_dpi(self, image: np.ndarray) -> int | None:
        """
        Estimate document DPI using a simple heuristic.

        High-DPI scans (≥200) are typically clean and don't need denoising.
        Low-DPI or photographed documents benefit from denoising.
        """
        h, w = image.shape[:2]

        # Assume standard document sizes (A4/Letter)
        # A4 is 210mm x 297mm ≈ 8.27" x 11.69"
        # If the image is large enough, it's probably a decent scan
        if w >= 1600 and h >= 2200:
            return 200  # Likely 200+ DPI scan
        elif w >= 800 and h >= 1100:
            return 150  # Moderate quality
        else:
            return 72  # Low quality / photographed


def load_image_from_bytes(file_bytes: bytes) -> np.ndarray:
    """Convert raw file bytes to an OpenCV image array.

    OpenCV handles the common path; Pillow provides a safe decoder fallback
    for image variants (notably some TIFF exports) that OpenCV cannot read.
    """
    image_np = np.frombuffer(file_bytes, np.uint8)
    image = cv2.imdecode(image_np, cv2.IMREAD_COLOR)
    if image is None:
        from io import BytesIO

        from PIL import Image

        try:
            rgb = np.asarray(Image.open(BytesIO(file_bytes)).convert("RGB"))
            image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except Exception as exc:
            raise ValueError("Failed to decode image from bytes") from exc
    return image


def load_pdf_pages(file_bytes: bytes) -> list[np.ndarray]:
    """
    Convert a PDF to a list of OpenCV images (one per page).

    Uses PyMuPDF (fitz) which is faster than pdf2image and
    doesn't require the Poppler system dependency.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    images = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        # 160 DPI is sufficient for OCR while materially reducing raster work.
        mat = fitz.Matrix(160 / 72, 160 / 72)
        pix = page.get_pixmap(matrix=mat)

        # Convert to numpy array
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)

        # Convert RGBA to BGR if needed
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        images.append(img)

    doc.close()
    logger.info("pdf_pages_loaded", page_count=len(images))
    return images


def extract_pdf_ocr_result(file_bytes: bytes) -> OCRResult | None:
    """Read a digital PDF's text layer with native word coordinates.

    Generated invoices usually contain selectable text. Bypassing render + OCR
    for those files is the largest latency win and preserves review overlays.
    """
    import fitz

    document = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        words: list[OCRWord] = []
        dimensions: dict[int, tuple[int, int]] = {}
        texts: list[str] = []
        for page_index, page in enumerate(document):
            rect = page.rect
            dimensions[page_index] = (max(1, round(rect.width)), max(1, round(rect.height)))
            texts.append(page.get_text("text").strip())
            for x0, y0, x1, y1, text, *_ in page.get_text("words"):
                if text.strip():
                    words.append(
                        OCRWord(
                            text=text,
                            confidence=0.99,
                            x=round(x0),
                            y=round(y0),
                            width=max(1, round(x1 - x0)),
                            height=max(1, round(y1 - y0)),
                            page=page_index,
                        )
                    )
    finally:
        document.close()

    if len(words) < 20:
        return None
    logger.info("pdf_native_text_used", page_count=len(dimensions), word_count=len(words))
    return OCRResult(
        raw_text="\n\f\n".join(text for text in texts if text),
        words=words,
        average_confidence=0.99,
        engine_name="pdf_text",
        page_count=len(dimensions),
        page_dimensions=dimensions,
    )


def load_pdf_page(file_bytes: bytes, page_number: int, dpi: int = 120) -> np.ndarray:
    """Render only the requested PDF page for fast review previews."""
    import fitz

    document = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        if page_number < 0 or page_number >= len(document):
            raise IndexError("PDF page out of range")
        pix = document[page_number].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR) if pix.n == 3 else image
    finally:
        document.close()


def extract_pdf_text(file_bytes: bytes) -> str | None:
    """Return the embedded text layer of a digital PDF when it is usable.

    Digital invoices already contain higher-fidelity text than raster OCR.  We
    still render/OCR every page for bounding boxes and scanned-PDF support, but
    use this text for field and table reconstruction when enough words exist.
    """
    import fitz

    document = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        # Preserve the PDF's content-stream reading order. Invoice generators
        # commonly emit each logical block (table, seller, billing, shipping)
        # separately; geometric sorting can interleave two visual columns.
        pages = [page.get_text("text").strip() for page in document]
    finally:
        document.close()
    text = "\n\f\n".join(page for page in pages if page)
    word_count = len(re.findall(r"\b\w+\b", text))
    if word_count < 20:
        logger.info("pdf_text_layer_unavailable", word_count=word_count)
        return None
    logger.info("pdf_text_layer_loaded", word_count=word_count)
    return text
