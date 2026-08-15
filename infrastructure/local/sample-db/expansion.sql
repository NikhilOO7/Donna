-- ---------------------------------------------------------------------------
-- Project Atlas — expanded operating history.
--
-- The original seed described the vendors as a static comparison: price,
-- latency, regions. That is enough to answer "what does Acme cost", and not
-- enough for anything a real evaluation turns on — whether a vendor has
-- actually held up, whether the cheap one is cheap for a reason, whether the
-- price you were quoted is the price you'll be paying in year three.
--
-- What follows is the operating record behind those three numbers. Each table
-- exists to make a specific kind of question answerable from data rather than
-- from the model's imagination:
--
--   incidents          -- has this vendor broken, and how badly
--   uptime_monthly     -- does the SLA hold up month over month
--   certifications     -- can they legally hold EU data
--   vendor_references  -- who else runs this, and did they stay
--   price_history      -- what happened at the last two renewals
--   team_members       -- who owns which decision internally
--   integration_effort -- what switching actually costs us
--
-- The rows are internally consistent with the documents in data/test_corpus
-- and with GROUND_TRUTH.json. Where they encode a conflict — and several do —
-- the conflict is deliberate: an evaluation where every number agrees is not
-- an evaluation, it is a formality.
-- ---------------------------------------------------------------------------

-- Two more vendors, so the shortlist isn't a three-way with one obvious answer.
INSERT INTO vendors (name, annual_cost_usd, p95_latency_ms, support_sla_hours, regions, status, notes) VALUES
  ('Northwind Data', 210000.00, 55, 3, 5, 'shortlisted',
   'Middle on every axis. Meets EU residency. The option nobody argues for and nobody rules out.'),
  ('Halcyon Grid',    95000.00, 140, 24, 2, 'eliminated',
   'Cheapest quote received. 24-hour support SLA is incompatible with the 4-hour P1 commitment in the Atlas MSA.')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Incidents. The row that matters most is the 2025-11-14 control-plane
-- failure: it took out CoreScale AND Beacon at the same time, which is the
-- evidence for the "shared control plane" claim in the evaluation document.
-- Without it that claim is an assertion; with it, it is a fact with a date.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incidents (
    id                SERIAL PRIMARY KEY,
    vendor_name       TEXT        NOT NULL,
    occurred_on       DATE        NOT NULL,
    severity          TEXT        NOT NULL,   -- P1 | P2 | P3
    duration_minutes  INTEGER     NOT NULL,
    customer_impact   TEXT        NOT NULL,
    root_cause        TEXT,
    rca_delivered     BOOLEAN     NOT NULL DEFAULT FALSE
);

INSERT INTO incidents (vendor_name, occurred_on, severity, duration_minutes, customer_impact, root_cause, rca_delivered) VALUES
  ('Acme Systems',  '2026-03-08', 'P1', 247, 'Full API outage in eu-west. 1,400 customer requests failed.',
   'Certificate rotation applied without staged rollout.', TRUE),
  ('Acme Systems',  '2025-12-02', 'P2',  95, 'Elevated latency, no data loss.',
   'Noisy-neighbour contention on shared compute.', TRUE),
  ('Beacon Cloud',  '2025-11-14', 'P1', 182, 'Control-plane failure. Provisioning unavailable across all regions.',
   'Shared control-plane deploy regression.', TRUE),
  ('CoreScale',     '2025-11-14', 'P1', 214, 'Same control-plane regression as Beacon Cloud, same window.',
   'Inherited Beacon Cloud control plane; no independent failure domain.', FALSE),
  ('CoreScale',     '2026-01-21', 'P1', 366, 'Region-wide outage. No failover available on a single-region deployment.',
   'Storage layer corruption; recovery required restore from backup.', FALSE),
  ('CoreScale',     '2026-04-02', 'P2', 130, 'Intermittent 5xx for 2 hours.', 'Unbounded connection pool.', FALSE),
  ('Northwind Data','2026-02-11', 'P3',  40, 'Dashboard unavailable. API unaffected.', 'Expired TLS certificate.', TRUE)
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Uptime. Acme's contractual commitment is 99.9%; two of these months miss it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uptime_monthly (
    id              SERIAL PRIMARY KEY,
    vendor_name     TEXT     NOT NULL,
    month           DATE     NOT NULL,
    uptime_pct      NUMERIC(6,3) NOT NULL,
    sla_target_pct  NUMERIC(6,3) NOT NULL,
    credits_owed_usd NUMERIC(12,2) NOT NULL DEFAULT 0
);

INSERT INTO uptime_monthly (vendor_name, month, uptime_pct, sla_target_pct, credits_owed_usd) VALUES
  ('Acme Systems',  '2026-01-01', 99.982, 99.900,     0.00),
  ('Acme Systems',  '2026-02-01', 99.951, 99.900,     0.00),
  ('Acme Systems',  '2026-03-01', 99.443, 99.900,  9250.00),
  ('Acme Systems',  '2026-04-01', 99.978, 99.900,     0.00),
  ('Beacon Cloud',  '2026-01-01', 99.995, 99.950,     0.00),
  ('Beacon Cloud',  '2026-02-01', 99.991, 99.950,     0.00),
  ('Beacon Cloud',  '2026-03-01', 99.987, 99.950,     0.00),
  ('Beacon Cloud',  '2026-04-01', 99.993, 99.950,     0.00),
  ('CoreScale',     '2026-01-01', 99.180, 99.500, 12000.00),
  ('CoreScale',     '2026-02-01', 99.610, 99.500,     0.00),
  ('CoreScale',     '2026-03-01', 99.702, 99.500,     0.00),
  ('CoreScale',     '2026-04-01', 99.488, 99.500,  4800.00),
  ('Northwind Data','2026-01-01', 99.960, 99.900,     0.00),
  ('Northwind Data','2026-02-01', 99.972, 99.900,     0.00),
  ('Northwind Data','2026-03-01', 99.968, 99.900,     0.00),
  ('Northwind Data','2026-04-01', 99.981, 99.900,     0.00)
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Certifications. This is where the EU data-residency tension becomes concrete:
-- Acme is the preferred vendor and the only shortlisted one that cannot hold
-- EU data, while the Atlas MSA marks EU coverage as required.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS certifications (
    id              SERIAL PRIMARY KEY,
    vendor_name     TEXT    NOT NULL,
    certification   TEXT    NOT NULL,
    status          TEXT    NOT NULL,   -- current | in_progress | none | expired
    valid_until     DATE,
    notes           TEXT
);

INSERT INTO certifications (vendor_name, certification, status, valid_until, notes) VALUES
  ('Acme Systems',  'SOC 2 Type II',      'current',     '2027-02-28', NULL),
  ('Acme Systems',  'ISO 27001',          'current',     '2027-09-30', NULL),
  ('Acme Systems',  'GDPR EU residency',  'in_progress', NULL,         'Frankfurt region targeted for Q3 2026. No contractual date offered yet.'),
  ('Acme Systems',  'HIPAA BAA',          'none',        NULL,         'Not offered.'),
  ('Beacon Cloud',  'SOC 2 Type II',      'current',     '2027-05-31', NULL),
  ('Beacon Cloud',  'ISO 27001',          'current',     '2028-01-31', NULL),
  ('Beacon Cloud',  'GDPR EU residency',  'current',     NULL,         'Frankfurt and Dublin regions live today.'),
  ('Beacon Cloud',  'HIPAA BAA',          'current',     NULL,         NULL),
  ('CoreScale',     'SOC 2 Type I',       'current',     '2026-11-30', 'Type I only. Type II audit not scheduled.'),
  ('CoreScale',     'ISO 27001',          'none',        NULL,         NULL),
  ('CoreScale',     'GDPR EU residency',  'none',        NULL,         'Single US region.'),
  ('Northwind Data','SOC 2 Type II',      'current',     '2027-07-31', NULL),
  ('Northwind Data','ISO 27001',          'current',     '2027-12-31', NULL),
  ('Northwind Data','GDPR EU residency',  'current',     NULL,         'Dublin region live.'),
  ('Halcyon Grid',  'SOC 2 Type II',      'expired',     '2025-08-31', 'Lapsed. Renewal audit not evidenced.')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- References. Answers the open action item "gather customer references" —
-- including the two that churned, which is the part a vendor never volunteers.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vendor_references (
    id              SERIAL PRIMARY KEY,
    vendor_name     TEXT    NOT NULL,
    company         TEXT    NOT NULL,
    industry        TEXT,
    seats           INTEGER,
    years_active    NUMERIC(4,1),
    still_customer  BOOLEAN NOT NULL DEFAULT TRUE,
    churn_reason    TEXT,
    would_recommend TEXT
);

INSERT INTO vendor_references (vendor_name, company, industry, seats, years_active, still_customer, churn_reason, would_recommend) VALUES
  ('Acme Systems',  'Meridian Health',   'Healthcare', 2400, 3.5, TRUE,  NULL, 'Yes — with reservations about EU coverage.'),
  ('Acme Systems',  'Bellweather Retail','Retail',     8100, 2.0, TRUE,  NULL, 'Yes.'),
  ('Acme Systems',  'Orion Freight',     'Logistics',  1200, 1.5, FALSE, 'Migrated to Beacon Cloud after the March outage.', 'No.'),
  ('Beacon Cloud',  'Kestrel Financial', 'Finance',    5600, 4.0, TRUE,  NULL, 'Yes.'),
  ('Beacon Cloud',  'Orion Freight',     'Logistics',  1200, 0.5, TRUE,  NULL, 'Too early to say.'),
  ('CoreScale',     'Tandem Labs',       'Biotech',     300, 1.0, FALSE, 'Repeated outages; single region unacceptable.', 'No.'),
  ('CoreScale',     'Pike Street Media', 'Media',       450, 2.0, TRUE,  NULL, 'Yes on price, no on reliability.'),
  ('Northwind Data','Calder Insurance',  'Insurance',  3300, 2.5, TRUE,  NULL, 'Yes.')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Price history. Acme has raised the renewal 12.1% across two cycles with no
-- cap in the contract — which is precisely why "obtain written price caps for
-- years 2 and 3" is an open action item rather than a formality.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_history (
    id                SERIAL PRIMARY KEY,
    vendor_name       TEXT    NOT NULL,
    contract_year     INTEGER NOT NULL,
    annual_cost_usd   NUMERIC(12,2) NOT NULL,
    change_pct        NUMERIC(5,2),
    cap_in_contract   BOOLEAN NOT NULL DEFAULT FALSE
);

INSERT INTO price_history (vendor_name, contract_year, annual_cost_usd, change_pct, cap_in_contract) VALUES
  ('Acme Systems',  2024, 165000.00,  NULL, FALSE),
  ('Acme Systems',  2025, 175000.00,  6.06, FALSE),
  ('Acme Systems',  2026, 185000.00,  5.71, FALSE),
  ('Beacon Cloud',  2025, 232000.00,  NULL, TRUE),
  ('Beacon Cloud',  2026, 240000.00,  3.45, TRUE),
  ('CoreScale',     2026, 120000.00,  NULL, FALSE),
  ('Northwind Data',2026, 210000.00,  NULL, TRUE)
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Who owns what internally. The activation agent routes a topic to a person;
-- this is where it learns that security questions belong to Priya.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_members (
    id            SERIAL PRIMARY KEY,
    full_name     TEXT NOT NULL,
    email         TEXT NOT NULL,
    role_title    TEXT NOT NULL,
    department    TEXT NOT NULL,
    expertise     TEXT NOT NULL,   -- comma-separated; matched lexically
    decision_rights TEXT
);

INSERT INTO team_members (full_name, email, role_title, department, expertise, decision_rights) VALUES
  ('Priya Raman',   'priya.raman@atlascorp.example',   'Head of Security',        'Security',
   'security, compliance, audit, soc2, iso 27001, penetration testing, data residency',
   'Blocks any vendor with unresolved high or critical findings.'),
  ('Sarah Chen',    'sarah.chen@atlascorp.example',    'Director of Procurement', 'Procurement',
   'budget, procurement, contracts, pricing, negotiation, renewals',
   'Approves spend up to $500,000 annually.'),
  ('Daniel Okafor', 'daniel.okafor@atlascorp.example', 'Principal Engineer',      'Platform Engineering',
   'infrastructure, latency, platform, capacity, migration, sre, incident response',
   'Signs off on technical fit and migration plan.'),
  ('Maya Oduya',    'maya.oduya@atlascorp.example',    'General Counsel',         'Legal',
   'legal, contracts, liability, indemnity, gdpr, data processing agreements',
   'Required for any contract above $200,000 or with EU data movement.'),
  ('Tom Ferreira',  'tom.ferreira@atlascorp.example',  'VP Customer Success',     'Customer Success',
   'customers, churn, references, escalations, renewals',
   'Owns the customer commitments a vendor choice has to honour.')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Switching cost. The number that usually decides these things and is usually
-- missing from the comparison table.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS integration_effort (
    id                    SERIAL PRIMARY KEY,
    vendor_name           TEXT    NOT NULL,
    engineer_weeks        INTEGER NOT NULL,
    data_migration_tb     NUMERIC(8,2),
    breaking_api_changes  INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd    NUMERIC(12,2),
    notes                 TEXT
);

INSERT INTO integration_effort (vendor_name, engineer_weeks, data_migration_tb, breaking_api_changes, estimated_cost_usd, notes) VALUES
  ('Acme Systems',   2,  0.00,  0,  24000.00, 'Incumbent. No migration required.'),
  ('Beacon Cloud',  14, 47.50, 23, 168000.00, 'Different auth model. Effectively a re-integration.'),
  ('CoreScale',      9, 47.50, 11, 108000.00, 'Beacon-derived API, so partially compatible.'),
  ('Northwind Data',11, 47.50, 16, 132000.00, NULL)
ON CONFLICT DO NOTHING;

-- More quarters, so trend questions have something to stand on.
INSERT INTO quarterly_financials (quarter, revenue_usd, revenue_growth_pct, operating_margin_pct, logo_churn_pct, net_revenue_retention_pct) VALUES
  ('Q4 2025', 3650000.00, 11.0, 19.0, 2.4, 108.0),
  ('Q4 2024', 2980000.00,  8.5, 15.0, 3.1, 101.0)
ON CONFLICT DO NOTHING;

-- Additional findings, including the first high-severity one — which changes
-- the answer to "are there any blocking findings" from a flat no.
INSERT INTO security_findings (id, severity, component, summary, remediation, status, found_on) VALUES
  ('SF-004', 'high',   'CoreScale control plane',
   'No independent failure domain. Control plane inherited from Beacon Cloud; a single regression took both providers down on 2025-11-14.',
   'Require evidence of an independent control plane before shortlisting.', 'open', '2026-02-03'),
  ('SF-005', 'medium', 'CoreScale compliance',
   'SOC 2 Type I only. Type II audit not scheduled, falling short of the vendor security baseline.',
   'Request a dated Type II audit plan.', 'open', '2026-02-03'),
  ('SF-006', 'medium', 'Acme Systems incident process',
   'Root cause analyses have been delivered on request, but no RCA timeline is committed in the MSA.',
   'Add a 5-business-day RCA commitment at renewal.', 'open', '2026-03-15'),
  ('SF-007', 'low',    'Northwind Data dashboard',
   'Expired TLS certificate caused a 40-minute dashboard outage. API unaffected.',
   'Certificate auto-renewal enabled by vendor.', 'resolved', '2026-02-11')
ON CONFLICT DO NOTHING;

-- Budget lines the new vendors would land against.
INSERT INTO budget_lines (department, line_item, approved_usd, spent_usd, fiscal_year) VALUES
  ('Platform Engineering', 'Vendor migration engineering', 150000.00,     0.00, 2026),
  ('Legal',                'Legal review — vendor contracts', 40000.00, 12000.00, 2026),
  ('Procurement',          'SLA credit recovery',              0.00, 26050.00, 2026)
ON CONFLICT DO NOTHING;

-- New tables inherit the read-only grant, but state it rather than rely on it.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO donna_readonly;
REVOKE ALL ON api_credentials FROM donna_readonly;

ANALYZE;
