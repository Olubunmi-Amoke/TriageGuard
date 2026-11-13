# TriageGuard privacy triage response plan

**illustrative – configure to policy**

**Synthetic, illustrative TrIP-style exercise only. Not a Microsoft/TrIP policy,
approved runbook, severity model, or statement of actual team purview.**

The incident platform's AI covers engineering triage. TriageGuard prototypes the
privacy triage layer, written as a response plan that existing agents could follow,
not as a separate tool. The Streamlit UI is a local rehearsal surface for this
plan; it is not an integration or an additional system of record.

Existing summary, troubleshooting, and SRE agents remain responsible for their
engineering workflows. Do not reproduce log queries, error-rate diagnosis, SLO
analysis, deployment investigation, or an engineering AI summary here. Instead,
attach privacy evidence and decisions in the familiar summary slots: **What we
know**, **What has been done**, **Recommended next actions**.

All suggestions need human review. Never send a communication, decide a legal or
notification obligation, transfer ownership, or close a case automatically.
Keep linked IcM/case IDs. All clocks, names, thresholds, and teams below are
fictional and configurable in `config.yaml`.

## 1. Scope/purview test

### 1.1 Privacy involvement

Suggest **In scope** when explicit facts establish customer/personal data
involvement or a configured private data type (contact, financial, health, or
credential data). An indicator is not proof of harm or a legal finding.
Government/restricted environments, attacks, insider concerns, and partner handling
must not be discarded through the engineering-only exclusion.

### 1.2 Engineering-only exclusion

Suggest **Out of scope – route to another team** only with all these confirmed:
customer/personal data involved = no; security-process concern only = yes;
environment = a configured non-production environment; data types are exclusively
configured non-personal internal identifiers; affected customer record count = 0.
Missing or contradictory evidence fails this test. Never assume an internal
identifier is non-personal merely because it is called internal.

Suggest **Demo Sandbox Engineering** for a test environment and **Demo Developer
Tools Engineering** for a development environment. These are synthetic receiving
teams, not actual Microsoft queues. The PM can override the receiving team with
a reason. Preserve unresolved facts in the handoff.

### 1.3 Ambiguity and contradictory evidence

Suggest **Needs review** when neither test is established or when exclusion
evidence conflicts with privacy facts, an attack/insider/restricted/partner/
notification-assessment indicator, or explicit report data-type wording.
Do not silently treat an UNKNOWN as no. A PM reviews purview before any handoff;
fact changes revoke purview and receiving-team decisions and stale draft approvals.

## 2. Fact confirmation

### 2.1 Evidence and unknowns

Extract only explicitly stated facts from the report or structured known fields:
data types, affected customers, regions, approximate record count, mechanism,
containment, deletion attestation, and the three purview facts from section 1.2.
Label every value CONFIRMED or UNKNOWN; retain the evidence. Conflicting explicit
statements remain UNKNOWN. Reporter-question checkboxes record that a question was
asked, not that its answer is known.

### 2.2 PM confirmation

A manual fact requires an explicit value and source note, labeled
CONFIRMED (by PM). Re-evaluate recommendations and revoke old decisions and draft
approvals. A workflow status is not evidence that containment or deletion occurred.

## 3. Severity rules

### 3.1 Baseline

P1 is highest, P3 is the baseline. This is a provisional privacy coordination
severity, not the platform's engineering severity or service-health assessment.

### 3.2 Attack and insider floor

Configured attack or insider indicators trigger P1. Containment cannot reduce
this floor. Preserve why the rule fired even when an owner overrides severity.

### 3.3 Data sensitivity and volume

Explicit financial, health, or credential data, or at least 1,000 records, elevates
to at least P2 before any permitted reduction. These illustrative thresholds do
not express notification thresholds.

### 3.4 Containment reduction

Explicitly confirmed containment AND recipient deletion permit a one-level
reduction, never below an attack/insider floor. Sensitive data remains ineligible
for routine ownership even after a reduction.

### 3.5 Non-incident suggestion

Explicit test-only, public-only, or confirmed false-positive indicators suggest
**Close as not an incident** for PM review, not automatic closure. This is distinct
from an out-of-purview engineering concern that still needs another owner.

## 4. Routing

### 4.1 FTE escalation

P1/P2, sensitive data, attack, insider, restricted/government environment,
vendor/partner handling, or notification-assessment requests require FTE ownership
in this exercise. This is not a real vendor delegation policy.

### 4.2 Unknowns and routine eligibility

More than one UNKNOWN among the seven core incident facts requires FTE ownership.
Routine eligibility requires explicit misdirection, containment, known
non-sensitive data, at most 100 records, and at most one core UNKNOWN.
The three purview-only fields are evaluated by section 1 and do not inflate this
core-fact threshold. If routine eligibility is not established, retain FTE ownership.

### 4.3 Purview handoff

Out-of-scope engineering concerns get a separate **Engineering handoff** lane
and a suggested receiving team, not the vendor routine queue. Needs-review cases
remain FTE-owned. A PM scope decision affects the displayed routing suggestion;
changes revoke stale routing decisions and approvals. Neither a suggested lane nor
an approved note transfers ownership.

## 5. Stakeholders

### 5.1 Accountable engagement

Privacy coordinates fact review; engineering validates the mechanism and
containment. Engage legal for configured sensitive/restricted/notification/insider
indicators, security for attack/insider indicators, and customer-facing owners when
customers are explicitly identified. Each suggestion needs a reason and PM review.
For engineering-only cases, the receiving team owns technical follow-through after
manual acceptance; privacy confirms the boundary and re-entry criteria.

## 6. Clocks

**All clock values: illustrative – configure to policy.**

### 6.1 Initial triage

Four hours from report; complete only at the first PM-recorded triage milestone.

### 6.2 First stakeholder update

Sixteen hours from report. Approval is not delivery; record completion only when
the PM attests that the manual update happened outside this prototype.

### 6.3 Deletion attestation

One business day from deletion-request approval. This illustrative start is approval,
not an invented delivery event. Complete on a PM-confirmed deletion attestation.

### 6.4 Follow-up and clock handling

Three business days from first triage. Business-day math preserves UTC time and
skips weekends, not holidays. Amber means strictly less than 25% of the allowance
remains; red means the deadline has been reached or passed. Closed cases stop
unfinished clocks without inventing successful completion. A suggested exclusion
does not stop clocks.

### 6.5 Notification-assessment coordination

An explicit notification-assessment request starts an illustrative 24-hour review
clock from report, to coordinate accountable privacy/legal owners. This is **not**
a statutory, contractual, or customer notification deadline and never decides
whether notification is required. Without an explicit request it is not applicable.
Actual obligations and dates must be established by accountable owners outside
this exercise. Only record a completed owner review manually; approval of a
communication does not complete this clock.

## 7. Communications

### 7.1 Deletion request

Draft a request for recipient receipt/access/sharing information, deletion, and
written attestation. Verify the recipient manually. No message is sent.

### 7.2 Facts-only status

Use confirmed facts and recorded workflow events only, with separate UNKNOWNs,
next steps, and next update time. Do not copy speculative report narratives,
severity rationales, or legal conclusions into the status draft. Configured wording
checks are only a conservative safeguard; a person must review the content.

### 7.3 Approval gate

Template edits require a reason. Approval records **Approved – ready to send
manually** only. Editing, fact changes, or decision changes revoke approval.
Status changes invalidate status/handoff drafts; an approved deletion request
keeps its approval if its template content is unaffected by the status change.
If a configured deletion template includes changed workflow context, invalidate
it too. Regenerate stale drafts. Record every generation, edit, approval, decision, and override;
never represent a suggestion or draft approval as an executed response action.

## 8. Handoff/closure

### 8.1 Handoff/closure note

When section 1.2 is established, generate a draft that includes confirmed facts,
remaining UNKNOWNs, exclusion rationale, and the synthetic receiving team for
further asks. Generation does not require accepting the suggestion; approval
requires explicit PM decisions confirming out-of-scope purview and a receiving
team. An override away from out-of-scope blocks handoff generation and approval.
Without confirmed exclusion evidence, a PM override alone cannot generate an
evidence-backed exclusion note.

The note must say that engineering remediation and ownership acceptance are not
confirmed by this prototype. Re-enter privacy triage if new customer/personal data
evidence appears. Approving a handoff note does not close either record or transfer
the case; the PM coordinates acceptance and records any closure separately.

### 8.2 Manual record and closure

Export linked IDs, evidence, purview/severity/routing suggestions and decisions,
stakeholders, clocks, approved drafts, and audit history to the case record.
Closure is always a separate human status change with evidence retained. This
local audit is not tamper-evident; reset intentionally clears demo history.
