#!/usr/bin/env python3
"""Generate a per-directory submission cheat sheet from the candidates JSON.

For each candidate in data/community_directory_candidates.json, emit a
markdown block with every field a typical directory submission form asks
for, pre-filled with the cuisine-specific values. Copy-paste workflow:
open data/submission_cheatsheet.md, jump to the directory you're about to
submit to, paste each field, hit submit, log it in
data/community_submissions.md.

Why this exists:
  - 43 candidates x 5-min per manual submission = 3.5 hours of typing
    the same fields with minor variations.
  - With this cheat sheet, each submission is 2 minutes of copy-paste.
  - Per-cuisine tagline is consistent across all directories for that
    cuisine, so the brand reads coherent if anyone Google-searches us.

Re-run anytime the candidates JSON changes:
  python tools/build_submission_cheatsheet.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = ROOT / 'data' / 'community_directory_candidates.json'
INTROS_PATH = ROOT / 'tools' / 'data' / 'cuisine_intros.json'
OUT_PATH = ROOT / 'data' / 'submission_cheatsheet.md'

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cuisines import CUISINE_LABEL

CONTACT_EMAIL = 'josh@nowservingto.com'
CONTACT_PHONE = '647-909-8652'
BASE_URL = 'https://nowservingto.com'

# Per-cuisine submission tagline. Short (≤90 chars), front-loaded with
# the cuisine, ends with the credibility anchor. Keep these identical
# across all directory submissions for the same cuisine so the brand
# voice reads coherent if a moderator cross-checks two listings.
def tagline_for(cuisine_label):
    return (f"Daily-fresh list of every {cuisine_label} restaurant newly "
            f"registered with the City of Toronto. Verified, free.")

# Per-cuisine ~100-word description for the longer "About" / "Description"
# field most directories include. Derived from intro + standard pitch.
def description_for(cuisine_key, cuisine_label):
    intros = {}
    if INTROS_PATH.exists():
        try: intros = json.loads(INTROS_PATH.read_text())
        except Exception: pass
    rec = intros.get(cuisine_key) or {}
    intro = (rec.get('intro') or '').strip()
    base = (
        f"NowServingTO tracks every restaurant newly registered with the "
        f"City of Toronto, updated daily from the City's open data feed "
        f"and verified against Google Places. Our /cuisine/{cuisine_key} "
        f"page surfaces the newest {cuisine_label} kitchens specifically "
        f"- past 30 days, past year, by district - so {cuisine_label}-"
        f"Canadian readers find new openings the day they appear in the "
        f"licence registry. Free, no signup, no ads. "
    )
    if intro:
        base += f"About {cuisine_label} dining in Toronto: {intro}"
    return base.strip()

# Reciprocity ask - a sentence to paste in the "Notes / Additional info"
# field of the form, or to email the moderator after submission. Frames
# the relationship as mutual from the first contact.
def reciprocity_for(cuisine_label):
    return (
        f"Happy to link back from our /cuisine page footer once you list "
        f"us - we maintain a 'community resources' section per cuisine "
        f"and {cuisine_label}-Canadian directories like yours are exactly "
        f"what belongs there. Reply to this email or just go ahead, and "
        f"I'll add you within a day."
    )

def block_for(cand):
    key = cand['cuisine_key']
    label = cand['cuisine_label']
    name = cand.get('name') or '?'
    dir_url = cand.get('url') or ''
    sub_url = cand.get('submission_url') or dir_url
    conf = cand.get('confidence')
    accepts = cand.get('accepts_submissions') or '?'
    active = cand.get('still_active') or '?'
    rationale = cand.get('rationale') or ''

    cuisine_page = f"{BASE_URL}/cuisine/{key}"
    business_name = f"NowServingTO - {label} Restaurant Tracker"

    return f"""### {name}

- **Directory homepage:** {dir_url}
- **Submission URL:** {sub_url}
- **Confidence:** {conf} · accepts={accepts} · active={active}
- **Rationale:** {rationale}

**Form fields to paste:**

| Field | Value |
|---|---|
| Business Name | `{business_name}` |
| Tagline / Short description | `{tagline_for(label)}` |
| Website URL | `{cuisine_page}` |
| Email | `{CONTACT_EMAIL}` |
| Phone | `{CONTACT_PHONE}` |
| Category | Restaurants / Food / Directory (whichever fits closest) |
| City | Toronto |
| Address | Online directory, Toronto, ON (or leave blank) |

**Full description (paste into longer fields):**

> {description_for(key, label)}

**Reciprocity ask (paste into Notes or email after submit):**

> {reciprocity_for(label)}

**After submitting, log it:**

```
| {dir_url:<40} | {label:<20} | {sub_url:<40} | YYYY-MM-DD  | pending  | ?       | ?   |                                                                       |
```

→ Paste into `data/community_submissions.md` table, fill the date.

---

"""

def main():
    if not CANDIDATES_PATH.exists():
        sys.exit(f"missing {CANDIDATES_PATH} - run tools/find_community_directories.py first")
    d = json.loads(CANDIDATES_PATH.read_text())
    cands = d.get('candidates') or []
    if not cands:
        sys.exit("no candidates in the JSON")

    by_cuisine = defaultdict(list)
    for c in cands:
        by_cuisine[c['cuisine_label']].append(c)

    # Sort each cuisine's candidates by confidence desc
    for label in by_cuisine:
        by_cuisine[label].sort(key=lambda c: -(c.get('confidence') or 0))

    lines = [
        f"# Community directory submission cheat sheet",
        f"",
        f"Auto-generated from `data/community_directory_candidates.json`.",
        f"Re-run `python tools/build_submission_cheatsheet.py` after each spider sweep.",
        f"",
        f"**Total candidates: {len(cands)} across {len(by_cuisine)} cuisines.**",
        f"",
        f"## Workflow",
        f"",
        f"1. Pick a cuisine section below.",
        f"2. Pick the highest-confidence directory you haven't submitted to.",
        f"3. Open the **Submission URL** in a tab.",
        f"4. Copy-paste each field from the table - 2 min per submission.",
        f"5. Paste the **Reciprocity ask** into a Notes field, or email the moderator after submitting.",
        f"6. Paste the **After submitting, log it** row into `data/community_submissions.md` and fill the date.",
        f"7. When the directory confirms reciprocity (or you see the listing live), add a `community_partners` entry to `tools/data/cuisine_intros.json` under that cuisine - next cron renders the footer link.",
        f"",
        f"## Submission etiquette",
        f"",
        f"- **Don't submit the same cuisine to the same directory twice.** Check `data/community_submissions.md` first.",
        f"- **Don't auto-submit.** These are community-moderated; reputation cost > time saved.",
        f"- **Personalize when the form has a 'Why are you listing?' field.** A one-liner about serving the diaspora specifically beats the templated description.",
        f"- **Reciprocity is normal.** Most community directories appreciate being linked back from your /cuisine page footer. Mention it.",
        f"",
        f"---",
        f"",
    ]

    for label in sorted(by_cuisine.keys()):
        items = by_cuisine[label]
        lines.append(f"## {label} ({len(items)} candidate(s))")
        lines.append("")
        for c in items:
            lines.append(block_for(c))

    OUT_PATH.write_text('\n'.join(lines))
    print(f"wrote {OUT_PATH}")
    print(f"  {len(cands)} blocks across {len(by_cuisine)} cuisines")

if __name__ == '__main__':
    main()
