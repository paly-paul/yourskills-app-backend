# Gemini API Call Audit Report

**Date:** 2026-06-23
**Issue:** 20-30 Gemini API calls logged per single user action

---

## 1. Executive Summary

**Total Gemini call sites found: 8** (across 2 files: `app/utils/cv_extractor.py` and `app/api/router.py`)

- **4 call sites are inside loops** (`asyncio.gather` over dynamic question lists)
- **Primary offender:** `get_audience_questions_service()` in `app/services/profile.py:233` regenerates all job attribute options on every `/job-questions` request, duplicating work already done by `/extract-cv`
- **Secondary offender:** Per-question `asyncio.gather` pattern fires 1 API call per question instead of batching
- **Estimated reduction possible:** 20-28 calls → 3-4 calls

---

## 2. All Gemini Call Sites

| # | File | Line | Function | In Loop? |
|---|------|------|----------|----------|
| 1 | `app/utils/cv_extractor.py` | 782 | `extract_cv_data_from_file` — `model.generate_content()` | No — 1 call |
| 2 | `app/utils/cv_extractor.py` | 40 | `_gemini_with_retry` — `model.generate_content_async()` (shared wrapper) | No — but invoked by loop-bound callers |
| 3 | `app/utils/cv_extractor.py` | 941 | `generate_missing_field_suggestions` via `_gemini_with_retry` | No — 1 call |
| 4 | `app/utils/cv_extractor.py` | 1078 | `generate_job_attribute_options` → `_fetch_options_for_question` via `_gemini_with_retry` | **YES — `asyncio.gather` over N questions** |
| 5 | `app/utils/cv_extractor.py` | 1433 | `generate_anchor_attribute_options` → `_fetch_anchor_option` via `_gemini_with_retry` | **YES — `asyncio.gather` over N questions** |
| 6 | `app/utils/cv_extractor.py` | 1564 | `generate_job_attribute_options_without_cv` → `_fetch_without_cv_option` via `_gemini_with_retry` | **YES — `asyncio.gather` over N questions** |
| 7 | `app/utils/cv_extractor.py` | 1724 | `generate_anchor_options_from_answers_without_cv` → `_fetch_anchor_without_cv` via `_gemini_with_retry` | **YES — `asyncio.gather` over N questions** |
| 8 | `app/api/router.py` | 1851 | `/summary/model` endpoint via `_gemini_sync_with_retry` | No — 1 call |

---

## 3. Loop Calls Table

| File | Line | Call | Loop Type | Loop Variable | Est. Iterations | Risk |
|------|------|------|-----------|---------------|-----------------|------|
| `cv_extractor.py:1113` | `_fetch_options_for_question` | `asyncio.gather` | Dynamic list from DB | `questions_from_db` | 5-10 | **HIGH** |
| `cv_extractor.py:1462` | `_fetch_anchor_option` | `asyncio.gather` | Dynamic list from DB | `questions` | 2-10 (filtered by `target_parameters`) | **HIGH** |
| `cv_extractor.py:1593` | `_fetch_without_cv_option` | `asyncio.gather` | Dynamic list from DB | `all_questions` | 5-10 | **HIGH** |
| `cv_extractor.py:1750` | `_fetch_anchor_without_cv` | `asyncio.gather` | Dynamic list from DB | `questions` | 2-10 | **HIGH** |

All loop counts are **dynamic and unbounded** — they depend on how many questions are stored in the MongoDB `questions` collection for a given `audienceType`.

---

## 4. Call Chain Map — How 20-30 Calls Are Triggered

### Path A: `POST /extract-cv` (WITH CV flow)

```
POST /extract-cv
  → extract_cv_data_from_file()            [1 Gemini call]
  → generate_job_attribute_options()
      → asyncio.gather(N questions)         [N Gemini calls]
  TOTAL: 1 + N
```

### Path B: `GET /job-questions` (WITH CV flow) — PRIMARY CULPRIT

```
GET /job-questions
  → get_audience_questions_service()
      → generate_job_attribute_options()    [REGENERATES from scratch!]
          → asyncio.gather(N questions)     [N Gemini calls]
  TOTAL: N calls (likely 5-10)
```

**This duplicates Path A's work — options were already generated and saved during `/extract-cv`.**

### Path C: `GET /anchor-questions/remaining` (WITH CV flow)

```
GET /anchor-questions/remaining
  → get_questions_excluding_parameters()
      → generate_anchor_attribute_options()
          → asyncio.gather(M questions)     [~2 Gemini calls after filtering]
  TOTAL: ~2 calls
```

### Path D: `GET /summary/model`

```
GET /summary/model
  → _gemini_sync_with_retry()               [1 Gemini call]
  TOTAL: 1
```

### Combined User Flow (typical session)

```
User uploads CV:
  POST /extract-cv              → 1 + N calls (extraction + job options)
User navigates to job questions:
  GET /job-questions             → N calls   (REDUNDANT regeneration!)
User navigates to anchor questions:
  GET /anchor-questions/remaining → ~2 calls
User views summary:
  GET /summary/model             → 1 call

If N = 8 job questions:
  extract-cv:          1 + 8 = 9
  job-questions:       8         ← REDUNDANT
  anchor-remaining:    2
  summary/model:       1
  ────────────────────────────
  TOTAL:               20 calls  ← MATCHES OBSERVED PATTERN

If N = 10:             TOTAL = 23 calls
With 429 retries:      TOTAL = 25-30 calls
```

---

## 5. Redundant / Identical Calls

### CRITICAL: `generate_job_attribute_options` called TWICE with same data

| Call # | Location | Trigger | Saves Result? |
|--------|----------|---------|---------------|
| 1st | `router.py:283` | `POST /extract-cv` | Yes — saves to `uploads.job_questions_with_options` |
| 2nd | `profile.py:233` | `GET /job-questions` | Yes — **overwrites** the same field with identical data |

The old (commented-out) code at `profile.py:148-168` correctly read saved options from DB. The current code at line 233 **always regenerates**, ignoring saved results.

### No caching or deduplication anywhere

- Zero `functools.lru_cache`, Redis, or in-memory dict lookups before any Gemini call
- No prompt deduplication
- No TTL-based cache for generated options

---

## 6. Missing Call Guards

| Guard | Present? | Details |
|-------|----------|---------|
| Caching layer | **NO** | No `lru_cache`, Redis, or in-memory dict |
| Rate limiting / call counter | **NO** | Only retry-on-429 (reactive), no proactive throttle |
| Batch processing | **NO** | 1 Gemini call per question instead of batching N questions into 1 prompt |
| Early exit / reuse | **PARTIAL** | `anchor_questions_with_options` checked before regenerating (good); `job_questions_with_options` NOT checked in `get_audience_questions_service` (bad) |
| Prompt deduplication | **NO** | Same CV context sent N times in parallel with only the question text varying |

---

## 7. Fix Recommendations (Ordered by Impact)

### FIX 1: Stop regenerating job options on every `/job-questions` call

**Priority:** CRITICAL
**Reduction:** ~8-10 calls → 0
**Root cause:** `get_audience_questions_service()` in `profile.py:233` always calls `generate_job_attribute_options()` even though options were already saved during `/extract-cv`.

```python
# app/services/profile.py — get_audience_questions_service()

# BEFORE (line 231-238):
job_questions = matching_job.get("questions", [])
job_options = await generate_job_attribute_options(parsed_data, job_questions)
questions = job_options.get("suggestions", [])

# AFTER — reuse saved options, only regenerate if missing:
job_questions_with_options = latest_cv.get("job_questions_with_options", [])
if not job_questions_with_options:
    job_questions = matching_job.get("questions", [])
    job_options = await generate_job_attribute_options(parsed_data, job_questions)
    job_questions_with_options = job_options.get("suggestions", [])
    await uploads_collection.update_one(
        {"_id": latest_cv["_id"]},
        {"$set": {"job_questions_with_options": job_questions_with_options}}
    )
questions = job_questions_with_options
```

---

### FIX 2: Batch job questions into a single Gemini call

**Priority:** HIGH
**Reduction:** N calls → 1 call (per invocation of `generate_job_attribute_options`)
**Root cause:** `generate_job_attribute_options` fires 1 API call per question via `asyncio.gather`. All questions share the same CV context.

```python
# app/utils/cv_extractor.py — generate_job_attribute_options()

# BEFORE: asyncio.gather with N separate Gemini calls
results = await asyncio.gather(*[_fetch_options_for_question(q) for q in questions_from_db])

# AFTER: single batched prompt
questions_payload = [
    {"parameter": q["parameter"], "question": q["question"]}
    for q in questions_from_db
]
prompt = (
    "Generate multiple-choice options for ALL of the following questions "
    "based on this professional context.\n\n"
    f"CONTEXT:\n{context_str}\n\n"
    f"QUESTIONS:\n{json.dumps(questions_payload)}\n\n"
    "Return JSON: {{\"results\": [{{\"parameter\": \"...\", \"options\": [...]}}]}}"
)
response = await _gemini_with_retry(prompt, caller="generate_job_attribute_options_batch")
# Parse and map results back to questions
```

---

### FIX 3: Batch anchor option generation

**Priority:** HIGH
**Reduction:** 2-10 calls → 1 call
**Root cause:** Same per-question pattern as Fix 2, in `generate_anchor_attribute_options` and `generate_anchor_options_from_answers_without_cv`.

Apply the same batching approach as Fix 2 to:
- `cv_extractor.py:1386` — `_fetch_anchor_option` loop
- `cv_extractor.py:1684` — `_fetch_anchor_without_cv` loop

---

### FIX 4: Guard `extract-cv-no-auth` suggestions call

**Priority:** MED
**Reduction:** 0-1 calls
**Root cause:** `router.py:1439` calls `generate_missing_field_suggestions` without checking if `LLM_Generated_*` fields were already populated by the main CV extraction call (which generates them in the same prompt).

```python
# router.py — /extract-cv-no-auth

# BEFORE:
if not data.get("Skills", {}).get("SoftSkills") or not data.get("Skills", {}).get("HardSkills"):
    suggestions = await generate_missing_field_suggestions(data)

# AFTER — also check LLM-generated fields:
has_llm_skills = (
    data.get("LLM_Generated_Soft_Skills")
    or data.get("LLM_Generated_Technical_Skills")
)
if not has_llm_skills and (
    not data.get("Skills", {}).get("SoftSkills")
    or not data.get("Skills", {}).get("HardSkills")
):
    suggestions = await generate_missing_field_suggestions(data)
```

---

## 8. Impact Summary

| Fix | Calls Eliminated | Priority |
|-----|-----------------|----------|
| #1 — Stop regenerating job options on `/job-questions` | 8-10 | **CRITICAL** |
| #2 — Batch job questions into 1 Gemini call | 7-9 per batch site | **HIGH** |
| #3 — Batch anchor questions into 1 Gemini call | 1-9 per batch site | **HIGH** |
| #4 — Guard no-auth suggestions | 0-1 | MED |
| **Total possible reduction** | **~20-28 calls → 3-4 calls** | |

Implementing Fix #1 alone cuts calls nearly in half. Implementing all four fixes reduces a typical user session from **20-30 Gemini API calls to 3-4**.
