"""Usage logging for the LLM Gateway.

Writes one ``LLMUsageLog`` row per provider call (including repair calls and
failed calls).  Write failures are caught and printed to stderr — observability
must never break the call path.

The ``llm_usage_log`` table is created by Alembic migration 0004.
"""

from __future__ import annotations

import hashlib
import sys
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class LLMUsageLog(Base):
    """One row per LLM call (primary attempt or repair attempt)."""

    __tablename__ = "llm_usage_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Which provider handled (or attempted) this call.
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    # SHA-256 of the prompt — avoids storing PII/secret data in the row.
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Estimated cost in USD; 0.0 if provider pricing is unknown.
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # "provider_error" | "validation_error" | "repair_failed" | None
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # True when this row is a repair (second) attempt rather than the first call.
    is_repair_attempt: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _sha256(text_: str) -> str:
    return hashlib.sha256(text_.encode("utf-8")).hexdigest()


def record_usage(
    db: "Session | None",
    *,
    provider: str,
    model: str,
    prompt: str,
    input_tokens: int,
    output_tokens: int,
    cost_per_input_token: float,
    cost_per_output_token: float,
    latency_ms: int,
    success: bool,
    error_type: str | None = None,
    is_repair_attempt: bool = False,
) -> None:
    """Write a usage row.  Silently swallows DB errors so they never propagate."""
    if db is None:
        return
    cost_usd = (
        input_tokens * cost_per_input_token + output_tokens * cost_per_output_token
    )
    row = LLMUsageLog(
        provider=provider,
        model=model,
        prompt_hash=_sha256(prompt),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        success=success,
        error_type=error_type,
        is_repair_attempt=is_repair_attempt,
        called_at=datetime.now(timezone.utc),
    )
    try:
        db.add(row)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        print(
            f"[llm_gateway] WARNING: failed to write usage log row: {exc}",
            file=sys.stderr,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
