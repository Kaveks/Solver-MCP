"""
config/settings.py — Central configuration for Solver-MCP MCP Connector

All environment variables are loaded, validated, and typed here.
No other module calls os.getenv() directly.

Usage
-----
    from config import get_settings

    settings = get_settings()
    print(settings.REDIS_URL)

    # Secrets use SecretStr — call .get_secret_value() to read the raw string
    api_key = settings.ANTHROPIC_API_KEY.get_secret_value()

get_settings() returns a cached singleton. The settings object is built once on first
call and reused for the lifetime of the process. Validation errors surface at startup,
not mid-request.

Field naming convention
-----------------------
Field names are UPPERCASE to match their environment variable / .env counterparts
exactly. settings.REDIS_URL reads REDIS_URL from the environment. There is no
ambiguity about which Python attribute maps to which env var.

Secret fields
-------------
Fields marked [SECRET] use Pydantic SecretStr. Their values are never printed,
logged, or included in repr() output. To read the raw value:
    settings.OPENAI_API_KEY.get_secret_value()

Secret fields have no hardcoded default. If a required secret for the active
provider is absent, the application raises a clear validation error at startup.

Non-secret fields
-----------------
All other fields are plain types (str, int, Path, Enum). They are safe to log
and include in debug output.

Environment file
----------------
Copy .env.example to .env and fill in the values for your setup.
.env is never committed to version control.
.env.example is always committed and contains every variable name with an empty
value and a comment. Only the block matching LLM_PROVIDER needs to be filled in.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Enums — constrained choices for string configuration fields
# ---------------------------------------------------------------------------

class LLMProvider(str, Enum):
    OPENAI       = "openai"
    ANTHROPIC    = "anthropic"
    AZURE        = "azure"
    OLLAMA       = "ollama"
    GOOGLE_GENAI = "google_genai"


class MCPTransport(str, Enum):
    STDIO = "stdio"
    HTTP  = "http"


class ArtifactStoreType(str, Enum):
    LOCAL = "local"
    S3    = "s3"


class RunnerBackend(str, Enum):
    """How the worker invokes a solver inside its isolated container.

    docker — Prototype: DockerExecRunner execs into the solver service via the Docker socket.
    k8s    — Production: K8sJobRunner submits a Kubernetes Job (implemented in Phase 4).
    """

    DOCKER = "docker"
    K8S    = "k8s"


class LogLevel(str, Enum):
    DEBUG   = "DEBUG"
    INFO    = "INFO"
    WARNING = "WARNING"
    ERROR   = "ERROR"


class LogFormat(str, Enum):
    JSON = "json"
    TEXT = "text"


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """
    All configuration for the Solver-MCP MCP Connector.

    Field names are UPPERCASE and match their env var names exactly.
    Secret fields use SecretStr — they are never logged or repr'd.
    Model validators run at instantiation and raise on missing required values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Field names are UPPERCASE; env vars are UPPERCASE.
        # case_sensitive=True ensures exact matching with no folding surprises.
        case_sensitive=True,
        # Ignore env vars from the OS that are not part of this config.
        extra="ignore",
        populate_by_name=True,
    )

    # ── LLM provider selection ─────────────────────────────────────────────

    LLM_PROVIDER: LLMProvider = Field(
        ...,
        description=(
            "Which LLM provider to use. "
            "One of: openai, anthropic, azure, ollama. "
            "Only set the credential block matching this value."
        )
    )

    # ── OpenAI ────────────────────────────────────────────────────────────

    OPENAI_API_KEY: SecretStr | None = Field(
        None,
        description="[SECRET] OpenAI API key. Required when LLM_PROVIDER=openai."
    )
    OPENAI_MODEL: str = Field(
        "gpt-4o",
        description="OpenAI model name. Default: gpt-4o."
    )

    # ── Anthropic / Claude ─────────────────────────────────────────────────

    ANTHROPIC_API_KEY: SecretStr | None = Field(
        None,
        description="[SECRET] Anthropic API key. Required when LLM_PROVIDER=anthropic."
    )
    ANTHROPIC_MODEL: str = Field(
        "claude-sonnet-4-5",
        description="Anthropic model name. Default: claude-sonnet-4-5."
    )

    # ── Azure OpenAI ───────────────────────────────────────────────────────

    AZURE_OPENAI_API_KEY: SecretStr | None = Field(
        None,
        description="[SECRET] Azure OpenAI API key. Required when LLM_PROVIDER=azure."
    )
    AZURE_OPENAI_ENDPOINT: str | None = Field(
        None,
        description="Azure OpenAI endpoint URL. Required when LLM_PROVIDER=azure."
    )
    AZURE_OPENAI_DEPLOYMENT: str | None = Field(
        None,
        description="Azure deployment name. Required when LLM_PROVIDER=azure."
    )
    AZURE_OPENAI_API_VERSION: str = Field(
        "2024-02-01",
        description="Azure OpenAI API version."
    )

    # ── Ollama (local — no key required) ───────────────────────────────────

    OLLAMA_MODEL: str = Field(
        "llama3",
        description="Ollama model name. Default: llama3."
    )
    OLLAMA_BASE_URL: str = Field(
        "http://localhost:11434",
        description="Ollama server base URL."
    )

    # ── Google Gemini (langchain-google-genai) ─────────────────────────────
    # Provider id is google_genai (LangChain's convention); the key uses Google's
    # GOOGLE_API_KEY env var; the model is a Gemini model.

    GOOGLE_API_KEY: SecretStr | None = Field(
        None,
        description="[SECRET] Google API key. Required when LLM_PROVIDER=google_genai."
    )
    GEMINI_MODEL: str = Field(
        "gemini-2.0-flash",
        description="Gemini model name. Default: gemini-2.0-flash."
    )

    # ── MCP transport ──────────────────────────────────────────────────────

    MCP_TRANSPORT: MCPTransport = Field(
        MCPTransport.STDIO,
        description=(
            "MCP transport mode. "
            "stdio — Prototype, agent launches server as a subprocess. "
            "http  — Production, agent connects to a running server over HTTP/SSE."
        )
    )
    MCP_SERVER_URL: str = Field(
        "http://localhost:8000",
        description="MCP server base URL. Used when MCP_TRANSPORT=http."
    )
    MCP_API_KEY: SecretStr | None = Field(
        None,
        description=(
            "[SECRET] API key sent in the X-API-Key request header. "
            "Required when MCP_TRANSPORT=http."
        )
    )

    # ── Redis ──────────────────────────────────────────────────────────────
    # SecretStr because the URL may embed a password:
    #   redis://:mypassword@redis-host:6379/0

    REDIS_URL: SecretStr = Field(
        default=SecretStr("redis://redis-svc:6379/0"),
        description=(
            "[SECRET] Redis connection URL. "
            "Treated as secret because the URL may embed a password. "
            "Used as Celery broker and simulation artifact cache."
        )
    )

    # ── Celery ─────────────────────────────────────────────────────────────
    # Optional overrides. Both default to REDIS_URL when not set (see validator).
    # SecretStr for the same reason as REDIS_URL.

    CELERY_BROKER_URL: SecretStr | None = Field(
        None,
        description=(
            "[SECRET] Celery broker URL. "
            "Defaults to REDIS_URL if not set. "
            "Set explicitly to use a different broker (e.g. RabbitMQ) in Production."
        )
    )
    CELERY_RESULT_BACKEND: SecretStr | None = Field(
        None,
        description=(
            "[SECRET] Celery result backend URL. "
            "Defaults to REDIS_URL if not set."
        )
    )

    # ── Artifact store ─────────────────────────────────────────────────────

    ARTIFACT_STORE_TYPE: ArtifactStoreType = Field(
        ArtifactStoreType.LOCAL,
        description=(
            "Artifact storage backend. "
            "local — Docker volume (Prototype). "
            "s3    — S3-compatible object store (Production)."
        )
    )
    LOCAL_ARTIFACT_PATH: Path = Field(
        Path("/artifacts"),
        description=(
            "Filesystem path for local artifact storage. "
            "Used when ARTIFACT_STORE_TYPE=local."
        )
    )

    # S3 — Production only
    S3_BUCKET: str | None = Field(
        None,
        description="S3 bucket name. Required when ARTIFACT_STORE_TYPE=s3."
    )
    S3_REGION: str | None = Field(
        None,
        description="AWS region for the S3 bucket. Required when ARTIFACT_STORE_TYPE=s3."
    )
    AWS_ACCESS_KEY_ID: SecretStr | None = Field(
        None,
        description="[SECRET] AWS access key ID. Required when ARTIFACT_STORE_TYPE=s3."
    )
    AWS_SECRET_ACCESS_KEY: SecretStr | None = Field(
        None,
        description="[SECRET] AWS secret access key. Required when ARTIFACT_STORE_TYPE=s3."
    )

    # ── Authentication ─────────────────────────────────────────────────────

    API_KEY: SecretStr | None = Field(
        None,
        description=(
            "[SECRET] Static API key for Prototype authentication. "
            "Clients send this value in the X-API-Key request header."
        )
    )
    JWT_SECRET: SecretStr | None = Field(
        None,
        description=(
            "[SECRET] Secret used to sign and validate JWT tokens. "
            "Required in Production when authentication mode is JWT."
        )
    )

    # ── Solver shared volume ───────────────────────────────────────────────

    WORK_DIR: Path = Field(
        Path("/work"),
        description=(
            "Path to the shared volume mounted by the worker and all solver containers. "
            "Worker writes input files here. "
            "Solver reads and executes. "
            "Worker reads output files and parses results."
        )
    )

    # ── Solver runner (how the worker invokes solvers in their containers) ──

    RUNNER_BACKEND: RunnerBackend = Field(
        RunnerBackend.DOCKER,
        description=(
            "Solver invocation backend. "
            "docker — Prototype: exec into the solver container via the Docker socket. "
            "k8s    — Production: submit a Kubernetes Job. "
            "The connector code is identical for both; only the runner differs."
        )
    )
    OPENFOAM_CONTAINER: str = Field(
        "Solver-MCP-openfoam",
        description=(
            "Name of the running openfoam-svc container the DockerExecRunner execs into. "
            "Matches container_name in docker-compose.yml."
        )
    )
    OPENFOAM_BASHRC: str = Field(
        "/opt/openfoam10/etc/bashrc",
        description=(
            "Path to the OpenFOAM environment script sourced before invoking simpleFoam. "
            "Image-specific; the openfoam10 Foundation image places it under /opt/openfoam10."
        )
    )
    LAMMPS_CONTAINER: str = Field(
        "Solver-MCP-lammps",
        description=(
            "Name of the running lammps-svc container the DockerExecRunner execs into. "
            "Matches container_name in docker-compose.yml."
        )
    )
    LAMMPS_BINARY: str = Field(
        "lmp_serial",
        description=(
            "LAMMPS executable name on the solver image's PATH. The official lammps image "
            "ships 'lmp_serial' (and 'lmp_mpi'); there is no plain 'lmp'. Set to 'lmp_mpi' "
            "for parallel runs in Production."
        )
    )

    # ── Logging ────────────────────────────────────────────────────────────

    LOG_LEVEL: LogLevel = Field(
        LogLevel.INFO,
        description="Application log level. One of: DEBUG, INFO, WARNING, ERROR."
    )
    LOG_FORMAT: LogFormat = Field(
        LogFormat.JSON,
        description=(
            "Log output format. "
            "json — structured logging for Production and log aggregators. "
            "text — human-readable for local development."
        )
    )
    CORRELATION_ID_HEADER: str = Field(
        "X-Correlation-ID",
        description=(
            "HTTP header carrying the request correlation ID. Reused if the caller (Layer 1) "
            "supplies it, otherwise a new ID is generated per request."
        )
    )

    # ── Observability — LangSmith tracing (optional) ───────────────────────

    LANGSMITH_TRACING: bool = Field(
        False,
        description="Enable LangSmith tracing. Off by default; tracing is never required."
    )
    LANGSMITH_API_KEY: SecretStr | None = Field(
        None,
        description="[SECRET] LangSmith API key. Required only when LANGSMITH_TRACING=true."
    )
    LANGSMITH_PROJECT: str | None = Field(
        "Solver-MCP",
        description="LangSmith project name traces are grouped under."
    )

    # ── Server ─────────────────────────────────────────────────────────────

    HOST: str = Field(
        "0.0.0.0",
        description="Bind address for the Gunicorn/Uvicorn server."
    )
    PORT: int = Field(
        8000,
        description="Bind port for the Gunicorn/Uvicorn server.",
        ge=1,
        le=65535,
    )

    # ── Gunicorn ───────────────────────────────────────────────────────────
    # Defined here so run-fastapi-server.sh reads them from the environment
    # rather than hardcoding them in the shell script. This way changing
    # worker count only requires a .env change, not a script edit.

    GUNICORN_WORKERS: int = Field(
        3,
        description=(
            "Number of Gunicorn worker processes. "
            "Fixed at 3 per container. "
            "Scale by adding pods in Production, not by increasing this value."
        ),
        ge=1,
        le=8,
    )
    GUNICORN_TIMEOUT: int = Field(
        120,
        description=(
            "Gunicorn worker request timeout in seconds. "
            "Simulation jobs are async (return a job ID immediately), "
            "so this only needs to cover the MCP call roundtrip and Redis write."
        ),
        ge=30,
    )
    GUNICORN_GRACEFUL_TIMEOUT: int = Field(
        30,
        description=(
            "Seconds Gunicorn gives workers to finish in-flight requests "
            "after receiving SIGTERM before forcefully killing them."
        ),
        ge=10,
    )

    # =========================================================================
    # Model validators
    # =========================================================================

    @model_validator(mode="after")
    def _default_celery_urls(self) -> Self:
        """
        Default Celery broker and result backend to REDIS_URL when not explicitly set.
        This means a minimal .env only needs REDIS_URL — Celery works automatically.
        """
        if self.CELERY_BROKER_URL is None:
            self.CELERY_BROKER_URL = self.REDIS_URL
        if self.CELERY_RESULT_BACKEND is None:
            self.CELERY_RESULT_BACKEND = self.REDIS_URL
        return self

    @model_validator(mode="after")
    def _validate_llm_credentials(self) -> Self:
        """
        Fail fast if the required credential for the active LLM provider is absent.
        Uses match/case so adding a new provider means adding one new case block.
        """
        match self.LLM_PROVIDER:
            case LLMProvider.OPENAI:
                if self.OPENAI_API_KEY is None:
                    raise ValueError(
                        "OPENAI_API_KEY must be set when LLM_PROVIDER=openai"
                    )
            case LLMProvider.ANTHROPIC:
                if self.ANTHROPIC_API_KEY is None:
                    raise ValueError(
                        "ANTHROPIC_API_KEY must be set when LLM_PROVIDER=anthropic"
                    )
            case LLMProvider.AZURE:
                missing = [
                    name for name, value in {
                        "AZURE_OPENAI_API_KEY":    self.AZURE_OPENAI_API_KEY,
                        "AZURE_OPENAI_ENDPOINT":   self.AZURE_OPENAI_ENDPOINT,
                        "AZURE_OPENAI_DEPLOYMENT": self.AZURE_OPENAI_DEPLOYMENT,
                    }.items()
                    if value is None
                ]
                if missing:
                    raise ValueError(
                        f"These must be set when LLM_PROVIDER=azure: "
                        f"{', '.join(missing)}"
                    )
            case LLMProvider.OLLAMA:
                pass  # No credentials required for local Ollama
            case LLMProvider.GOOGLE_GENAI:
                if self.GOOGLE_API_KEY is None:
                    raise ValueError(
                        "GOOGLE_API_KEY must be set when LLM_PROVIDER=google_genai"
                    )
        return self

    @model_validator(mode="after")
    def _validate_s3_credentials(self) -> Self:
        """Fail fast if S3 artifact store is configured but credentials are missing."""
        if self.ARTIFACT_STORE_TYPE == ArtifactStoreType.S3:
            missing = [
                name for name, value in {
                    "S3_BUCKET":             self.S3_BUCKET,
                    "S3_REGION":             self.S3_REGION,
                    "AWS_ACCESS_KEY_ID":     self.AWS_ACCESS_KEY_ID,
                    "AWS_SECRET_ACCESS_KEY": self.AWS_SECRET_ACCESS_KEY,
                }.items()
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"These must be set when ARTIFACT_STORE_TYPE=s3: "
                    f"{', '.join(missing)}"
                )
        return self

    @model_validator(mode="after")
    def _validate_http_transport(self) -> Self:
        """Fail fast if HTTP MCP transport is configured without an API key."""
        if self.MCP_TRANSPORT == MCPTransport.HTTP and self.MCP_API_KEY is None:
            raise ValueError(
                "MCP_API_KEY must be set when MCP_TRANSPORT=http"
            )
        return self


# ---------------------------------------------------------------------------
# Cached singleton accessor
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the application settings singleton.

    Built once on first call. All subsequent calls return the same cached instance.

    In tests, clear the cache before patching environment variables
    to force a fresh Settings instantiation:

        from config.settings import get_settings
        get_settings.cache_clear()
    """
    return Settings()