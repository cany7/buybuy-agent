"""Runtime configuration helpers for env-driven LLM clients."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class OpenAICompatibleClientConfig:
    """Resolved runtime settings for an OpenAI-compatible chat client."""

    model: str
    base_url: str | None
    api_key: str | None
    env_file_path: str | None


def default_env_path() -> Path:
    """Return the repository-level .env path."""

    return Path(__file__).resolve().parents[2] / ".env"


def load_runtime_env() -> str | None:
    """Load repository .env if present and return its path for downstream clients."""

    env_path = default_env_path()
    if env_path.exists():
        load_dotenv(env_path, override=False)
        return str(env_path)
    return None


def _read_optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def resolve_openai_compatible_client_config(
    *,
    model_env_var: str,
    default_model: str,
    agent_base_url_env: str,
    agent_api_key_env: str,
) -> OpenAICompatibleClientConfig:
    """Resolve env-backed configuration for one agent-scoped chat client."""

    env_file_path = load_runtime_env()
    model = _read_optional_env(model_env_var) or default_model

    agent_base_url = _read_optional_env(agent_base_url_env)
    agent_api_key = _read_optional_env(agent_api_key_env)
    if (agent_base_url is None) != (agent_api_key is None):
        raise ValueError(f"{agent_base_url_env} and {agent_api_key_env} must be set together.")

    base_url: str | None
    api_key: str | None
    if agent_base_url is not None and agent_api_key is not None:
        base_url = agent_base_url
        api_key = agent_api_key
    else:
        base_url = _read_optional_env("LLM_BASE_URL")
        api_key = _read_optional_env("LLM_API_KEY")

    return OpenAICompatibleClientConfig(
        model=model,
        base_url=base_url,
        api_key=api_key,
        env_file_path=env_file_path,
    )
