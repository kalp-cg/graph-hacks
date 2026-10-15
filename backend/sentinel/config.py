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


settings = Settings()
