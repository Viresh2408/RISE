"""Security Log Normalizer — deterministic pre-processor for the ingest pipeline.

Converts raw security log text (JSON array, newline-delimited JSON, CSV, or
plain syslog lines) into a list of structured dicts that can be passed directly
to ``run_ingestion_agent`` as ``raw_payload``.

Design goals
------------
- **Format-agnostic**: auto-detects JSON vs CSV vs plain text so callers never
  need to know the format ahead of time.
- **LLM-cheap**: structured, labelled dicts reduce the token footprint sent to
  the Ingestion Agent versus raw unstructured text.
- **Security-safe**: no execution of log content; fields are copied verbatim
  with no ``eval``/``exec``.  The agent still wraps everything in
  ``<untrusted_data>`` tags before the LLM sees it.
- **Lossless**: the original raw line is always preserved in ``_raw_text`` so
  the DLQ can replay it.

Supported formats
-----------------
JSON
  Either a top-level JSON array ``[{...}, ...]`` or one JSON object per line
  (newline-delimited JSON / NDJSON).

CSV
  Any delimiter-separated file with a header row.  Common security log field
  aliases are normalised to canonical names (see ``_CSV_FIELD_ALIASES``).

Plain text / syslog
  Each non-empty line is treated as an opaque log line and wrapped in a dict
  with a ``message`` key plus basic parsed fields extracted via regex
  (timestamp, host, process, PID).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field alias map — normalise CSV column names to canonical keys
# ---------------------------------------------------------------------------

_CSV_FIELD_ALIASES: Dict[str, str] = {
    # timestamps
    "timestamp": "timestamp",
    "time": "timestamp",
    "datetime": "timestamp",
    "date_time": "timestamp",
    "event_time": "timestamp",
    "@timestamp": "timestamp",
    # source IP / host
    "src_ip": "src_ip",
    "source_ip": "src_ip",
    "srcip": "src_ip",
    "client_ip": "src_ip",
    "remote_addr": "src_ip",
    "ip": "src_ip",
    # destination
    "dst_ip": "dst_ip",
    "dest_ip": "dst_ip",
    "destination_ip": "dst_ip",
    "dstip": "dst_ip",
    # ports
    "src_port": "src_port",
    "source_port": "src_port",
    "srcport": "src_port",
    "dst_port": "dst_port",
    "dest_port": "dst_port",
    "dstport": "dst_port",
    "port": "dst_port",
    # action / result
    "action": "action",
    "result": "action",
    "outcome": "action",
    "disposition": "action",
    # protocol
    "protocol": "protocol",
    "proto": "protocol",
    # message / description
    "message": "message",
    "msg": "message",
    "description": "message",
    "log_message": "message",
    "event": "message",
    "alert": "message",
    # user / account
    "user": "user",
    "username": "user",
    "account": "user",
    "login": "user",
    # host / device
    "host": "host",
    "hostname": "host",
    "device": "host",
    "server": "host",
    # event type / category
    "event_type": "event_type",
    "type": "event_type",
    "category": "event_type",
    "log_type": "event_type",
    # severity
    "severity": "severity",
    "priority": "severity",
    "level": "severity",
    # bytes / volume
    "bytes": "bytes_out",
    "bytes_out": "bytes_out",
    "tx_bytes": "bytes_out",
    "data_volume": "bytes_out",
    "bytes_sent": "bytes_out",
}


# ---------------------------------------------------------------------------
# Regex patterns for plain-text syslog parsing
# ---------------------------------------------------------------------------

# Standard syslog timestamp: "Sep  1 11:20:30" or ISO "2026-09-01T11:20:30"
_SYSLOG_TIMESTAMP_RE = re.compile(
    r"^(?P<ts>"
    r"(?:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)"
    r"|(?:[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})"
    r")\s+"
)
_SYSLOG_HOST_PROCESS_RE = re.compile(
    r"(?P<host>\S+)\s+(?P<process>\w[\w\-\.]*?)(?:\[(?P<pid>\d+)\])?:\s+"
)

# SSH brute-force patterns
_SSH_FAIL_RE = re.compile(
    r"Failed (?P<auth_method>\w+) for (?:invalid user )?(?P<user>\S+) from "
    r"(?P<src_ip>\d{1,3}(?:\.\d{1,3}){3}) port (?P<src_port>\d+)"
)
_SSH_ACCEPT_RE = re.compile(
    r"Accepted (?P<auth_method>\w+) for (?P<user>\S+) from "
    r"(?P<src_ip>\d{1,3}(?:\.\d{1,3}){3}) port (?P<src_port>\d+)"
)

# Generic IP extraction fallback
_IP_RE = re.compile(r"\b(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\b")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class SecurityLogNormalizer:
    """Converts raw security log text into a list of structured payload dicts.

    Usage::

        normalizer = SecurityLogNormalizer()
        records = normalizer.parse_auto(text, filename="auth.csv")
        # records is a List[Dict] ready for run_ingestion_agent()
    """

    # Maximum number of log lines accepted per batch (caller enforces this via
    # the endpoint; the normalizer itself does not truncate — it returns all
    # records so the caller can decide).
    MAX_LINES = 1000

    def parse_auto(
        self,
        text: str,
        filename: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Detect format from *filename* extension or content heuristic and parse.

        Parameters
        ----------
        text:
            Raw file content or pasted text as a string.
        filename:
            Original upload filename (used for extension-based detection).
            May be ``None`` for pasted text.

        Returns
        -------
        List[Dict]
            One dict per log record.  Each dict always contains at minimum:
            ``_line_index`` (int), ``_raw_text`` (str), ``_format`` (str).
        """
        text = text.strip()
        if not text:
            return []

        ext = (filename or "").lower().rsplit(".", 1)[-1]

        if ext in ("json", "ndjson", "jsonl"):
            return self.parse_json(text)
        if ext in ("csv", "tsv", "log"):
            return self.parse_csv(text)

        # Content heuristic: does the first non-empty line start with '{'  or '['?
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if first_line.startswith(("{", "[")):
            return self.parse_json(text)

        # Does it look like CSV (has commas or tabs in the first line)?
        if "," in first_line or "\t" in first_line:
            # Only treat as CSV if there are at least 3 fields in the first line
            delimiter = "\t" if "\t" in first_line else ","
            if len(first_line.split(delimiter)) >= 3:
                return self.parse_csv(text)

        # Fall back to plain syslog / free-text
        return self.parse_syslog(text)

    def parse_json(self, text: str) -> List[Dict[str, Any]]:
        """Parse JSON array or newline-delimited JSON into a list of record dicts."""
        text = text.strip()
        records: List[Dict[str, Any]] = []

        # Try to parse as a single JSON value first
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                raw_records = parsed
            elif isinstance(parsed, dict):
                raw_records = [parsed]
            else:
                # Scalar JSON — wrap in a dict
                raw_records = [{"value": parsed}]
            for i, rec in enumerate(raw_records):
                if not isinstance(rec, dict):
                    rec = {"value": rec}
                rec.setdefault("_line_index", i)
                rec.setdefault("_raw_text", json.dumps(rec))
                rec["_format"] = "json"
                records.append(rec)
            return records
        except json.JSONDecodeError:
            pass  # fall through to NDJSON

        # Try newline-delimited JSON
        errors: List[str] = []
        for i, line in enumerate(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    obj = {"value": obj}
                obj.setdefault("_line_index", i)
                obj["_raw_text"] = line
                obj["_format"] = "ndjson"
                records.append(obj)
            except json.JSONDecodeError as exc:
                logger.debug("NDJSON parse error on line %d: %s", i, exc)
                errors.append(f"line {i}: {exc}")

        if not records and errors:
            logger.warning(
                "SecurityLogNormalizer: JSON parse failed for all lines (%d errors)", len(errors)
            )

        return records

    def parse_csv(self, text: str) -> List[Dict[str, Any]]:
        """Parse a CSV (or TSV) string into a list of normalised record dicts."""
        text = text.strip()
        if not text:
            return []

        # Auto-detect delimiter
        first_line = text.splitlines()[0]
        delimiter = "\t" if first_line.count("\t") > first_line.count(",") else ","

        records: List[Dict[str, Any]] = []
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

        for i, row in enumerate(reader):
            normalised: Dict[str, Any] = {}
            raw_row = dict(row)

            for col, val in raw_row.items():
                canonical = _CSV_FIELD_ALIASES.get(col.strip().lower(), col.strip().lower())
                normalised[canonical] = val.strip() if val else val

            normalised["_line_index"] = i
            normalised["_raw_text"] = delimiter.join(str(v) for v in raw_row.values())
            normalised["_format"] = "csv"
            records.append(normalised)

        return records

    def parse_syslog(self, text: str) -> List[Dict[str, Any]]:
        """Parse plain syslog / free-text lines into structured dicts.

        Applies regex patterns for SSH auth events, firewall denies, and
        generic lines.  Unknown lines are wrapped with ``message`` = the full
        line text.
        """
        records: List[Dict[str, Any]] = []
        lines = [line for line in text.splitlines() if line.strip()]

        for i, line in enumerate(lines):
            rec = self._parse_syslog_line(line)
            rec["_line_index"] = i
            rec["_raw_text"] = line
            rec["_format"] = "syslog"
            records.append(rec)

        return records

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_syslog_line(self, line: str) -> Dict[str, Any]:
        """Extract structured fields from a single syslog / free-text line."""
        rec: Dict[str, Any] = {}
        remaining = line

        # Extract timestamp
        ts_match = _SYSLOG_TIMESTAMP_RE.match(remaining)
        if ts_match:
            rec["timestamp"] = ts_match.group("ts")
            remaining = remaining[ts_match.end():]

        # Extract host + process[pid]
        hp_match = _SYSLOG_HOST_PROCESS_RE.match(remaining)
        if hp_match:
            rec["host"] = hp_match.group("host")
            rec["process"] = hp_match.group("process")
            if hp_match.group("pid"):
                rec["pid"] = hp_match.group("pid")
            remaining = remaining[hp_match.end():]

        # SSH-specific patterns
        ssh_fail = _SSH_FAIL_RE.search(remaining)
        if ssh_fail:
            rec.update(ssh_fail.groupdict())
            rec["action"] = "failed_auth"
            rec["event_type"] = "authentication_failure"
            rec["message"] = remaining.strip()
            return rec

        ssh_ok = _SSH_ACCEPT_RE.search(remaining)
        if ssh_ok:
            rec.update(ssh_ok.groupdict())
            rec["action"] = "accepted_auth"
            rec["event_type"] = "authentication_success"
            rec["message"] = remaining.strip()
            return rec

        # Keyword-based event_type hints
        lower = remaining.lower()
        if any(k in lower for k in ("denied", "deny", "block", "reject", "drop")):
            rec["event_type"] = "firewall_deny"
            rec["action"] = "deny"
        elif any(k in lower for k in ("sqli", "sql injection", "union select", "' or '", "1=1")):
            rec["event_type"] = "ids_sql_injection"
            rec["action"] = "alert"
        elif any(k in lower for k in ("scan", "probe", "port scan", "nmap")):
            rec["event_type"] = "port_scan"
            rec["action"] = "alert"
        elif any(k in lower for k in ("exfil", "outbound", "upload", "data transfer")):
            rec["event_type"] = "anomalous_outbound"
            rec["action"] = "alert"

        # Extract any IP addresses present
        ips = _IP_RE.findall(remaining)
        if ips:
            rec.setdefault("src_ip", ips[0])
            if len(ips) > 1:
                rec.setdefault("dst_ip", ips[1])

        rec["message"] = remaining.strip()
        return rec

    def enrich_with_metadata(
        self,
        records: List[Dict[str, Any]],
        *,
        upload_filename: Optional[str] = None,
        ingested_at: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Add ingestion-time metadata fields to every record.

        Parameters
        ----------
        records:
            Output of any ``parse_*`` method.
        upload_filename:
            Original upload filename for provenance tracking.
        ingested_at:
            ISO-8601 timestamp of ingestion.  Defaults to UTC now.

        Returns
        -------
        The same list, mutated in-place and returned for chaining.
        """
        ts = ingested_at or datetime.now(timezone.utc).isoformat()
        for rec in records:
            rec["_ingested_at"] = ts
            if upload_filename:
                rec["_source_file"] = upload_filename
        return records
