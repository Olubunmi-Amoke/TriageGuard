# TriageGuard

**Faster, consistent triage with humans in control. A prototype built on synthetic data.**

TriageGuard rehearses a **privacy response plan** against fictional reports:
explicit facts and unknowns, purview, privacy severity and ownership suggestions,
illustrative clocks, and approval-gated communications. A PM reviews every
suggestion and controls every workflow change.

## Positioning

**The incident platform's AI covers engineering triage. TriageGuard prototypes the
privacy triage layer, written as a response plan that existing agents could follow,
not as a separate tool.**

The existing platform already provides an AI summary ("What we know / What has
been done / Recommended actions"), a troubleshooting agent, and an SRE agent
following a markdown response plan for logs, error rates, SLOs, and deployments.
TriageGuard does not duplicate those capabilities. The Streamlit UI is a local,
interactive rehearsal of privacy-specific checks in the familiar summary layout,
not another AI summarizer or a deployed agent integration.

[The privacy response plan](docs/privacy-response-plan.md) is the deliverable
existing agents could follow after policy validation and authorized integration.
It is a **synthetic, illustrative TrIP-style exercise, not actual Microsoft/TrIP
policy or purview**, labeled **illustrative – configure to policy** along with
all clock displays, clock rationales, and exported summaries.
Every rationale includes `Rule fired: Plan §X.Y`; the
configuration maps rule names to numbered sections and validates those references
on load.
The response-plan path accepts Windows or POSIX separators and is resolved
relative to the configuration/application directory, not the shell's working
directory, so the same configuration works on Windows and Linux hosting.

IcM and the approved case system remain the systems of record. Linked synthetic
IDs and a copy-ready export demonstrate a manual handoff only. The per-incident
**Privacy lens vs. engineering lens** panel marks service-health checks as
**not applicable / not run** by this prototype, never healthy or investigated.
Legal obligations and notification decisions remain with accountable owners.

## Run locally

Use Python **3.11**. From this repository in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Open `http://127.0.0.1:8501`. If PowerShell blocks activation, use the venv
executables directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Package installation requires access to a package index; the running prototype
uses only local files and its local browser connection. No external API, LLM,
database, or messaging service is used. Streamlit usage telemetry is disabled.
Its deployment/developer toolbar is hidden. "No outbound integrations" does not
mean "no network transport": Streamlit still serves HTTP/WebSocket traffic
between the browser and the loopback-bound local server.
On Windows ARM, use **x64 Python 3.11** if native ARM dependency wheels are
unavailable; this avoids requiring a local C/C++ toolchain.

Run the tests:

```powershell
python -m pytest -q
```

## Two-minute demo

1. **Overview:** open the numbered privacy plan; explain why engineering agents
   and approved case systems stay in place.
2. Select `TG-DEMO-001` in the sidebar. In **Incident**, contrast the two lenses,
   confirm one UNKNOWN with a source note, and inspect plan-referenced
   purview, severity, and ownership suggestions.
3. Select `TG-DEMO-002`: suspected insider misuse with P1 privacy severity, FTE
   routing, privacy/legal/security reasons, breached clocks, and unresolved
   regions, volume, containment, and deletion. Generate a facts-only status
   update to show those UNKNOWNs without repeating the unverified allegation.
4. Select `TG-DEMO-003`: this is an engineering security-process
   concern, not proof of a privacy incident. Review the exclusion facts,
   accept purview and the synthetic receiving team, then generate the handoff note.
5. Review and approve the note. Approval records **Approved – ready to send
   manually**, not delivery, transfer, remediation, or closure. Export it for the
   existing case record.
6. View **Dashboard** for repeat root causes, teams, and response-clock risks.

The queue and sidebar pin **001, 002, 003** in that order. All remaining cases
retain soonest-outstanding-deadline order. Pins are a presentation convenience,
not an operational priority or a change to clock/severity rules. Configure the
pin order under `demo.pinned_incident_ids` in `config.yaml`. `TG-DEMO-019`
retains the incomplete misdirected-file scenario and `TG-DEMO-020` remains a
second engineering handoff example.

Open the full numbered plan from the **Overview** tab's **Open privacy response
plan** expander. Tables wrap text instead of requiring horizontal scrolling.
Deadline colors are green (OK), amber (at risk), and red (breached); purview uses
green (in scope), amber (needs review), and blue (engineering handoff). In scope
is a scope finding, not a safety finding.

All 20 incidents start **New**; seed loading does not pretend a human has triaged
them. Change a status to **Triaged** to populate the on-time triage metric. The
deterministic clock makes older items overdue and recent items OK or at risk.
Use **Overview → Demo controls → Reset demo data** and its confirmation checkbox
to restore the initial state, including seed facts, suggestions, initial system
audit entries, and all 20 New statuses. Reset also clears PM edits, decisions,
drafts/approvals, milestones, questions, export snapshots, and pending form values.
The restored state is persisted; a reload must not bring previous edits back.

## Rules and state

- `config.yaml` owns `demo_now`, extraction regexes, keyword indicators, severity
  and routing thresholds, stakeholders, workflow milestone mappings, clocks,
  dashboard age boundaries, and draft templates. Suggestion entry points are
  named `suggest_*`. Rule explanations, fact evidence, stakeholder reasons,
  draft rationales, and clocks trace to `response_plan.rules` section references.
- `suggest_purview()` returns **In scope**, **Out of scope – route to another
  team**, or **Needs review**. Out-of-scope requires confirmed no customer/personal
  data involvement, engineering-process-only concern, a configured non-production
  environment, exclusively non-personal internal identifiers, and zero affected
  customer records. Conflicts or protected escalation indicators prevent exclusion.
  An internal identifier alone, or absence of known personal data, is insufficient.
- `TG-DEMO-003` suggests **Demo Sandbox Engineering**; `TG-DEMO-020` suggests
  **Demo Developer Tools Engineering**. These are synthetic team names. A
  receiving-team override requires a reason. Handoff generation requires
  evidence-backed exclusion; approval additionally requires PM purview and team
  decisions. Approving the note never closes/transfers the case or declares
  engineering remediation complete. Changed facts invalidate those decisions
  and approvals. A PM override alone cannot manufacture exclusion evidence.
- Facts are **CONFIRMED** only from explicit report wording or structured known
  fields; otherwise **UNKNOWN**. Reporter-question checkboxes persist and are
  audited without confirming an answer. Extraction is conservative, not language
  understanding. Contradictions remain UNKNOWN. PM answers require a source note
  and become **CONFIRMED (by PM)**; no unchecked answer is inferred.
- P1 is the highest severity. Attack/insider indicators retain their configured
  severity floor despite containment. Containment plus deletion may reduce other
  provisional severities, but sensitive data never qualifies for the routine lane.
  Non-incident indicators suggest closure; neither accepting that suggestion nor
  generating a draft changes the workflow status.
  Engineering exclusions use a separate **Engineering handoff** lane, not the
  routine privacy queue. Needs-review cases remain FTE-owned. The routine UNKNOWN
  threshold counts the seven core facts; purview-only fields are evaluated separately.
- Every recommendation displays why and has PM acceptance/override controls.
  Template edits require a reason. Facts and decisions revoke draft approval;
  fact changes also revoke prior recommendation decisions. Status changes revoke
  status/handoff approvals but preserve an approved deletion request if its
  template content is unchanged. Status-dependent deletion templates are
  invalidated too. Regenerate stale drafts before approving them again.
- UTC business days skip Saturday and Sunday, **not holidays**. A business day
  preserves the starting time: Friday 14:00 + one business day is Monday 14:00.
  Initial triage and stakeholder update start at report time. Deletion attestation
  starts at request **approval**, deliberately not a delivery event. Follow-up
  starts at the first PM-recorded triage milestone. Closed cases stop unfinished
  clocks without inventing completion.
- An explicit notification-assessment request adds an illustrative 24-hour
  **owner-review coordination** clock. It is not a legal notification deadline.
  Without a request the clock is not applicable. Accountable owners establish
  real regulatory, contractual, or customer commitments outside this demo.
- An approved status draft does **not** complete the stakeholder-update clock.
  Record an externally completed manual action separately. Initial triage time is
  retained through later status changes. Contained status does not manufacture a
  confirmed containment fact.
- Green means OK; amber is **strictly less than 25%** of elapsed-clock allowance
  remaining by default; red means the deadline has been reached or passed.
  The fraction is configurable. The triage KPI includes only incidents with a
  recorded triage time and shows its denominator; untriaged cases are not successes.
- State lives in `st.session_state` and atomically written `data/state.json`,
  including audit before/after snapshots and the configuration snapshot. Restart
  restores edits. Invalid state fails visibly rather than silently resetting.
  After editing config, restart Streamlit and reset the demo when prompted;
  configuration changes are not silently applied to past decisions.
  **Upgrading from the earlier demo:** existing saved state is preserved and the
  app prompts for a confirmed reset because the facts/configuration changed.
  Back up `data/state.json` first if its edits matter.

## Guardrails and limitations

**Synthetic data only. Do not enter real personal, customer, credential, or
incident data.** All named companies and people in the seed are fictional.
Reporter teams, receiving teams, and stakeholder roles are illustrative, not
actual organizational assignments. Every incident and populated linked ID uses
an explicit `TG-DEMO-`, `ICM-DEMO-`, or `CASE-DEMO-` prefix. Engineering examples
describe disposable build identifiers without including an actual identifier.
Manual input is not a data-loss-prevention filter: the operator must continue
using synthetic values.

The safety banner is outside the tab containers, so Overview, Queue, Incident,
and Dashboard share it. Loading or browsing computes provisional suggestions,
but never accepts them, generates a draft, approves a communication, transfers
ownership, or closes a case. Acceptance, draft generation/approval, and status
changes require their explicit UI controls; delivery and ownership transfer
have no implementation. Previously saved PM decisions and drafts are restored,
not reapplied.

There is no delivery function or delivery transport. Approval is only metadata,
and exports are local text/CSV downloads. Suggestions and PM decisions are labeled
separately. The text summary includes only approved draft bodies and a concise
audit action list. Full audit before/after records in the UI and CSV can still
contain historical draft versions.

Status and handoff templates use confirmed facts, explicit unknowns, and recorded workflow
actions, never raw report narratives or speculative severity indicators.
Configured wording checks reject common speculative and legal-assessment phrases
on generation, edit, and approval. These checks are a conservative prototype
safeguard, **not a proof of factual accuracy or a complete semantic/legal filter**.
PM review remains mandatory for all manual communications.

This is a **single-process, single-operator demo**, not an authenticated,
multi-user case system. Local audit history is append-only through the UI but is
not tamper-evident; reset intentionally clears it. Back up `data/state.json`
manually if you need to preserve a demo. File permissions, concurrency control,
authentication, retention, real holiday calendars, and production privacy
controls are out of scope.

## What I'd do next

1. Contribute the privacy response plan, validated with accountable owners, so
   the platform's existing agents could follow it instead of running a separate tool.
2. Integrate with the incident platform and the case system of record through
   approved integrations, replacing the copy/paste export.
3. Plug an LLM in behind `suggest_*`, with an evaluation set and regression tests
   per scenario type, retaining the human approval gates.
4. Measure time-to-triage, clock adherence, and purview-routing accuracy before
   and after.
5. Complete access-control and data-handling reviews before touching any real data.
