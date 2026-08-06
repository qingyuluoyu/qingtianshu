# Advisor Stock Dialogue Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make stock-chat answers question-scoped, evidence-bounded, explainable in Preview mode, and visibly distinguish model execution from deterministic fallback.

**Architecture:** Preserve the existing stock-research evidence pipeline. Add a deterministic research-plan contract that limits selected modules, have Preview and model prompts consume that contract, and expose the same runtime metadata through the advisor-lab API/UI. Output guards validate the public answer contract rather than relying on frontend hiding.

**Tech Stack:** Python 3, FastAPI, existing AgentService/ResearchPlanService, static browser JavaScript, pytest.

## Global Constraints

- Do not hard-code specific securities or responses.
- No additional data providers, database migrations, or model dependencies.
- Position reassessment is research-only: never issue a buy/sell/position instruction.
- The formal chat API remains backward compatible; the advisor lab stays read-only.

---

### Task 1: Research-plan contract and routing

**Files:**
- Modify: `app/services/research_plan.py`
- Test: `tests/test_research_plan.py`

- [ ] Write failing tests for unknown/default, position reassessment, explicit comprehensive, peer valuation, and price-cause topic selection.
- [ ] Run `pytest --noconftest tests/test_research_plan.py -q` and confirm the old default-comprehensive expectation fails.
- [ ] Add `answer_mode`, `selected_topics`, `skipped_topics`, and `selection_reasons`; route `position_reassessment`; cap focused topics at three and explicit comprehensive core topics at four.
- [ ] Make analyst expectations, shareholder structure, business structure, peer comparison, and outlook calibration explicit opt-ins.
- [ ] Re-run the focused test selection and record its result.

### Task 2: Deterministic preview and model-answer contract

**Files:**
- Modify: `app/services/agent_preview_stock.py`
- Modify: `app/services/agent_preview.py`
- Modify: `app/services/agent_prompt_contracts.py`
- Modify: `app/services/agent_response_relevance.py`
- Modify: `app/services/agent_output_guard_stock.py`
- Modify: `app/services/agent.py`
- Test: `tests/test_stock_research_contract.py`
- Test: `tests/test_agent_guard.py`

- [ ] Write failing unit tests proving Preview uses only selected topics, begins with a user-readable deterministic-source declaration, caps factual modules and gaps, and treats short backtest samples as insufficient.
- [ ] Run the selected tests and confirm they fail on the old unconstrained output.
- [ ] Render the four public sections: `综合判断`, `关键证据`, `专题核验`, `仍需确认`; enforce Preview 300–700 Chinese characters when evidence permits, and cap explicit comprehensive output at 1000 characters.
- [ ] Add prompt and guard checks for selected modules only, hidden internal terms, topic/length limits, position-reassessment boundary, evidence conflict confidence downgrade, and technical-level/valuation-direction restrictions.
- [ ] Ensure guard failures label their answer source accurately as guard fallback or degraded fallback.
- [ ] Re-run the selected tests and record its result.

### Task 3: Runtime metadata and advisor-lab transparency

**Files:**
- Modify: `app/services/chat_execution.py`
- Modify: `app/services/chat_orchestration.py`
- Modify: `app/main.py`
- Modify: `app/static/advisor-lab.html`
- Modify: `app/static/advisor-lab.js`
- Modify: `app/static/advisor-lab.css`
- Modify: `tests/test_advisor_lab_service.py`
- Test: `tests/test_chat_execution.py`

- [ ] Write failing tests for Preview state (`status=preview`, `answer_source=preview`, `model_executed=false`) and plan metadata propagation.
- [ ] Run the selected tests and confirm the new runtime fields are absent.
- [ ] Return and persist `answer_source`, `model_executed`, selected/skipped topics and selection reasons without changing formal API fields.
- [ ] Replace the default raw-JSON lab panel with readable status, execution/source, selected topics, skipped topics and evidence summary; keep technical JSON in a collapsed diagnostics panel.
- [ ] Re-run focused API/service tests and JavaScript syntax validation.

### Task 4: Regression and local quality smoke

**Files:**
- Modify: `tests/test_research_plan.py`
- Modify: `tests/test_agent_guard.py`
- Modify: `tests/test_advisor_lab_service.py`

- [ ] Add the seven specified behavioural regressions using generic evidence fixtures and no fixed response text.
- [ ] Run collection for the affected tests, then their full focused suite with `--noconftest` where database fixtures are not required.
- [ ] Run `compileall`, JavaScript syntax validation, and a local advisor-lab smoke request that prints status/source/model execution/topic fields and answer.
- [ ] Attempt the project suite; if the existing protected test database remains unavailable, report its exact failure without using a potentially real database.
