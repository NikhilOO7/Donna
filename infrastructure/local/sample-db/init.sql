-- ===========================================================================
-- Sample "customer" database — Project Atlas
-- ===========================================================================
-- A stand-in for a company's own production database, so the read-only
-- connection feature (§11) can be exercised end to end without pointing at
-- anything real.
--
-- The figures deliberately MATCH data/test_corpus/GROUND_TRUTH.json, so the
-- documents and the database agree. That is what makes cross-source retrieval
-- testable: a claim contradicted by the corpus is contradicted by the database
-- too, and a correct claim is corroborated by both.
--
-- It also contains tables that SHOULD NOT be approved (employees,
-- api_credentials). They exist so the guardrails have something to catch:
-- sensitive-column detection has real columns to flag, and the table allowlist
-- has a real thing to exclude. A security feature you cannot see working is a
-- security feature nobody trusts.
-- ===========================================================================

CREATE SCHEMA IF NOT EXISTS public;

-- ---------------------------------------------------------------- vendors --
CREATE TABLE vendors (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    annual_cost_usd NUMERIC(12,2) NOT NULL,
    p95_latency_ms  INTEGER NOT NULL,
    support_sla_hours INTEGER NOT NULL,
    regions         INTEGER NOT NULL,
    status          TEXT NOT NULL,
    notes           TEXT
);

INSERT INTO vendors (name, annual_cost_usd, p95_latency_ms, support_sla_hours, regions, status, notes) VALUES
 ('Acme Systems', 185000.00, 42, 4, 3, 'preferred',  'Strongest latency profile. Only 3 regions — conflicts with the EU data residency commitment.'),
 ('Beacon Cloud', 240000.00, 68, 2, 7, 'runner_up',  'Best compliance posture and coverage, but exceeds the approved $200,000 budget line.'),
 ('CoreScale',    120000.00, 95, 8, 1, 'eliminated', 'Cheapest option. Spun out of Beacon Cloud in 2022 and still shares parts of its control plane.');

-- ------------------------------------------------------ vendor evaluations --
CREATE TABLE vendor_evaluations (
    id          SERIAL PRIMARY KEY,
    vendor_id   INTEGER REFERENCES vendors(id),
    criterion   TEXT NOT NULL,
    score       INTEGER NOT NULL,   -- 1..10
    evaluator   TEXT NOT NULL,
    evaluated_on DATE NOT NULL
);

INSERT INTO vendor_evaluations (vendor_id, criterion, score, evaluator, evaluated_on) VALUES
 (1,'query latency',9,'Daniel Okafor','2026-05-02'),
 (1,'total cost of ownership',7,'Sarah Chen','2026-05-02'),
 (1,'data residency',4,'Priya Raman','2026-05-03'),
 (2,'query latency',6,'Daniel Okafor','2026-05-02'),
 (2,'total cost of ownership',4,'Sarah Chen','2026-05-02'),
 (2,'data residency',9,'Priya Raman','2026-05-03'),
 (3,'query latency',3,'Daniel Okafor','2026-05-02'),
 (3,'total cost of ownership',9,'Sarah Chen','2026-05-02'),
 (3,'data residency',2,'Priya Raman','2026-05-03');

-- ------------------------------------------------------- security findings --
-- GROUND TRUTH: 3 medium, 0 critical. The scripted transcript claims
-- "seven findings including two critical" — fact-check should contest it.
CREATE TABLE security_findings (
    id          TEXT PRIMARY KEY,
    severity    TEXT NOT NULL,
    component   TEXT NOT NULL,
    summary     TEXT NOT NULL,
    remediation TEXT,
    status      TEXT NOT NULL,
    found_on    DATE NOT NULL
);

INSERT INTO security_findings VALUES
 ('SEC-01','medium','Acme Systems','Audit logging omits failed authentication events','Enable auth failure logging','open','2026-04-18'),
 ('SEC-02','medium','Acme Systems','TLS 1.1 still accepted on a legacy endpoint','Disable TLS < 1.2','open','2026-04-18'),
 ('SEC-03','medium','Beacon Cloud','Log retention set to 30 days, policy requires 90','Raise retention to 90 days','in_progress','2026-04-19');

-- -------------------------------------------------------------- financials --
-- GROUND TRUTH: 15% growth to $4.2M, 22% margin, 2.1% churn, 112% NRR.
CREATE TABLE quarterly_financials (
    id                  SERIAL PRIMARY KEY,
    quarter             TEXT NOT NULL,
    revenue_usd         NUMERIC(14,2) NOT NULL,
    revenue_growth_pct  NUMERIC(5,2) NOT NULL,
    operating_margin_pct NUMERIC(5,2) NOT NULL,
    logo_churn_pct      NUMERIC(5,2) NOT NULL,
    net_revenue_retention_pct NUMERIC(5,2) NOT NULL
);

INSERT INTO quarterly_financials (quarter, revenue_usd, revenue_growth_pct, operating_margin_pct, logo_churn_pct, net_revenue_retention_pct) VALUES
 ('Q1 2026', 3600000.00, 11.00, 18.00, 2.6, 105.00),
 ('Q2 2026', 3900000.00, 13.00, 19.00, 2.4, 108.00),
 ('Q3 2026', 4200000.00, 15.00, 22.00, 2.1, 112.00);

-- ------------------------------------------------------------ budget lines --
CREATE TABLE budget_lines (
    id            SERIAL PRIMARY KEY,
    department    TEXT NOT NULL,
    line_item     TEXT NOT NULL,
    approved_usd  NUMERIC(12,2) NOT NULL,
    spent_usd     NUMERIC(12,2) NOT NULL,
    fiscal_year   INTEGER NOT NULL
);

INSERT INTO budget_lines (department, line_item, approved_usd, spent_usd, fiscal_year) VALUES
 ('Engineering','Project Atlas search infrastructure', 200000.00,      0.00, 2026),
 ('Engineering','Platform headcount',                 3200000.00, 3400000.00, 2026),
 ('Marketing',  'Demand generation',                  1500000.00, 1200000.00, 2026);

-- --------------------------------------------------------------- contracts --
CREATE TABLE contracts (
    id                SERIAL PRIMARY KEY,
    counterparty      TEXT NOT NULL,
    kind              TEXT NOT NULL,
    renewal_date      DATE NOT NULL,
    notice_period_days INTEGER NOT NULL,
    p1_response_hours INTEGER NOT NULL,
    eu_region_required BOOLEAN NOT NULL,
    annual_value_usd  NUMERIC(12,2)
);

INSERT INTO contracts (counterparty, kind, renewal_date, notice_period_days, p1_response_hours, eu_region_required, annual_value_usd) VALUES
 ('Acme Systems','Master Services Agreement','2026-06-30',60,4,TRUE,185000.00),
 ('Beacon Cloud','Evaluation Agreement',     '2026-09-30',30,2,TRUE,     0.00);

-- ------------------------------------------------------- open action items --
CREATE TABLE project_actions (
    id          SERIAL PRIMARY KEY,
    project     TEXT NOT NULL,
    description TEXT NOT NULL,
    owner       TEXT NOT NULL,
    due_date    DATE,
    status      TEXT NOT NULL
);

INSERT INTO project_actions (project, description, owner, due_date, status) VALUES
 ('Project Atlas','Confirm EU region roadmap in writing with Acme','Priya Raman','2026-06-01','open'),
 ('Project Atlas','Close SEC-02 before production traffic is routed','Priya Raman','2026-05-30','in_progress'),
 ('Project Atlas','Finance committee exception if Beacon is selected','Sarah Chen','2026-05-25','open');

-- ===========================================================================
-- Tables that exist so the GUARDRAILS have something to catch.
-- Do NOT approve these in Settings — that is the point of the demo.
-- ===========================================================================

-- Sensitive-column detection should flag salary/ssn/dob on this table.
CREATE TABLE employees (
    id              SERIAL PRIMARY KEY,
    full_name       TEXT NOT NULL,
    email           TEXT NOT NULL,
    department      TEXT NOT NULL,
    salary_usd      NUMERIC(12,2) NOT NULL,
    ssn             TEXT NOT NULL,
    date_of_birth   DATE NOT NULL,
    performance_note TEXT
);

INSERT INTO employees (full_name, email, department, salary_usd, ssn, date_of_birth, performance_note) VALUES
 ('Priya Raman','priya.raman@example.com','Security',   168000.00,'000-00-0001','1989-03-14','Exceeds expectations'),
 ('Daniel Okafor','daniel.okafor@example.com','Platform',175000.00,'000-00-0002','1985-11-02','Exceeds expectations'),
 ('Sarah Chen','sarah.chen@example.com','Finance',      159000.00,'000-00-0003','1991-07-22','Meets expectations');

-- Every column here is a secret. Nothing should ever read this table.
CREATE TABLE api_credentials (
    id            SERIAL PRIMARY KEY,
    service       TEXT NOT NULL,
    api_key       TEXT NOT NULL,
    client_secret TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    rotated_on    DATE NOT NULL
);

INSERT INTO api_credentials (service, api_key, client_secret, password_hash, rotated_on) VALUES
 ('billing-provider','ak_live_DO_NOT_READ_0001','cs_DO_NOT_READ_0001','$2b$12$notarealhash0001','2026-01-05'),
 ('email-provider',  'ak_live_DO_NOT_READ_0002','cs_DO_NOT_READ_0002','$2b$12$notarealhash0002','2026-02-11');

-- ===========================================================================
-- The read-only role Donna should authenticate as.
-- ===========================================================================
-- This is what a correctly-provisioned customer account looks like, and it is
-- what makes the write probe meaningful: verification attempts a write and
-- expects the DATABASE to refuse it. Connecting as the owner instead would
-- surface the "this account can write" warning — also worth seeing once.
CREATE ROLE donna_readonly WITH LOGIN PASSWORD 'readonly_demo_pw';

GRANT CONNECT ON DATABASE atlas_corp TO donna_readonly;
GRANT USAGE   ON SCHEMA public       TO donna_readonly;
GRANT SELECT  ON ALL TABLES IN SCHEMA public TO donna_readonly;

-- Future tables are readable too, but still never writable.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO donna_readonly;

-- Belt and braces: explicitly deny the ability to create anything, so the
-- write probe fails at the database rather than relying on absent grants.
REVOKE CREATE ON SCHEMA public FROM donna_readonly;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO donna_readonly;

-- Credentials table is readable by the owner only — belt and braces again.
REVOKE ALL ON api_credentials FROM donna_readonly;

-- ---------------------------------------------------------------------------
-- Populate planner statistics.
-- Without this, pg_class.reltuples is -1 ("never analyzed") on every table,
-- and any UI that renders it as a number shows a freshly-seeded database as
-- "~0 rows" — which reads as a fact rather than as "not measured yet".

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
