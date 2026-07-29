"""Prometheus instrumentation with a dependency-free local fallback."""

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

    DOCUMENTS = Counter("invoice_documents_total", "Documents processed", ["status", "source"])
    PROCESSING_TIME = Histogram("invoice_processing_seconds", "End-to-end document processing time")

    def record_document(status: str, source: str = "unknown", seconds: float = 0.0) -> None:
        DOCUMENTS.labels(status=status, source=source).inc()
        if seconds > 0:
            PROCESSING_TIME.observe(seconds)

    def render_metrics() -> tuple[bytes, str]:
        return generate_latest(), CONTENT_TYPE_LATEST

except ImportError:

    def record_document(status: str, source: str = "unknown", seconds: float = 0.0) -> None:
        return None

    def render_metrics() -> tuple[bytes, str]:
        return (
            b"# Prometheus metrics are unavailable until prometheus-client is installed\n",
            "text/plain",
        )
