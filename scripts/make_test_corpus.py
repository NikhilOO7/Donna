#!/usr/bin/env python3
"""
Generate a test corpus with *planted ground truth*.

A random PDF proves the upload endpoint works. It does not tell you whether
the table agent parsed the table, whether the KG agent found a two-hop path,
or whether fact-check caught a contradicted number — because with arbitrary
content you have nothing to check the answer against.

Every document here is built so that specific machinery has something to bite
on, and so the correct answer is known in advance:

  01_vendor_evaluation.docx   headings + a REAL table    -> layout, table agent,
                                                            element-type boost
  02_security_audit.docx      entities shared with #1     -> KG 2-hop traversal
  03_q3_financials.pdf        precise figures             -> fact-check ground truth,
                                                            groundedness
  04_master_services_agreement.pdf  SLA/MSA acronyms,     -> acronym handling,
                                    dates                    memory/decision recall

The companion transcript (scripts/meeting_scenario.json) contains utterances
that deliberately CONTRADICT figures in #3 and #4, so a passing fact-check is
evidence rather than vibes.

No new dependencies: .docx via python-docx (already present, and .docx is an
allowed upload type), .pdf via macOS `cupsfilter`.

    uv run python scripts/make_test_corpus.py
    uv run python scripts/make_test_corpus.py --out data/test_corpus
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

# --- The planted facts. The transcript and any assertion checks read these,
# --- so the ground truth lives in exactly one place.
GROUND_TRUTH = {
    "vendors": {
        "Acme Systems": {
            "annual_cost_usd": 185_000,
            "p95_latency_ms": 42,
            "support_sla_hours": 4,
            "regions": 3,
        },
        "Beacon Cloud": {
            "annual_cost_usd": 240_000,
            "p95_latency_ms": 68,
            "support_sla_hours": 2,
            "regions": 7,
        },
        "CoreScale": {
            "annual_cost_usd": 120_000,
            "p95_latency_ms": 95,
            "support_sla_hours": 8,
            "regions": 1,
        },
    },
    "security_audit": {
        "medium_findings": 3,
        "critical_findings": 0,
        "vendors_reviewed": ["Acme Systems", "Beacon Cloud"],
    },
    "financials_q3": {
        "revenue_growth_pct": 15,
        "revenue_usd": "4.2M",
        "operating_margin_pct": 22,
        "logo_churn_pct": 2.1,
        "net_revenue_retention_pct": 112,
    },
    "contract": {
        "renewal_date": "2026-06-30",
        "notice_days": 60,
        "p1_response_hours": 4,
    },
    # Facts introduced by the expanded corpus. Kept here so the eval harness
    # and the sample database agree with the documents rather than merely
    # resembling them.
    "incident_2025_11_14": {
        "date": "2025-11-14",
        "vendors_affected": ["Beacon Cloud", "CoreScale"],
        "beacon_duration_minutes": 182,
        "corescale_duration_minutes": 214,
        "root_cause": "shared control plane",
    },
    "certifications": {
        "eu_residency_current": ["Beacon Cloud", "Northwind Data"],
        "eu_residency_in_progress": ["Acme Systems"],
        "eu_residency_none": ["CoreScale"],
    },
    "renewal": {
        "acme_2024_usd": 165_000,
        "acme_2025_usd": 175_000,
        "acme_2026_usd": 185_000,
        "two_year_increase_pct": 12.1,
        "cap_in_contract": False,
    },
    "switching_cost": {
        "beacon_engineer_weeks": 14,
        "beacon_estimated_usd": 168_000,
        "corescale_engineer_weeks": 9,
    },
    "people": {
        "Priya Raman": ["security", "compliance", "audit"],
        "Daniel Okafor": ["infrastructure", "latency", "platform"],
        "Sarah Chen": ["budget", "procurement", "contracts"],
    },
}


def _docx_vendor_evaluation(path: Path) -> None:
    """Headings + a real ruled table: the layout and table agents' target."""
    from docx import Document

    doc = Document()
    doc.add_heading("Project Atlas — Vendor Evaluation", level=0)
    doc.add_paragraph(
        "Prepared by Sarah Chen, Procurement. Reviewed by Daniel Okafor (Platform) "
        "and Priya Raman (Security)."
    )

    doc.add_heading("Executive Summary", level=1)
    doc.add_paragraph(
        "Three vendors were assessed for the Project Atlas search infrastructure. "
        "Acme Systems offers the strongest latency profile at a mid-tier price. "
        "Beacon Cloud leads on compliance and multi-region coverage but is the most "
        "expensive. CoreScale is the cheapest option and the weakest operationally."
    )

    doc.add_heading("Evaluation Criteria", level=1)
    for c in [
        "Query latency at the 95th percentile under production-like load.",
        "Annual total cost of ownership including support.",
        "Support responsiveness for P1 incidents.",
        "Multi-region coverage for data residency commitments.",
    ]:
        doc.add_paragraph(c, style="List Bullet")

    doc.add_heading("Vendor Comparison", level=1)
    vendors = GROUND_TRUTH["vendors"]
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"  # ruled — far more reliably parsed than whitespace
    hdr = table.rows[0].cells
    for i, h in enumerate(
        ["Vendor", "Annual Cost", "p95 Latency", "Support SLA", "Regions"]
    ):
        hdr[i].text = h
    for name, v in vendors.items():
        row = table.add_row().cells
        row[0].text = name
        row[1].text = f"${v['annual_cost_usd']:,}"
        row[2].text = f"{v['p95_latency_ms']}ms"
        row[3].text = f"{v['support_sla_hours']} business hours"
        row[4].text = str(v["regions"])

    doc.add_heading("Risks and Tensions", level=1)
    doc.add_paragraph(
        "Acme Systems covers only 3 regions, which conflicts with the EU data "
        "residency commitment made to two enterprise accounts. Beacon Cloud's "
        "$240,000 annual cost exceeds the approved Project Atlas budget line. "
        "CoreScale spun out of Beacon Cloud in 2022 and still shares parts of its "
        "control plane, so the two are not fully independent options."
    )

    doc.add_heading("Recommendation", level=1)
    doc.add_paragraph(
        "Proceed with Acme Systems at $185,000 per year, contingent on a written "
        "commitment to add EU region coverage before the Q3 launch. Final sign-off "
        "requires Priya Raman's security review and Sarah Chen's budget approval."
    )
    doc.save(path)


def _docx_security_audit(path: Path) -> None:
    """Shares entities with doc 1 so the KG agent has a real 2-hop path."""
    from docx import Document

    doc = Document()
    doc.add_heading("Project Atlas — Security Audit 2026", level=0)
    doc.add_paragraph("Auditor: Priya Raman, Security Engineering.")

    doc.add_heading("Scope", level=1)
    doc.add_paragraph(
        "This audit reviewed the integration surface of Acme Systems and "
        "Beacon Cloud against our control framework. CoreScale was excluded "
        "because it was eliminated on cost-performance grounds."
    )

    doc.add_heading("Findings", level=1)
    audit = GROUND_TRUTH["security_audit"]
    doc.add_paragraph(
        f"{audit['medium_findings']} medium-severity findings were identified. "
        f"{audit['critical_findings']} critical issues were found."
    )
    t = doc.add_table(rows=1, cols=4)
    t.style = "Table Grid"
    for i, h in enumerate(["ID", "Severity", "Component", "Summary"]):
        t.rows[0].cells[i].text = h
    for row in [
        ("SEC-01", "Medium", "Acme Systems", "Audit logging omits failed auth events"),
        (
            "SEC-02",
            "Medium",
            "Acme Systems",
            "TLS 1.1 still accepted on legacy endpoint",
        ),
        (
            "SEC-03",
            "Medium",
            "Beacon Cloud",
            "Log retention set to 30 days, policy requires 90",
        ),
    ]:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = val

    doc.add_heading("Conclusion", level=1)
    doc.add_paragraph(
        "No critical vulnerabilities were found in either vendor. All three "
        "medium findings have documented remediation paths and none block "
        "signing. Priya Raman recommends proceeding subject to SEC-02 being "
        "closed before production traffic is routed."
    )
    doc.save(path)


def _docx_incident_postmortem(path: Path) -> None:
    """The 2025-11-14 correlated outage.

    The single most useful document in the corpus for testing reasoning rather
    than recall: the evaluation doc *claims* CoreScale and Beacon share a
    control plane, and this is the evidence. Answering "are CoreScale and
    Beacon independent?" correctly requires connecting a claim in one document
    to an incident timeline in another.
    """
    from docx import Document

    doc = Document()
    doc.add_heading("Post-Incident Review — 14 November 2025", level=0)
    doc.add_paragraph(
        "Prepared by Daniel Okafor, Platform Engineering. "
        "Reviewed by Priya Raman (Security) and Tom Ferreira (Customer Success)."
    )

    doc.add_heading("Summary", level=1)
    doc.add_paragraph(
        "On 14 November 2025 a control-plane deploy regression at Beacon Cloud "
        "caused a provisioning outage across all Beacon regions lasting 182 "
        "minutes. CoreScale, which operates on a control plane inherited from "
        "Beacon Cloud, experienced the same regression in the same window for "
        "214 minutes. Two vendors we had been treating as independent options "
        "failed together, from one cause."
    )

    doc.add_heading("Timeline", level=1)
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, h in enumerate(["Time (UTC)", "Event", "Vendor"]):
        hdr[i].text = h
    for t, e, v in [
        ("09:14", "Provisioning API begins returning 503", "Beacon Cloud"),
        ("09:31", "Beacon Cloud acknowledges, declares P1", "Beacon Cloud"),
        ("09:47", "Independent 503s observed on a second provider", "CoreScale"),
        ("10:05", "CoreScale declares P1; cause not yet identified", "CoreScale"),
        ("11:22", "Beacon Cloud identifies deploy regression, begins rollback", "Beacon Cloud"),
        ("12:16", "Beacon Cloud service restored", "Beacon Cloud"),
        ("12:48", "CoreScale service restored following the same rollback", "CoreScale"),
    ]:
        row = table.add_row().cells
        row[0].text = t
        row[1].text = e
        row[2].text = v

    doc.add_heading("What This Changes", level=1)
    doc.add_paragraph(
        "Any evaluation that treats CoreScale as a hedge against Beacon Cloud "
        "is mistaken. A shared control plane means a shared failure domain, and "
        "on this date it produced a shared outage. CoreScale has not delivered "
        "a root cause analysis for its own incident."
    )

    doc.add_heading("Open Questions", level=1)
    for q in [
        "Which components of the CoreScale control plane remain Beacon-derived?",
        "Does CoreScale commit to an independent failure domain, and by when?",
        "Should correlated-failure risk be a formal criterion in future evaluations?",
    ]:
        doc.add_paragraph(q, style="List Bullet")
    doc.save(path)


def _docx_reference_calls(path: Path) -> None:
    """Reference calls, including the two customers who left.

    Named people and direct quotes: the material the activation and memory
    agents work from. The churned references are the point — a reference list
    containing only happy customers is marketing, not diligence.
    """
    from docx import Document

    doc = Document()
    doc.add_heading("Project Atlas — Reference Call Notes", level=0)
    doc.add_paragraph(
        "Compiled by Tom Ferreira, Customer Success. Calls conducted "
        "February–March 2026."
    )

    doc.add_heading("Acme Systems", level=1)
    doc.add_paragraph(
        "Meridian Health (2,400 seats, 3.5 years). Positive overall. Their "
        "platform lead flagged that EU data residency has been \u201con the roadmap\u201d "
        "for two consecutive renewals without a contractual date."
    )
    doc.add_paragraph(
        "Orion Freight (1,200 seats) churned to Beacon Cloud in April 2026 "
        "following the March outage. Their reason, verbatim: \u201cthe outage was "
        "survivable, the four hours of silence during it was not.\u201d"
    )

    doc.add_heading("Beacon Cloud", level=1)
    doc.add_paragraph(
        "Kestrel Financial (5,600 seats, 4 years). Strongly positive on "
        "reliability and compliance. Confirmed the November 2025 control-plane "
        "incident but noted the root cause analysis arrived within two days."
    )

    doc.add_heading("CoreScale", level=1)
    doc.add_paragraph(
        "Tandem Labs (300 seats) churned in January 2026 after the region-wide "
        "outage. Single-region deployment left them with no failover."
    )
    doc.add_paragraph(
        "Pike Street Media (450 seats) remains a customer and summarized it as "
        "\u201cyes on price, no on reliability.\u201d"
    )

    doc.add_heading("Pattern Worth Noting", level=1)
    doc.add_paragraph(
        "Both churned references left after an availability incident rather than "
        "over price. Every reference that stayed cited responsiveness during an "
        "incident, not the absence of incidents."
    )
    doc.save(path)


COMPLIANCE_TXT = """Project Atlas \u2014 Vendor Compliance Matrix
Prepared by Priya Raman, Head of Security. Current as of 30 April 2026.

SCOPE
Certification status for all shortlisted and eliminated vendors, assessed
against the Atlas vendor security baseline.

ACME SYSTEMS
  SOC 2 Type II          Current, valid until 28 February 2027
  ISO 27001              Current, valid until 30 September 2027
  GDPR EU residency      IN PROGRESS \u2014 Frankfurt region targeted for Q3 2026.
                         No contractual date has been offered.
  HIPAA BAA              Not offered

BEACON CLOUD
  SOC 2 Type II          Current, valid until 31 May 2027
  ISO 27001              Current, valid until 31 January 2028
  GDPR EU residency      CURRENT \u2014 Frankfurt and Dublin regions live today
  HIPAA BAA              Current

CORESCALE
  SOC 2 Type I           Current, valid until 30 November 2026
                         Type I only. A Type II audit is not scheduled.
  ISO 27001              Not held
  GDPR EU residency      Not held \u2014 single US region

NORTHWIND DATA
  SOC 2 Type II          Current, valid until 31 July 2027
  ISO 27001              Current, valid until 31 December 2027
  GDPR EU residency      CURRENT \u2014 Dublin region live

HALCYON GRID
  SOC 2 Type II          EXPIRED 31 August 2025. Renewal audit not evidenced.

ASSESSMENT
Of the shortlisted vendors, only Beacon Cloud and Northwind Data can hold EU
personal data today. Acme Systems, the preferred vendor, cannot \u2014 while the
Atlas Master Services Agreement marks EU region coverage as required. That gap
is the single largest compliance risk in this evaluation and cannot be closed
by a roadmap commitment alone.
"""


RENEWAL_TXT = """Project Atlas \u2014 Acme Renewal Negotiation Brief
Prepared by Sarah Chen, Procurement. For internal use.

CONTRACT POSITION
  Agreement              Master Services Agreement, Acme Systems
  Current annual value   $185,000
  Renewal date           30 June 2026
  Notice period          60 days
  Notice deadline        1 May 2026
  Auto-renewal           Yes, for a further 12 months if notice is not served

PRICE HISTORY
  2024                   $165,000
  2025                   $175,000   (+6.06%)
  2026                   $185,000   (+5.71%)
  Two-year increase      12.1%
  Cap in contract        None

The absence of a price cap is the material point. Acme has increased the
renewal 12.1% over two cycles without one, and the agreement auto-renews. On
the current trajectory a three-year commitment at uncapped rates reaches
approximately $207,000 by 2028.

SERVICE CREDITS OUTSTANDING
  March 2026 availability  99.443% against a 99.9% commitment
  Credits owed             $9,250, not yet claimed

NEGOTIATION POSITIONS
  1. Written price caps for years 2 and 3, not to exceed 4% annually.
  2. A contractual date for EU region availability, with a termination right
     if it is missed.
  3. A committed root cause analysis timeline of five business days.
  4. Recovery of the $9,250 in outstanding March service credits.

ALTERNATIVE COST OF SWITCHING
  Beacon Cloud           14 engineer-weeks, approximately $168,000 one-off
  Northwind Data         11 engineer-weeks, approximately $132,000 one-off

Switching to Beacon Cloud costs roughly one year of the price difference in
migration effort alone, which materially weakens the threat to leave. That is
worth knowing before the conversation, not during it.
"""


FINANCIALS_TXT = """Project Atlas \u2014 Q3 Financial Summary

Prepared by Sarah Chen, Finance and Procurement.

REVENUE
Revenue grew 15% year over year, reaching $4.2M in Q3. Operating margin
improved to 22%, up from 19% in the prior quarter.

RETENTION
Monthly logo churn is 2.1%. Net revenue retention is 112%, driven mainly by
expansion within existing enterprise accounts.

BUDGET POSITION
Marketing spend is $1.2M against a $1.5M budget. Engineering is at $3.4M
against $3.2M, an overrun of $200,000 that the CFO flagged in the October
review.

PROJECT ATLAS BUDGET LINE
The approved annual budget line for Project Atlas search infrastructure is
$200,000. Any vendor contract above that figure requires an exception approved
by the finance committee.
"""

CONTRACT_TXT = """Master Services Agreement — Project Atlas

Parties: NeuroLogica and the selected infrastructure vendor.

SECTION 7 — SUPPORT AND SERVICE LEVELS
Support response time is four business hours for P1 incidents. P2 incidents
carry a next-business-day response commitment. The SLA is measured monthly and
reported within five business days of month end.

SECTION 12 — TERM AND RENEWAL
The agreement auto-renews on 2026-06-30 unless either party gives 60 days
written notice. Renewal pricing is capped at CPI plus two percent.

SECTION 15 — DATA RESIDENCY
The vendor shall provide EU region coverage for all customer data designated as
EU-resident. Failure to provide EU coverage by the launch date constitutes a
material breach under the terms of this MSA.

SECTION 19 — TERMINATION
Either party may terminate for material breach with 30 days written notice and
an opportunity to cure.
"""


def _text_pdf(path: Path, body: str) -> bool:
    """Plain-text -> PDF via macOS cupsfilter. Returns False if unavailable."""
    if not shutil.which("cupsfilter"):
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write(body)
        tmp = fh.name
    try:
        with open(path, "wb") as out:
            proc = subprocess.run(
                ["cupsfilter", tmp], stdout=out, stderr=subprocess.DEVNULL
            )
        return proc.returncode == 0 and path.exists() and path.stat().st_size > 500
    finally:
        Path(tmp).unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/test_corpus")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    made = []

    print("generating corpus…")

    p = out / "01_vendor_evaluation.docx"
    _docx_vendor_evaluation(p)
    made.append((p, "headings + ruled table -> layout agent, table agent"))

    p = out / "02_security_audit.docx"
    _docx_security_audit(p)
    made.append((p, "entities shared with #1 -> KG 2-hop traversal"))

    p = out / "03_q3_financials.pdf"
    if _text_pdf(p, FINANCIALS_TXT):
        made.append((p, "precise figures -> fact-check + groundedness ground truth"))
    else:
        p = p.with_suffix(".txt")
        p.write_text(FINANCIALS_TXT)
        made.append((p, "cupsfilter unavailable — wrote .txt instead"))

    p = out / "05_incident_postmortem.docx"
    _docx_incident_postmortem(p)
    made.append((p, "cross-document reasoning -> shared-failure-domain evidence"))

    p = out / "06_reference_calls.docx"
    _docx_reference_calls(p)
    made.append((p, "named people + quotes -> activation, memory"))

    p = out / "07_compliance_matrix.pdf"
    if _text_pdf(p, COMPLIANCE_TXT):
        made.append((p, "certification status -> fact-check on EU residency"))
    else:
        p = p.with_suffix(".txt")
        p.write_text(COMPLIANCE_TXT)
        made.append((p, "cupsfilter unavailable — wrote .txt instead"))

    p = out / "08_renewal_brief.pdf"
    if _text_pdf(p, RENEWAL_TXT):
        made.append((p, "dates + price deltas -> deadline and trend reasoning"))
    else:
        p = p.with_suffix(".txt")
        p.write_text(RENEWAL_TXT)
        made.append((p, "cupsfilter unavailable — wrote .txt instead"))

    p = out / "04_master_services_agreement.pdf"
    if _text_pdf(p, CONTRACT_TXT):
        made.append((p, "SLA/MSA acronyms + dates -> acronym handling, recall"))
    else:
        p = p.with_suffix(".txt")
        p.write_text(CONTRACT_TXT)
        made.append((p, "cupsfilter unavailable — wrote .txt instead"))

    gt = out / "GROUND_TRUTH.json"
    gt.write_text(json.dumps(GROUND_TRUTH, indent=2) + "\n")

    print()
    for path, why in made:
        size = path.stat().st_size
        print(f"  {path.name:<38} {size:>7,}B  {why}")
    print(f"  {gt.name:<38} {gt.stat().st_size:>7,}B  the planted answers")

    print(
        "\nAlso worth uploading, already in the repo:\n"
        "  'Donna - You are AUO, a proactive meeting collaborator.pdf'\n"
        "     35 pages, ZERO extractable text, one image per page — a genuine\n"
        "     scanned-document test that exercises EasyOCR and the vision-based\n"
        "     image agent. Slow by design; run it when testing ingestion, not\n"
        "     when iterating on the meeting loop.\n"
        "  'arch docs/AUO Feedback_Report_01.pdf'\n"
        "     5 pages of clean prose — a fast, realistic text-PDF path.\n"
    )
    print("Next:  uv run python scripts/run_test_scenario.py --help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
