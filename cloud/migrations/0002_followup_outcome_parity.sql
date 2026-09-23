ALTER TABLE followup_recommendations
    ADD COLUMN outcome text;

UPDATE followup_recommendations AS target
SET outcome = legacy.payload ->> 'outcome'
FROM legacy_import_records AS legacy
WHERE legacy.environment = target.environment
  AND legacy.owner_user_id = target.owner_user_id
  AND legacy.source_table = 'followup_recommendations'
  AND legacy.source_key = target.recommendation_id
  AND legacy.payload ->> 'outcome' IS NOT NULL;

UPDATE followup_recommendations
SET outcome = CASE status
        WHEN 'Dismissed' THEN 'Not Applied'
        WHEN 'NotApplicable' THEN 'Not Applicable'
        ELSE status
    END,
    status = 'Acknowledged'
WHERE status IN ('Applied', 'Dismissed', 'NotApplicable');
