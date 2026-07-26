-- Expand-only workflow discriminator for independently triggered AI workspaces.
ALTER TABLE ai_research_runs ADD COLUMN workflow TEXT NOT NULL
    DEFAULT 'lao_li_diagnosis_v1'
    CHECK(workflow IN ('lao_li_diagnosis_v1', 'five_dimension_v7'));

UPDATE ai_research_runs
SET workflow = 'lao_li_diagnosis_v1'
WHERE workflow IS NULL OR workflow = '';

CREATE INDEX idx_ai_research_user_workflow_created
    ON ai_research_runs(user_id, workflow, created_at DESC);
