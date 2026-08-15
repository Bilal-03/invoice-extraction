"""llama.cpp local provider facade for Intel CPU fallback deployments."""

from app.adapters.vlm.llama_cpp_client import LlamaCppVLMClient

__all__ = ["LlamaCppVLMClient"]
