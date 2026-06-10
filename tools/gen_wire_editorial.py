#!/usr/bin/env python3
"""
Generate 350-word wire editorial paragraphs for each cuisine's wire page.
Uses Claude Haiku with the existing intro seed + district distribution data.

Run:
  python3 tools/gen_wire_editorial.py [--cuisine jamaican] [--dry-run]

Output: tools/data/wire_editorial.json
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent.parent
INTROS_PATH   = ROOT / 'tools' / 'data' / 'cuisine_intros.json'
CORRIDORS_PATH = ROOT / 'data' / 'corridors.json'
OUTPUT_PATH   = ROOT / 'tools' / 'data' / 'wire_editorial.json'
WIRE_DIR      = ROOT / 'wire'

CUISINE_LABEL = {
    'afghan': 'Afghan', 'bangladeshi': 'Bangladeshi', 'caribbean': 'Caribbean',
    'chinese': 'Chinese', 'colombian': 'Colombian', 'ethiopian': 'Ethiopian',
    'filipino': 'Filipino', 'french': 'French', 'greek': 'Greek',
    'indian': 'Indian', 'italian': 'Italian', 'jamaican': 'Jamaican',
    'japanese': 'Japanese', 'korean': 'Korean', 'lebanese': 'Lebanese',
    'mexican': 'Mexican', 'middle_east': 'Middle Eastern', 'nepalese': 'Nepalese',
    'nigerian': 'Nigerian', 'pakistani': 'Pakistani', 'persian': 'Persian',
    'portuguese': 'Portuguese', 'sri_lankan': 'Sri Lankan', 'tamil': 'Tamil',
    'thai': 'Thai', 'trinidadian': 'Trinidadian', 'turkish': 'Turkish',
    'vietnamese': 'Vietnamese',
}


def load_district_data(corridors, cuisine_key):
    """Extract district distribution for a cuisine from corridors.json."""
    cuisines = corridors.get('newOpenings', {}).get('cuisines', [])
    for c in cuisines:
        if c.get('key') == cuisine_key:
            districts = c.get('districts', {})
            total = c.get('count365d', 0)
            return total, districts
    return 0, {}


def build_prompt(cuisine_key, label, intro, total, districts):
    district_lines = ''
    if districts:
        sorted_d = sorted(districts.items(), key=lambda x: -x[1])[:5]
        district_lines = '\n'.join(f'  {d}: {n} new' for d, n in sorted_d)

    return f"""You are writing editorial content for NowServingTO, a Toronto restaurant directory that tracks every newly licensed restaurant in the city. The audience is immigrants and diaspora community members looking for the newest {label} restaurants in Toronto.

Write exactly 3 paragraphs (~350 words total) of editorial context for the {label} wire page. This content appears above the restaurant listing cards.

Tone: authoritative but warm. Factual. No hype, no tourism-speak. Write for someone from the community, not a tourist.

Facts to weave in naturally:
- Cuisine: {label}
- New restaurants licensed in Toronto in the past year: {total}
- District breakdown (where new openings are clustering):
{district_lines if district_lines else '  (data not available)'}
- Existing intro sentence (expand on this, do not repeat verbatim): {intro}

Structure:
1. First paragraph: Where this cuisine lives in Toronto — which neighbourhoods, corridors, and communities have built it. Be specific to Toronto geography (Scarborough, Etobicoke, Danforth, Eglinton, Dundas, etc.). Ground it in real community history.
2. Second paragraph: What the current opening pattern reveals. Use the district data to say something specific about where growth is happening and what that signals about the community's commercial footprint.
3. Third paragraph: What to look for in a new {label} restaurant. What dishes, formats, or qualities distinguish a serious new opening from a generic one. Practical, insider-voice guidance.

Do not use the words "vibrant", "diverse", "bustling", "tapestry", or any tourism-brochure language.
Do not start paragraphs with "Toronto's" or "The".
Write plain HTML paragraphs only — no headings, no bullet points, no markdown. Just three <p> tags."""


def generate_editorial(client, cuisine_key, label, intro, total, districts, dry_run=False):
    prompt = build_prompt(cuisine_key, label, intro, total, districts)
    if dry_run:
        print(f'[DRY RUN] Would generate for {cuisine_key}')
        print(prompt[:200], '...')
        return f'<p>Dry run placeholder for {label}.</p>'

    resp = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=600,
        messages=[{'role': 'user', 'content': prompt}],
    )
    return resp.content[0].text.strip()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cuisine', help='Only run for this cuisine key')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()

    api_key = None
    env_path = Path('/var/secrets/nowservingto.env')
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith('ANTHROPIC_API_KEY='):
                api_key = line.split('=', 1)[1].strip()
    if not api_key:
        api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        sys.exit('No ANTHROPIC_API_KEY found.')

    client = anthropic.Anthropic(api_key=api_key)

    intros = json.loads(INTROS_PATH.read_text())
    intros.pop('_doc', None)
    corridors = json.loads(CORRIDORS_PATH.read_text())

    existing = {}
    if OUTPUT_PATH.exists():
        existing = json.loads(OUTPUT_PATH.read_text())

    wire_keys = sorted(
        f.stem for f in WIRE_DIR.glob('*.html') if f.stem != 'monica-lewis'
    )
    if args.cuisine:
        wire_keys = [k for k in wire_keys if k == args.cuisine]
        if not wire_keys:
            sys.exit(f'Cuisine {args.cuisine} not found.')

    for key in wire_keys:
        if key in existing and not args.cuisine:
            print(f'  skip {key} (already done)')
            continue

        label = CUISINE_LABEL.get(key, key.replace('_', ' ').title())
        rec = intros.get(key, {})
        intro = (rec.get('intro') or '').strip()
        total, districts = load_district_data(corridors, key)

        print(f'Generating: {key} ({total} openings)...', end=' ', flush=True)
        try:
            text = generate_editorial(client, key, label, intro, total, districts, args.dry_run)
            existing[key] = text
            if not args.dry_run:
                OUTPUT_PATH.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
            print(f'done ({len(text.split())} words)')
        except Exception as e:
            print(f'ERROR: {e}')
            continue

        if not args.dry_run:
            time.sleep(0.3)

    print(f'\nSaved to {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
