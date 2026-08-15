"""Optional llama.cpp server adapter using its OpenAI-compatible API."""

import httpx
import numpy as np

from app.adapters.vlm.base import VLMClient
from app.adapters.vlm.structured import (
    image_b64,
    map_to_extraction,
    parse_json_response,
    prompt_for,
    token_count,
    zero_cost,
)
from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.schemas import InvoiceExtraction

logger = get_logger(__name__)


class LlamaCppVLMClient(VLMClient):
    """Call a local ``llama-server`` multimodal model over HTTP."""

    def __init__(self, base_url: str | None = None, model: str | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.llama_cpp_base_url).rstrip("/")
        self.model = model or settings.llama_cpp_model

    @property
    def name(self) -> str:
        return f"llama.cpp/{self.model}"

    async def extract_fields(
        self,
        image: np.ndarray,
        existing_extraction: InvoiceExtraction | None = None,
    ) -> InvoiceExtraction:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_for(existing_extraction)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64(image)}"},
                        },
                    ],
                }
            ],
            "temperature": 0,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(f"{self.base_url}/v1/chat/completions", json=payload)
            response.raise_for_status()
        result = response.json()
        message = ((result.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        if isinstance(message, list):
            message = "".join(part.get("text", "") for part in message if isinstance(part, dict))
        extraction = map_to_extraction(parse_json_response(str(message)))
        usage = result.get("usage") or {}
        extraction.vlm_input_tokens = token_count(usage.get("prompt_tokens"))
        extraction.vlm_output_tokens = token_count(usage.get("completion_tokens"))
        extraction.estimated_cost_usd = zero_cost()
        return extraction

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/health")
                if response.is_success:
                    return True
                response = await client.get(f"{self.base_url}/v1/models")
                return response.is_success
        except Exception as exc:
            logger.debug("llama_cpp_health_failed", error=str(exc))
            return False
