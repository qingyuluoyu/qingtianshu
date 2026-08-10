# Public Market Entry and Dashboard Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let anonymous visitors read the public market snapshot immediately and give the Today experience a clear, production-ready information hierarchy.

**Architecture:** Preserve the existing public/private query split. Change routing policy so `/today` is a public discovery route; private modules remain gated in place. Replace the developer-oriented shell labels with grouped human navigation and a responsive menu control, then reorder Today into market status, primary signals, and secondary research layers without changing data contracts.

**Tech Stack:** React 19, React Router, TanStack Query, CSS Modules, Vitest, React Testing Library.

## Global Constraints

- Do not alter market data endpoints, units, formulas, provider selection, or session API contracts.
- Do not mount personal queries for anonymous users.
- Keep login explicit for public routes; it must only open from a user action.
- Preserve accessible keyboard navigation and existing route URLs.

### Task 1: Make `/today` a readable public entry route

**Files:**
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `frontend/src/app/App.tsx`

- [x] Write a test that anonymous `/today` renders the page without a dialog.
- [x] Run `npm run test -- src/app/App.test.tsx` and confirm it fails because the dialog auto-opens.
- [x] Remove `/today` from route-level automatic authentication prompting; retain explicit login and protected personal routes.
- [x] Re-run the focused test and confirm it passes.

### Task 2: Replace shell developer labels with usable navigation

**Files:**
- Create: `frontend/src/components/AppShell.test.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/AppShell.module.css`

- [x] Test grouped primary navigation, a human page label, and a mobile menu control.
- [x] Run the focused test and confirm it fails because the shell exposes a raw pathname and hides navigation on mobile.
- [x] Add grouped navigation, active state, page-title mapping, and a keyboard-accessible mobile toggle.
- [x] Re-run the focused test and confirm it passes.

### Task 3: Establish Today hierarchy through composition and CSS

**Files:**
- Modify: `frontend/src/features/today/TodayPage.tsx`
- Modify: `frontend/src/features/today/TodayPage.module.css`
- Modify: `frontend/src/features/today/TodayPage.test.tsx`

- [x] Test named primary/secondary sections that retain all public modules and preserve private locks.
- [x] Run the focused test and confirm it fails because the page only uses equal-weight generic grids.
- [x] Introduce semantic landmarks for market pulse, market context, and research follow-up; style a two-level grid with readable metadata and responsive collapse.
- [x] Re-run the focused test and confirm it passes.

### Task 4: Release verification

**Files:**
- Modify: this plan with actual results only.

- [x] Run `npm run test -- src/app/App.test.tsx src/components/AppShell.test.tsx src/features/today/TodayPage.test.tsx` — 15 tests passed.
- [x] Run `npm run test` and `npm run build` — 32 test files / 174 tests passed; production build succeeded.
- [x] Run `git diff --check` — no whitespace errors; Git reported pre-existing CRLF normalization warnings across the dirty working tree.
