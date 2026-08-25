"""Slack History Fetcher — grounding data source for Context Builder.

Optional enrichment source. If SLACK_API_TOKEN is not configured,
this fetcher returns an empty result without marking slack as a missing source.
If the token is present but the API call fails, it IS marked as missing.

All Slack content is wrapped in <untrusted_data source="slack_history"> in the prompt
to prevent prompt-injection from crafted Slack messages.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

_SLACK_SEARCH_URL = "https://slack.com/api/search.messages"
_MAX_RESULTS = 10


@dataclass
class SlackThread:
    """A single Slack message/thread result."""

    thread_ts: str
    channel: str
    permalink: str
    snippet: str          # max 300 chars, from Slack API text field
    matched_pattern: str  # the query that produced this result


def _extract_error_pattern(root_cause_summary: str) -> str:
    """Extract the most specific error phrase from a root cause summary.

    Takes the first 60 characters of the summary, strips problematic
    characters, and returns a sanitised search query.
    """
    # Remove prompt-injection-suspicious patterns before passing to API
    clean = re.sub(r"[<>\"'`\\]", " ", root_cause_summary)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:60]


def search_slack_history(
    service: str,
    error_pattern: str,
    *,
    slack_token: Optional[str] = None,
    time_window: str = "7d",
    timeout_s: float = 8.0,
) -> Tuple[List[SlackThread], bool]:
    """Search Slack for messages related to a service error pattern.

    Args:
        service: Service name (e.g. "auth-service").
        error_pattern: Error phrase extracted from root cause summary.
        slack_token: Slack API token with search:read scope.
                     Falls back to SLACK_API_TOKEN env var.
        time_window: Not directly sent to API — used to label matched_pattern.
        timeout_s: Request timeout in seconds.

    Returns:
        (threads, is_missing_source):
        - threads: list of SlackThread objects (may be empty)
        - is_missing_source: True only when token is set but API call fails.
          False when token is absent (optional enrichment, not a missing source).
    """
    token = slack_token or os.getenv("SLACK_API_TOKEN", "")
    if not token:
        # Token not configured — Slack is an optional enrichment source.
        # Do not mark as missing; simply return empty.
        logger.debug("search_slack_history: SLACK_API_TOKEN not configured, skipping Slack search")
        return [], False

    query = f"{service} {_extract_error_pattern(error_pattern)}"
    matched_pattern = query

    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.get(
                _SLACK_SEARCH_URL,
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "query": query,
                    "count": _MAX_RESULTS,
                    "sort": "timestamp",
                    "sort_dir": "desc",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok"):
                logger.warning(
                    "search_slack_history: Slack API returned ok=false: %s", data.get("error")
                )
                return [], True

            messages = data.get("messages", {}).get("matches", [])
            threads: List[SlackThread] = []
            for msg in messages:
                text = msg.get("text", "")
                # Truncate to 300 chars — enough context, not so much that it
                # dominates the prompt with potentially adversarial content
                snippet = text[:300]
                threads.append(
                    SlackThread(
                        thread_ts=msg.get("ts", ""),
                        channel=msg.get("channel", {}).get("name", ""),
                        permalink=msg.get("permalink", ""),
                        snippet=snippet,
                        matched_pattern=matched_pattern,
                    )
                )

            return threads, False

    except httpx.TimeoutException as exc:
        logger.warning("search_slack_history: timeout: %s", exc)
        return [], True
    except httpx.HTTPStatusError as exc:
        logger.warning("search_slack_history: HTTP error %s: %s", exc.response.status_code, exc)
        return [], True
    except Exception as exc:
        logger.warning("search_slack_history: unexpected error: %s", exc)
        return [], True
