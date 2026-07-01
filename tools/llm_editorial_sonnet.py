#!/usr/bin/env python3
"""
Sync Sonnet editorial rewrite for all current directory listings.

Overwrites every evidence_rewrite_cache entry (or fills missing ones) with
Sonnet-quality prose. Run with no args to do all 289; --dry-run to preview
candidates without calling the API.

Uses the same system prompt + four-sentence structure as
llm_evidence_rewrite_batch.py, but sync (immediate results) and with the
claude-sonnet-4-6 model.
"""
import json, sys, time, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

ROOT   = Path(__file__).resolve().parent.parent
DATA   = ROOT / 'data' / 'corridors.json'
WV     = ROOT / 'tools' / 'cache' / 'web_verify_cache.json'
WT     = ROOT / 'tools' / 'cache' / 'website_text_cache.json'
CACHE  = ROOT / 'tools' / 'cache' / 'evidence_rewrite_cache.json'
SECRETS = Path('/var/secrets/nowservingto.env')
MODEL  = 'claude-sonnet-4-6'

# Reuse the exact system prompt from llm_evidence_rewrite_batch so the
# register/rules stay identical — only the model and transport change.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm_evidence_rewrite_batch import SYSTEM_PROMPT

def load_api_key():
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if line.startswith('ANTHROPIC_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    sys.exit('ANTHROPIC_API_KEY not in secrets')

API_KEY = load_api_key()
HEADERS = {
    'x-api-key': API_KEY,
    'anthropic-version': '2023-06-01',
    'content-type': 'application/json',
}


def call_api(prompt_text, retries=4):
    payload = {
        'model': MODEL,
        'max_tokens': 512,
        'system': SYSTEM_PROMPT,
        'messages': [{'role': 'user', 'content': prompt_text}],
    }
    for attempt in range(retries):
        try:
            req = Request(
                'https://api.anthropic.com/v1/messages',
                data=json.dumps(payload).encode(),
                headers=HEADERS,
                method='POST',
            )
            with urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except HTTPError as e:
            body = e.read().decode()
            if e.code == 529 or e.code == 429:
                wait = 30 * (attempt + 1)
                print(f'    [{e.code}] rate-limited, waiting {wait}s…')
                time.sleep(wait)
                continue
            print(f'    HTTP {e.code}: {body[:200]}')
            raise
    raise RuntimeError(f'failed after {retries} retries')


def build_prompt(name, cuisine_label, addr, district, ev, ev_src):
    lines = [
        f'Restaurant: {name}',
        f'Cuisine: {cuisine_label}',
        f'Address: {addr}' + (f' ({district})' if district else ''),
    ]
    if ev_src == 'website':
        lines.append(
            'Source — the restaurant\'s own website text (extract real '
            'dishes / focus from it; ignore nav labels, hours, and '
            'ordering/catering boilerplate):'
        )
        lines.append(ev)
    else:
        lines.append(f'Verification note: {ev}')
    lines.append('')
    lines.append(
        'Write a 120-160 word editorial blurb following the '
        'four-sentence structure in the system prompt. Do not add a '
        'source-attribution closing sentence.'
    )
    return '\n'.join(lines)


def extract_blurb(resp):
    """Pull the blurb string from the API response JSON."""
    text = ''
    for block in resp.get('content', []):
        if block.get('type') == 'text':
            text = block['text'].strip()
            break
    if not text:
        return None, text
    # Strip ```json fences if present
    cleaned = re.sub(r'^```\w*\s*', '', text)
    cleaned = re.sub(r'\s*```\s*$', '', cleaned).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and 'blurb' in parsed:
            return parsed['blurb'].strip(), text
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: regex extract
    m = re.search(r'"blurb"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        return m.group(1).replace('\\"', '"').replace('\\n', ' ').strip(), text
    return None, text


def main():
    dry_run = '--dry-run' in sys.argv

    data   = json.loads(DATA.read_text())
    wv     = json.loads(WV.read_text())
    wt     = json.loads(WT.read_text()) if WT.exists() else {}
    cache  = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    recent = data.get('newOpenings', {}).get('recent', [])
    labels = {c['key']: c.get('label', c['key'])
              for c in data.get('newOpenings', {}).get('cuisines', [])
              if c.get('key')}

    targets = []
    for r in recent:
        ck = r.get('_cacheKey', '')
        if not ck:
            continue
        # Never overwrite hand-authored (opus_manual_v1) blurbs.
        if cache.get(ck, {}).get('via', '').startswith('opus_manual'):
            continue
        wv_e = wv.get(ck) or {}
        ev = (wv_e.get('validator_evidence') or wv_e.get('evidence') or '').strip()
        ev_src = 'verify'
        # Prefer website text when it's meaningfully richer than the
        # validator_evidence (which is often a single thin sentence for
        # web_search-only entries or early batch runs).
        site = (r.get('website') or '').strip()
        wt_text = ((wt.get(site) or {}).get('text') or '') if site else ''
        wt_text = wt_text.replace('HOMEPAGE (jina-rendered):', '').replace('HOMEPAGE:', '').strip()
        if len(wt_text) >= 300 and len(wt_text) > len(ev) * 2:
            ev, ev_src = wt_text[:2000], 'website'
        if not ev:
            continue
        keys = r.get('cuisines') or ([r['cuisine']] if r.get('cuisine') else [])
        cuisine_label = labels.get(keys[0], keys[0].title()) if keys else 'restaurant'
        targets.append({
            'ck': ck,
            'name': r.get('operatingName', ''),
            'cuisine': cuisine_label,
            'addr': (r.get('address') or '').strip(),
            'district': (r.get('district') or '').strip(),
            'ev': ev,
            'ev_src': ev_src,
        })

    print(f'{len(targets)} listings to rewrite  (model={MODEL})')
    if dry_run:
        for t in targets[:10]:
            print(f'  {t["name"]}')
        return

    ok = fail = 0
    for i, t in enumerate(targets, 1):
        label = f'[{i}/{len(targets)}] {t["name"]}'
        print(label, end='  ', flush=True)
        prompt = build_prompt(
            t['name'], t['cuisine'], t['addr'], t['district'],
            t['ev'], t['ev_src']
        )
        try:
            resp = call_api(prompt)
            blurb, raw = extract_blurb(resp)
            in_tok  = resp.get('usage', {}).get('input_tokens', 0)
            out_tok = resp.get('usage', {}).get('output_tokens', 0)
            if not blurb:
                print(f'PARSE-FAIL  raw={raw[:80]}')
                fail += 1
                continue
            cache[t['ck']] = {
                'blurb': blurb,
                'raw': raw[:500],
                'in_tok': in_tok,
                'out_tok': out_tok,
                'rewrote_at': datetime.now(timezone.utc).isoformat(),
                'via': 'sonnet_editorial_v1',
                'status': 'ok',
            }
            print(f'ok  ({in_tok}in/{out_tok}out)')
            ok += 1
        except Exception as ex:
            print(f'ERROR: {ex}')
            fail += 1

        # Write cache every 10 entries so progress survives interruption
        if i % 10 == 0:
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    print(f'\ndone: {ok} ok, {fail} failed')


if __name__ == '__main__':
    main()
