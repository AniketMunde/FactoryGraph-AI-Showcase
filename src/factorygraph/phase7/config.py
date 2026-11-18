"""Strict local configuration and server-side secret files."""

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["full", "gallery"] = "full"
    api_host: Literal["127.0.0.1"] = "127.0.0.1"
    api_port: int = Field(default=18080, ge=1024, le=65535)
    dashboard_port: int = Field(default=18501, ge=1024, le=65535)
    case_deadline_seconds: float = Field(default=120, gt=0, le=120)
    concurrency: Literal[1] = 1
    max_body_bytes: int = Field(default=16384, ge=1024, le=16384)
    requests_per_minute: int = Field(default=240, ge=10, le=240)
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "testserver", "api"]
    allowed_origins: list[str] = []
    gallery_directory: Path = Path("docs/examples/phase6")


def load_settings():
    value = yaml.safe_load(Path("configs/phase7/local.yaml").read_text(encoding="utf-8"))
    value["mode"] = os.environ.get("FG7_MODE", value["mode"])
    if os.environ.get("WEB_CONCURRENCY", "1") != "1":
        raise ValueError("Phase 7 admits one worker only")
    return Settings.model_validate(value)


def secret(name):
    path = os.environ.get(f"FG7_{name.upper()}_TOKEN_FILE")
    if not path:
        raise ValueError("Required credential file is not configured")
    value = Path(path).read_text(encoding="utf-8").strip()
    if (
        len(value) < 32
        or len(value) > 256
        or not value.isascii()
        or any(c.isspace() for c in value)
    ):
        raise ValueError("Invalid credential file")
    return value
