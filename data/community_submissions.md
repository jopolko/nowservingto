# Community directory submissions

Track every cultural / diaspora directory we've submitted NowServingTO to, plus
the candidate pipeline. Goal: zero duplicate submissions, zero forgotten dead
listings, easy hand-off to whoever takes over directory outreach later.

## Status values

- `todo`      — discovered, not yet submitted
- `research`  — looks promising but need to verify it accepts submissions
- `pending`   — submitted, awaiting approval / no listing visible yet
- `live`      — listing confirmed live on their site
- `rejected`  — denied (note reason)
- `dead`      — site abandoned (no updates in 12+ months) — skip

## Quality checks before submitting (run these on each candidate)

1. **Sitemap exists?** `curl -sI https://<directory>/sitemap.xml` returns 200 → search engines crawl their listings → SEO juice flows to us
2. **Recently updated?** Click any sample listing, check date. If newest content is >12 months old → mark `dead`, skip
3. **Domain authority?** Quick MozBar check (free Chrome extension) — DA ≥20 worth doing, DA <10 probably not unless community-strategic

| Directory URL                | Cuisine / community | Submission page          | Submitted   | Status   | Sitemap | DA  | Notes                                                                 |
|------------------------------|---------------------|--------------------------|-------------|----------|---------|-----|-----------------------------------------------------------------------|
| tamildirectory.ca            | Tamil               | /add-business            | 2026-05-30  | pending  | ?       | ?   | bing AI cited /cuisine/tamil 2026-05-29 — confirm causation later     |
|                              | Afghan              |                          |             | todo     |         |     |                                                                       |
|                              | Bangladeshi         |                          |             | todo     |         |     |                                                                       |
|                              | Brazilian           |                          |             | todo     |         |     |                                                                       |
|                              | Caribbean / Jamaican|                          |             | todo     |         |     |                                                                       |
|                              | Chinese             |                          |             | todo     |         |     |                                                                       |
|                              | Colombian / Latin   |                          |             | todo     |         |     |                                                                       |
|                              | Eritrean / Ethiopian|                          |             | todo     |         |     |                                                                       |
|                              | Filipino            |                          |             | todo     |         |     |                                                                       |
|                              | Ghanaian / Nigerian |                          |             | todo     |         |     |                                                                       |
|                              | Greek               |                          |             | todo     |         |     |                                                                       |
|                              | Indian              |                          |             | todo     |         |     |                                                                       |
|                              | Italian             |                          |             | todo     |         |     |                                                                       |
|                              | Japanese            |                          |             | todo     |         |     |                                                                       |
|                              | Jewish              |                          |             | todo     |         |     |                                                                       |
|                              | Korean              |                          |             | todo     |         |     |                                                                       |
|                              | Lebanese / Levantine|                          |             | todo     |         |     |                                                                       |
|                              | Mexican             |                          |             | todo     |         |     |                                                                       |
|                              | Nepalese            |                          |             | todo     |         |     |                                                                       |
|                              | Pakistani           |                          |             | todo     |         |     |                                                                       |
|                              | Persian / Iranian   |                          |             | todo     |         |     |                                                                       |
|                              | Polish              |                          |             | todo     |         |     |                                                                       |
|                              | Portuguese          |                          |             | todo     |         |     |                                                                       |
|                              | Sri Lankan          |                          |             | todo     |         |     |                                                                       |
|                              | Thai                |                          |             | todo     |         |     |                                                                       |
|                              | Tibetan             |                          |             | todo     |         |     |                                                                       |
|                              | Turkish             |                          |             | todo     |         |     |                                                                       |
|                              | Vietnamese          |                          |             | todo     |         |     |                                                                       |

## How to find candidates for a cuisine

Cheapest-to-most-effort search order:

1. **Google site search**: `"<cuisine> Toronto" directory OR community OR association`
   - e.g. `"Filipino Toronto" directory OR community OR association`
2. **Google site search for submission pages**: `inurl:add OR inurl:submit OR inurl:list-your "<cuisine>" Toronto`
   - e.g. `inurl:submit "Persian" Toronto restaurant`
3. **Find the diaspora newspaper** for the cuisine in Toronto — most have a business directory or accept editorial pitches. Search: `"<cuisine>" newspaper Toronto` or `<cuisine>-language newspaper Canada`
4. **Wikipedia "<X> Canadians" page** — usually lists community organizations with websites at the bottom
5. **Embassy / consulate page** — most have a "Community in Canada" section linking to associations and media

## Process

1. Found a candidate → add a `todo` row with the directory URL + cuisine
2. Before submitting, verify the 3 quality checks above; mark `research` while doing them
3. Submit → flip to `pending`, fill `Submitted` date and `Submission page` column
4. Sample-search the directory weekly for "NowServingTO" — when it appears, flip to `live`
5. If denied or no response after 4 weeks → mark `rejected` with reason
6. Commit each change — `git log data/community_submissions.md` becomes the audit trail
