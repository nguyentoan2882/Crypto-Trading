-- NXT cloud-shadow schema v1. PostgreSQL 15+ / Supabase compatible.
-- This migration is intentionally cloud-provider neutral and SHADOW-only.

CREATE TABLE scan_runs (
    run_id text PRIMARY KEY,
    environment text NOT NULL CHECK (environment = 'SHADOW'),
    owner_user_id text,
    candle_date date,
    status text NOT NULL,
    source text NOT NULL,
    input_hash text NOT NULL,
    rule_version text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    errors_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (environment, candle_date, rule_version, source)
);

CREATE TABLE scan_run_symbols (
    run_id text NOT NULL REFERENCES scan_runs(run_id) ON DELETE CASCADE,
    symbol text NOT NULL,
    latest_closed_date date,
    row_count integer NOT NULL CHECK (row_count >= 0),
    data_hash text NOT NULL,
    status text NOT NULL,
    PRIMARY KEY (run_id, symbol)
);

CREATE TABLE signals (
    signal_id text PRIMARY KEY,
    environment text NOT NULL CHECK (environment = 'SHADOW'),
    owner_user_id text,
    run_id text REFERENCES scan_runs(run_id) ON DELETE SET NULL,
    symbol text NOT NULL,
    side text NOT NULL,
    signal_type text NOT NULL,
    signal_date date NOT NULL,
    rule_version text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (environment, signal_id)
);

CREATE TABLE trade_plans (
    plan_id text PRIMARY KEY,
    environment text NOT NULL CHECK (environment = 'SHADOW'),
    owner_user_id text,
    signal_id text NOT NULL REFERENCES signals(signal_id) ON DELETE CASCADE,
    rule_version text NOT NULL,
    status text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (environment, plan_id)
);

CREATE TABLE decisions (
    decision_id text PRIMARY KEY,
    environment text NOT NULL CHECK (environment = 'SHADOW'),
    owner_user_id text NOT NULL,
    signal_id text NOT NULL REFERENCES signals(signal_id) ON DELETE CASCADE,
    decision text NOT NULL CHECK (decision IN ('Accept', 'Reject', 'Watchlist')),
    note text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE manual_positions (
    position_id text PRIMARY KEY,
    environment text NOT NULL CHECK (environment = 'SHADOW'),
    owner_user_id text NOT NULL,
    signal_id text REFERENCES signals(signal_id) ON DELETE SET NULL,
    entry_price numeric NOT NULL CHECK (entry_price > 0),
    quantity numeric NOT NULL CHECK (quantity > 0),
    lifecycle text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE followup_recommendations (
    recommendation_id text PRIMARY KEY,
    environment text NOT NULL CHECK (environment = 'SHADOW'),
    owner_user_id text,
    signal_id text NOT NULL REFERENCES signals(signal_id) ON DELETE CASCADE,
    position_id text REFERENCES manual_positions(position_id) ON DELETE SET NULL,
    candle_date date NOT NULL,
    action text NOT NULL,
    priority integer NOT NULL,
    status text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    outcome_at timestamptz,
    UNIQUE (environment, recommendation_id)
);

CREATE TABLE notification_outbox (
    outbox_id text PRIMARY KEY,
    environment text NOT NULL CHECK (environment = 'SHADOW'),
    delivery_key text NOT NULL,
    channel text NOT NULL CHECK (channel = 'TELEGRAM'),
    message text NOT NULL CHECK (message LIKE '[NXT-CLOUD][SHADOW]%'),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL CHECK (status IN ('PENDING', 'FAILED', 'DELIVERED')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz,
    UNIQUE (environment, delivery_key)
);

CREATE TABLE idempotency_keys (
    owner_user_id text NOT NULL,
    idempotency_key text NOT NULL,
    operation text NOT NULL,
    response_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_user_id, idempotency_key, operation)
);

-- Retains local-only records that have no cloud runtime table without losing provenance.
CREATE TABLE legacy_import_records (
    environment text NOT NULL CHECK (environment = 'SHADOW'),
    owner_user_id text NOT NULL,
    source_table text NOT NULL,
    source_key text NOT NULL,
    payload jsonb NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (environment, owner_user_id, source_table, source_key)
);

CREATE INDEX signals_owner_date_idx ON signals(environment, owner_user_id, signal_date DESC);
CREATE INDEX scan_runs_owner_started_idx ON scan_runs(environment, owner_user_id, started_at DESC);
CREATE INDEX followups_owner_date_idx ON followup_recommendations(environment, owner_user_id, candle_date DESC);
CREATE INDEX outbox_delivery_idx ON notification_outbox(environment, status, created_at);

ALTER TABLE scan_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE scan_run_symbols ENABLE ROW LEVEL SECURITY;
ALTER TABLE signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE manual_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE followup_recommendations ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE legacy_import_records ENABLE ROW LEVEL SECURITY;

-- No client policies are defined: browser-facing Supabase roles receive no direct table access.
-- The backend connects through the server-side PostgreSQL adapter.
CREATE VIEW accepted_monitor_subjects WITH (security_invoker = true) AS
WITH latest_decision AS (
    SELECT DISTINCT ON (environment, owner_user_id, signal_id)
        environment, owner_user_id, signal_id, decision
    FROM decisions
    ORDER BY environment, owner_user_id, signal_id, created_at DESC, decision_id DESC
), latest_plan AS (
    SELECT DISTINCT ON (environment, owner_user_id, signal_id)
        environment, owner_user_id, signal_id, payload
    FROM trade_plans
    ORDER BY environment, owner_user_id, signal_id, created_at DESC, plan_id DESC
)
SELECT
    s.environment,
    s.signal_id,
    s.symbol,
    s.payload AS signal_payload,
    COALESCE(lp.payload, '{}'::jsonb) AS plan_payload,
    p.position_id,
    CASE WHEN p.position_id IS NULL THEN NULL ELSE p.payload END AS position_payload,
    COALESCE((
        SELECT jsonb_agg(DISTINCT f.action)
        FROM followup_recommendations f
        WHERE f.environment = s.environment
          AND f.owner_user_id = s.owner_user_id
          AND f.signal_id = s.signal_id
          AND f.status = 'Acknowledged'
    ), '[]'::jsonb) AS acknowledged_actions,
    (
        SELECT f.payload
        FROM followup_recommendations f
        WHERE f.environment = s.environment
          AND f.owner_user_id = s.owner_user_id
          AND f.signal_id = s.signal_id
          AND f.status = 'Pending'
        ORDER BY f.priority, f.candle_date DESC, f.created_at DESC
        LIMIT 1
    ) AS pending_followup
FROM signals s
JOIN latest_decision d
  ON d.environment = s.environment
 AND d.owner_user_id = s.owner_user_id
 AND d.signal_id = s.signal_id
 AND d.decision = 'Accept'
LEFT JOIN latest_plan lp
  ON lp.environment = s.environment
 AND lp.owner_user_id = s.owner_user_id
 AND lp.signal_id = s.signal_id
LEFT JOIN manual_positions p
  ON p.environment = s.environment
 AND p.owner_user_id = s.owner_user_id
 AND p.signal_id = s.signal_id
 AND p.lifecycle NOT IN ('Closed', 'Stopped', 'Rejected', 'Expired');
