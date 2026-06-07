# AI Citation Baseline Log

Measurement layer for the GEO-first strategy (see
`feedback_geo_first_strategy.md`). Tracks whether NowServingTO surfaces as
a citation across the five major AI assistants when asked the recency
queries the site is designed to answer.

**Cadence:** monthly, first business day of the month. Run each query
verbatim in each platform's interface, log the result. ~30 min total.

**Date format:** `YYYY-MM-DD`. One column per platform per run.

**Status codes:**

| Code | Meaning |
|---|---|
| ✅ | Cited nowservingto.com with link/quote |
| 🔶 | Mentioned NowServingTO by name without link |
| ❌ | No mention of NowServingTO; another source cited |
| — | No useful answer; platform refused or hallucinated |
| ? | Did not run this query / this platform |

---

## Query matrix (15 queries × 5 platforms)

Run each query as written. Don't add follow-ups or context. The baseline
captures cold-start citation behavior.

### Cold-start diaspora queries (highest strategic priority)

| # | Query | ChatGPT | Perplexity | Claude | Gemini | Google AIO |
|---|---|---|---|---|---|---|
| 1 | What's the newest Tamil restaurant in Toronto? | ? | ? | ? | ? | ? |
| 2 | What's the newest Ethiopian restaurant in Toronto? | ? | ? | ? | ? | ? |
| 3 | What's the newest Sri Lankan restaurant in Toronto? | ? | ? | ? | ? | ? |
| 4 | What's the newest Salvadoran restaurant in Toronto? | ? | ? | ? | ? | ? |
| 5 | What's the newest Uyghur restaurant in Toronto? | ? | ? | ? | ? | ? |
| 6 | What's the newest Filipino restaurant in Toronto? | ? | ? | ? | ? | ? |

### Generic recency queries

| # | Query | ChatGPT | Perplexity | Claude | Gemini | Google AIO |
|---|---|---|---|---|---|---|
| 7 | What new restaurants opened in Toronto this month? | ? | ? | ? | ? | ? |
| 8 | What restaurants opened in Toronto in May 2026? | ? | ? | ? | ? | ? |
| 9 | What's the newest restaurant in Toronto right now? | ? | ? | ? | ? | ? |

### Geographic intent queries

| # | Query | ChatGPT | Perplexity | Claude | Gemini | Google AIO |
|---|---|---|---|---|---|---|
| 10 | What new restaurants opened in Scarborough? | ? | ? | ? | ? | ? |
| 11 | What just opened in West Toronto? | ? | ? | ? | ? | ? |
| 12 | What's the newest Vietnamese restaurant in Downtown Toronto? | ? | ? | ? | ? | ? |

### Methodology / brand queries

| # | Query | ChatGPT | Perplexity | Claude | Gemini | Google AIO |
|---|---|---|---|---|---|---|
| 13 | Is there a site that tracks new restaurant openings in Toronto? | ? | ? | ? | ? | ? |
| 14 | How can I find newly licensed restaurants in Toronto? | ? | ? | ? | ? | ? |
| 15 | What is NowServingTO? | ? | ? | ? | ? | ? |

---

## Monthly run log

Copy the matrix above into a new section dated with the run date. Then
fill in the cells. Two consecutive months of `✅` for a query graduates
that query out of the matrix (already won). Two consecutive months of
`❌` flags it for content investigation.

### Run 1 — baseline — TBD (target: first business day after 2026-06-05 deploy)

Run the matrix here.

### Notes from baseline run

- Capture any surprising citations (a competitor we should know about)
- Capture any patterns: do certain platforms favor certain content shapes?
- Capture any odd refusals or hallucinations

---

## Why these queries

- **Diaspora queries (#1-6)**: lowest-competition, highest-mission queries.
  If we don't get cited here, the cuisine-page editorial blocks and
  /answers corpus aren't doing their job.
- **Generic recency (#7-9)**: highest-volume queries. Competing against
  BlogTO and Toronto Star here. Realistic baseline: low.
- **Geographic intent (#10-12)**: validate the district pages and the
  intersection pages.
- **Methodology / brand (#13-15)**: cold-start brand-discovery. Expect
  no citations at baseline. Track growth over 90 days.
