CREATE OR REPLACE VIEW accepted_monitor_subjects WITH (security_invoker = true) AS
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
          AND f.outcome IN ('Applied', 'Already Closed')
    ), '[]'::jsonb) AS acknowledged_actions,
    (
        SELECT f.payload
        FROM followup_recommendations f
        WHERE f.environment = s.environment
          AND f.owner_user_id = s.owner_user_id
          AND f.signal_id = s.signal_id
          AND f.status = 'Pending'
          AND f.action NOT IN ('NO_ACTION', 'DATA_STALE', 'NEEDS_REVIEW')
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
 AND p.lifecycle NOT IN ('Closed', 'Stopped', 'Rejected', 'Expired')
WHERE NOT EXISTS (
    SELECT 1
    FROM followup_recommendations terminal
    WHERE terminal.environment = s.environment
      AND terminal.owner_user_id = s.owner_user_id
      AND terminal.signal_id = s.signal_id
      AND terminal.status = 'Acknowledged'
      AND terminal.outcome IN ('Applied', 'Already Closed')
      AND terminal.action IN ('STOP_LOSS', 'BE_STOP', 'TAIL_EXIT_EMA50', 'TAIL_EXIT_SSL', 'MANUAL_CLOSE')
);
