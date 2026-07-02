# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import smtplib
from datetime import UTC, datetime
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from partscout.config import SMTPConfig
from partscout.db.models import ListingRecord, MatchRecord

logger = logging.getLogger(__name__)


def build_digest(session: Session) -> str:
    """Build plaintext digest of unnotified matches."""
    unnotified: list[MatchRecord] = (
        session.query(MatchRecord).filter(MatchRecord.notified_at.is_(None)).all()
    )

    if not unnotified:
        return "PartScout digest: no new matches today.\n"

    lines = [
        f"PartScout Match Digest — {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"New matches: {len(unnotified)}",
        "=" * 60,
        "",
    ]

    for match in unnotified:
        wtb = session.get(ListingRecord, match.wtb_id)
        fs = session.get(ListingRecord, match.fs_id)
        if not wtb or not fs:
            continue

        lines += [
            f"Match #{match.id}  tier={match.tier}  score={match.score:.2f}",
            f"  WTB: {wtb.item_name_en}  [{wtb.country or '??'}]",
            f"       {wtb.raw_post.url if wtb.raw_post else ''}",
            f"   FS: {fs.item_name_en}  [{fs.country or '??'}]",
            f"       {fs.raw_post.url if fs.raw_post else ''}",
        ]
        if match.llm_verdict:
            lines.append(f"  LLM verdict: {match.llm_verdict}")
        lines.append("")

    return "\n".join(lines)


def send_digest(session: Session, smtp_cfg: SMTPConfig) -> None:
    if not smtp_cfg.to_addrs:
        logger.warning("No SMTP_TO configured — skipping digest email")
        return

    body = build_digest(session)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = (
        f"PartScout digest {datetime.now(UTC).strftime('%Y-%m-%d')}"
    )
    msg["From"] = smtp_cfg.from_addr
    msg["To"] = ", ".join(smtp_cfg.to_addrs)

    try:
        if smtp_cfg.use_tls:
            with smtplib.SMTP_SSL(smtp_cfg.host, smtp_cfg.port) as server:
                server.login(smtp_cfg.username, smtp_cfg.password)
                server.sendmail(smtp_cfg.from_addr, smtp_cfg.to_addrs, msg.as_string())
        else:
            with smtplib.SMTP(smtp_cfg.host, smtp_cfg.port) as server:
                if smtp_cfg.username:
                    server.starttls()
                    server.login(smtp_cfg.username, smtp_cfg.password)
                server.sendmail(smtp_cfg.from_addr, smtp_cfg.to_addrs, msg.as_string())

        # Mark as notified
        now = datetime.now(UTC)
        unnotified: list[MatchRecord] = (
            session.query(MatchRecord).filter(MatchRecord.notified_at.is_(None)).all()
        )
        for m in unnotified:
            m.notified_at = now
        session.commit()
        logger.info("Digest sent to %s", smtp_cfg.to_addrs)
    except Exception:
        logger.exception("Failed to send digest email")
