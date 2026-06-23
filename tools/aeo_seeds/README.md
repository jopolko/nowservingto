# AEO seed prompts

One file per site, named `<host>.txt` (e.g. `joshuaopolko.com.txt`,
`nowservingto.com.txt`). One query per line. Blank lines and `#` comments are
ignored.

`seo_pull.py --aeo` resolves its query set in this order:

1. `--prompts "a; b; c"` or `--prompts @file.txt` (CLI, overrides everything)
2. this seed file for the site's host, if present
3. the top GSC queries by impressions (the default)

Use a seed file to pin the demand you actually care about — the head/torso
queries you want AI answer engines to cite you for — instead of inheriting
GSC's impression skew. With (1) or (2) the GSC call is skipped entirely, so the
AEO map works on a site that has no Search Console grant yet.
