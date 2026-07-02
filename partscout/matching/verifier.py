# -*- coding: utf-8 -*-
from __future__ import annotations

import logging

from partscout.extraction.llm import VERIFICATION_TOOL, LLMClient
from partscout.extraction.prompts import VERIFICATION_SYSTEM, VERIFICATION_USER_TEMPLATE

logger = logging.getLogger(__name__)


class MatchVerifier:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def verify(self, wtb_text: str, fs_text: str) -> tuple[str, str]:
        """Call LLM to verify a candidate match pair.

        Returns (verdict, reason) where verdict is 'match' | 'likely' | 'no'.
        On failure returns ('no', 'verification error') so the pair is stored
        and not re-verified.
        """
        user = VERIFICATION_USER_TEMPLATE.format(wtb_text=wtb_text, fs_text=fs_text)
        try:
            result = self._client.call(
                system=VERIFICATION_SYSTEM,
                user=user,
                tool=VERIFICATION_TOOL,
            )
            verdict = str(result.get("verdict", "no"))
            reason = str(result.get("reason", ""))
            logger.debug("LLM verdict=%s reason=%s", verdict, reason)
            return verdict, reason
        except Exception:
            logger.exception("LLM verification failed")
            return "no", "verification error"
