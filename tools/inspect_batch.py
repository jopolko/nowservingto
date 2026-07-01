#!/usr/bin/env python3
"""Inspect raw batch results to find parse_failed responses."""
import json, sys
from pathlib import Path
from urllib.request import urlopen, Request

BATCH_ID = sys.argv[1] if len(sys.argv) > 1 else 'msgbatch_012VYt3EcCtY2LnRFbJ3FaM5'

api_key = ''
for line in Path('/var/secrets/nowservingto.env').read_text().splitlines():
    if line.startswith('ANTHROPIC_API_KEY='):
        api_key = line.split('=', 1)[1]; break

def get(url):
    req = Request(url, headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01'})
    with urlopen(req, timeout=120) as r:
        return r.read().decode('utf-8')

info = json.loads(get(f'https://api.anthropic.com/v1/messages/batches/{BATCH_ID}'))
print(f"batch: {BATCH_ID}  status: {info['processing_status']}  counts: {info['request_counts']}")

results_url = info.get('results_url')
if not results_url:
    print("No results_url yet"); sys.exit(0)

raw = get(results_url)
lines = [json.loads(l) for l in raw.strip().split('\n') if l.strip()]
print(f"total lines: {len(lines)}")

fails = []
ok = 0
for obj in lines:
    r = obj.get('result', {})
    if r.get('type') != 'succeeded':
        continue
    content = r['message'].get('content', [])
    texts = [b.get('text', '') for b in content if b.get('type') == 'text']
    text = (texts[-1] if texts else '').strip()
    parsed = None
    for block in reversed(texts):
        block = block.strip()
        for ln in block.split('\n'):
            s = ln.strip().lstrip('`').strip()
            if s.startswith('{') and s.endswith('}'):
                try: parsed = json.loads(s); break
                except Exception: continue
        if parsed is not None:
            break
        try: parsed = json.loads(block); break
        except Exception: pass
    if parsed is None:
        fails.append((obj['custom_id'], content, text))
    else:
        ok += 1

print(f"\nparsed ok: {ok}  parse_failed: {len(fails)}")

if fails:
    cid, content, text = fails[0]
    print(f"\n--- first parse_failed: {cid} ---")
    print(f"block types: {[b.get('type') for b in content]}")
    print(f"text output:\n{text[:800]}")

    if len(fails) > 1:
        cid2, content2, text2 = fails[1]
        print(f"\n--- second parse_failed: {cid2} ---")
        print(f"block types: {[b.get('type') for b in content2]}")
        print(f"text output:\n{text2[:400]}")
