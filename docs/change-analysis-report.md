# Repository Change Analysis Report

**Repository:** `paly-paul/yourskills-app-backend`
**Branch analyzed:** `claude/async-gemini-refactor` (vs base `punit-branch-for-testing`)
**Report date:** 2026-06-22

## Executive Summary

This branch contains a focused three-phase refactoring of the Gemini LLM integration layer: (1) all blocking synchronous Gemini API calls were converted to native async using `generate_content_async`, eliminating `asyncio.to_thread` wrappers; (2) all duplicate prompt strings scattered across `cv_extractor.py` and `router.py` were extracted into a centralized `prompts.py` constants file, removing ~960 lines of duplication and commented-out dead code; (3) the two highest-token prompts (`CV_EXTRACTION_PROMPT` and `SUMMARY_EXTRACTION_PROMPT`) were compressed by 55-64% while preserving identical output behavior. Net result: **290 lines added, 960 lines removed** across 3 files.

---

## STEP 1 — Repository Overview

### Recent Commit History (all branches)
```
fc2e0cb Optimize highest-token prompts for reduced token usage
981d9d6 Extract all duplicate prompts into centralized prompts.py
ecae3fa Refactor blocking Gemini API calls to async
0653c51 Add Gemini API usage audit report
4990acb feat: add Gemini call logging with caller, timing, retry and gather counts
b2dcdd1 fix: correct infinite recursion in _gemini_with_retry
128be23 fix: replace curly quotes with straight quotes on line 1395
1929d25 fix: resolve Gemini API concurrency and scalability issues
9d9d383 Updated Merged Code
0ebd97b Merge-Branch
```

### Branches
| Branch | Type |
|--------|------|
| `claude/async-gemini-refactor` | Local + Remote (current) |
| `claude/festive-tesla-y5yve5` | Local + Remote |
| `punit-branch-for-testing` | Local + Remote (base) |

### Working Tree Status
Clean — no uncommitted changes.

---

## STEP 2 — Commit-by-Commit Breakdown

### Commit 1: `ecae3fa` — Refactor blocking Gemini API calls to async
**Author:** Claude | **Date:** 2026-06-22

| File | Added | Removed |
|------|-------|---------|
| `app/api/router.py` | 11 | 13 |
| `app/utils/cv_extractor.py` | 6 | 6 |

### Commit 2: `981d9d6` — Extract all duplicate prompts into centralized prompts.py
**Author:** Claude | **Date:** 2026-06-22

| File | Added | Removed |
|------|-------|---------|
| `app/api/router.py` | 2 | 80 |
| `app/utils/cv_extractor.py` | 41 | 915 |
| `app/utils/prompts.py` (NEW) | 487 | 0 |

### Commit 3: `fc2e0cb` — Optimize highest-token prompts for reduced token usage
**Author:** Claude | **Date:** 2026-06-22

| File | Added | Removed |
|------|-------|---------|
| `app/utils/prompts.py` | 51 | 305 |

---

## STEP 3 — Full Diff Summary (vs `punit-branch-for-testing`)

### `app/api/router.py`

**Added (+10 lines):**
- Import of `build_summary_extraction_prompt` from `app.utils.prompts`
- Replaced `_gemini_sync_with_retry` with `_gemini_async_with_retry` using native `generate_content_async`
- Direct `await extract_cv_data_from_file(...)` calls (no more `asyncio.to_thread` wrapper)
- One-liner `extract_prompt = build_summary_extraction_prompt(parsed_resume)` replacing 75-line inline prompt

**Removed (-88 lines):**
- `_gemini_sync_with_retry` function (sync-in-thread approach)
- 75-line inline `SUMMARY_EXTRACTION_PROMPT` f-string in `extract_cv_summary`
- `asyncio.to_thread` wrappers around `extract_cv_data_from_file` at two call sites
- Unused `import asyncio as _asyncio`

**Summary:** Router now uses native async Gemini calls and imports prompts from the centralized module instead of inlining them.

### `app/utils/cv_extractor.py`

**Added (+47 lines):**
- Import block for 8 prompt constants from `app.utils.prompts`
- `.format()` calls on imported prompt constants at each LLM call site

**Removed (-872 lines):**
- 290 lines of commented-out old `extract_cv_data_from_file` (dead code)
- 147 lines of commented-out old `generate_anchor_attribute_options` (dead code)
- ~200-line inline CV extraction prompt (replaced by `CV_EXTRACTION_PROMPT` import)
- ~80-line inline missing-field suggestion prompt
- ~60-line inline job attribute options prompt (with-CV version)
- ~50-line inline job attribute options prompt (without-CV version)
- ~80-line inline anchor options prompt (with-CV version)
- ~60-line inline anchor options prompt (without-CV version)
- Duplicate `style_noise_pool` list definitions
- Duplicate `variation_instructions` string definitions
- Changed `extract_cv_data_from_file` from `def` (sync) to `async def`
- Changed `model.generate_content()` to `await _gemini_with_retry()`

**Summary:** Massive cleanup — 872 lines of inline prompts and dead code removed, replaced by 47 lines of imports and format calls. Function converted from sync to async.

### `app/utils/prompts.py` (NEW FILE)

**Added (+233 lines):**
- All 9 LLM prompt constants centralized in one module
- `build_summary_extraction_prompt()` helper function
- `STYLE_NOISE_POOL` and `VARIATION_INSTRUCTIONS` shared building blocks
- Token-optimized versions of the two largest prompts

**Summary:** New centralized prompt constants file, serving as the single source of truth for all Gemini LLM prompts.

---

## STEP 4 — Structured Summary Table

| File | Change Type | Lines Added | Lines Removed | What Changed (plain English) |
|------|-------------|-------------|---------------|------------------------------|
| `app/api/router.py` | Modified | 10 | 88 | Converted sync-in-thread Gemini calls to native async; replaced 75-line inline prompt with one-liner import |
| `app/utils/cv_extractor.py` | Modified | 47 | 872 | Removed 872 lines of inline prompts + dead code; added imports from centralized prompts.py; converted main extraction function to async |
| `app/utils/prompts.py` | **New** | 233 | 0 | Centralized all 9 LLM prompt constants with token-optimized versions of the two largest prompts |
| **TOTAL** | | **290** | **960** | **Net reduction: 670 lines** |

---

## STEP 5 — Logical Change Groupings

### Refactors / Code Cleanup
- Deleted 437 lines of commented-out dead code (old `extract_cv_data_from_file` and `generate_anchor_attribute_options`)
- Removed all duplicate prompt definitions across two files
- Removed duplicate `style_noise_pool` and `variation_instructions` definitions

### Prompt / LLM Logic Changes
- Created `app/utils/prompts.py` as single source of truth for all 9 LLM prompts
- `CV_EXTRACTION_PROMPT`: compressed from ~1082 → ~490 tokens (55% reduction) — instructions condensed, JSON schema compacted to single-line format
- `SUMMARY_EXTRACTION_PROMPT`: compressed from ~370 → ~133 tokens (64% reduction) — instructions condensed, output schema compacted
- All call sites now use `from app.utils.prompts import X` + `.format()` instead of inline strings

### Performance / Async Changes
- `extract_cv_data_from_file()` converted from sync `def` to `async def`
- `model.generate_content()` → `await _gemini_with_retry()` (native `generate_content_async`)
- `_gemini_sync_with_retry()` → `_gemini_async_with_retry()` (removed `asyncio.to_thread` wrapper)
- Two `asyncio.to_thread(extract_cv_data_from_file, ...)` call sites → direct `await extract_cv_data_from_file(...)`

---

## STEP 6 — Uncommitted / Staged Changes

**None.** Working tree is clean. All changes are committed and pushed to `origin/claude/async-gemini-refactor`.
