/*! NowServingTO embed widget - https://nowservingto.com/embed.js
 *
 * Drop into any page:
 *   <div data-nsto-embed data-cuisine="vietnamese" data-count="5"></div>
 *   <script src="https://nowservingto.com/embed.js" async></script>
 *
 * Attributes on the container div:
 *   data-cuisine    one of ~50 cuisine keys (italian, vietnamese, etc.)
 *   data-district   one of: downtown, east-toronto, etobicoke,
 *                   north-york, scarborough, west-toronto
 *   data-count      1-10, default 5
 *   data-theme      "light" (default) | "dark"
 *
 * Renders inline HTML (no iframe) so the outbound links pass SEO link
 * equity to the linked /r/<slug> pages. Footer attribution link to
 * nowservingto.com is the canonical backlink we want from embedders.
 */
(function () {
  'use strict';

  var DATA_URL = 'https://nowservingto.com/data/corridors.json';
  var SITE     = 'https://nowservingto.com';
  var CSS_ID   = 'nsto-embed-css';

  function injectCss() {
    if (document.getElementById(CSS_ID)) return;
    var s = document.createElement('style');
    s.id = CSS_ID;
    s.textContent = [
      '.nsto-embed{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif;color:#15110d;background:#fff;border:1px solid #ebecef;border-radius:10px;padding:14px 16px 12px;max-width:520px;font-size:14px;line-height:1.45;box-shadow:0 1px 3px rgba(0,0,0,.04)}',
      '.nsto-embed.dark{background:#15110d;color:#fafafa;border-color:#2a2a2a}',
      '.nsto-embed-h{font:800 11px/1 inherit;letter-spacing:.1em;text-transform:uppercase;color:#74787c;margin:0 0 12px}',
      '.nsto-embed.dark .nsto-embed-h{color:#a8a8a8}',
      '.nsto-embed-h a{color:inherit;text-decoration:none;border-bottom:1px solid currentColor;padding-bottom:1px}',
      '.nsto-embed ul{list-style:none;padding:0;margin:0}',
      '.nsto-embed li{display:flex;gap:10px;padding:8px 0;border-top:1px solid #ebecef;align-items:center}',
      '.nsto-embed.dark li{border-color:#2a2a2a}',
      '.nsto-embed li:first-child{border-top:0;padding-top:0}',
      '.nsto-embed-body{flex:1;min-width:0}',
      '.nsto-embed-name{font:700 14px/1.25 inherit;margin:0 0 2px;letter-spacing:-.005em}',
      '.nsto-embed-name a{color:inherit;text-decoration:none;border-bottom:1px solid transparent;transition:border-color .12s}',
      '.nsto-embed-name a:hover{border-bottom-color:#c83624;color:#c83624}',
      '.nsto-embed-meta{font:400 12px/1.3 inherit;color:#74787c;margin:0}',
      '.nsto-embed.dark .nsto-embed-meta{color:#a8a8a8}',
      '.nsto-embed-foot{margin-top:10px;padding-top:10px;border-top:1px solid #ebecef;font:600 11px/1 inherit;color:#74787c;text-align:right;letter-spacing:.04em;text-transform:uppercase}',
      '.nsto-embed.dark .nsto-embed-foot{border-color:#2a2a2a;color:#a8a8a8}',
      '.nsto-embed-foot a{color:inherit;text-decoration:none;border-bottom:1px solid currentColor;padding-bottom:1px}',
      '.nsto-embed-empty{padding:10px 0;color:#74787c;font-style:italic;font-size:13px}'
    ].join('');
    document.head.appendChild(s);
  }

  function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function ago(days) {
    if (days <= 1)   return 'today';
    if (days <= 60)  return days + 'd ago';
    if (days <= 365) return Math.round(days / 30) + 'mo ago';
    return (days / 365).toFixed(1) + 'y ago';
  }

  function districtSlug(label) {
    return String(label || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  }

  function matchRow(r, cuisine, district) {
    var keys = r.cuisines || (r.cuisine ? [r.cuisine] : []);
    if (cuisine && keys.indexOf(cuisine) === -1) return false;
    if (district && districtSlug(r.district) !== district) return false;
    return true;
  }

  function render(container, rows, opts) {
    var label = opts.cuisine
      ? (opts.cuisineLabel || (opts.cuisine.replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); })))
      : (opts.district
          ? opts.district.replace(/-/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); })
          : 'Toronto');
    var landing = opts.cuisine ? (SITE + '/cuisine/' + opts.cuisine)
                : opts.district ? (SITE + '/district/' + opts.district)
                : SITE;
    var headline = 'Newest ' + esc(label) + ' restaurants in Toronto';
    var utm = '?utm_source=embed&utm_medium=widget&utm_campaign=' +
      (opts.cuisine || opts.district || 'all');

    container.className = 'nsto-embed' + (opts.theme === 'dark' ? ' dark' : '');
    if (!rows.length) {
      container.innerHTML =
        '<p class="nsto-embed-h"><a href="' + esc(landing + utm) + '" target="_blank" rel="noopener">' + headline + '</a></p>' +
        '<div class="nsto-embed-empty">No new openings in this slice yet - check back tomorrow.</div>' +
        '<div class="nsto-embed-foot"><a href="' + esc(SITE + utm) + '" target="_blank" rel="noopener">Powered by NowServingTO</a></div>';
      return;
    }
    var items = rows.map(function (r) {
      var slug = r.slug || '';
      var rUrl = slug ? (SITE + '/r/' + slug + utm) : (SITE + utm);
      var addr  = r.address || '';
      var dist  = r.district || '';
      var meta  = ago(r.daysOpen || 0) + (dist ? ' · ' + dist : '');
      // Photo thumbnail retired 2026-06-03 (site went text-only).
      return ''
        + '<li>'
        + '<div class="nsto-embed-body">'
        +   '<p class="nsto-embed-name"><a href="' + esc(rUrl) + '" target="_blank" rel="noopener">' + esc(r.operatingName || '') + '</a></p>'
        +   '<p class="nsto-embed-meta">' + esc(addr) + (addr ? ' · ' : '') + esc(meta) + '</p>'
        + '</div>'
        + '</li>';
    }).join('');
    container.innerHTML =
      '<p class="nsto-embed-h"><a href="' + esc(landing + utm) + '" target="_blank" rel="noopener">' + headline + '</a></p>' +
      '<ul>' + items + '</ul>' +
      '<div class="nsto-embed-foot"><a href="' + esc(SITE + utm) + '" target="_blank" rel="noopener">Powered by NowServingTO</a></div>';
  }

  function hydrate(data) {
    var rows = (data && data.newOpenings && data.newOpenings.recent) || [];
    // Build label lookup from the cuisines array so the human-readable
    // label matches what the site itself shows (avoids "South Asian"
    // vs "South_asian" type slop in the headline).
    var labels = {};
    (data && data.newOpenings && data.newOpenings.cuisines || []).forEach(function (c) {
      if (c && c.key) labels[c.key] = c.label;
    });
    var containers = document.querySelectorAll('[data-nsto-embed]');
    Array.prototype.forEach.call(containers, function (el) {
      var cuisine  = (el.getAttribute('data-cuisine') || '').toLowerCase().trim();
      var district = (el.getAttribute('data-district') || '').toLowerCase().trim();
      var count    = Math.max(1, Math.min(10, parseInt(el.getAttribute('data-count'), 10) || 5));
      var theme    = (el.getAttribute('data-theme') || 'light').toLowerCase();
      var matched  = rows.filter(function (r) { return matchRow(r, cuisine, district); }).slice(0, count);
      render(el, matched, {
        cuisine: cuisine || null,
        cuisineLabel: cuisine ? labels[cuisine] : null,
        district: district || null,
        theme: theme,
      });
    });
  }

  function fail(containers, msg) {
    Array.prototype.forEach.call(containers, function (el) {
      el.className = 'nsto-embed';
      el.innerHTML = '<div class="nsto-embed-empty">' + esc(msg) + '</div>'
        + '<div class="nsto-embed-foot"><a href="' + SITE + '" target="_blank" rel="noopener">Powered by NowServingTO</a></div>';
    });
  }

  function boot() {
    injectCss();
    var containers = document.querySelectorAll('[data-nsto-embed]');
    if (!containers.length) return;
    fetch(DATA_URL, { mode: 'cors', credentials: 'omit' })
      .then(function (r) { if (!r.ok) throw new Error('http ' + r.status); return r.json(); })
      .then(hydrate)
      .catch(function () { fail(containers, 'Unable to load NowServingTO feed.'); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
