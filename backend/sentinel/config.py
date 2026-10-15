"""Settings read from environment variables (and a local .env if present)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Repo-root .env first, then backend/.env; real env vars always win.
_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")
load_dotenv(_ROOT / "backend" / ".env")


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = os.getenv("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.getenv("FALKORDB_PORT", "6380"))
    falkordb_username: str | None = os.getenv("FALKORDB_USERNAME") or None
    falkordb_password: str | None = os.getenv("FALKORDB_PASSWORD") or None
    graph_name: str = os.getenv("GRAPH_NAME", "sentinel")

    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_max_steps: int = int(os.getenv("LLM_MAX_STEPS", "14"))
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    cors_origins: tuple[str, ...] = tuple(
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3001").split(",") if o.strip()
    )


settings = Settings()
