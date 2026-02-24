# Project Wishlist

This file is the single source of truth for feature ideas and improvements.
Keep entries short and actionable so they can be moved through the stages.

## Status Values

- `idea`: captured, not triaged
- `triaged`: reviewed and prioritized
- `planned`: ready for implementation
- `done`: shipped and documented

## Item Template

Copy this block when adding a new item:

```md
### <Short title>
- Problem: <What user/project problem does this solve?>
- Proposed approach: <How we could solve it>
- Effort: <S|M|L>
- Impact: <Low|Med|High>
- Status: <idea|triaged|planned|done>
- Notes: <Optional acceptance criteria, links, constraints>
```

## Intake

Raw ideas go here first.

### Example: Save breathing presets
- Problem: Users repeat the same target and breathing rate setup each session.
- Proposed approach: Add named preset save/load controls in the main UI.
- Effort: M
- Impact: High
- Status: idea
- Notes: Start with local config storage; no cloud sync required.

## Prioritized

Top candidates after triage. Keep this list focused and ordered by value.

### 1) Define session user selection flow
- Problem: The app needs to know who is using the current session before data and settings can be applied correctly.
- Proposed approach: Define when/how the active user is selected at session start.
- Effort: M
- Impact: High
- Status: done
- Notes: Prioritize first because it unblocks per-user settings and history behavior.

### 2) Multiple user profiles with per-user history
- Problem: Sessions and history are not separated by person, which makes tracking progress across users difficult.
- Proposed approach: Add support for multiple user profiles and persist profile-specific session history (SQLite is a candidate).
- Effort: L
- Impact: High
- Status: done
- Notes: Decide where profile management lives in the UI (new card/screen vs settings area).

### 3) Per-user welcome/disclaimer visibility preference
- Problem: Users may not want to see the Welcome/Disclaimer every launch, but this preference should be tracked per user.
- Proposed approach: Add a "don't show again" preference stored per user profile.
- Effort: M
- Impact: Med
- Status: done
- Notes: Depends on session user identity and profile storage.

### 4) Decide QTc presentation format
- Problem: It is unclear how QTc should be presented in a way that is useful and not misleading.
- Proposed approach: Evaluate options such as a dedicated QTc plot, single end-of-session value, or both.
- Effort: S
- Impact: Med
- Status: triaged
- Notes: Finalize UX before implementing calculation output.

### 5) QTc estimation capability
- Problem: The app currently lacks QTc estimate support for users who want a rough indication.
- Proposed approach: Add QTc estimation with clear messaging that results are approximate.
- Effort: M
- Impact: Med
- Status: triaged
- Notes: Show prominent disclaimer that estimate may be off by around 15% and is not diagnostic.

### 6) Add profile demographics metadata (age, gender, notes)
- Problem: Profile records currently do not capture key contextual demographics needed for interpretation and reporting.
- Proposed approach: Extend profile data model and UI to store age, gender, and free-text notes per user profile.
- Effort: M
- Impact: High
- Status: done
- Notes: Implemented in profile store schema and Profile Manager details form.

## PlannedNext

Items that are implementation-ready and should be picked up soon.

### A) Session user selection flow (from prioritized item 1)
- Problem: The app must know the active user at session start.
- Proposed approach: Add a startup user-selection step before session data loads.
- Effort: M
- Impact: High
- Status: done
- Notes: Should support quick start and avoid breaking current single-user behavior.

Implementation checklist:
- [x] Define UX path: startup selector vs quick switch entry point.
- [x] Define session lifecycle states (`no_user_selected`, `user_selected`, `guest_mode` if used).
- [x] Add active-user state to app session context.
- [x] Ensure new session start requires a selected user (or explicit guest fallback).
- [x] Define behavior when switching users mid-app (currently startup selection only; switch action deferred).
- [x] Add acceptance criteria for flow (startup, cancel, user choose, and reconnect baseline checks).

### B) Multiple user profiles and per-user history (from prioritized item 2)
- Problem: Data is not currently segmented by user identity.
- Proposed approach: Add profile entities and persist profile-linked session history (SQLite candidate).
- Effort: L
- Impact: High
- Status: done
- Notes: Build after user-selection flow contract is finalized.

Implementation checklist:
- [x] Choose storage model (SQLite tables vs existing storage path extension).
- [x] Define profile schema (id, display name, created/updated timestamps, optional metadata).
- [x] Define history schema linked to profile id.
- [x] Add profile CRUD operations (create, rename, select, archive/delete policy).
- [x] Migrate existing single-user history to profile-backed indexing safely (legacy fallback profile included).
- [x] Update history queries/views to filter by active profile.
- [x] Add tests for profile isolation and migration edge cases.

## Done

Completed items. Include completion date and optional version reference.

### Session user selection flow
- Completed: 2026-02-24
- Outcome: Startup profile chooser implemented (select/create/guest), active profile shown at top of monitoring card, startup flow gates session context.
- Notes: Mid-session quick-switch UI is intentionally deferred; current behavior is select at startup.

### Per-user welcome/disclaimer visibility preference
- Completed: 2026-02-24
- Outcome: Disclaimer display is now profile-specific with "Don't show again" persistence.
- Notes: Settings includes queued reset for disclaimer prompt (active user or all users) applied on Save and Close; confirmation popup and persistence behavior were hardened.

### Multiple user profiles and per-user history
- Completed: 2026-02-24
- Outcome: Profile CRUD (create/rename/archive/restore/delete), one-time legacy migration indexing, profile-scoped history query APIs, and read-only in-app history viewer.
- Notes: Active-profile safeguards are enforced; profile changes are blocked during active recording.

### Profile demographics metadata (age, gender, notes)
- Completed: 2026-02-24
- Outcome: Profile records now persist age, gender, and notes; Profile Manager includes editable fields with save action.
- Notes: Demographics are currently profile metadata only (not yet surfaced in report documents).

## Triage Workflow

1. Add new suggestions to `Intake` using the template.
2. During review, clarify scope and acceptance criteria.
3. Assign `Effort` and `Impact`, then move strong candidates to `Prioritized`.
4. Move build-ready items to `PlannedNext` and set status to `planned`.
5. After release, move to `Done`, set status to `done`, and link version notes in `changelog.md` when relevant.
