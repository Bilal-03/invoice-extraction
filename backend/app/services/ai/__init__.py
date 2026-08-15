"""Provider-independent local AI boundary."""

from app.services.ai.base import VLMClient
from app.services.ai.llama_cpp import LlamaCppVLMClient
from app.services.ai.ollama import OllamaVLMClient

__all__ = ["LlamaCppVLMClient", "OllamaVLMClient", "VLMClient"]
