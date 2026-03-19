"""Allow running the registry standalone: python -m registry."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from registry.app import create_registry_app

db_path = Path(os.environ.get("ACE_REGISTRY_DB", "registry_data/registry.db"))
port = int(os.environ.get("PORT", "9000"))

app = create_registry_app(db_path=db_path)
uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
