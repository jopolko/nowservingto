#!/usr/bin/env python3
"""
Branded 1200x675 PNG card generator for a restaurant entry.

Used by:
  - inject_openings.py - writes one PNG per kept entry to /og/<slug>.png
    at inject time. The per-listing HTML at /r/<slug>.html points its
    og:image meta tag at this PNG so X / Facebook / Slack / iMessage all
    show the personalized card when the URL is shared.
  - x_post_new_openings.py - historically attached the PNG directly to
    tweets via the v1.1 /media/upload endpoint; with per-listing OG
    pages live, the bot can post text-only and X auto-cards from the
    page's og:image, giving the same visual + a click-target on the URL.

Stdlib + rsvg-convert (apt: librsvg2-bin). Card design lives in
build_card_svg() - edit there to change the look.
"""
import os, re, subprocess, tempfile, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cuisines import CUISINE_LABEL, cuisine_color


# Curated palette for seed cuisines (mirrors inject_openings.PALETTE_HEX);
# novel/dynamic cuisines fall through to cuisine_color() hash-derived hex.
PALETTE_HEX = {
    'italian':'#c83624','caribbean':'#1a8a5a','south_asian':'#d4a017','indian':'#e88e2c',
    'pakistani':'#a06030','afghan':'#7a5d3a','bangladeshi':'#b88820','chinese':'#b13e6a',
    'vietnamese':'#4a8b8b','japanese':'#2f3aa3','korean':'#6b2456','filipino':'#e08226',
    'tamil':'#8a5d20','tibetan':'#b15a25','greek':'#1f7a6a','portuguese':'#9b2538',
    'polish':'#4a5a6a','french':'#5a3a7a','irish_uk':'#2a6a40','german':'#6a5a30',
    'jewish_deli':'#4a4a8a','eastern_eu':'#7a4a4a','ukrainian':'#6a5a8a','russian':'#7a4a4a',
    'hungarian':'#8a5050','middle_east':'#b87a25','lebanese':'#c89538','turkish':'#a8662a',
    'syrian':'#9b5520','persian':'#8a4a25','latin':'#cc4a4a','mexican':'#d63d2a',
    'salvadoran':'#c8553a','peruvian':'#b35b50','colombian':'#cc6248','brazilian':'#3d8a47',
    'african_horn':'#a0522d','ethiopian':'#a0522d','eritrean':'#8a4528','somali':'#b06530',
    'african_west':'#5a8a3a','nigerian':'#4a7a30','ghanaian':'#6a8a40','moroccan':'#b87a2a',
    'jamaican':'#1f7a4a','trinidadian':'#2a9560','guyanese':'#3a8060','haitian':'#1a6855',
    'thai':'#7a8a3a','indonesian':'#7a6a40','malaysian':'#5a7a55','burmese':'#8a7050',
}


def _xml_escape(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
                  .replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;'))


def _fit_font_size(text, base_size, max_chars):
    n = len(text or '')
    if n <= max_chars: return base_size
    if n <= max_chars * 1.4: return int(base_size * 0.78)
    if n <= max_chars * 1.8: return int(base_size * 0.6)
    return int(base_size * 0.5)


def _tag_text(days):
    if days is None: return 'NEWLY LICENSED'
    if days <= 1:    return 'LICENSED TODAY'
    if days <= 30:   return f'LICENSED {days}D AGO'
    if days <= 60:   return f'LICENSED {days // 7}W AGO'
    return f'LICENSED {days // 30}MO AGO'


def build_card_svg(entry):
    name = entry.get('operatingName', '')
    keys = entry.get('cuisines') or ([entry['cuisine']] if entry.get('cuisine') else [])
    pills = []
    for k in keys[:3]:
        if not k: continue
        color = PALETTE_HEX.get(k) or cuisine_color(k)
        label = CUISINE_LABEL.get(k, k.replace('_', ' ').title())
        pills.append((label, color))
    addr = entry.get('address') or ''
    district = entry.get('district') or ''
    addr_line = addr
    if district and district not in addr:
        addr_line = f"{addr_line} · {district}" if addr_line else district
    if len(addr_line) > 64:
        addr_line = addr_line[:61] + '…'
    tag_text = _tag_text(entry.get('daysOpen'))
    name_size = _fit_font_size(name, 80, 22)

    pill_x = 70
    pill_svg = []
    for label, color in pills:
        w = max(140, 28 * len(label) + 32)
        pill_svg.append(
            f'<g transform="translate({pill_x},420)">'
            f'<rect width="{w}" height="48" rx="24" fill="{color}"/>'
            f'<text x="{w//2}" y="32" font-family="-apple-system,Helvetica,Arial,sans-serif" '
            f'font-size="22" font-weight="700" fill="#fff" text-anchor="middle" '
            f'letter-spacing="1.5">{_xml_escape(label.upper())}</text>'
            f'</g>'
        )
        pill_x += w + 12

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675" width="1200" height="675">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#faf7ee"/>
      <stop offset="100%" stop-color="#f0e8d4"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="675" fill="url(#bg)"/>
  <rect x="0" y="0" width="1200" height="8" fill="#15110d"/>

  <g transform="translate(70,80)">
    <rect width="{32 + 14 * len(tag_text)}" height="44" rx="22" fill="#c83624"/>
    <text x="{(32 + 14 * len(tag_text))//2}" y="30"
          font-family="-apple-system,Helvetica,Arial,sans-serif"
          font-size="20" font-weight="800" fill="#fff" text-anchor="middle"
          letter-spacing="2">{_xml_escape(tag_text)}</text>
  </g>

  <text x="70" y="350" font-family="Iowan Old Style, Charter, Georgia, serif"
        font-size="{name_size}" font-weight="800" fill="#15110d"
        letter-spacing="-2">{_xml_escape(name)}</text>

  {chr(10).join(pill_svg)}

  <text x="70" y="540" font-family="Iowan Old Style, Charter, Georgia, serif"
        font-size="32" font-style="italic" fill="#45403a">{_xml_escape(addr_line)}</text>

  <text x="70" y="625" font-family="Iowan Old Style, Charter, Georgia, serif"
        font-size="28" font-weight="800" fill="#15110d">NowServingTO</text>
  <text x="70" y="652" font-family="ui-monospace,Menlo,Consolas,monospace"
        font-size="18" fill="#7a746a">nowservingto.com</text>
</svg>"""


def render_card_png(entry, out_path=None):
    """Render the card SVG to a PNG. If out_path is given, write there;
    else return the PNG bytes."""
    svg = build_card_svg(entry)
    with tempfile.NamedTemporaryFile(suffix='.svg', mode='w', delete=False, encoding='utf-8') as f:
        f.write(svg); svg_path = f.name
    if out_path:
        png_path = str(out_path)
        return_bytes = False
    else:
        png_path = svg_path[:-4] + '.png'
        return_bytes = True
    try:
        subprocess.run(
            ['rsvg-convert', '-w', '1200', '-h', '675', svg_path, '-o', png_path],
            check=True, capture_output=True,
        )
        if return_bytes:
            return Path(png_path).read_bytes()
    finally:
        try: os.unlink(svg_path)
        except OSError: pass
        if return_bytes:
            try: os.unlink(png_path)
            except OSError: pass


# --- Trends share card ---------------------------------------------------
# Standalone 1200x675 card for /trends. Rendered alongside the page each
# inject and referenced as og:image so the X intent URL produces a rich
# embedded card. Now uses real restaurant thumbnails from og/thumb/ — six
# photo squares of the hero-strip entries instead of flag-colored cuisine
# percentage chips. The chips read as "fisher-price colours" per the user;
# real spots are more arresting in a tweet preview.
import base64 as _b64
from pathlib import Path as _Path

def _photo_data_uri(path_str):
    """Read a local image file and return a data: URI for SVG <image href>.
    Returns '' if the file can't be read so the card falls back gracefully."""
    if not path_str: return ''
    p = _Path(path_str)
    if not p.exists() or not p.is_file(): return ''
    ext = p.suffix.lower()
    mime = ('image/webp' if ext == '.webp'
            else 'image/jpeg' if ext in ('.jpg', '.jpeg')
            else 'image/png' if ext == '.png'
            else None)
    if not mime: return ''
    try:
        data = _b64.b64encode(p.read_bytes()).decode('ascii')
        return f'data:{mime};base64,{data}'
    except Exception:
        return ''


def _wrap_text(text, max_chars):
    """Greedy word-wrap returning a list of line strings."""
    words = (text or '').split()
    lines, current = [], ''
    for w in words:
        if not current:
            current = w
        elif len(current) + 1 + len(w) <= max_chars:
            current = f'{current} {w}'
        else:
            lines.append(current); current = w
    if current: lines.append(current)
    return lines


def build_trends_card_svg(dispatch_label, total_licences, hero_entries):
    """Build the /trends OG card SVG — Design B: full-bleed editorial.

    Single big storefront/food photo fills the whole card; dark gradient
    overlays the bottom ~40% with white serif text (restaurant name big,
    cuisine + dishes blurb below). Reads at any size — works in tiny X
    feed previews where the multi-card design got lost.

    Args:
      dispatch_label: e.g. 'JUNE 2026'
      total_licences: int — cumulative 3-year licence count (unused in
        Design B but kept in signature for caller compatibility)
      hero_entries: list with at least 1 dict — only the first is used
        in the full-bleed treatment. Keys: thumb_path, photo_path,
        name, cuisine_label, district, age_label, dishes, address
    """
    if not hero_entries:
        return ''  # caller should skip render

    f = hero_entries[0]
    photo_uri = _photo_data_uri(f.get('photo_path') or f.get('thumb_path'))
    name = (f.get('name') or '').strip()
    if len(name) > 30: name = name[:28] + '…'
    cuisine = (f.get('cuisine_label') or '').strip()
    district = (f.get('district') or '').strip()
    meta_line = cuisine + (f' · {district}' if district else '')
    age = (f.get('age_label') or '').strip()
    dishes = [d for d in (f.get('dishes') or []) if d][:3]
    blurb = ('Try the ' + ', '.join(dishes) + '.') if dishes else ''
    blurb_lines = _wrap_text(blurb, 56)[:2]
    eyebrow = f"TORONTO'S FRESHEST · {age.upper()}" if age else "TORONTO'S FRESHEST"

    # Photo layer (or paper fallback)
    if photo_uri:
        photo_svg = (
            f'<image x="0" y="0" width="1200" height="675" '
            f'href="{photo_uri}" preserveAspectRatio="xMidYMid slice" />'
        )
    else:
        photo_svg = '<rect width="1200" height="675" fill="#ebe9e4" />'

    # Blurb text lines (under meta)
    blurb_y_start = 630
    blurb_svg = []
    for i, line in enumerate(blurb_lines):
        blurb_svg.append(
            f'<text x="60" y="{blurb_y_start + i * 26}" '
            f'font-family="Iowan Old Style, Charter, Georgia, serif" font-size="20" '
            f'fill="rgba(255,255,255,0.92)">{_xml_escape(line)}</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675" width="1200" height="675">
  <defs>
    <linearGradient id="darken" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="black" stop-opacity="0"/>
      <stop offset="35%" stop-color="black" stop-opacity="0"/>
      <stop offset="55%" stop-color="black" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="black" stop-opacity="0.92"/>
    </linearGradient>
  </defs>
  {photo_svg}
  <rect width="1200" height="675" fill="url(#darken)" />

  <g transform="translate(40,32)">
    <rect width="180" height="32" rx="2" fill="rgba(0,0,0,0.55)" />
    <text x="90" y="22" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="13"
          font-weight="700" fill="#fff" text-anchor="middle" letter-spacing="3">NOWSERVING</text>
  </g>

  <text x="60" y="475" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="14"
        font-weight="800" fill="#ff6b52" letter-spacing="3">{_xml_escape(eyebrow)}</text>

  <text x="60" y="555" font-family="Iowan Old Style, Charter, Georgia, serif" font-size="64"
        font-weight="800" fill="#fff" letter-spacing="-2.5">{_xml_escape(name)}</text>

  <text x="60" y="600" font-family="Iowan Old Style, Charter, Georgia, serif" font-size="24"
        font-style="italic" fill="rgba(255,255,255,0.85)">{_xml_escape(meta_line)}</text>

  {chr(10).join(blurb_svg)}
</svg>"""


def _build_trends_card_svg_OLD_design_A(dispatch_label, total_licences, hero_entries):
    """Kept for reference only — Design A (1 featured + 4 thumbs) replaced
    by Design B (full-bleed). Not called from production."""
    if not hero_entries:
        return ''
    featured = hero_entries[0]
    HERO_X, HERO_Y, HERO_W, HERO_H = 60, 250, 560, 280
    hero_photo_uri = _photo_data_uri(featured.get('photo_path') or featured.get('thumb_path'))
    hero_name = (featured.get('name') or '').strip()
    if len(hero_name) > 32: hero_name = hero_name[:30] + '…'
    hero_cuisine = (featured.get('cuisine_label') or '').strip()
    hero_district = (featured.get('district') or '').strip()
    hero_meta = hero_cuisine + (f' · {hero_district}' if hero_district else '')
    hero_age = (featured.get('age_label') or '').strip()
    hero_dishes = featured.get('dishes') or []
    if hero_dishes:
        hero_blurb = 'Try the ' + ', '.join(hero_dishes[:3]) + '.'
    else:
        hero_blurb = 'Just registered with the City. Verified open via Google Places.'
    blurb_lines = _wrap_text(hero_blurb, 56)[:2]

    hero_svg = []
    if hero_photo_uri:
        hero_svg.append(
            f'<image x="{HERO_X}" y="{HERO_Y}" width="{HERO_W}" height="{HERO_H}" '
            f'href="{hero_photo_uri}" preserveAspectRatio="xMidYMid slice" />'
        )
    else:
        hero_svg.append(
            f'<rect x="{HERO_X}" y="{HERO_Y}" width="{HERO_W}" height="{HERO_H}" fill="#ebe9e4" />'
        )
    hero_svg.append(
        f'<rect x="{HERO_X}" y="{HERO_Y}" width="{HERO_W}" height="{HERO_H}" '
        f'fill="none" stroke="rgba(21,17,13,0.12)" stroke-width="1" />'
    )
    # "EDITOR'S PICK" eyebrow above hero name
    hero_svg.append(
        f'<text x="{HERO_X}" y="{HERO_Y + HERO_H + 28}" '
        f'font-family="ui-monospace,Menlo,Consolas,monospace" font-size="11" '
        f'font-weight="700" fill="#e84e3a" letter-spacing="2">'
        f'EDITOR&#39;S PICK · {_xml_escape(hero_age.upper()) if hero_age else "NEW"}</text>'
    )
    # Hero name (big serif)
    hero_svg.append(
        f'<text x="{HERO_X}" y="{HERO_Y + HERO_H + 64}" '
        f'font-family="Iowan Old Style, Charter, Georgia, serif" font-size="30" '
        f'font-weight="800" fill="#15110d" letter-spacing="-1">{_xml_escape(hero_name)}</text>'
    )
    # Cuisine · district (italic)
    hero_svg.append(
        f'<text x="{HERO_X}" y="{HERO_Y + HERO_H + 92}" '
        f'font-family="Iowan Old Style, Charter, Georgia, serif" font-size="17" '
        f'font-style="italic" fill="#45403a">{_xml_escape(hero_meta)}</text>'
    )
    # Dishes blurb (serif body)
    for i, line in enumerate(blurb_lines):
        hero_svg.append(
            f'<text x="{HERO_X}" y="{HERO_Y + HERO_H + 122 + i * 22}" '
            f'font-family="Iowan Old Style, Charter, Georgia, serif" font-size="16" '
            f'fill="#15110d">{_xml_escape(line)}</text>'
        )

    # ---- 4 supporting thumbs (right side, 2x2 grid) ----
    THUMB_W = THUMB_H = 175
    THUMB_GAP = 14
    THUMB_LABEL_H = 50
    SUPPORT_X0 = 670  # right of hero with gap
    SUPPORT_Y0 = HERO_Y
    supporting = hero_entries[1:5]
    thumbs_svg = []
    for i, e in enumerate(supporting):
        col = i % 2
        row = i // 2
        x = SUPPORT_X0 + col * (THUMB_W + THUMB_GAP)
        y = SUPPORT_Y0 + row * (THUMB_H + THUMB_LABEL_H + THUMB_GAP)
        uri = _photo_data_uri(e.get('thumb_path'))
        name = (e.get('name') or '').strip()
        if len(name) > 18: name = name[:16] + '…'
        cuisine = (e.get('cuisine_label') or '').strip()
        district = (e.get('district') or '').strip()
        meta = cuisine + (f' · {district}' if district else '')
        if len(meta) > 22: meta = meta[:20] + '…'
        age = (e.get('age_label') or '').strip()
        if uri:
            thumbs_svg.append(
                f'<image x="{x}" y="{y}" width="{THUMB_W}" height="{THUMB_H}" '
                f'href="{uri}" preserveAspectRatio="xMidYMid slice" />'
            )
        else:
            thumbs_svg.append(
                f'<rect x="{x}" y="{y}" width="{THUMB_W}" height="{THUMB_H}" fill="#ebe9e4" />'
            )
        thumbs_svg.append(
            f'<rect x="{x}" y="{y}" width="{THUMB_W}" height="{THUMB_H}" '
            f'fill="none" stroke="rgba(21,17,13,0.12)" stroke-width="1" />'
        )
        if age:
            tag_w = max(58, 8 * len(age) + 14)
            thumbs_svg.append(
                f'<g transform="translate({x + 5},{y + 5})">'
                f'<rect width="{tag_w}" height="18" rx="2" fill="rgba(232,78,58,0.95)" />'
                f'<text x="{tag_w // 2}" y="13" font-family="-apple-system,Helvetica,Arial,sans-serif" '
                f'font-size="10" font-weight="800" fill="#fff" text-anchor="middle" '
                f'letter-spacing="1">{_xml_escape(age.upper())}</text>'
                f'</g>'
            )
        thumbs_svg.append(
            f'<text x="{x + THUMB_W // 2}" y="{y + THUMB_H + 20}" '
            f'font-family="-apple-system,Helvetica,Arial,sans-serif" font-size="12" '
            f'font-weight="700" fill="#15110d" text-anchor="middle">{_xml_escape(name)}</text>'
            f'<text x="{x + THUMB_W // 2}" y="{y + THUMB_H + 38}" '
            f'font-family="-apple-system,Helvetica,Arial,sans-serif" font-size="10" '
            f'font-weight="500" fill="#7a746a" text-anchor="middle">{_xml_escape(meta)}</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675" width="1200" height="675">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#faf7ee"/>
      <stop offset="100%" stop-color="#f0e8d4"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="675" fill="url(#bg)"/>
  <rect x="0" y="0" width="1200" height="58" fill="#15110d"/>
  <text x="60" y="38" font-family="ui-monospace,Menlo,Consolas,monospace"
        font-size="20" font-weight="700" fill="#fff" letter-spacing="3">NOWSERVING</text>
  <text x="280" y="38" font-family="ui-monospace,Menlo,Consolas,monospace"
        font-size="16" fill="#c8c4bd" letter-spacing="2">TORONTO RESTAURANT INDUSTRY DATA · {_xml_escape(dispatch_label.upper())}</text>

  <text x="60" y="140" font-family="Iowan Old Style, Charter, Georgia, serif"
        font-size="62" font-weight="800" fill="#15110d" letter-spacing="-2">Toronto's Freshest</text>
  <text x="60" y="180" font-family="Iowan Old Style, Charter, Georgia, serif"
        font-size="20" font-style="italic" fill="#45403a">{total_licences:,} restaurant licences since {int(dispatch_label.split()[-1]) - 3} · the food press misses most of them</text>

  {chr(10).join(hero_svg)}

  {chr(10).join(thumbs_svg)}

  <text x="1140" y="660" font-family="ui-monospace,Menlo,Consolas,monospace"
        font-size="16" fill="#7a746a" text-anchor="end">nowservingto.com/trends</text>
</svg>"""


def render_trends_card_png(dispatch_label, total_licences, hero_entries, out_path):
    """Render the trends share card SVG to PNG at out_path."""
    svg = build_trends_card_svg(dispatch_label, total_licences, hero_entries)
    if not svg:
        return  # no hero entries — skip card render
    with tempfile.NamedTemporaryFile(suffix='.svg', mode='w', delete=False, encoding='utf-8') as f:
        f.write(svg); svg_path = f.name
    try:
        subprocess.run(
            ['rsvg-convert', '-w', '1200', '-h', '675', svg_path, '-o', str(out_path)],
            check=True, capture_output=True,
        )
    finally:
        try: os.unlink(svg_path)
        except OSError: pass
