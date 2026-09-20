# Sample Security Logs — `eval/sample_security_logs/`

Synthetic security log datasets for demo and evaluation of the
`POST /ingest/security-log` endpoint.  All IP addresses and hostnames are
fictitious (RFC 5737 / RFC 3849 ranges).

---

## Files

| File | Format | Threat Type | Records |
|---|---|---|---|
| [`ssh_bruteforce.csv`](./ssh_bruteforce.csv) | CSV | SSH brute-force credential stuffing | 12 |
| [`port_scan.json`](./port_scan.json) | JSON array | Horizontal port scan / firewall denies | 10 |
| [`sql_injection.csv`](./sql_injection.csv) | CSV | WAF/IDS SQL injection alerts | 8 |
| [`anomalous_outbound.json`](./anomalous_outbound.json) | JSON array | Anomalous outbound data volume / exfiltration | 6 |

---

## Field Reference

### CSV files (`ssh_bruteforce.csv`, `sql_injection.csv`)

| Field | Description |
|---|---|
| `timestamp` | ISO-8601 UTC event time |
| `src_ip` | Source IP address |
| `dst_ip` | Destination IP address |
| `src_port` / `dst_port` | Transport ports |
| `protocol` | TCP / UDP |
| `action` | `failed_auth`, `alert`, `deny`, `allow` |
| `event_type` | Normalised RISE event category |
| `host` | Sensor / host that generated the log |
| `user` | Account targeted or involved |
| `severity` | Raw severity from the source sensor |
| `message` | Human-readable log message |

### JSON files (`port_scan.json`, `anomalous_outbound.json`)

Same fields as CSV, plus:

| Field | Description |
|---|---|
| `bytes_out` | Outbound bytes in the flow |
| `bytes_in` | Inbound bytes in the flow |
| `duration_sec` | Flow duration in seconds |
| `process` | Process name on the source host |

---

## Demo: Upload via curl

> **Prerequisites**: API running on `http://localhost:8000`, valid JWT token.

### File upload (CSV)

```bash
TOKEN="<your-jwt-token>"

curl -s -X POST http://localhost:8000/ingest/security-log \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@eval/sample_security_logs/ssh_bruteforce.csv" \
  | python -m json.tool
```

### File upload (JSON)

```bash
curl -s -X POST http://localhost:8000/ingest/security-log \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@eval/sample_security_logs/port_scan.json" \
  | python -m json.tool
```

### Dry-run (validate without writing to DB)

```bash
curl -s -X POST http://localhost:8000/ingest/security-log \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@eval/sample_security_logs/sql_injection.csv" \
  -F "dry_run=true" \
  | python -m json.tool
```

### JSON body variant

```bash
curl -s -X POST http://localhost:8000/ingest/security-log/json \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "lines": [
      "Sep  1 02:01:03 prod-bastion-01 sshd[12345]: Failed password for root from 185.220.101.47 port 54321 ssh2",
      "Sep  1 02:01:09 prod-bastion-01 sshd[12345]: Failed password for root from 185.220.101.47 port 54322 ssh2"
    ],
    "dry_run": false
  }' \
  | python -m json.tool
```

---

## Expected Response Shape

```json
{
  "data": {
    "processed": 12,
    "incidents_created": 8,
    "deduplicated": 3,
    "queued_dlq": 0,
    "dry_run_skipped": 0,
    "errors": 1,
    "results": [
      {
        "line_index": 0,
        "status": "created",
        "incident_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "summary": "SSH brute-force: 12 failed auth attempts from 185.220.101.47 targeting prod-bastion-01"
      },
      {
        "line_index": 1,
        "status": "deduplicated",
        "incident_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
      }
    ]
  },
  "meta": {
    "request_id": "...",
    "timestamp": "2026-09-01T02:00:00Z"
  },
  "error": null
}
```

---

## Threat Scenarios Covered

### SSH Brute-Force (`ssh_bruteforce.csv`)
- Single source IP (`185.220.101.47`) attempting 12 auth failures in ~65 seconds
- Targets multiple common usernames: `root`, `admin`, `ubuntu`, `postgres`, `ec2-user`
- Matches MITRE ATT&CK **T1110.001** — Brute Force: Password Guessing

### Port Scan (`port_scan.json`)
- Single source IP (`203.0.113.88`) probing 10 well-known service ports in 5 seconds
- Hits databases (MySQL/Postgres/Redis), SSH, HTTP/S, Elasticsearch
- Matches MITRE ATT&CK **T1046** — Network Service Discovery

### SQL Injection (`sql_injection.csv`)
- Single source IP (`91.108.4.130`) with 8 injection variants over 26 seconds
- Covers: boolean-based, UNION-based, stacked queries, time-based blind, `xp_cmdshell`
- Matches MITRE ATT&CK **T1190** — Exploit Public-Facing Application

### Anomalous Outbound Data Volume (`anomalous_outbound.json`)
- Two compromised hosts exfiltrating data to unknown external IPs
- `worker-node-07`: 225 MB HTTPS to `198.51.100.42` over ~3 minutes (staged exfil pattern)
- `db-replica-02`: `pg_dump` process sending 90 MB to external IP (suspected credential DB dump)
- `worker-node-07`: 5 MB DNS UDP traffic (DNS tunneling pattern)
- Matches MITRE ATT&CK **T1041** — Exfiltration Over C2 Channel
