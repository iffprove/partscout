# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class EmbeddingConfig:
    provider: str  # "voyage" | "openai_compatible"
    model: str
    api_key: str
    base_url: str | None = None
    dimensions: int = 1024


@dataclass
class LLMConfig:
    provider: str  # "anthropic" | "openai_compatible"
    model: str
    api_key: str
    base_url: str | None = None  # required for openai_compatible
    max_retries: int = 5


@dataclass
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    from_addr: str
    to_addrs: list[str]
    use_tls: bool = True


@dataclass
class SourceConfig:
    name: str
    adapter_class_path: str  # dotted import path
    base_url: str
    poll_interval_seconds: int
    enabled: bool
    country: str
    kind: str  # "fs" | "wtb" | "both"
    extra: dict[str, str] = field(default_factory=dict)


def get_embedding_config() -> EmbeddingConfig | None:
    api_key = os.environ.get("VOYAGE_API_KEY") or os.environ.get("EMBEDDING_API_KEY")
    if not api_key:
        return None
    return EmbeddingConfig(
        provider=os.environ.get("EMBEDDING_PROVIDER", "voyage"),
        model=os.environ.get("EMBEDDING_MODEL", "voyage-3"),
        api_key=api_key,
        base_url=os.environ.get("EMBEDDING_BASE_URL"),
    )


def get_llm_config() -> LLMConfig:
    provider = os.environ.get("LLM_PROVIDER", "anthropic")
    return LLMConfig(
        provider=provider,
        model=os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001"),
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        base_url=os.environ.get("LLM_BASE_URL"),
        max_retries=int(os.environ.get("LLM_MAX_RETRIES", "5")),
    )


def get_smtp_config() -> SMTPConfig:
    to_raw = os.environ.get("SMTP_TO", "")
    return SMTPConfig(
        host=os.environ.get("SMTP_HOST", "localhost"),
        port=int(os.environ.get("SMTP_PORT", "587")),
        username=os.environ.get("SMTP_USERNAME", ""),
        password=os.environ.get("SMTP_PASSWORD", ""),
        from_addr=os.environ.get("SMTP_FROM", "partscout@localhost"),
        to_addrs=[a.strip() for a in to_raw.split(",") if a.strip()],
        use_tls=os.environ.get("SMTP_TLS", "true").lower() == "true",
    )


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return url


SOURCE_REGISTRY: list[SourceConfig] = [
    SourceConfig(
        name="nettimoto",
        adapter_class_path="partscout.adapters.nettimoto.NettimotoAdapter",
        base_url="https://www.nettivaraosa.com/en/moottoripyoran-varaosat-ja-tarvikkeet",
        poll_interval_seconds=1800,  # 30 min
        enabled=True,
        country="FI",
        kind="fs",
    ),
    SourceConfig(
        name="biker_ee",
        adapter_class_path="partscout.adapters.biker_ee.BikerEeAdapter",
        base_url="https://biker.ee/phpbb/viewforum.php?f=90",
        poll_interval_seconds=7200,  # 2 h
        enabled=True,
        country="EE",
        kind="both",
    ),
    SourceConfig(
        name="tori",
        adapter_class_path="partscout.adapters.tori.ToriAdapter",
        base_url="https://www.tori.fi/recommerce/forsale/search",
        poll_interval_seconds=1800,  # 30 min
        enabled=True,
        country="FI",
        kind="fs",
    ),
    SourceConfig(
        name="ss_lv",
        adapter_class_path="partscout.adapters.ss_lv.SsLvAdapter",
        base_url="https://www.ss.lv/lv/transport/moto-transport/spare-parts/other-parts/",
        poll_interval_seconds=1800,  # 30 min
        enabled=True,
        country="LV",
        kind="both",
    ),
]
