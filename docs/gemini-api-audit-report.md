# Gemini API Usage Audit Report

**Date:** 2026-06-22  
**Scope:** All Python files in `yourskills-app-backend`  
**Focus:** Redundancy, token optimization, latency, code quality, security

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Total files with Gemini calls** | 2 (`app/utils/cv_extractor.py`, `app/api/router.py`) |
| **Total Gemini call sites** | 10 (1 sync, 1 sync-in-thread, 8 async) |
| **Model used** | `gemini-2.5-flash-lite` (hardcoded in 2 locations) |
| **Critical issues** | Security: 2 HIGH, Redundancy: 4, Latency: 3, Quality: 6, Token: 3 |

---

## 1. REDUNDANT GEMINI API CALLS

| File | Line | Issue | Severity | Fix |
|------|------|-------|----------|-----|
| `cv_extractor.py` | 782 | `extract_cv_data_from_file()` uses **sync** `generate_content()` — bypasses `_gemini_with_retry()`. No retry, no rate-limit handling. | HIGH | Wrap in `_gemini_with_retry()` or add retry logic |
| `router.py` | 1439 vs 251 | `extract_cv_no_auth` calls `generate_missing_field_suggestions()` for soft/hard skills, but `extract_cv` reads LLM-generated fields directly from parsed data. The no-auth path makes an **extra redundant LLM call**. | MED | Use `data.get("LLM_Generated_*")` in no-auth path too |
| `cv_extractor.py` | 1044-1113, 1534-1593 | `generate_job_attribute_options()` and `generate_job_attribute_options_without_cv()` are **near-identical** — same prompt template, option-count logic, JSON parsing. | MED | Extract shared `_build_option_prompt()` + `_fetch_options()` helper |
| `cv_extractor.py` | 1279-1474, 1610-1763 | `generate_anchor_attribute_options()` and `generate_anchor_options_from_answers_without_cv()` are **near-identical** — same prompt structure, variation logic, style noise. | MED | Consolidate into single function with `has_cv` flag |

---

## 2. REDUNDANT / REPEATED PROMPT INPUTS

| Prompt Preview (first 100 chars) | Location | Est. Token Waste | Recommendation |
|---|---|---|---|
| `"You are a Senior HR Recruitment, Talent Analyst..."` | `cv_extractor.py:515-767` | ~650 tokens of JSON schema repeated every call | Move schema to a constant; use Gemini `system_instruction` param |
| `"You are a Senior HR Recruitment..."` (commented-out) | `cv_extractor.py:177-467` | ~800 tokens dead code | Delete the 290-line commented-out block |
| `"You are an AI assistant generating short, career-related..."` | 4 locations: lines 1054, 1405, 1544, 1703 | ~200 tokens x4 = 800 tokens repeated | Extract shared system instruction constant |
| `"Generate focused, high-quality multiple-choice options..."` | `cv_extractor.py:1054` | ~80 tokens overlap with line 1405 variant | Merge into single template |
| Variation instructions block | Lines 1397-1403 and 1695-1701 | ~100 tokens x2 = 200 tokens exact duplicate | Extract to constant `VARIATION_INSTRUCTIONS` |

---

## 3. TOKEN OPTIMIZATION

| File | Prompt ID | Est. Tokens | Action |
|------|-----------|-------------|--------|
| `cv_extractor.py:515` | CV extraction prompt | ~1,950 | Move JSON schema (~500 tokens) to `system_instruction` on model init — Gemini caches system instructions across calls |
| `router.py:1775` | Summary extraction prompt | ~780 | Use `response_schema` parameter instead of embedding schema in prompt |
| `cv_extractor.py:1405` | Anchor options prompt | ~350 + context | `combined_context` embeds full work experience + education. Truncate to 500 chars each |
| `cv_extractor.py:1054` | Job attribute options | ~250 + context | `context_str` includes all CV fields. Filter to `Summary` + `Industry` + `Domain` only |
| `router.py:1849` | `json.dumps(parsed_resume)` | ~500-2000 | Pre-filter to non-empty fields before serializing |

---

## 4. LATENCY ISSUES

| File | Line | Pattern | Severity | Fix |
|------|------|---------|----------|-----|
| `cv_extractor.py` | 782 | **Sync blocking** `generate_content()` with no timeout | HIGH | Convert to `generate_content_async()` with `request_options={"timeout": 60}` |
| `cv_extractor.py` | 40 | `generate_content_async()` has **no timeout** | MED | Add `request_options={"timeout": 30}` |
| `router.py` | 59 | `_gemini_sync_with_retry` wraps sync in `asyncio.to_thread` — unnecessary overhead | LOW | Use `generate_content_async()` directly |
| `cv_extractor.py` | 1112 | `asyncio.gather()` fires ALL questions in parallel — triggers mass rate limiting | MED | Use `asyncio.Semaphore(5)` to limit concurrency |
| `router.py` | 230 | CV extraction then suggestions + job options run sequentially | MED | Run suggestions and job options with `asyncio.gather()` |

---

## 5. CODE QUALITY

| File | Issue Type | Line Range | Fix |
|------|-----------|------------|-----|
| `cv_extractor.py`, `router.py` | **Hardcoded model name** `"gemini-2.5-flash-lite"` | Lines 25, router:45 | Move to `settings.GEMINI_MODEL` in config.py |
| `cv_extractor.py:24`, `router.py:43` | **`genai.configure()` called twice** | 24, 43 | Single initialization in a shared module |
| `cv_extractor.py` | Bare `except Exception` swallows errors | 811 | Log the exception; return specific error codes |
| `router.py` | **`get_cv_profile_data` duplicated** as route handler (1237) and function (1535) | 1237-1694 | Delete the duplicate; route calls the function |
| `cv_extractor.py` | `extract_cv_data_from_file` is 85 lines mixing I/O, prompt, API, parsing, business logic | 513-813 | Split into `build_cv_prompt()`, `call_gemini()`, `parse_cv_response()` |
| `router.py` | `safe_keyword()` loop runs **twice identically** | 1886-1895 | Delete the second loop |
| `cv_extractor.py` | **Missing type hints** on `extract_cv_data_from_file`, `clean_json`, `extract_docx_text`, `extract_job_role` | various | Add return type annotations |
| `cv_extractor.py` | **290 lines of commented-out code** | 175-467 | Delete |
| `router.py` | Duplicate dict keys in `talent_info` | 1279-1292 | Remove duplicates |

---

## 6. SECURITY

| File | Line | Severity | Issue | Remediation |
|------|------|----------|-------|-------------|
| `cv_extractor.py` | 24 | **HIGH** | `os.getenv("GEMINI_API_KEY")` at module level — `None` silently passed if `.env` missing | Use `settings.GEMINI_API_KEY` from Pydantic config |
| `router.py` | 43 | **HIGH** | Same `os.getenv("GEMINI_API_KEY")` duplication | Use `settings.GEMINI_API_KEY` |
| `cv_extractor.py` | 35 | **MED** | Logger logs prompt preview (first 120 chars) — may contain PII from CV (name, email, phone) | Sanitize/hash PII before logging |
| `cv_extractor.py` | 928 | **MED** | User CV data injected directly into prompt — **prompt injection risk** | Add input sanitization |
| `cv_extractor.py` | 1414 | **MED** | `combined_context` (user answers + resume) passed directly into prompt — injection risk | Sanitize user-supplied context |
| `router.py` | 1849 | **LOW** | `json.dumps(parsed_resume)` in prompt — malicious strings could corrupt prompt | Use proper escaping or separate content part |

---

## Recommended Refactors (Top 5 by Impact)

### 1. Eliminate redundant LLM call in no-auth flow (Latency + Cost)
`router.py:1439` — `extract_cv_no_auth` calls `generate_missing_field_suggestions()` unnecessarily. The CV extraction prompt already generates `LLM_Generated_*` fields. Use those directly as the auth flow does (line 251). **Saves 1 API call per no-auth extraction.**

### 2. Move CV extraction prompt schema to `system_instruction` (Token Cost)
The 250-line prompt in `cv_extractor.py:515-767` is static. Pass it as `system_instruction` when initializing the model — Gemini caches this server-side, reducing per-request token cost by ~1,500 tokens.

### 3. Add concurrency limiter to `asyncio.gather()` calls (Latency)
All 4 `asyncio.gather()` sites fire unbounded parallel requests. With 10+ questions, this triggers 429 rate limits and cascading retries. Add `asyncio.Semaphore(3-5)`.

### 4. Consolidate duplicate functions (Maintainability)
Merge `generate_job_attribute_options` / `generate_job_attribute_options_without_cv` and `generate_anchor_attribute_options` / `generate_anchor_options_from_answers_without_cv` — each pair is 90%+ identical.

### 5. Single Gemini initialization point (Security + Quality)
`genai.configure()` is called in two files with `os.getenv()`. Use the existing Pydantic `Settings` class and initialize once in a shared module.

---

## Quick Wins (< 30 min each)

1. **Delete 290 lines of commented-out code** (`cv_extractor.py:175-467`) — zero risk, immediate clarity.
2. **Remove duplicate `safe_keyword` loop** (`router.py:1892-1895`) — exact duplicate of line 1886 loop.
3. **Remove duplicate dict keys** (`router.py:1279-1292`) — `"Core Tasks"`, `"Skills"`, etc. appear twice in `talent_info`.
4. **Add timeouts to Gemini calls** — `request_options={"timeout": 60}` in `_gemini_with_retry`. One-line change.
5. **Use `settings.GEMINI_API_KEY`** instead of `os.getenv()` in both files. Two-line change.
6. **Extract prompt constants** — move repeated preamble to module-level constant. ~5 min.
