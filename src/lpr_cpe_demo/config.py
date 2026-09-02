from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


MCP_PROFILE_VERSIONS = {
    "custom_stateless_2026": "2026-07-28",
}


class Settings(BaseSettings):
    """Runtime settings. Safe simulation is the default posture."""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "LPR CPE Service Assurance Demo"
    app_environment: Literal["local", "docker", "test"] = "local"
    application_mode: Literal["simulation", "production"] = "simulation"
    production_writes_enabled: bool = False
    demo_auth_enabled: bool = False
    demo_default_user: str = "demo.operator"
    demo_default_role: str = "operations_supervisor"

    database_url: str = "sqlite+pysqlite:///./data/lpr_cpe_demo.db"
    langgraph_postgres_dsn: str = ""
    langgraph_strict_msgpack: bool = True

    api_url: str = "http://localhost:8000"
    api_port: int = 8000
    ui_port: int = 8501
    mcp_port: int = 8100
    mcp_url: str = "http://localhost:8100/mcp"
    mcp_profile: Literal["custom_stateless_2026"] = "custom_stateless_2026"
    mcp_health_url: str = "http://localhost:8100/health"
    mcp_use_network: bool = False
    mcp_protocol_version: str = "2026-07-28"
    mcp_strict_version: bool = True
    mcp_approval_signing_secret: str = "change-me-demo-secret"
    mcp_effect_db: str = "./data/mcp_effects.db"

    use_langgraph: bool = False
    langgraph_fallback_allowed: bool = False
    workflow_engine: Literal["langgraph", "portable"] = "portable"
    model_provider: Literal["fake", "openai", "anthropic"] = "fake"
    model_name: str = "fake-lpr-cpe-v1"
    model_timeout_seconds: float = 30.0
    model_max_tokens: int = 1200
    model_temperature: float = 0.0
    model_fallback_allowed: bool = True
    model_base_url: str = ""
    model_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    rca_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    max_remote_attempts: int = Field(default=2, ge=1)
    max_field_visits: int = Field(default=3, ge=1)
    max_mr_attempts: int = Field(default=2, ge=1)
    max_diagnostic_cycles: int = Field(default=4, ge=1)
    graph_max_steps: int = Field(default=40, ge=10)
    stability_window_minutes: int = Field(default=15, ge=1)
    ui_refresh_seconds: int = Field(default=2, ge=1, le=30)

    post_action_quarantine_enabled: bool = False
    post_action_quarantine_scheduler_enabled: bool = False
    post_action_quarantine_duration_seconds: int = Field(default=900, ge=1)
    post_action_quarantine_check_interval_seconds: int = Field(default=60, ge=1)
    post_action_quarantine_required_healthy_checks: int = Field(default=2, ge=1)
    post_action_quarantine_max_extensions: int = Field(default=2, ge=0)
    post_action_quarantine_lease_seconds: int = Field(default=120, ge=5)
    post_action_quarantine_worker_interval_seconds: int = Field(default=15, ge=1)

    log_level: str = "INFO"
    tz: str = "America/Puerto_Rico"
    demo_banner: str = (
        "DEMONSTRATION MODE — NXT, CPE, WFM and jTrack operations are simulated. "
        "No production writes are enabled."
    )


    @model_validator(mode="after")
    def validate_safe_compatibility_profile(self) -> "Settings":
        expected = MCP_PROFILE_VERSIONS[self.mcp_profile]
        if self.mcp_strict_version and self.mcp_protocol_version != expected:
            raise ValueError(
                f"MCP protocol {self.mcp_protocol_version} does not match "
                f"profile {self.mcp_profile} (expected {expected})"
            )
        return self

    @property
    def writes_permitted(self) -> bool:
        return self.application_mode == "production" and self.production_writes_enabled

    @property
    def fixture_dir(self) -> Path:
        return Path(__file__).resolve().parent / "fixtures"

    @property
    def effective_model_api_key(self) -> str:
        if self.model_api_key:
            return self.model_api_key
        if self.model_provider == "openai":
            return self.openai_api_key
        if self.model_provider == "anthropic":
            return self.anthropic_api_key
        return ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
