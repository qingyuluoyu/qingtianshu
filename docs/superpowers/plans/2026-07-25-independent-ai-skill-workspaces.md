# Independent AI Skill Workspaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build two visually balanced, independently triggered AI research workspaces: Lao Li stock diagnosis on the left and v7.0.0 five-dimension analysis on the right.

**Architecture:** Keep the existing durable AI research run and Redis worker path, but add an explicit workflow value to the persisted task payload. Lao Li runs keep the existing conversation-oriented path; five-dimension runs create their own audit conversation, load five versioned project-owned Skills, execute only the five dimension tasks, and never read Lao Li conversation messages.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite-compatible versioned migrations, Redis research worker, vanilla HTML/CSS/JavaScript, pytest.

## Global Constraints

- Only A-share symbols ending in `.SS`, `.SZ`, or `.BJ` are accepted.
- Clicking one workspace must not create, mutate, poll, or execute the other workspace.
- Five-dimension analysis uses v7.0.0 `fundamental`, `industry`, `valuation`, `technical`, and `risk` Skills.
- Raw Skill instructions never appear in public API responses or browser HTML.
- Both workflows use persisted runs, idempotency keys, existing per-user concurrency limits, cancellation, retry, budget, and trace fields.
- Desktop result text is at least 16px with line-height at least 1.7.
- At 390×844 the page has no document-level horizontal overflow.

---

### Task 1: Versioned five-dimension Skill loader

**Files:**
- Create: `app/skills/a_share_five_dimension_v7/COMMON_RUNTIME_STANDARD.md`
- Create: `app/skills/a_share_five_dimension_v7/{fundamental,industry,valuation,technical,risk}/SKILL.md`
- Create: `app/skills/a_share_five_dimension_v7/{fundamental,industry,valuation,technical,risk}/manifest.json`
- Create: `app/skills/a_share_five_dimension_v7/{fundamental,industry,valuation,technical,risk}/OUTPUT_SCHEMA.json`
- Create: `app/services/five_dimension_skill.py`
- Modify: `app/config.py`
- Modify: `pyproject.toml`
- Test: `tests/test_five_dimension_skill.py`
- Test: `tests/test_packaging.py`

**Interfaces:**
- Produces: `FiveDimensionSkillLoader.load_all() -> dict[str, DimensionSkillPrompt]`
- Produces: `FiveDimensionSkillLoader.public_metadata() -> dict[str, Any]`
- Each `DimensionSkillPrompt` exposes `key`, `name`, `version`, `digest`, `instructions`, and `output_schema`.

- [ ] **Step 1: Write failing loader and packaging tests**

```python
def test_five_dimension_loader_reads_all_v7_skills(settings):
    bundle = FiveDimensionSkillLoader(settings).load_all()
    assert list(bundle) == ["fundamental", "industry", "valuation", "technical", "risk"]
    assert {item.version for item in bundle.values()} == {"7.0.0"}
    assert all(item.instructions and item.output_schema for item in bundle.values())


def test_five_dimension_public_metadata_hides_prompts(settings):
    metadata = FiveDimensionSkillLoader(settings).public_metadata()
    assert metadata["version"] == "7.0.0"
    assert "instructions" not in json.dumps(metadata)
```

- [ ] **Step 2: Run the tests and verify missing loader/assets fail**

Run: `pytest tests/test_five_dimension_skill.py tests/test_packaging.py -q`

Expected: failure because `app.services.five_dimension_skill` and packaged assets do not yet exist.

- [ ] **Step 3: Add the trusted assets, configuration, loader and package-data declarations**

The loader must reject a missing manifest, mismatched dimension, mismatched version, invalid JSON Schema, or a bundle missing any required dimension. Cache only when every loaded file’s path, modification time and size are unchanged.

- [ ] **Step 4: Run loader and packaging tests**

Run: `pytest tests/test_five_dimension_skill.py tests/test_packaging.py -q`

Expected: all tests pass.

### Task 2: Persisted workflow routing and independent five-dimension API

**Files:**
- Modify: `app/services/research_dispatcher.py`
- Modify: `app/services/ai_research.py`
- Modify: `app/db.py`
- Modify: `app/main.py`
- Modify: `app/research_worker_main.py`
- Test: `tests/test_research_dispatcher.py`
- Test: `tests/test_ai_research.py`
- Create: `tests/test_ai_skill_workspace_api.py`

**Interfaces:**
- Extend: `ResearchDispatcher.submit(..., workflow: Literal["lao_li_diagnosis_v1", "five_dimension_v7"])`
- Add: `AIResearchService.execute_queued(task: dict[str, Any]) -> bool`
- Add endpoint: `POST /me/ai-research/five-dimension-runs`
- Add endpoint: `GET /me/ai-research/five-dimension-runs/current`
- Reuse endpoint: `GET /me/ai-research/runs/{run_id}`

- [ ] **Step 1: Write failing workflow isolation tests**

```python
def test_five_dimension_submission_is_independent_of_lao_li_conversation(client, app):
    _login(client)
    created = client.post(
        "/me/ai-research/five-dimension-runs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"symbol": "300750.SZ", "name": "宁德时代", "focus": "盈利持续性"},
    )
    assert created.status_code == 202
    run = created.json()
    assert run["workflow"] == "five_dimension_v7"
    assert run["skill_bundle"]["version"] == "7.0.0"
    assert set(run["dimensions"]) == {
        "fundamental", "industry", "valuation", "technical", "risk"
    }
    assert "instructions" not in json.dumps(run, ensure_ascii=False)
```

Also assert that a Lao Li submission persists `workflow=lao_li_diagnosis_v1`, five-dimension task payloads do not contain conversation history, unsupported markets return 422, idempotency conflicts return 409, and current-run lookup filters by workflow.

- [ ] **Step 2: Run focused tests and confirm missing route/workflow failures**

Run: `pytest tests/test_ai_skill_workspace_api.py tests/test_ai_research.py tests/test_research_dispatcher.py -q`

Expected: failures for the missing five-dimension route and workflow contract.

- [ ] **Step 3: Implement workflow-aware persistence and execution**

Persist `workflow` inside the generic run input and research task payload. Build one evidence snapshot for a five-dimension run, attach private per-dimension Skill instructions to the persisted snapshot, and expose only `name`, `version`, `dimension`, and `digest`.

`AIResearchService.execute_queued()` dispatches:

```python
if workflow == "five_dimension_v7":
    return self.execute_five_dimension_run(user_id, run_id)
return self.execute_queued_main(task)
```

Five-dimension completion is `completed` only when all five results are saved. A partial dimension failure produces `constrained` public status and retains every successful result and structured error.

- [ ] **Step 4: Run focused backend tests**

Run: `pytest tests/test_ai_skill_workspace_api.py tests/test_ai_research.py tests/test_research_dispatcher.py tests/test_research_worker.py -q`

Expected: all tests pass.

### Task 3: Independent dual-workspace front end

**Files:**
- Modify: `app/static/high-fidelity-demo.html`
- Modify: `app/static/high-fidelity-demo.css`
- Modify: `app/static/high-fidelity-demo.js`
- Create: `tests/test_ai_skill_workspace_frontend.py`
- Modify: `tests/test_stock_dashboard.py`

**Interfaces:**
- Left IDs: `laoLiTarget`, `laoLiQuestion`, `startLaoLiDiagnosis`, `laoLiAnswer`, `laoLiFollowup`
- Right IDs: `fiveDimTarget`, `fiveDimFocus`, `startFiveDimension`, `fiveDimensionList`
- Separate state objects: `laoLiState` and `fiveDimensionState`

- [ ] **Step 1: Write failing DOM and JavaScript isolation tests**

```python
def test_ai_page_has_independent_skill_workspaces(frontend_text):
    assert 'id="startLaoLiDiagnosis"' in frontend_text
    assert 'id="startFiveDimension"' in frontend_text
    assert "var laoLiState=" in frontend_text
    assert "var fiveDimensionState=" in frontend_text
    assert "runLaoLiDiagnosis" in frontend_text
    assert "runFiveDimensionAnalysis" in frontend_text
    assert "fiveDimTarget" in frontend_text
    assert "researchState" not in the_ai_workspace_script(frontend_text)
```

Also assert that the right button calls only `/me/ai-research/five-dimension-runs`, the left button calls only `/me/ai-research/runs`, the five public Skill labels are present, and no raw `SKILL.md` content is embedded in HTML.

- [ ] **Step 2: Run focused front-end tests and confirm failures**

Run: `pytest tests/test_ai_skill_workspace_frontend.py tests/test_stock_dashboard.py -q`

Expected: failures against the current coupled research form and shared `researchState`.

- [ ] **Step 3: Replace the coupled layout and event flow**

Build a `.skill-workspace-grid` with two equal columns. The left side owns its inputs, conversation run and polling timer. The right side owns its stock, focus, run and polling timer. Dimension cards render status and structured results inline or in the existing accessible modal.

Set:

```css
.skill-result-copy { font-size: 16px; line-height: 1.75; }
.skill-workspace-title h2 { font-size: 23px; }
@media (max-width: 820px) {
  .skill-workspace-grid { grid-template-columns: 1fr; }
}
```

- [ ] **Step 4: Run front-end contract and syntax tests**

Run: `pytest tests/test_ai_skill_workspace_frontend.py tests/test_stock_dashboard.py -q`

Run: `node --check app/static/high-fidelity-demo.js`

Expected: all tests and JavaScript syntax check pass.

### Task 4: End-to-end regression and responsive verification

**Files:**
- Modify only files required by failures discovered in this task.

**Interfaces:**
- No new interface. This task verifies the complete vertical slice.

- [ ] **Step 1: Run affected backend and front-end suites**

Run:

```powershell
pytest tests/test_five_dimension_skill.py tests/test_packaging.py tests/test_ai_skill_workspace_api.py tests/test_ai_skill_workspace_frontend.py tests/test_ai_research.py tests/test_research_dispatcher.py tests/test_research_worker.py tests/test_stock_dashboard.py -q
```

Expected: all tests pass with no skips.

- [ ] **Step 2: Run complete test suite and static checks**

Run:

```powershell
pytest tests/test_api.py -q
pytest -q --ignore=tests/test_api.py
python -m compileall -q app
node --check app/static/high-fidelity-demo.js
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 3: Verify the live page**

At 1440×900 verify two equal workspaces, readable 16px-or-larger result text, no broken assets and no document overflow. Click the left button with a valid stock and confirm only the Lao Li request is created. Click the right button with a valid stock and confirm only a five-dimension request is created.

At 390×844 verify single-column layout, workspace shortcut navigation, full-width controls, dimension cards, modal/dialog bounds, and no document overflow.

- [ ] **Step 4: Record real results**

Report modified files, workflow and data-flow changes, actual command outputs, warnings, skipped checks, compatibility impact, model-cost impact, remaining production risks and manual reproduction steps.
