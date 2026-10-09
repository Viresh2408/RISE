# Stitch — Pending Generation Prompts (staged, ready to fire verbatim)

**Visual language:** LIVING SUBSTRATE + THE SPINE — premium, enterprise-grade autonomous
incident-command environment. ONE coherent design system (RISE "Antigravity"); do NOT
introduce a second theme, do NOT restart the design system, do NOT redesign canonical screens.

**Write-path status (2026-09-28, latest):** `generate_screen_from_text` is DOWN. Fired the
Operations Analytics prompt below (per the user's explicit "generate one at a time" brief) →
"The operation timed out"; verified via `list_screens` immediately after — the screen did NOT
register. Recurs the prior-session outage. Per the brief's rule ("if generation fails/times
out: STOP, do not rapidly retry"), the loop is paused. READ path (`list_screens`/`get_project`)
healthy. **No duplicates:** none of the four surfaces exist yet (checked 2026-09-28).

## Fire parameters (all four)
- `projectId`: `13472080743180234873`
- `designSystem`: `assets/ba9cc48972bf4a02800ab3e11b1f62a9`  (RISE Antigravity)
- `deviceType`: `DESKTOP`
- Order: 1) Operations Analytics  2) Policy Engine  3) Knowledge/Runbooks  4) Integrations.
- After EACH success: verify it registered (`list_screens`) — do NOT assume success or
  fabricate IDs; surface `outputComponents`; download HTML + screenshot to `.stitch/designs/`;
  update `.stitch/metadata.json` (add screen id + drop the route from `coverageGaps.routes`).

## Shared shell (every prompt embeds this — keeps the four cohesive)
- **Left console rail:** persistent vertical nav; RISE wordmark top; lifecycle sections
  (Command Center, Active Incidents, Analytics, Policy Engine, Knowledge, Integrations) with the
  current one highlighted; user/tenant marker pinned bottom.
- **Top command bar:** page title + honest subtitle + primary action(s).
- **Elevation:** restrained Layer 0–4 depth; a calm base substrate with panels raised onto
  distinct layers. Dimensionality/2.5D ONLY where it aids comprehension — never decorative 3D,
  no particles/globes/neon/excessive glass or gradients.
- **The Spine:** the incident-lifecycle rhythm is the recurring visual signature; use it only
  where it carries semantic value, never forced.
- **Responsive:** desktop-first, degrading intentionally to 1280 / 1024 / 768 / 390. Mobile is
  purpose-built (rail collapses to drawer/bottom nav; content reflows to one column), never a
  shrunken desktop.

## Honesty invariants (do NOT restyle away — governing rule: never more confident than evidence)
- Values in existing screens are DESIGN REFERENCES; invent no telemetry, confidence, latency,
  IDs, agent names, counts, audit records, GitHub state, or outcomes.
- Unavailable data renders as one of: "—", "Not computed", "Insufficient evidence",
  "Unavailable", "No data" — never a zero or fabricated figure.
- Load failures show an honest error banner (never a silent demo/sample fallback).
- No fabricated benchmark/accuracy claims anywhere.

---

## PROMPT 1 — Operations Analytics / Reports  (Midnight surface)

Design a desktop Operations Analytics surface for an autonomous incident-remediation platform.
This is a read-only retrospective view over resolved incident activity — an operator reviews
how the system has performed, not a live incident.

**PLATFORM:** Web, desktop-first.

**PAGE STRUCTURE:**
1. **Left console rail (shared shell):** persistent vertical navigation; product wordmark at
   top; lifecycle sections — Command Center, Active Incidents, Analytics, Policy Engine,
   Knowledge, Integrations — with **Analytics** highlighted as current; a user/tenant marker
   pinned at the bottom.
2. **Top command bar:** title "Operations Analytics"; honest subtitle describing a retrospective
   window; a relative time-range control reading "Last 30 days" (with alternates like 7d / 90d /
   custom); a secondary "Export" affordance. No live/streaming indicator — this is historical.
3. **Honest-state region (directly under the command bar):** a single slot that renders exactly
   one of: an error banner ("Analytics data could not be loaded" with a retry) OR a neutral empty
   note ("No resolved incidents in this window") OR the populated content below. When a metric is
   not computable it shows "—" or "Not computed", never a zero.
4. **KPI row — four cards on one Layer-2 shelf:** (a) Mean time to remediation; (b) Incident
   volume; (c) Auto-remediation rate; (d) Human-approval rate. Each card = label, a large value
   slot that can fall back to "—", and a small relative-delta line that can read "Not computed".
   No benchmark or accuracy claim anywhere on these cards.
5. **Trend region (two panels):** a line panel "Time to remediation over time" and an area panel
   "Incident volume over time". Each panel has its own honest empty/insufficient-data state
   ("Insufficient evidence to plot").
6. **Distribution region (two panels):** a horizontal bar panel "Severity distribution" and a
   donut panel "Autonomy mix" (auto-remediated vs human-approved vs manual handoff). Legends use
   the canonical severity/outcome status vocabulary.
7. **Detail table — "Affected services":** columns for service, incident count, median time to
   remediation, and dominant outcome; empty cells render "—". Sortable headers; paginated.

**DEPTH & MOTION:** restrained Layer 0–4 elevation — base substrate, raised shelves for KPI and
chart panels; subtle hover elevation on cards and rows only. No decorative 3D, particles, or
glows.

**RESPONSIVE:** at 1280 the KPI row stays 4-up and charts go 2-up; at 1024 KPIs wrap 2×2 and
charts stack; at 768 the rail collapses to a drawer and all panels are single-column; at 390 it
is a purpose-built mobile stack (KPIs as a vertical list, charts full-width, table becomes
stacked rows), not a shrunken desktop.

---

## PROMPT 2 — Policy Engine  (Midnight surface, admin)

Design a desktop Policy Engine surface for an autonomous incident-remediation platform. Its job
is to make the governance model legible: it shows how a proposed remediation action is judged by
TWO DISTINCT LAYERS and when a human must approve. This is an admin/governance view. There is NO
autopilot toggle and NO global "enable auto-execution" switch anywhere on this page.

**PLATFORM:** Web, desktop-first.

**PAGE STRUCTURE:**
1. **Left console rail (shared shell):** as defined above, **Policy Engine** highlighted.
2. **Top command bar:** title "Policy Engine"; honest subtitle; primary action "New policy"
   (admin only) and a secondary "Simulate an action" affordance.
3. **The two-layer model — the centerpiece, presented as a left-to-right Spine:** two clearly
   separated, labeled columns/stages that an action flows through in order:
   - **Stage A — Real-time policy evaluation (upstream, in the Risk Engine):** evaluates the
     action against governance policies and yields a risk tier and a policy decision. Show that
     this stage can be **UNAVAILABLE**, and that when it is, the system **FAILS CLOSED** — every
     action then requires human approval. Label this stage as policy evaluation; do NOT call the
     other layer "policy" or "OPA".
   - **Stage B — Static tool allow-list (defense-in-depth):** a fixed allow-list check applied at
     execution. Present it explicitly as a secondary safety net that is SEPARATE from Stage A —
     not the same mechanism, not a policy engine.
   Between and after the stages, show the resolved states as status chips using the canonical
   vocabulary: **risk tier**, **policy decision (allow / requires approval / blocked)**,
   **approval requirement**, **fail-closed**, **blocked action**, **policy-evaluation-unavailable**.
   Make explicit (in copy, honestly) that **critical-risk actions and any plan lacking a rollback
   strategy always require human approval** and cannot be auto-executed.
4. **Policy list (Layer-2 table):** columns for action pattern, environment, risk tier, and
   "requires approval" (shown as a read state, not a live master switch). Honest empty state
   ("No policies defined") and honest error banner. Critical-tier rows visibly indicate approval
   is mandatory and locked.
5. **Right detail / simulate panel:** selecting a policy or running "Simulate an action" shows the
   step-by-step verdict through Stage A then Stage B, ending in the approval requirement. All
   values are illustrative of structure — no fabricated live evaluation numbers, latencies, or
   audit IDs; unknown fields render "—" / "Not computed".

**DEPTH & MOTION:** the two stages sit on distinct elevation layers so the hand-off reads
spatially; connector lines carry the Spine motif. Restrained depth only; no decorative 3D.

**RESPONSIVE:** at 1280 the two stages stay side-by-side with the list below; at 1024 the detail
panel docks under the Spine; at 768 the rail collapses and the two stages stack vertically with
the connector rotating to top-to-bottom; at 390 a purpose-built stack — Spine as a vertical
stepper, list as cards.

---

## PROMPT 3 — Knowledge / Runbooks  (light Day-Mode reading surface)

Design a desktop Knowledge & Runbooks surface for an autonomous incident-remediation platform.
This is the calm reading/reference surface of the product — a searchable library of runbooks and
past-incident knowledge that the investigation stages draw on. It reads like documentation, not a
dense operations console.

**PLATFORM:** Web, desktop-first.

**PAGE STRUCTURE:**
1. **Left console rail (shared shell):** as defined above, **Knowledge** highlighted.
2. **Top command bar:** title "Knowledge & Runbooks"; honest subtitle; a prominent search field;
   primary action "New entry" (for authorized users).
3. **Filter/browse strip:** filter by type (runbook, postmortem, reference) and by tag/service;
   filters reflect only what exists — no fabricated category counts.
4. **Results region — a readable list of entry cards:** each card shows title, type, a short
   excerpt, tags, and a provenance/last-updated line. Where an entry links back to the incidents
   it was derived from, show that as a relationship link (the knowledge-to-evidence tie). Missing
   metadata renders "—"; do not invent authors, dates, or match scores.
5. **Honest states:** an empty state ("No entries match" / "No knowledge entries yet") and an
   error banner ("Knowledge base could not be loaded" with retry) — never a demo/sample fallback.
6. **Reading view (detail):** opening an entry shows a spacious document layout — title, metadata
   header, body with headings and code/technical blocks, and a "Related incidents / evidence"
   sidebar. Any similarity/match indicators only appear when genuinely present; otherwise the
   sidebar states "No linked evidence" rather than showing a fabricated score.

**DEPTH & MOTION:** lighter, flatter than the Midnight consoles — gentle Layer 0–2 elevation,
generous whitespace, comfortable reading measure. Restrained depth; no decorative 3D.

**RESPONSIVE:** at 1280 a two-column browse (filters + results); at 1024 filters collapse into a
top bar; at 768 the rail becomes a drawer and results are single-column; at 390 a purpose-built
reading stack with search pinned and the reading view full-width.

---

## PROMPT 4 — Integrations  (Midnight surface, admin)

Design a desktop Integrations surface for an autonomous incident-remediation platform. It manages
the external systems the platform connects to (source control, chat/notifications, cloud/tool
servers, observability). The surface must be scrupulously honest about connection reality — it
must NEVER imply a live connection that does not exist.

**PLATFORM:** Web, desktop-first.

**PAGE STRUCTURE:**
1. **Left console rail (shared shell):** as defined above, **Integrations** highlighted.
2. **Top command bar:** title "Integrations"; honest subtitle; primary action "Add integration".
3. **Integration grid (Layer-2 cards), one card per external system.** Each card carries an
   explicit connection state chip using EXACTLY this vocabulary, visually distinct from each
   other: **CONNECTED**, **DEGRADED**, **DISCONNECTED**, **NOT CONFIGURED**, **UNAVAILABLE**. Each
   card also shows:
   - **Auth state** (e.g., authorized / expired / none) — honest, no assumed success.
   - **Last sync** timestamp when available; otherwise "—" / "No data". Never invent a time.
   - A **config entry point** (Configure / Connect) appropriate to the state — NOT CONFIGURED
     shows a setup CTA; DISCONNECTED/DEGRADED shows a **Reconnect** flow.
   - A **failure state** line for DEGRADED/UNAVAILABLE explaining honestly what is wrong (no
     fabricated error codes).
   The card must not show live throughput/metrics for a system that isn't CONNECTED.
4. **Connect / reconnect flow (panel or modal):** initiating a connection shows a real handoff —
   an OAuth/redirect-style step to the external provider — rather than a fake in-app credential
   capture that silently succeeds. Copy is honest about redirecting off-platform; on return the
   card reflects the true resulting state.
5. **Honest page states:** an error banner if the integrations list itself fails to load, and an
   empty state ("No integrations configured") — never a demo roster of pre-connected services.

**DEPTH & MOTION:** restrained Layer 0–4; cards lift slightly on hover; state chips are the loud
element, not the chrome. No decorative 3D, no neon.

**RESPONSIVE:** at 1280 a 3-up card grid; at 1024 2-up; at 768 the rail collapses to a drawer and
cards go 1-up; at 390 a purpose-built vertical stack with the state chip and primary action
prominent per card.
