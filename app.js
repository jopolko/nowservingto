const CUISINE_PALETTE = {
  italian:'var(--c-italian)', caribbean:'var(--c-caribbean)', south_asian:'var(--c-sasian)',
  chinese:'var(--c-chinese)', vietnamese:'var(--c-vietnam)', japanese:'var(--c-japan)',
  korean:'var(--c-korean)', filipino:'var(--c-filipino)', tamil:'var(--c-tamil)',
  tibetan:'var(--c-tibet)', greek:'var(--c-greek)', portuguese:'var(--c-portuguese)',
  polish:'var(--c-polish)', french:'var(--c-french)', irish_uk:'var(--c-irish_uk)',
  german:'var(--c-german)', jewish_deli:'var(--c-jewish_deli)', eastern_eu:'var(--c-eastern_eu)',
  middle_east:'var(--c-mideast)', latin:'var(--c-latin)',
  african_horn:'var(--c-african_horn)', african_west:'var(--c-african_west)',
  thai:'#7a8a3a',
  indian:'#e88e2c', pakistani:'#a06030', afghan:'#7a5d3a', bangladeshi:'#b88820', persian:'#8a4a25',
  mexican:'#d63d2a', salvadoran:'#c8553a', peruvian:'#b35b50', colombian:'#cc6248', brazilian:'#3d8a47',
  jamaican:'#1f7a4a', trinidadian:'#2a9560', guyanese:'#3a8060', haitian:'#1a6855',
  lebanese:'#c89538', turkish:'#a8662a', syrian:'#9b5520',
  ukrainian:'#6a5a8a', russian:'#7a4a4a', hungarian:'#8a5050',
  ethiopian:'#a0522d', eritrean:'#8a4528', somali:'#b06530',
  nigerian:'#4a7a30', ghanaian:'#6a8a40', moroccan:'#b87a2a',
  indonesian:'#7a6a40', malaysian:'#5a7a55', burmese:'#8a7050',
  cambodian:'#7a5a3a', laotian:'#8a6a4a',
  sri_lankan:'#b8702a', nepalese:'#a05a25',
  cuban:'#2a8a6a', dominican:'#256a8a',
  spanish:'#c8553a',
  israeli:'#3a6a8a', egyptian:'#b88a4a', yemeni:'#a05a30', armenian:'#9b3a3a', georgian:'#7a4a8a',
  argentinian:'#5a8aa0', venezuelan:'#c8a838',
  senegalese:'#7a8a30',
};
const CUISINE_LABEL = {
  italian:'Italian', chinese:'Chinese', japanese:'Japanese', korean:'Korean',
  vietnamese:'Vietnamese', filipino:'Filipino', thai:'Thai',
  indonesian:'Indonesian', malaysian:'Malaysian', burmese:'Burmese',
  cambodian:'Cambodian', laotian:'Laotian',
  south_asian:'South Asian', indian:'Indian', pakistani:'Pakistani', afghan:'Afghan',
  bangladeshi:'Bangladeshi', tamil:'Tamil', tibetan:'Tibetan',
  sri_lankan:'Sri Lankan', nepalese:'Nepalese',
  caribbean:'Caribbean', jamaican:'Jamaican', trinidadian:'Trinidadian', guyanese:'Guyanese', haitian:'Haitian',
  cuban:'Cuban', dominican:'Dominican',
  greek:'Greek', portuguese:'Portuguese', polish:'Polish', french:'French',
  irish_uk:'Irish/UK', german:'German', jewish_deli:'Jewish deli', spanish:'Spanish',
  eastern_eu:'Eastern European', ukrainian:'Ukrainian', russian:'Russian', hungarian:'Hungarian',
  middle_east:'Middle Eastern', lebanese:'Lebanese', turkish:'Turkish', syrian:'Syrian', persian:'Persian',
  israeli:'Israeli', egyptian:'Egyptian', yemeni:'Yemeni', armenian:'Armenian', georgian:'Georgian',
  latin:'Latin American', mexican:'Mexican', salvadoran:'Salvadoran', peruvian:'Peruvian',
  colombian:'Colombian', brazilian:'Brazilian', argentinian:'Argentinian', venezuelan:'Venezuelan',
  african_horn:'East African', ethiopian:'Ethiopian', eritrean:'Eritrean', somali:'Somali',
  african_west:'West African', nigerian:'Nigerian', ghanaian:'Ghanaian', moroccan:'Moroccan', senegalese:'Senegalese',
};

const NAME_STOP = new Set(['THE','AND','OF','RESTAURANT','CAFE','BAR','GRILL','KITCHEN','TORONTO','INC','LTD','CO','CORP','CUISINE','HOUSE','SHOP','MARKET','STORE','FOOD','FOODS','SUPER','PLACE','SPOT','EATERY','BISTRO','PUB','BAKERY','DELI','DINER','LOUNGE']);
function nameTokens(s) {
  if (!s) return new Set();
  const out = new Set();
  s.toUpperCase().replace(/[^A-Z0-9 ]/g,' ').split(/\s+/).forEach(w => {
    if (w.length > 1 && !NAME_STOP.has(w)) out.add(w);
  });
  return out;
}
function nameJaccard(a, b) {
  const A = nameTokens(a), B = nameTokens(b);
  if (!A.size || !B.size) return 0;
  let inter = 0; A.forEach(x => B.has(x) && inter++);
  return inter / (A.size + B.size - inter);
}

const _SOCIAL_HOSTS = new Set([
  'instagram.com','www.instagram.com',
  'facebook.com','www.facebook.com','m.facebook.com',
  'tiktok.com','www.tiktok.com',
  'twitter.com','www.twitter.com',
  'x.com','www.x.com',
  'linkedin.com','www.linkedin.com',
  'youtube.com','www.youtube.com',
]);
function isSocialUrl(url) {
  if (!url) return false;
  try { return _SOCIAL_HOSTS.has(new URL(url).hostname); } catch(e) { return false; }
}

function tierLabel(days) {
  // Compact freshness label for row contexts. Drops "First seen" + "ago"
  // — repetitive on every row, no info value. Must match Python _tier_label().
  if (days == null) return '';
  if (days <= 1)    return '1 day';
  if (days <= 30)   return days + ' days';
  if (days <= 365) {
    const m = Math.max(1, Math.round(days/30));
    return m === 1 ? '1 month' : m + ' months';
  }
  return '1+ year';
}

// On single-restaurant /r/<slug> pages (.page-listing), monthly
// dispatch archive pages (.page-dispatch), and trends pages
// (.page-trends), skip the directory-level fetch entirely. Those
// pages are pre-rendered with curated/computed static content -
// hydrating against /data/corridors.json would replace it with the
// full 280-entry feed and break the editorial scope.
if (!document.body.classList.contains('page-listing')
    && !document.body.classList.contains('page-dispatch')
    && !document.body.classList.contains('page-trends')
    && !document.body.classList.contains('page-all')
    && !document.body.classList.contains('page-data')
    && !document.body.classList.contains('page-answers'))
// Low priority: the feed is pre-rendered server-side, so this 119KB hydration
// payload is only needed for the interactive layer (filtering/search/full list),
// never for first paint. Deprioritizing it frees the throttled pipe for the LCP
// font instead of competing with it.
fetch('/data/corridors.json?v=' + Date.now(), { priority: 'low' }).then(r => r.json()).then(data => {
  const no = data.newOpenings;
  // (Subtitle reads "updated daily" - no dynamic date to inject.)

  // Dynamic cuisine taxonomy: corridors.json carries label + color for every
  // active cuisine (curated palette for seed keys, hash-derived hex for
  // novel keys auto-registered when Haiku surfaced a new ethnicity). This
  // map lets the renderer use server-side colors/labels first, falling back
  // to the legacy JS CUISINE_PALETTE/LABEL only for keys the JSON didn't
  // ship - typically nothing, since the JSON is the source of truth now.
  const CUISINE_META = {};
  (no && no.cuisines || []).forEach(c => {
    if (c && c.key) CUISINE_META[c.key] = { label: c.label, color: c.color };
  });

  // Favorites: localStorage-backed set of saved slugs. No accounts, no backend.
  function getSaved() { try { return new Set(JSON.parse(localStorage.getItem('nsto_saved') || '[]')); } catch { return new Set(); } }
  function isSaved(slug) { return getSaved().has(slug); }
  // A friendly micro-burst of sparkles at an element's centre (fires on save).
  function nsSparkle(el) {
    if (!el || !el.getBoundingClientRect) return;
    if (matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const glyphs = ['✨', '⭐', '💫', '✦'];
    for (let i = 0; i < 6; i++) {
      const s = document.createElement('span');
      s.className = 'ns-spark'; s.textContent = glyphs[i % glyphs.length];
      s.style.left = cx + 'px'; s.style.top = cy + 'px';
      const a = Math.PI * 2 * (i / 6) + Math.random() * 0.6, d = 18 + Math.random() * 22;
      s.style.setProperty('--dx', (Math.cos(a) * d).toFixed(1) + 'px');
      s.style.setProperty('--dy', (Math.sin(a) * d - 10).toFixed(1) + 'px');
      document.body.appendChild(s);
      setTimeout(() => s.remove(), 760);
    }
  }
  function toggleSaved(slug) {
    const s = getSaved();
    if (s.has(slug)) s.delete(slug); else s.add(slug);
    localStorage.setItem('nsto_saved', JSON.stringify([...s]));
    return s.has(slug);
  }
  let savedOnly = false;
  function refreshSavedToggle() {
    const btn = document.getElementById('saved-toggle');
    if (!btn) return;
    const n = getSaved().size;
    btn.textContent = n ? `♥ Saved (${n})` : '♡ Saved';
    btn.classList.toggle('has-saves', n > 0);
    btn.classList.toggle('active', savedOnly);
  }

  if (!no || !no.cuisines || !no.cuisines.length) {
    document.getElementById('open-feed').innerHTML = '<div class="empty">No new-openings data in feed.</div>';
    return;
  }

  const trigger = document.getElementById('cp-trigger');
  const panel = document.getElementById('cp-panel');
  const rTrigger = document.getElementById('rp-trigger');
  const rPanel = document.getElementById('rp-panel');
  const feed = document.getElementById('open-feed');

  // District list - same 6 derived from FSA mapping in inject_openings.py
  const DISTRICTS = ['Downtown', 'East Toronto', 'Etobicoke', 'North York', 'Scarborough', 'West Toronto'];

  // Picker panels are pre-rendered server-side with <a> elements (crawlable
  // links + first-paint visible without JS). Only fall back to dynamic build
  // when the server-rendered options are absent (e.g. dev / template state).
  const totalCount = no.cuisines.reduce((s,c)=>s+c.count365d,0);
  function makeOpt(key, label, count, allFlag) {
    const b = document.createElement('button');
    b.className = 'cp-opt' + (allFlag ? ' cp-all' : '');
    b.type = 'button';
    b.role = 'option';
    b.dataset.key = key;
    b.innerHTML = `<span class="lbl">${label}</span><span class="ct">${count}</span>`;
    return b;
  }
  if (!panel.querySelector('.cp-opt')) {
    panel.appendChild(makeOpt('__all', 'All cuisines', totalCount, true));
    [...no.cuisines]
      .sort((a, b) => (a.label || a.key).localeCompare(b.label || b.key))
      .forEach(c => panel.appendChild(makeOpt(c.key, c.label, c.count365d, false)));
  }
  // Region dropdown - count entries per district from the recent feed
  const regionCount = {};
  no.recent.forEach(r => { if (r.district) regionCount[r.district] = (regionCount[r.district]||0)+1; });
  if (!rPanel.querySelector('.cp-opt')) {
    rPanel.appendChild(makeOpt('__all', 'All Toronto', no.recent.length, true));
    DISTRICTS.forEach(d => rPanel.appendChild(makeOpt(d, d, regionCount[d] || 0, false)));
  }

  const INITIAL_SHOW = 50, PAGE_SIZE = 50;
  let currentRows = [], currentShown = INITIAL_SHOW;
  let currentCuisine = '__all', currentRegion = '__all', singleSlug = null;
  // Heat-bar drill-down: when true, the home feed shows only the new-this-month
  // entries. Reset whenever the cuisine/region scope changes (see applyFilters).
  let freshOnly = false;
  // currentNeighborhood: iconic-corridor filter set from /neighborhood/<slug>
  // URLs. Compounds with cuisine + region filters so visitors can narrow to
  // e.g. "Italian restaurants in Greektown" by selecting cuisine on a
  // neighborhood page. Server-rendered HTML is pre-filtered to the right
  // set, but JS hydration replaces it on page load — without this flag the
  // re-render would show all-Toronto entries on top of the static feed.
  let currentNeighborhood = null;
  function buildRowEl(r) {
    // Multi-cuisine entries render one pill per declared cuisine; legacy single-
    // cuisine entries fall back to `r.cuisine`.
    const cuisineKeys = (r.cuisines && r.cuisines.length) ? r.cuisines : [r.cuisine];
    const pillsHtml = cuisineKeys
      .map(k => {
        const meta = CUISINE_META[k];
        const bg = (meta && meta.color) || CUISINE_PALETTE[k] || '#999';
        const lab = (meta && meta.label) || CUISINE_LABEL[k] || k;
        return `<a class="pill" href="/cuisine/${k}" style="background:${bg}" aria-label="See newest ${lab} restaurants">${lab}</a>`;
      }).join('');
    const isHot = r.daysOpen <= 30;
    const isRecent = !isHot && r.daysOpen <= 90;
    // Primary cuisine colour → left-edge accent strip (mirrors the
    // server-rendered row builder's --row-accent inline style).
    const accentKey = cuisineKeys[0];
    const accentMeta = accentKey ? CUISINE_META[accentKey] : null;
    const accentBg = (accentMeta && accentMeta.color) || (accentKey && CUISINE_PALETTE[accentKey]) || null;
    const row = document.createElement('article');
    row.className = 'ticket';
    if (r.slug) row.setAttribute('data-slug', r.slug);
    if (isHot) row.setAttribute('data-fresh', 'hot');
    else if (isRecent) row.setAttribute('data-fresh', 'recent');
    else if (r.daysOpen != null && r.daysOpen <= 365) row.setAttribute('data-fresh', 'aged');
    if (cuisineKeys.length > 1) row.setAttribute('data-multi', '');
    const trustMatch = !r.matchedName || nameJaccard(r.operatingName, r.matchedName) >= 0.34;
    // Name link precedence: own website (when trust gate passes) > Places
    // deep-link > our own /r/<slug> listing page. The listing page is the
    // always-available fallback - never sends to a wrong business or a
    // generic-building Maps result, and provides cuisine + address + a
    // breadcrumb back to the cuisine hub.
    const internalUrl = r.slug ? `/r/${r.slug}` : null;
    const ownSite = (trustMatch && r.website && !isSocialUrl(r.website)) ? r.website : null;
    const link = ownSite || r.mapsUrl || internalUrl;
    const linkClass = link ? 'ext' : '';
    // target=_blank on devices with a mouse / trackpad available (preserve
    // NowServingTO tab); same-tab on pure-touch so the back button cleanly
    // returns from Maps. `(any-pointer: fine)` is the correct signal:
    // it's true on Windows touchscreen laptops where the PRIMARY input is
    // touch but a mouse is also attached - `(pointer: fine)` returns
    // false there because it only checks the primary. Phones/tablets
    // with no mouse return false on both.
    const desktopUA = window.matchMedia('(any-pointer: fine)').matches;
    const tgt = desktopUA ? ' target="_blank"' : '';
    // ↗ arrow only when the name link is the restaurant's OWN website
    // (not Maps fallback, not our internal /r/ page). Signals to the
    // visitor that the click leaves NowServingTO for the restaurant's
    // actual site.
    const isOwnerSite = !!ownSite;
    const extArrow = isOwnerSite ? '<span class="ext-arrow" aria-hidden="true">↗</span>' : '';
    const nameHtml = link
      ? `<a class="${linkClass}" href="${link}"${tgt} rel="noopener">${r.operatingName}${extArrow}</a>`
      : r.operatingName;
    // Rating display removed 2026-06-04 — Maps Platform ToS §5.3 restricts
    // caching of Places-derived ratings. Row shows name + address + date only.
    const ratingHtml = '';
    // (Was: "unverified" pill rendered when Places' matched name diverges
    // too far from the licence name. The user-protective behavior - link
    // suppression - still happens silently via trustMatch. Pill removed
    // 2026-05-19 because Google's JS-rendering crawl was picking it up
    // and concatenating it next to the restaurant name in SERP snippets
    // ("CAFEMIA ITALIAN BAKERYunverified 84 OAKDALE RD"), which read
    // worse to searchers than the protective behavior was worth.)
// Address link ladder:
    //   1) Places CID (mapsUrl) - exact business profile match
    //   2) coord-pin (?q=lat,lng) - geocoded address, gives map + Street View
    //      pegman without falsely claiming "this IS the restaurant" the way
    //      a name+address search would (CAFEMIA-style false positives).
    //   3) plain text - no Places, no lat/lng (rare; <5% of no-Places).
    const coordPin = (r.lat != null && r.lng != null)
      ? `https://www.google.com/maps?q=${r.lat},${r.lng}`
      : '';
    const addrUrl = r.mapsUrl || coordPin;
    // Split address so mobile CSS can hide the postal/city tail and keep
    // just the street. Matches the server-rendered structure.
    const addrFull = r.address || '-';
    const commaIdx = addrFull.indexOf(',');
    const addrStreet = commaIdx > 0 ? addrFull.slice(0, commaIdx) : addrFull;
    const addrRest = commaIdx > 0 ? addrFull.slice(commaIdx) : '';
    const addrInnerBody = addrRest
      ? `${addrStreet}<span class="oad-rest">${addrRest}</span>`
      : addrStreet;
    const addrLink = addrUrl ? `<a href="${addrUrl}"${tgt} rel="noopener">${addrInnerBody}</a>` : addrInnerBody;
    // Suffix the address with either distance (when Near me is active and we
    // have coords) or the district (when not, and we're showing all-Toronto).
    // Distance replaces district under near-me - the district is less useful
    // once the user's already filtered to their own neighbourhood radius.
    let addrSuffix = '';
    if (nearMeActive && userLatLng && r.lat && r.lng) {
      const km = haversineKm(userLatLng, [r.lat, r.lng]);
      const kmText = km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1)} km`;
      addrSuffix = `<span class="oad-d oad-dist"> · ${kmText}</span>`;
    } else if (r.district && currentRegion === '__all') {
      addrSuffix = `<span class="oad-d"> · ${r.district}</span>`;
    }
    const addrLine = `${addrLink}${addrSuffix}`;
    const saved = r.slug && isSaved(r.slug);
    const favHtml = r.slug
      ? `<button class="row-fav ${saved ? 'fav-on' : ''}" type="button" aria-label="${saved ? 'Remove from saved' : 'Save for later'}">${saved ? '♥' : '♡'}</button>`
      : '';
    // Material/Android share glyph - 3 dots connected by lines. More universally
    // recognized as "share" than ↗ (which we already use for external links on
    // business names).
    const shareHtml = r.slug
      ? `<button class="row-share" type="button" aria-label="Share this listing"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" aria-hidden="true"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/></svg></button>`
      : '';
    const thumb = r.thumb || '';
    // Thumbnail click → Google Places card preferred (Maps has more photos
    // + reviews + hours than a typical one-page restaurant website). Falls
    // back to coord-pin, then website, then the internal listing page.
    // Same ladder as addrUrl above; coordPin slots between Places and the
    // website because for entries whose thumb is a Street View image (the
    // photogenic fallback for no-Places entries), tapping the pic should
    // land the user at the exact same view.
    // No image slot — photos retired site-wide 2026-06-03. Row carries
    // cuisine identity via the cuisine-color pill on the right side.
    const thumbHtml = '';
    const agoText = tierLabel(r.daysOpen);
    const agoHtml = agoText
      ? (r.slug
        ? `<a class="ago" href="/r/${r.slug}">${agoText}</a>`
        : `<span class="ago">${agoText}</span>`)
      : '';
    // Editorial blurb beneath the name+address line. Pulled from the
    // pre-baked `r.blurb` field (set by inject_openings.py). Bare-bones
    // entries (no website) get a sage "no website yet" tag + 🌱 sprout
    // next to the date — subtle gamified flag for discovery rows.
    const bare = !!r.bare;
    if (bare) row.setAttribute('data-bare', '');
    const escHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
    const bareTag = bare
      ? '<span class="row-fresh"> · No website yet.</span>'
      : '';
    const blurbHtml = (r.blurb || bare)
      ? `<p class="row-blurb">${escHtml(r.blurb || '')}${bareTag}</p>`
      : '';
    // Primary cuisine badge for ticket header
    const primaryKey = cuisineKeys[0];
    const primaryMeta = primaryKey ? CUISINE_META[primaryKey] : null;
    const badgeBg = (primaryMeta && primaryMeta.color) || (primaryKey && CUISINE_PALETTE[primaryKey]) || '#888';
    const badgeLabel = (primaryMeta && primaryMeta.label) || CUISINE_LABEL[primaryKey] || primaryKey || '';
    const daysNum = r.daysOpen != null ? r.daysOpen : '?';
    // Freshness: days under a month, months once it's over (matches nsAgo).
    const _fd = r.daysOpen;
    const freshN = (typeof _fd === 'number' && _fd >= 30) ? Math.floor(_fd / 30) : daysNum;
    const freshU = (typeof _fd !== 'number') ? 'days'
                 : _fd < 30 ? (_fd === 1 ? 'day' : 'days')
                 : (Math.floor(_fd / 30) === 1 ? 'month' : 'months');
    // Neighborhood label from entry data
    const nbhd = (r.neighborhood && r.neighborhood.label) ? r.neighborhood.label : '';
    const nbhdHtml = nbhd && r.district
      ? `<span class="nbhd">${escHtml(nbhd)} · ${escHtml(r.district)}</span>`
      : (r.district ? `<span class="nbhd">${escHtml(r.district)}</span>` : '');
    const bareNote = bare ? ' <span class="row-fresh">· No website yet.</span>' : '';
    const blurbBody = (r.blurb || bare)
      ? `<p class="tk-blurb">${escHtml(r.blurb || '')}${bareNote}</p>` : '';
    // No "Full listing" CTA when we're already on that listing page (/r/…) —
    // it would just self-link. Mirrors show_cta=False in the server renderer.
    const onListingPage = location.pathname.startsWith('/r/');
    const ctaHtml = (r.slug && !onListingPage) ? `<a class="tk-cta" href="/r/${r.slug}">Full listing →</a>` : '';
    row.innerHTML = `
      <div class="tk-head">
        <span class="tk-badge" style="background:${badgeBg}">${badgeLabel}</span>
        <span class="tk-freshness"><span class="days">${freshN}</span> ${freshU} ago</span>
      </div>
      <div class="tk-body">
        <h2 class="tk-name">${nameHtml}</h2>
        ${blurbBody}
      </div>
      <div class="tear"></div>
      <div class="tk-foot">
        <div class="tk-addr">${nbhdHtml}${addrLink}${addrSuffix}</div>
        <div class="tk-actions">${favHtml}${shareHtml}${ctaHtml}</div>
      </div>`;
    const favBtn = row.querySelector('.row-fav');
    if (favBtn) {
      favBtn.addEventListener('click', e => {
        e.preventDefault(); e.stopPropagation();
        const now = toggleSaved(r.slug);
        favBtn.classList.toggle('fav-on', now);
        if (now) nsSparkle(favBtn);
        favBtn.textContent = now ? '♥' : '♡';
        favBtn.setAttribute('aria-label', now ? 'Remove from saved' : 'Save for later');
        refreshSavedToggle();
        if (savedOnly && !now) renderFeed();
      });
    }
    const shareBtn = row.querySelector('.row-share');
    if (shareBtn) {
      shareBtn.addEventListener('click', e => {
        e.preventDefault(); e.stopPropagation();
        window.__nsShare(r.slug, shareBtn);
      });
    }
    return row;
  }
  // ── Cuisine emoji (homepage friendly layout). Falls back to 🍴. ──
  const EMOJI = {
    indian:'🍛', chinese:'🥡', vietnamese:'🍜', italian:'🍕', mexican:'🌮',
    japanese:'🍣', korean:'🍲', turkish:'🥙', thai:'🍜', pakistani:'🍛',
    sri_lankan:'🍛', lebanese:'🥙', tamil:'🍛', persian:'🍢', middle_east:'🥙',
    filipino:'🍢', greek:'🥙', french:'🥐', bangladeshi:'🍛', argentinian:'🥩',
    jamaican:'🍢', afghan:'🍢', taiwanese:'🧋', south_asian:'🍛', caribbean:'🍹',
    latin:'🌮', eritrean:'🍲', ethiopian:'🍲', portuguese:'🥐', peruvian:'🐟',
    nigerian:'🍲', tibetan:'🥟', armenian:'🥙', belgian:'🧇', venezuelan:'🫓',
    palestinian:'🥙', ghanaian:'🍲', senegalese:'🍲', costa_rican:'🍤',
    singaporean:'🍜', kurdish:'🥙', guatemalan:'🌮', spanish:'🥘',
    indonesian:'🍜', colombian:'🫓'
  };
  const esc = (s) => String(s==null?'':s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // Licence data is ALL-CAPS; title-case it for the friendly layout.
  const titleCase = (s) => String(s==null?'':s).toLowerCase().replace(/\b([a-z])/g, (m,c) => c.toUpperCase()).replace(/([A-Za-z])'S\b/g, "$1's");
  // Cuisine colour → soft pastel tile background for list icons.
  function iconTint(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return '#f0ece3';
    const n = parseInt(m[1], 16);
    return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},0.16)`;
  }
  const nsLabel = (k) => (CUISINE_META[k] && CUISINE_META[k].label) || CUISINE_LABEL[k] || k;
  const nsKeys = (r) => (r.cuisines && r.cuisines.length) ? r.cuisines : [r.cuisine];
  const nsHood = (r) => (r.neighborhood && r.neighborhood.label) || r.district || '';
  // Field-synthesized fallback so brand-new spots (editorial blurb not yet
  // generated) never render blank. Mirrors _fallback_blurb() in inject.
  function nsBlurbText(r) {
    if (r.blurb) return r.blurb.replace(/\s+—\s+/g, ', ').replace(/—/g, '-');
    const name = titleCase(r.operatingName || '');
    if (!name) return '';
    const lab = nsLabel(nsKeys(r)[0]) || '';
    const hood = nsHood(r);
    const street = (r.address || '').split(',')[0].replace(/^\s*\d+\s*/, '').trim();
    let where = '';
    if (street) where += ' on ' + street;
    if (hood) where += ' in ' + hood;
    return name + ' is a ' + (lab ? lab + ' ' : '') + 'spot' + where + '.';
  }
  // Own website, only when the Places name actually matches (don't ship a
  // visitor to a wrong business's site). Aggregator/dead/ghost sites are
  // already stripped upstream by inject, so r.website here is clean.
  function nsSite(r) {
    if (!r.website) return null;
    const trust = !r.matchedName || nameJaccard(r.operatingName, r.matchedName) >= 0.34;
    return trust ? r.website : null;
  }
  // Direct-out action buttons (website ↗ / Map) surfaced on the card itself,
  // so visitors don't have to hop through /r/ to reach the restaurant. Buttons
  // (not <a>) because the card is already one big <a> to /r/ — nested anchors
  // are invalid; click handlers wired after render open data-url in a new tab.
  function nsActions(r) {
    const site = nsSite(r);
    let h = '';
    if (site) h += `<button class="ns-act web" type="button" data-url="${esc(site)}">Visit site <span class="ext-arrow" aria-hidden="true">↗</span></button>`;
    if (r.mapsUrl) h += `<button class="ns-act map" type="button" data-url="${esc(r.mapsUrl)}">Map</button>`;
    return h;
  }
  // Recency label — no "ago" (the masthead lede already frames it). today /
  // yesterday / N days / N months.
  function nsAgo(d) {
    if (typeof d !== 'number') return '';
    if (d <= 0) return 'today';
    if (d === 1) return 'yesterday';
    if (d < 30) return d + ' days';
    const m = Math.floor(d / 30);
    return m + (m === 1 ? ' month' : ' months');
  }
  // Recency chip — the gamified hook. Fresh (≤7 days) pops in accent; older is
  // muted. One colored chip carries the "ooh, new" signal, no clutter.
  function nsChip(r) {
    const d = r.daysOpen;
    const fresh = (typeof d === 'number' && d <= 7);
    return `<span class="ns-when${fresh ? ' fresh' : ''}">${nsAgo(d)}</span>`;
  }
  // "First seen" explainer — one info disclosure for the whole feed (the dates
  // on each listing are first-seen dates). Native <details> so it needs no JS
  // handler and works in the static render too. Mirrors _NS_FIRSTSEEN in inject.
  const NS_FIRSTSEEN = '<details class="ns-firstseen"><summary>First seen <span class="ns-i" aria-hidden="true">i</span></summary>'
    + "<p>Each listing's date is when the spot was <strong>first seen in official Toronto records</strong>: its Toronto Public Health (DineSafe) inspection date when there is one (the most reliable sign it was actually serving), otherwise the City of Toronto business-licence date. Every listing is also confirmed open via its website or social media.</p></details>";
  // Tag labels the DATE we show, not open/closed — every listing already
  // passed the Places OPERATIONAL gate, so all are open. dateSource 'dinesafe'
  // means the shown date is a Toronto Public Health inspection ("Operating" —
  // confirmed serving then); otherwise it's the City licence date
  // ("Registered" — paperwork date). The swap in inject_openings.py already
  // shows whichever date is the better signal; this just names which it is.
  function nsStatus(r) {
    return (r && r.dateSource === 'dinesafe')
      ? '<span class="ns-status operating" title="Operating date — confirmed by a Toronto Public Health (DineSafe) inspection">Operating</span>'
      : '<span class="ns-status registered" title="Registered date — City of Toronto business licence">Registered</span>';
  }
  function nsLegend() {
    return '<p class="ns-legend">'
      + '<span class="ns-status operating">Operating</span> date confirmed by a Toronto Public Health inspection'
      + ' · <span class="ns-status registered">Registered</span> date from the City licence'
      + ' · every listing is open &amp; verified</p>';
  }
  // Best destination for a listing: its own trusted website, else its Places/
  // Maps page, else the internal /r/ profile as fallback. The whole card links
  // here (no separate buttons); a small name ↗ signals it opens out.
  function nsBestLink(r) {
    const site = nsSite(r);
    if (site) return site;
    if (r.mapsUrl) return r.mapsUrl;
    return r.slug ? `/r/${r.slug}` : '#';
  }
  function nsExt(r) { const l = nsBestLink(r); return !!l && l !== '#' && !l.startsWith('/r/'); }
  // Split tap targets (card is a container, not one big <a>, so each zone is a
  // real link — nested <a> is invalid HTML): name+↗ → own site / Places;
  // location line → Google Maps; blurb + glyph → /r/ full editorial profile.
  function nsRLink(r) { return r.slug ? `/r/${r.slug}` : nsBestLink(r); }
  function nsSubLine(r, lab, cls) {
    const inner = `${esc(lab)}${nsHood(r)?' · '+esc(nsHood(r)):''}`;
    return r.mapsUrl
      ? `<a class="${cls} ns-maplink" href="${esc(r.mapsUrl)}" target="_blank" rel="noopener"><span class="ns-pin" aria-hidden="true">📍</span>${inner}</a>`
      : `<p class="${cls}">${inner}</p>`;
  }
  function nsHeroCard(r, rank) {
    const k = nsKeys(r)[0], lab = nsLabel(k);
    const href = nsBestLink(r), ext = nsExt(r), rHref = nsRLink(r);
    const saved = r.slug && isSaved(r.slug);
    const distTag = r.district ? `<span class="ns-tag hood">${esc(r.district)}</span>` : '';
    const bt = nsBlurbText(r);
    const blurb = bt ? `<a class="ns-card-blurb" href="${esc(rHref)}">${esc(bt)}</a>` : '';
    const crown = rank === 1 ? '<span class="ns-crown">Newest</span>' : '';
    const arr = ext ? '<span class="ext-arrow" aria-hidden="true">↗</span>' : '';
    return `<article class="ns-hero-card${rank===1?' rank-1':''}" data-slug="${esc(r.slug||'')}">`
      + `<div class="ns-card-top">${crown}${nsChip(r)}</div>`
      + `<div class="ns-card-body"><a class="ns-card-name" href="${esc(href)}"${ext?' target="_blank" rel="noopener"':''}>${esc(titleCase(r.operatingName))}${arr}</a>`
      + nsSubLine(r, lab, 'ns-card-sub')
      + blurb
      + `<span class="ns-tag cuisine">${esc(lab)}</span>${distTag}`
      + `<div class="ns-card-actions"><button class="ns-save-btn${saved?' saved':''}" type="button" data-slug="${esc(r.slug||'')}">${saved?'♥ Saved':'♡ Save'}</button></div>`
      + `</div></article>`;
  }
  function nsGridCard(r) {
    const k = nsKeys(r)[0], lab = nsLabel(k);
    const href = nsBestLink(r), ext = nsExt(r), rHref = nsRLink(r);
    const bt = nsBlurbText(r);
    const nm = esc(titleCase(r.operatingName));
    const blurb = bt ? `<a class="ns-gc-blurb" href="${esc(rHref)}">${esc(bt)}</a>` : '';
    const arr = ext ? '<span class="ext-arrow" aria-hidden="true">↗</span>' : '';
    const color = (CUISINE_META[k] && CUISINE_META[k].color) || CUISINE_PALETTE[k] || '#b06a2c';
    const emoji = EMOJI[k] || '🍴';
    return `<div class="ns-gc" data-slug="${esc(r.slug||'')}">`
      + `<a class="ns-gc-ico" href="${esc(rHref)}" style="background:${iconTint(color)};border-color:${color}33" aria-label="${nm} — full profile">${emoji}</a>`
      + `<div class="ns-gc-main">`
      + `<div class="ns-gc-top"><a class="ns-gc-name" href="${esc(href)}"${ext?' target="_blank" rel="noopener"':''}>${nm}${arr}</a>${nsChip(r)}</div>`
      + nsSubLine(r, lab, 'ns-gc-meta')
      + blurb
      + `</div></div>`;
  }
  // Scoped "new entrants" window. The all-Toronto homepage stays a strict
  // 30 days (it's always populated), but a single hood/cuisine often has
  // nothing in the last 30 days. When scoped, widen the window step-by-step
  // (30→90→180→365 days) until a few recent entrants surface, and relabel to
  // the real span — a North York spot from 3 months ago is still new to
  // someone who can't always pay attention. Keeps 30 days whenever the hood
  // does have a fresh-this-month entrant.
  const NS_SPAN = { 30: 'last 30 days', 90: 'last 3 months', 180: 'last 6 months', 365: 'last year' };
  function nsStreakWindow(rows, scoped) {
    const WINDOWS = scoped ? [30, 90, 180, 365] : [30];
    let win = 30, count = 0;
    for (let i = 0; i < WINDOWS.length; i++) {
      win = WINDOWS[i];
      count = rows.filter(r => typeof r.daysOpen === 'number' && r.daysOpen <= win).length;
      // Narrowest window that holds any entrant: keeps 30d when fresh, else
      // expands to the true span of the most recent newcomers (never overstates).
      if (count >= 1 || i === WINDOWS.length - 1) break;
    }
    return { win, count };
  }
  function nsStreak(rows, scopePrefix, scoped, freshOnly) {
    const { win, count } = nsStreakWindow(rows, scoped);
    const span = NS_SPAN[win];
    const total = rows.length;
    // Activity gauge: 5 dots lit by how active the window is. It's a heat meter
    // bound to the word ("Blazing"), NOT a fraction of the total beside it.
    const heat = count <= 1 ? 1 : count <= 3 ? 2 : count <= 6 ? 3 : count <= 10 ? 4 : 5;
    const heatWord = ['', 'Quiet', 'Warm', 'Toasty', 'Hot', 'Blazing'][heat];
    let pips = '';
    for (let i = 1; i <= 5; i++) pips += `<div class="ns-dot${i <= heat ? ' on' : ''}"></div>`;
    const lbl = win === 30 ? 'new this month' : `new · ${span}`;
    // Tappable only on the unscoped home view, and only when there's something
    // to drill into. Tapping filters the feed below to those entries.
    const tappable = !scoped && count > 0;
    const cta = !tappable ? ''
      : (freshOnly ? '<span class="ns-streak-cta">✕ show all</span>'
                   : `<span class="ns-streak-cta">view ${count} ›</span>`);
    return `<div class="ns-streak-bar${tappable ? ' ns-tappable' : ''}${freshOnly ? ' ns-active' : ''}"`
      + (tappable ? ` role="button" tabindex="0" aria-pressed="${!!freshOnly}" aria-label="Show the ${count} ${lbl}"` : '')
      + `><span class="ns-flame">🔥</span>`
      + `<div class="ns-streak-main"><div class="ns-count">${count}</div><div class="ns-label">${lbl}</div></div>`
      + `<div class="ns-heat" title="How active the ${span} are"><div class="ns-dots" aria-label="activity ${heat} of 5">${pips}</div><div class="ns-heat-word">${heatWord}</div></div>`
      + `<span class="ns-updated">${total} tracked</span>`
      + cta
      + `</div>`;
  }
  // Friendly layout: streak → 3 ranked hero cards → ranked list (with blurbs).
  function nsRenderHome() {
    const rows = currentRows;
    let scopeNoun = 'spots';
    if (currentCuisine !== '__all') scopeNoun = nsLabel(currentCuisine) + ' spots';
    const scopeWhere = (currentRegion !== '__all') ? ' in ' + currentRegion : '';
    const scoped = (currentCuisine !== '__all') || (currentRegion !== '__all') || (nearMeActive && userLatLng);
    feed.classList.add('ns-feed-wide');
    // Streak bar is a home-only flourish; on scoped views it's redundant. It
    // summarizes the FULL scope (count + "N tracked" total). freshOnly is a tap
    // drill-down that filters only the feed below — so the bar's total stays
    // honest even while the list shows just the new-this-month entries.
    let html = scoped ? '' : nsStreak(rows, `new ${scopeNoun}${scopeWhere}`, scoped, freshOnly);
    html += scoped ? '' : NS_FIRSTSEEN;
    const displayRows = (!scoped && freshOnly)
      ? rows.filter(r => typeof r.daysOpen === 'number' && r.daysOpen <= 30)
      : rows;
    // Tier 1 — freshest as big feature cards (this week if there are ≥2, else
    // the top 3 so the tier is never empty). Tier 2 — the rest as a responsive
    // compact grid. Recency is the organizing principle, not month dividers.
    const fresh = displayRows.filter(r => typeof r.daysOpen === 'number' && r.daysOpen <= 7);
    const featured = (fresh.length >= 2 ? fresh.slice(0, 4) : displayRows.slice(0, 3));
    const featSet = new Set(featured);
    const tierHead = freshOnly ? `${displayRows.length} new this month`
                               : (fresh.length >= 2 ? 'Just landed this week' : 'Newest');
    html += `<div class="ns-tier-head">${tierHead}</div>`;
    html += '<div class="ns-feature-grid">' + featured.map((r,i) => nsHeroCard(r, i+1)).join('') + '</div>';
    const rest = displayRows.filter(r => !featSet.has(r)).slice(0, currentShown);
    if (rest.length) {
      html += `<div class="ns-tier-head">More recent openings</div>`;
      html += '<div class="ns-grid">' + rest.map(r => nsGridCard(r)).join('') + '</div>';
    }
    feed.innerHTML = html;
    // Tap the heat bar → filter the feed to the new-this-month spots (toggle).
    const sbar = feed.querySelector('.ns-streak-bar.ns-tappable');
    if (sbar) {
      const toggle = () => { freshOnly = !freshOnly; currentShown = INITIAL_SHOW; nsRenderHome(); };
      sbar.addEventListener('click', toggle);
      sbar.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      });
    }
    const shownTotal = featured.length + rest.length;
    if (displayRows.length > shownTotal) {
      const remaining = displayRows.length - shownTotal;
      const more = document.createElement('button');
      more.className = 'show-more'; more.type = 'button';
      more.textContent = `Show ${Math.min(PAGE_SIZE, remaining)} more`;
      more.addEventListener('click', () => { currentShown += PAGE_SIZE; paintFeed(); });
      feed.appendChild(more);
    }
    feed.querySelectorAll('.ns-save-btn').forEach(btn => {
      btn.addEventListener('click', e => {
        e.preventDefault(); e.stopPropagation();
        const slug = btn.getAttribute('data-slug'); if (!slug) return;
        const nowSaved = toggleSaved(slug);
        btn.classList.toggle('saved', nowSaved);
        if (nowSaved) nsSparkle(btn);
        btn.textContent = nowSaved ? '♥ Saved' : '♡ Save';
        refreshSavedToggle();
      });
    });
    // Direct-out actions (Visit site ↗ / Map). Buttons, not <a>, so they can
    // live inside the card's /r/ anchor — open the target in a new tab.
    feed.querySelectorAll('.ns-act').forEach(b => {
      b.addEventListener('click', e => {
        e.preventDefault(); e.stopPropagation();
        if (b.dataset.url) window.open(b.dataset.url, '_blank', 'noopener');
      });
    });
  }
  function paintFeed() {
    feed.classList.remove('ns-feed-wide');
    feed.innerHTML = '';
    if (!currentRows.length) {
      // Filter-aware empty state. Composes "No newly registered <Cuisine>
      // restaurants <where>" from whichever filters are active. Vocab is
      // "registered restaurants" (per the City licence-data framing in
      // CLAUDE.md - the site knows registration date, not opening date,
      // and "licensed" implies LLBO/alcohol licensing in Ontario).
      const c = currentCuisine !== '__all'
        ? no.cuisines.find(x => x.key === currentCuisine)
        : null;
      const cuisineFrag = c ? `${c.label} ` : '';
      let whereFrag = ' in the last 365 days';
      if (nearMeActive && userLatLng) {
        whereFrag = ' near you';
      } else if (currentRegion !== '__all') {
        whereFrag = ` in ${currentRegion}`;
      }
      const emptyHead = '<div style="font:700 17px/1.3 var(--ui,system-ui,sans-serif);color:var(--ink);margin-bottom:6px;">Nothing here yet 🍽️</div>';
      let msg = emptyHead + `No newly registered ${cuisineFrag}restaurants${whereFrag} — yet. Try clearing the filter or browsing another neighbourhood.`;
      // Bare fallback when both filters are __all (homepage edge case).
      if (currentCuisine === '__all' && currentRegion === '__all' && !nearMeActive) {
        msg = emptyHead + 'No newly registered restaurants in the last 365 days.';
      }
      const empty = document.createElement('div');
      empty.className = 'empty';
      // Offer to clear whichever location filter is active (region OR near-me).
      let clearBtn = '';
      if (nearMeActive) {
        clearBtn = ' <button class="filter-clear" id="clear-region">Clear near-me filter</button>';
      } else if (currentRegion !== '__all') {
        clearBtn = ' <button class="filter-clear" id="clear-region">Clear region filter</button>';
      }
      empty.innerHTML = msg + clearBtn;
      feed.appendChild(empty);
      const clr = document.getElementById('clear-region');
      if (clr) clr.addEventListener('click', () => {
        if (nearMeActive) { nearMeActive = false; applyFilters(currentCuisine, currentRegion); }
        else applyFilters(currentCuisine, '__all');
      });
      return;
    }
    const visible = currentRows.slice(0, currentShown);
    // Date-grouped section headers — mirrors the server-side _date_bucket
    // logic in tools/inject_openings.py. Buckets: THIS WEEK (daysOpen<=7),
    // EARLIER THIS MONTH (current YYYY-MM, not this week), then prior months
    // by name + year. Headers emit between groups to give the feed a
    // chronological reading rhythm rather than a flat scroll.
    const MONTH_NAMES = ['','JANUARY','FEBRUARY','MARCH','APRIL','MAY','JUNE',
                         'JULY','AUGUST','SEPTEMBER','OCTOBER','NOVEMBER','DECEMBER'];
    const today = new Date();
    const refY = today.getFullYear(), refM = today.getMonth() + 1;
    const bucketOf = (r) => {
      const d = r.daysOpen;
      if (typeof d === 'number' && d <= 7) return 'THIS WEEK';
      const iso = r.issuedDate || '';
      if (iso.length >= 7) {
        const y = iso.slice(0, 4), m = parseInt(iso.slice(5, 7), 10);
        if (y === String(refY) && m === refM) return 'EARLIER THIS MONTH';
        if (m >= 1 && m <= 12) return `${MONTH_NAMES[m]} ${y}`;
      }
      return 'EARLIER';
    };
    // Pre-count entries per bucket across the FULL filtered set (not just
    // the currently-visible slice) so the header count is stable across
    // "Show more" interactions.
    const bucketCounts = {};
    currentRows.forEach(r => {
      const b = bucketOf(r);
      bucketCounts[b] = (bucketCounts[b] || 0) + 1;
    });
    let lastBucket = null;
    visible.forEach(r => {
      const b = bucketOf(r);
      if (b !== lastBucket) {
        const hdr = document.createElement('div');
        hdr.className = 'feed-section';
        hdr.setAttribute('aria-hidden', 'true');
        hdr.innerHTML = `<span class="fs-label">${b}</span><span class="fs-rule"></span><span class="fs-count">${bucketCounts[b]} new</span>`;
        feed.appendChild(hdr);
        lastBucket = b;
      }
      feed.appendChild(buildRowEl(r));
    });
    if (currentRows.length > currentShown) {
      const remaining = currentRows.length - currentShown;
      const more = document.createElement('button');
      more.className = 'show-more';
      more.type = 'button';
      more.textContent = `Show ${Math.min(PAGE_SIZE, remaining)} more`;
      more.addEventListener('click', () => {
        currentShown += PAGE_SIZE;
        paintFeed();
      });
      feed.appendChild(more);
    }
  }
  function renderFeed() {
    // Single-listing mode (/r/<slug>): the user arrived from a shared link
    // or X card - show ONLY that one entry, with a "Browse all" link at the
    // top so they can broaden to the full feed.
    if (singleSlug) {
      const target = no.recent.find(r => r.slug === singleSlug);
      currentRows = target ? [target] : [];
      currentShown = currentRows.length;
      paintFeed();
      return;
    }
    feed.classList.toggle('single-cuisine', currentCuisine !== '__all');
    let rows;
    if (currentCuisine === '__all') {
      rows = no.recent.slice();
    } else {
      // Multi-cuisine entries (e.g. Afghan + Pakistani + Indian) match each cuisine
      // they claim. Falls back to single `cuisine` for legacy entries.
      rows = no.recent.filter(r => (r.cuisines || [r.cuisine]).includes(currentCuisine));
      // pull in cuisine's full curated set (recent5 = top 10 per cuisine)
      const c = no.cuisines.find(x => x.key === currentCuisine);
      if (c && c.recent5) {
        const seen = new Set(rows.map(r => r.operatingName + '|' + r.issuedDate));
        c.recent5.forEach(r => { const k = r.operatingName+'|'+r.issuedDate; if (!seen.has(k)) { rows.push(r); seen.add(k); } });
        rows.sort((a,b)=> a.issuedDate < b.issuedDate ? 1 : -1);
      }
    }
    if (savedOnly) {
      const saved = getSaved();
      rows = rows.filter(r => saved.has(r.slug));
    }
    if (nearMeActive && userLatLng) {
      rows = rows.filter(r => r.lat && r.lng && haversineKm(userLatLng, [r.lat, r.lng]) <= nearMeRadius);
      // Near Me overrides the default freshest-first sort with closest-first.
      // Memoize the distance on the row so we don't haversine twice per row
      // (sort + later distance label rendering both want it).
      rows.forEach(r => { r._distKm = haversineKm(userLatLng, [r.lat, r.lng]); });
      rows.sort((a, b) => a._distKm - b._distKm);
    } else if (currentRegion !== '__all') {
      rows = rows.filter(r => r.district === currentRegion);
    }
    // Neighborhood (iconic corridor) filter compounds AFTER region — locks
    // the feed to entries whose lat/lng falls in the corridor polygon.
    // Stable across user picker interaction so the cuisine/region dropdowns
    // narrow further rather than escaping the corridor.
    if (currentNeighborhood) {
      rows = rows.filter(r => r.neighborhood && r.neighborhood.slug === currentNeighborhood);
    }
    currentRows = rows;
    currentShown = INITIAL_SHOW;
    paintFeed();
  }
  // Build the row set that would result from a given (cuisine, region, nearMe) tuple.
  // Mirrors the logic in renderFeed() so option counts agree with what the user sees.
  // When nearMe is true (and userLatLng is set), filters to entries within nearMeRadius
  // of the user - overriding the region argument since they're mutually exclusive.
  function rowsFor(cuisineKey, regionKey, nearMe) {
    let rows;
    if (cuisineKey === '__all') rows = no.recent.slice();
    else {
      // Multi-cuisine entries match each of their declared cuisines.
      rows = no.recent.filter(r => (r.cuisines || [r.cuisine]).includes(cuisineKey));
      const c = no.cuisines.find(x => x.key === cuisineKey);
      if (c && c.recent5) {
        const seen = new Set(rows.map(r => r.operatingName + '|' + r.issuedDate));
        c.recent5.forEach(r => { const k = r.operatingName+'|'+r.issuedDate; if (!seen.has(k)) { rows.push(r); seen.add(k); } });
      }
    }
    if (savedOnly) {
      const saved = getSaved();
      rows = rows.filter(r => saved.has(r.slug));
    }
    if (nearMe && userLatLng) {
      // Entries without coords can't be evaluated for proximity - exclude them.
      rows = rows.filter(r => r.lat && r.lng && haversineKm(userLatLng, [r.lat, r.lng]) <= nearMeRadius);
    } else if (regionKey !== '__all') {
      rows = rows.filter(r => r.district === regionKey);
    }
    if (currentNeighborhood) {
      rows = rows.filter(r => r.neighborhood && r.neighborhood.slug === currentNeighborhood);
    }
    return rows;
  }
  function updateOptionCounts() {
    // Region counts = entries that survive (currentCuisine, that-region, no near-me).
    // Region pickers are "if I picked this region" hypotheticals - distinct from near-me.
    rPanel.querySelectorAll('.cp-opt').forEach(o => {
      const ct = o.querySelector('.ct'); if (!ct) return;
      ct.textContent = rowsFor(currentCuisine, o.dataset.key, false).length;
    });
    // Cuisine counts = entries that survive (that-cuisine, currentRegion, currentNearMe).
    // Hide zero-count cuisines when a region/near-me filter is active so
    // the dropdown shows only what's actually available in the current
    // slice. The "All cuisines" entry is always visible.
    const cuisineFilterActive = currentRegion !== '__all' || nearMeActive;
    panel.querySelectorAll('.cp-opt').forEach(o => {
      const ct = o.querySelector('.ct'); if (!ct) return;
      const n = rowsFor(o.dataset.key, currentRegion, nearMeActive).length;
      ct.textContent = n;
      const isAll = o.classList.contains('cp-all');
      o.hidden = (cuisineFilterActive && n === 0 && !isAll);
    });
  }
  // The alert-form at the bottom of /cuisine/* and /district/* pages
  // morphs as the user narrows: a visitor on /cuisine/argentinian who
  // picks Scarborough sees the form flip to an "Argentine in Scarborough"
  // intersection signup without leaving the page. data-base-* on the
  // form is the page's "primary" identity (what it's about even when
  // unfiltered); data-kind/value/label is the live state the submit
  // handler POSTs. Homepage has no .alert-form, so this is a no-op there.
  function updateAlertForm(cuisineKey, regionKey) {
    const form = document.querySelector('form.alert-form');
    if (!form) return;
    const titleEl = document.getElementById('alert-title');
    const blurbEl = document.getElementById('alert-blurb');
    if (!titleEl || !blurbEl) return;
    const baseKind = form.dataset.baseKind;
    const baseValue = form.dataset.baseValue;
    const baseLabel = form.dataset.baseLabel;
    const cuisineActive = cuisineKey && cuisineKey !== '__all';
    const regionActive  = regionKey  && regionKey  !== '__all';
    let kind, value, label, title, blurb;
    if (baseKind === 'cuisine') {
      // /cuisine/<X> page - base is the cuisine, region narrows it
      if (regionActive) {
        kind = 'intersection';
        value = baseValue + '|' + districtSlug(regionKey);
        label = baseLabel + ' in ' + regionKey;
        title = 'Get an email when a new ' + baseLabel + ' restaurant opens in ' + regionKey;
        blurb = "You'll get one email the moment a new " + baseLabel + ' restaurant is registered with the City in ' + regionKey + " specifically. Rare - possibly a few times a year at most. No weekly digest, no spam, one-click unsub.";
      } else {
        kind = baseKind; value = baseValue; label = baseLabel;
        title = 'Get an email when a new ' + baseLabel + ' restaurant opens';
        blurb = "You'll get one email the moment a new " + baseLabel + " restaurant is registered with the City of Toronto - typically a handful of times per year. No weekly digest, no spam, one-click unsub.";
      }
    } else if (baseKind === 'district') {
      // /district/<Y> page - base is the district, cuisine narrows it
      if (cuisineActive) {
        const c = no.cuisines.find(x => x.key === cuisineKey);
        const cLabel = c ? c.label : cuisineKey;
        kind = 'intersection';
        value = cuisineKey + '|' + baseValue;
        label = cLabel + ' in ' + baseLabel;
        title = 'Get an email when a new ' + cLabel + ' restaurant opens in ' + baseLabel;
        blurb = "You'll get one email the moment a new " + cLabel + ' restaurant is registered with the City in ' + baseLabel + " specifically. Rare - possibly a few times a year at most. No weekly digest, no spam, one-click unsub.";
      } else {
        kind = baseKind; value = baseValue; label = baseLabel;
        title = 'Get an email when a new restaurant opens in ' + baseLabel;
        blurb = "You'll get one email the moment a new restaurant is registered with the City in " + baseLabel + ". No weekly digest, no spam, one-click unsub.";
      }
    } else {
      return; // unknown base kind - leave form alone
    }
    form.dataset.kind = kind;
    form.dataset.value = value;
    form.dataset.label = label;
    titleEl.textContent = title;
    blurbEl.textContent = blurb;
  }

  function applyFilters(cuisineKey, regionKey, updateHash=true) {
    currentCuisine = cuisineKey;
    currentRegion = regionKey;
    freshOnly = false;  // a scope change exits the heat-bar drill-down
    // Recompute counts for both dropdowns under the new filter state
    updateOptionCounts();
    // Update cuisine trigger - count reflects current region (or near-me) too
    const cuisineN = rowsFor(cuisineKey, regionKey, nearMeActive).length;
    const c = cuisineKey === '__all' ? null : no.cuisines.find(x => x.key === cuisineKey);
    trigger.textContent = c ? `${c.label} (${cuisineN})` : `All cuisines (${cuisineN})`;
    panel.querySelectorAll('.cp-opt').forEach(o => o.setAttribute('aria-selected', o.dataset.key === cuisineKey ? 'true' : 'false'));
    // Update region trigger - Near me overrides the region pick.
    // Near me overrides the region pick. Trigger shows just "Near me" - no
    // km value, because the dropdown only offers regions and a number in the
    // trigger misleads users into expecting a km picker inside.
    rTrigger.textContent = nearMeActive
      ? 'Near me'
      : (regionKey === '__all' ? 'All Toronto' : regionKey);
    rPanel.querySelectorAll('.cp-opt').forEach(o => o.setAttribute('aria-selected', !nearMeActive && o.dataset.key === regionKey ? 'true' : 'false'));
    renderFeed();
    renderMapPins();  // no-op if map hasn't been initialized yet
    updateAlertForm(cuisineKey, regionKey);
    if (updateHash) {
      const parts = [];
      if (cuisineKey !== '__all') parts.push('cuisine=' + cuisineKey);
      if (regionKey !== '__all') parts.push('region=' + encodeURIComponent(regionKey));
      const newHash = parts.length ? '#' + parts.join('&') : '';
      if (location.hash !== newHash) history.replaceState(null, '', location.pathname + location.search + newHash);
    }
  }
  // Initial filter state. Priority:
  //   1. URL hash (`#cuisine=X&region=Y`) - sticky across refreshes + share-links
  //   2. URL path (`/cuisine/X`) - SEO landing pages
  //   3. defaults
  const pathCuisineMatch  = location.pathname.match(/^\/cuisine\/([a-z_]+)(?:\.html)?\/?$/);
  // Cuisine × district intersection landing (e.g. /cuisine/colombian/west-toronto):
  // recognise it so the app hydrates with BOTH filters instead of falling through
  // to the all-Toronto feed (which read as a redirect to the homepage).
  const pathIntersectionMatch = location.pathname.match(/^\/cuisine\/([a-z_]+)\/([a-z-]+)(?:\.html)?\/?$/);
  const pathDistrictMatch = location.pathname.match(/^\/district\/([a-z-]+)(?:\.html)?\/?$/);
  const pathNeighborhoodMatch = location.pathname.match(/^\/neighborhood\/([a-z-]+)(?:\.html)?\/?$/);
  const pathListingMatch  = location.pathname.match(/^\/r\/([\w-]+)\/?$/);
  // Iconic-corridor URL → narrow JS hydration to entries with matching
  // `neighborhood.slug`. Without this, /neighborhood/agincourt renders
  // the all-Toronto feed on top of the server-rendered Agincourt-only
  // listings — visitors see Downtown restaurants on a page titled
  // "Agincourt". Pre-validated against the entry set so a stale URL
  // doesn't lock the view to an empty feed.
  if (pathNeighborhoodMatch) {
    const _candSlug = pathNeighborhoodMatch[1];
    if (no.recent.some(r => r.neighborhood && r.neighborhood.slug === _candSlug)) {
      currentNeighborhood = _candSlug;
    }
  }
  const hashCuisine = (location.hash.match(/cuisine=([a-z_]+)/) || [])[1];
  const hashRegion = (location.hash.match(/region=([^&]+)/) || [])[1];
  const cuisineFromUrl = hashCuisine || (pathCuisineMatch && pathCuisineMatch[1]) || (pathIntersectionMatch && pathIntersectionMatch[1]);
  const initialCuisine = (cuisineFromUrl && no.cuisines.some(c => c.key === cuisineFromUrl)) ? cuisineFromUrl : '__all';
  const decodedRegion = hashRegion ? decodeURIComponent(hashRegion) : '';
  // District-from-path: when visiting /district/scarborough directly (no hash),
  // resolve the slug back to the DISTRICTS label so the in-page filter syncs
  // with the URL. Without this, the JS hydrates with currentRegion='__all'
  // and re-renders ALL entries on top of the server-rendered district feed -
  // visitors see every Toronto restaurant on a page labeled "Scarborough".
  // Slug logic mirrors `districtSlug` defined later in this script.
  const _slugize = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const pathDistrictRegion = pathDistrictMatch
    ? (DISTRICTS.find(d => _slugize(d) === pathDistrictMatch[1]) || '')
    : (pathIntersectionMatch
        ? (DISTRICTS.find(d => _slugize(d) === pathIntersectionMatch[2]) || '')
        : '');
  const initialRegion = decodedRegion && DISTRICTS.includes(decodedRegion)
    ? decodedRegion
    : (pathDistrictRegion || '__all');
  applyFilters(initialCuisine, initialRegion, false);


  // Cuisine landing pages get a per-cuisine title + description for SEO. Done
  // post-render since the JS app boots from a single index.html in all cases.
  if (initialCuisine !== '__all' && pathCuisineMatch) {
    const c = no.cuisines.find(x => x.key === initialCuisine);
    if (c) {
      const n = c.count365d;
      const yr = new Date().getFullYear();
      const t = n === 1
        ? `Toronto's Newest ${c.label} Restaurant (${yr}) · NowServingTO`
        : `Toronto's ${n} Newest ${c.label} Restaurants (${yr}) · NowServingTO`;
      document.title = t;
      const desc = `Every newly registered ${c.label} restaurant in Toronto over the past 365 days, updated daily. ${n} entries tracked, ${c.count30d} from the last 30 days.`;
      const setMeta = (sel, attr, val) => {
        const el = document.querySelector(sel);
        if (el) el.setAttribute(attr, val);
      };
      setMeta('meta[name="description"]', 'content', desc);
      setMeta('meta[property="og:title"]', 'content', t);
      setMeta('meta[property="og:description"]', 'content', desc);
      setMeta('meta[name="twitter:title"]', 'content', t);
      setMeta('meta[name="twitter:description"]', 'content', desc);
      setMeta('link[rel="canonical"]', 'href', `https://nowservingto.com/cuisine/${c.key}`);
    }
  }

  // Per-listing share link `/r/{slug}` - single-listing mode. Show just
  // this entry, hide the filter row, and add a "Browse all restaurants"
  // link so the visitor can broaden when they're ready.
  if (pathListingMatch) {
    const slug = pathListingMatch[1];
    const target = no.recent.find(r => r.slug === slug);
    if (target) {
      singleSlug = slug;
      document.title = `${target.operatingName} - NowServingTO`;
      const link = document.querySelector('link[rel="canonical"]');
      if (link) link.setAttribute('href', `https://nowservingto.com/r/${slug}`);
      // Hide filter row (cuisine/region/near-me/saved/view) and inject a
      // single-listing banner with the "back to all" link.
      const filters = document.querySelector('.filters');
      if (filters) filters.style.display = 'none';
      const feedEl = document.getElementById('open-feed');
      if (feedEl && !document.getElementById('single-back')) {
        const back = document.createElement('a');
        back.id = 'single-back';
        back.href = '/';
        back.textContent = '← Browse all newly registered restaurants';
        back.style.cssText = 'display:inline-block;margin:12px 4px 18px;font:600 14px/1 var(--sans);color:var(--accent);text-decoration:none;';
        feedEl.parentNode.insertBefore(back, feedEl);
      }
      renderFeed();
    }
  }

  // Reusable dropdown toggle/close for both pickers. allPickers lets each picker
  // close the others on open - fixes the "both open at once" overlap bug since
  // stopPropagation on the trigger click prevents the document-level outside-click
  // from reaching the other picker's handler.
  const allPickers = [];
  function setupPicker(trig, pnl, onSelect) {
    const close = () => { if (!pnl.hidden) { pnl.hidden = true; trig.setAttribute('aria-expanded', 'false'); } };
    const open = () => {
      allPickers.forEach(p => { if (p.trig !== trig) p.close(); });
      pnl.hidden = false;
      trig.setAttribute('aria-expanded', 'true');
      const sel = pnl.querySelector('.cp-opt[aria-selected="true"]');
      if (sel) sel.scrollIntoView({block: 'nearest'});
    };
    trig.addEventListener('click', e => { e.stopPropagation(); pnl.hidden ? open() : close(); });
    pnl.addEventListener('click', e => {
      const opt = e.target.closest('.cp-opt'); if (!opt) return;
      e.preventDefault();  // suppress <a> default navigation; JS routes the pick
      onSelect(opt.dataset.key); close(); trig.focus();
    });
    document.addEventListener('click', e => { if (!pnl.hidden && !pnl.contains(e.target) && e.target !== trig) close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !pnl.hidden) { close(); trig.focus(); } });

    // Typeahead — letter key while picker is open jumps to the first option
    // whose label starts with that letter. Cycles through repeated presses
    // (type "I" twice → Indian → Indonesian → Iranian).
    let _typeIdx = -1;
    let _typeLastLetter = '';
    let _typeLastT = 0;
    function _onTypeahead(e) {
      if (pnl.hidden) return;
      if (e.key.length !== 1 || !/[a-zA-Z]/.test(e.key)) return;
      const letter = e.key.toLowerCase();
      const opts = [...pnl.querySelectorAll('.cp-opt:not(.cp-all)')];
      const matches = opts.filter(o =>
        (o.querySelector('.lbl')?.textContent || o.textContent).trim().toLowerCase().startsWith(letter));
      if (!matches.length) return;
      e.preventDefault();
      const now = Date.now();
      // Same letter pressed again within 1.5s → cycle to next match.
      if (letter === _typeLastLetter && now - _typeLastT < 1500) {
        _typeIdx = (_typeIdx + 1) % matches.length;
      } else {
        _typeIdx = 0;
      }
      _typeLastLetter = letter; _typeLastT = now;
      const target = matches[_typeIdx];
      target.scrollIntoView({block: 'nearest'});
      target.setAttribute('aria-current', 'true');
      // Clear the visual marker on other matches
      pnl.querySelectorAll('[aria-current="true"]').forEach(o => {
        if (o !== target) o.removeAttribute('aria-current');
      });
    }
    trig.addEventListener('keydown', _onTypeahead);
    pnl.addEventListener('keydown', _onTypeahead);
    const picker = { trig, pnl, close };
    allPickers.push(picker);
    return picker;
  }
  // District slug helper - mirrors tools/inject_openings.py _district_slug.
  // Used to navigate between /district/<slug> landing pages.
  const districtSlug = label => label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

  setupPicker(trigger, panel, key => {
    // Cuisine pick → navigate to the canonical landing page in most cases.
    // The cuisine landing page is richer than the homepage filter view
    // (cuisine-specific h1, FAQ, breadcrumb, JSON-LD CollectionPage,
    // and the by-district nav strip). Hash-filtering the homepage gave
    // visitors none of that. Two cases that still in-page filter:
    //   - "__all" picked while already on homepage: stay (already showing all)
    //   - Same cuisine picked while already on that cuisine page: no-op
    if (key === '__all') {
      if (pathCuisineMatch || pathDistrictMatch) {
        location.href = '/';
      } else {
        applyFilters(key, currentRegion);
      }
      return;
    }
    if (pathCuisineMatch && key === pathCuisineMatch[1]) {
      applyFilters(key, currentRegion);
      return;
    }
    // On a district landing page, picking a cuisine should DRILL DOWN
    // to the intersection ("Argentinian restaurants in Scarborough"),
    // not navigate away to /cuisine/X and drop the district context.
    // applyFilters handles both axes; the rich district landing remains.
    if (pathDistrictMatch) {
      applyFilters(key, currentRegion);
      return;
    }
    location.href = '/cuisine/' + key;
  });
  setupPicker(rTrigger, rPanel, key => {
    // Picking any region (including "All Toronto") turns Near me off - they're
    // mutually exclusive spatial filters.
    if (nearMeActive) {
      nearMeActive = false;
      document.getElementById('locate-btn').classList.remove('active');
      if (mapInstance && userMarker) mapInstance.removeLayer(userMarker);
    }
    // Region pick → navigate to the canonical /district/<slug> landing page
    // in most cases. The landing page is richer than the homepage filter
    // view (district-specific h1, FAQ, breadcrumb, JSON-LD, and the
    // by-cuisine nav strip). Two cases that still in-page filter:
    //   - "__all" picked while already on homepage: stay
    //   - Same district picked while already on that district page: no-op
    if (key === '__all') {
      if (pathCuisineMatch || pathDistrictMatch) {
        location.href = '/';
      } else {
        applyFilters(currentCuisine, key);
      }
      return;
    }
    if (pathDistrictMatch && districtSlug(key) === pathDistrictMatch[1]) {
      applyFilters(currentCuisine, key);
      return;
    }
    // On a cuisine landing page, picking a region should DRILL DOWN
    // to the intersection ("Argentine in Scarborough"), not navigate
    // away to /district/X and drop the cuisine context.
    if (pathCuisineMatch) {
      applyFilters(currentCuisine, key);
      return;
    }
    location.href = '/district/' + districtSlug(key);
  });

  // Brand-as-home: clicking NowServingTO always navigates to the
  // root, clearing any cuisine/district path AND any filter hash.
  // Using location.href = '/' (not location.reload) so we leave the
  // current per-cuisine/per-district page properly rather than just
  // refreshing it. assign() pushes history; current behavior matches
  // the user's "go home" intent.
  const brandLink = document.getElementById('brand-link');
  if (brandLink) {
    brandLink.addEventListener('click', e => {
      e.preventDefault();
      if (location.pathname === '/' && !location.hash && !location.search) {
        location.reload();  // already at root - refresh in place
      } else {
        location.href = '/';
      }
    });
  }


  // ---- MAP VIEW ----
  // Leaflet + markercluster. Lazy-inits on first toggle to Map view.
  // Pins drawn from currentRows (the filtered set) - re-renders on filter change
  // and on view toggle. Geolocation is user-initiated only.
  //
  // `var` (not `let`) so these hoist alongside their function decls. `renderMapPins`
  // gets called from applyFilters during initial hash-restore, BEFORE control flow
  // reaches this block - `let` would put these in TDZ and the call would throw.
  var mapInstance = null;
  var mapMarkers = null;
  var userMarker = null;
  var userLatLng = null;
  var mapInitialized = false;


  // 📱 Send to phone - show a QR code linking to Google Maps with the
  // destination pre-filled. Phone's camera scans → opens in its native Maps app
  // (Google on Android, Apple Maps via Safari handoff on iOS) with directions
  // ready. We let the phone provide its own current location as the origin -
  // more reliable than passing our (possibly browser-cached) lat/lng across.
  function sendToPhone(lat, lng, encodedName) {
    const name = decodeURIComponent(encodedName || '');
    const mapsUrl = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}` +
                    (name ? `&destination_place_id=&travelmode=walking` : '');
    if (typeof qrcode !== 'function') { alert('QR library still loading - try again in a moment.'); return; }
    const qr = qrcode(0, 'M');
    qr.addData(mapsUrl);
    qr.make();
    const imgTag = qr.createImgTag(6, 12);

    const modal = document.createElement('div');
    modal.className = 'phone-modal';
    modal.innerHTML = `
      <div class="pm-card" role="dialog" aria-label="Send to phone">
        <div class="pm-head">
          <span class="pm-title">📱 Open on your phone</span>
          <button class="pm-close" aria-label="Close">×</button>
        </div>
        <div class="pm-name">${name || 'Restaurant'}</div>
        <div class="pm-qr">${imgTag}</div>
        <div class="pm-hint">Scan with your phone's camera to open directions in Google Maps.</div>
        <div class="pm-url"><a href="${mapsUrl}" target="_blank" rel="noopener">${mapsUrl}</a></div>
      </div>`;
    const close = () => modal.remove();
    modal.querySelector('.pm-close').addEventListener('click', close);
    modal.addEventListener('click', e => { if (e.target === modal) close(); });
    document.body.appendChild(modal);
  }
  window.__nsSendToPhone = sendToPhone;
  // Near-me is a proximity-based spatial filter that REPLACES the region pick.
  // Once active, all counts/feed/pins constrain to entries within nearMeRadius km
  // of userLatLng. Selecting any region from the dropdown turns this off.
  var nearMeActive = false;
  var nearMeRadius = 5; // km - generous enough that one transit hop (TTC bus or
                         // streetcar from a typical neighbourhood) lands inside
                         // the radius, not just walking distance.

  function haversineKm(a, b) {
    const R = 6371, toRad = x => x * Math.PI / 180;
    const dLat = toRad(b[0] - a[0]), dLon = toRad(b[1] - a[1]);
    const A = Math.sin(dLat/2)**2 + Math.sin(dLon/2)**2 * Math.cos(toRad(a[0])) * Math.cos(toRad(b[0]));
    return 2 * R * Math.asin(Math.sqrt(A));
  }

  // Lazy-load Leaflet (CSS + JS + MarkerCluster) only when the Map view is
  // first activated. ~200KB of assets the vast majority of visitors never
  // need - eager-loading them cost ~700ms LCP for every page load (per
  // PageSpeed Insights). Returns a Promise that resolves once Leaflet is
  // ready to use; memoized so subsequent calls return the same Promise.
  let _leafletLoadPromise = null;
  function loadLeaflet() {
    if (_leafletLoadPromise) return _leafletLoadPromise;
    _leafletLoadPromise = new Promise((resolve, reject) => {
      // CSS files first - inject all three in parallel
      [
        'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
        'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css',
        'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css',
      ].forEach(href => {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        link.crossOrigin = '';
        document.head.appendChild(link);
      });
      // Leaflet JS, then MarkerCluster JS (must load after Leaflet's global L is defined)
      const leafletJs = document.createElement('script');
      leafletJs.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
      leafletJs.crossOrigin = '';
      leafletJs.onload = () => {
        const mcJs = document.createElement('script');
        mcJs.src = 'https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js';
        mcJs.onload = resolve;
        mcJs.onerror = reject;
        document.head.appendChild(mcJs);
      };
      leafletJs.onerror = reject;
      document.head.appendChild(leafletJs);
    });
    return _leafletLoadPromise;
  }
  // qrcode-generator is also only used by the map's directions-popup QR
  // (no map view → no QR usage). Load on demand.
  let _qrcodeLoadPromise = null;
  function loadQrcode() {
    if (_qrcodeLoadPromise) return _qrcodeLoadPromise;
    _qrcodeLoadPromise = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.js';
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
    return _qrcodeLoadPromise;
  }

  function initMap() {
    if (mapInitialized) return;
    if (typeof L === 'undefined') {
      document.getElementById('map').innerHTML = '<div style="padding:20px;color:#7a746a">Map library still loading - try again in a moment.</div>';
      return;
    }
    mapInstance = L.map('map', { preferCanvas: true }).setView([43.6532, -79.3832], 12);
    // CartoDB Voyager: full-color basemap (parks/water/streets look alive) but
    // strips most POI icons so our green pins are the only "where to eat" signal.
    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
      attribution: '© <a href="https://openstreetmap.org/copyright">OSM</a> · © <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(mapInstance);
    mapMarkers = L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 50 });
    mapInstance.addLayer(mapMarkers);
    mapInitialized = true;
    renderMapPins();
    // Frame to actually fit the current pins (downtown-centered default cuts off
    // West-Toronto/Parkdale and Scarborough). Cap zoom so a sparse set doesn't
    // over-zoom into a single block.
    const coords = currentRows.filter(r => r.lat && r.lng).map(r => [r.lat, r.lng]);
    if (coords.length >= 2) mapInstance.fitBounds(coords, { padding: [30, 30], maxZoom: 13 });
  }

  function renderMapPins() {
    if (!mapInitialized) return;
    mapMarkers.clearLayers();
    const rows = currentRows.filter(r => r.lat && r.lng);
    const PIN_COLOR = '#1a7340';  // var(--fresh) - same green as walking route
    // Permanent name labels are useful when there are few pins (e.g. filtered to
    // a small cuisine). Above ~25 they crowd the map and we let clicks reveal names.
    const showLabels = rows.length <= 25;
    rows.forEach(r => {
      const m = L.marker([r.lat, r.lng], {
        icon: L.divIcon({
          className: 'cuisine-pin',
          html: `<span style="background:${PIN_COLOR}"></span>`,
          iconSize: [28, 28],
          iconAnchor: [14, 14],
        }),
      });
      if (showLabels) {
        m.bindTooltip(r.operatingName, {
          permanent: true,
          direction: 'right',
          offset: [10, 0],
          className: 'pin-label',
        });
      }
      m.bindPopup(() => buildPopupHtml(r), { maxWidth: 280 });
      mapMarkers.addLayer(m);
    });
    const total = currentRows.length;
    const info = document.getElementById('map-info');
    if (info) {
      info.textContent = rows.length < total
        ? `${rows.length.toLocaleString()} of ${total.toLocaleString()} on map · rest geocoding (check back tomorrow)`
        : `${rows.length.toLocaleString()} on map`;
    }
  }

  function buildPopupHtml(r) {
    const keys = (r.cuisines && r.cuisines.length) ? r.cuisines : [r.cuisine];
    const cuisineLbl = keys.map(k => (CUISINE_META[k] && CUISINE_META[k].label) || CUISINE_LABEL[k] || k).join(' · ');
    const dist = userLatLng
      ? `<div class="pop-dist">${haversineKm(userLatLng, [r.lat, r.lng]).toFixed(1)} km away</div>`
      : '';
    const shareLink = r.slug
      ? `<button class="pop-share" onclick="window.__nsShare('${r.slug}', this)"><svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" aria-hidden="true" style="vertical-align:-2px;margin-right:4px"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/></svg>Share</button>`
      : '';
    // Always show route buttons. If location isn't granted yet, showRoute() will
    // prompt for it and auto-route once acquired.
    // On mobile, the user IS the phone - open Google Maps directly. On desktop,
    // show a QR for handoff to a separate phone.
    const onMobile = window.matchMedia('(max-width: 700px)').matches || ('ontouchstart' in window);
    const encName = encodeURIComponent(r.operatingName||'');
    // Single Directions button - opens Google Maps' Directions UI where the user
    // picks walk/drive/transit themselves. Cleaner than duplicating mode selection
    // here. On desktop, also offer 📱 To phone (QR for handoff).
    const dirBtn = onMobile
      ? `<button class="pop-btn" onclick="location.href='https://www.google.com/maps/dir/?api=1&destination=${r.lat},${r.lng}'">🗺️ Directions</button>`
      : `<button class="pop-btn" onclick="location.href='https://www.google.com/maps/dir/?api=1&destination=${r.lat},${r.lng}'">🗺️ Directions</button>
         <button class="pop-btn" onclick="window.__nsSendToPhone(${r.lat},${r.lng},'${encName}')">📱 To phone</button>`;
    const routeBtns = `<div class="pop-routes">${dirBtn}</div>`;
    return `
      <div class="pop-name">${r.operatingName}</div>
      <div class="pop-addr">${r.address || ''}${r.district ? ' · ' + r.district : ''}</div>
      <div class="pop-cuisine">${cuisineLbl}</div>
      ${dist}
      ${routeBtns}
      ${shareLink}`;
  }
  // Native share with full restaurant context. Web Share API opens the OS share
  // sheet on mobile (Messages, Email, WhatsApp, etc.) and on desktop in supporting
  // browsers. Falls back to clipboard copy on browsers without navigator.share.
  window.__nsShare = async (slug, btn) => {
    const r = no.recent.find(x => x.slug === slug);
    if (!r) return;
    const url = `https://nowservingto.com/r/${slug}`;
    const sKeys = (r.cuisines && r.cuisines.length) ? r.cuisines : [r.cuisine];
    const cuisineLbl = sKeys.map(k => (CUISINE_META[k] && CUISINE_META[k].label) || CUISINE_LABEL[k] || k).join(' · ');
    const ago = r.daysOpen <= 1 ? 'today'
              : r.daysOpen <= 60 ? `${r.daysOpen}d ago`
              : `${Math.round(r.daysOpen/30)}mo ago`;
    // "Downtown" alone reads awkwardly - pin it as "Downtown Toronto". Other
    // districts (Scarborough, Etobicoke, North York) are well-known on their own.
    const districtPhrase = r.district === 'Downtown' ? 'Downtown Toronto' : r.district;
    const where = r.address && districtPhrase
      ? ` at ${r.address} in ${districtPhrase}`
      : r.address ? ` at ${r.address}`
      : districtPhrase ? ` in ${districtPhrase}` : '';
    const text = `${r.operatingName} - newly-registered ${cuisineLbl} kitchen${where}. First seen ${ago}.`;
    if (navigator.share) {
      try { await navigator.share({ title: r.operatingName, text, url }); }
      catch (e) { /* user dismissed */ }
      return;
    }
    // Fallback: copy URL with the pitch text
    const fallback = text + '\n' + url;
    try {
      await navigator.clipboard.writeText(fallback);
      const orig = btn.textContent;
      btn.textContent = '✓ Copied';
      btn.disabled = true;
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 1500);
    } catch {
      prompt('Copy this link:', fallback);
    }
  };

  function setNearMeActive(on) {
    nearMeActive = on;
    const btn = document.getElementById('locate-btn');
    btn.classList.toggle('active', on);
    if (mapInstance && userMarker) {
      if (on) userMarker.addTo(mapInstance);
      else mapInstance.removeLayer(userMarker);
    }
    applyFilters(currentCuisine, '__all', true);
  }

  function locateUser() {
    // Already active? Treat the click as a toggle-off.
    if (nearMeActive) { setNearMeActive(false); return; }
    const btn = document.getElementById('locate-btn');
    const originalLabel = btn.textContent;
    btn.disabled = true;

    // Apply a fix and turn Near Me on. Used for cache hits, ipapi hits,
    // and (silent background) browser-geolocation upgrades.
    const applyFix = (latlng, persist) => {
      const wasActive = nearMeActive;
      userLatLng = latlng;
      if (mapInstance) {
        if (userMarker) mapInstance.removeLayer(userMarker);
        userMarker = L.marker(userLatLng, {
          icon: L.divIcon({ className: 'user-pin', html: '<span></span>', iconSize: [22, 22], iconAnchor: [11, 11] }),
          zIndexOffset: 1000,
        }).addTo(mapInstance);
        if (!wasActive) mapInstance.setView(userLatLng, 14);
      }
      if (persist) {
        try {
          localStorage.setItem('nsto.userLatLng', JSON.stringify({
            lat: latlng[0], lng: latlng[1], t: Date.now()
          }));
        } catch (_) {}
      }
      btn.textContent = originalLabel;
      btn.disabled = false;
      if (!wasActive) setNearMeActive(true);
      else applyFilters(currentCuisine, '__all', true);  // silent upgrade - refresh distances
    };

    // Stage 1: localStorage cache (30-min TTL). Re-clicks are instant.
    try {
      const cached = JSON.parse(localStorage.getItem('nsto.userLatLng') || 'null');
      if (cached && cached.t && Date.now() - cached.t < 30 * 60 * 1000
          && typeof cached.lat === 'number' && typeof cached.lng === 'number') {
        applyFix([cached.lat, cached.lng], false);
        return;
      }
    } catch (_) {}

    btn.textContent = 'locating…';

    // Stage 2: ipapi.co - free, ~200ms, city-level accuracy (~5-10km).
    // No permission prompt, no waiting. Plenty precise for the 5km Near
    // Me radius. Free tier: 1K req/day per IP, no key, HTTPS. Falls
    // through to browser geolocation only if ipapi fails.
    fetch('https://ipapi.co/json/', { credentials: 'omit' })
      .then(r => r.ok ? r.json() : Promise.reject(new Error('ipapi http ' + r.status)))
      .then(data => {
        if (typeof data.latitude !== 'number' || typeof data.longitude !== 'number') {
          throw new Error('ipapi returned no lat/lng');
        }
        applyFix([data.latitude, data.longitude], true);

        // Stage 3 (silent background): browser geolocation. If it returns
        // a more precise fix (GPS on mobile) replace the pin and refresh
        // distances. Skipped if the browser doesn't support it or denies.
        if (navigator.geolocation) {
          navigator.geolocation.getCurrentPosition(
            pos => applyFix([pos.coords.latitude, pos.coords.longitude], true),
            () => {},
            { enableHighAccuracy: false, timeout: 8000, maximumAge: 30 * 60 * 1000 }
          );
        }
      })
      .catch(() => {
        // ipapi unreachable - fall back to native geolocation.
        if (!navigator.geolocation) {
          btn.textContent = originalLabel;
          btn.disabled = false;
          alert('Could not get your location.');
          return;
        }
        const slowTimer = setTimeout(() => { if (btn.disabled) btn.textContent = 'still locating…'; }, 2500);
        navigator.geolocation.getCurrentPosition(pos => {
          clearTimeout(slowTimer);
          applyFix([pos.coords.latitude, pos.coords.longitude], true);
        }, err => {
          clearTimeout(slowTimer);
          btn.textContent = originalLabel;
          btn.disabled = false;
          const msg = err.code === 1 ? 'Permission denied - enable location in your browser to use this.'
                    : err.code === 2 ? 'Location unavailable right now.'
                    : err.code === 3 ? 'Timed out - try again.' : 'Could not get location.';
          alert(msg);
        }, { enableHighAccuracy: false, timeout: 8000, maximumAge: 30 * 60 * 1000 });
      });
  }

  function setView(v) {
    document.querySelectorAll('.view-toggle .vt-btn').forEach(x => {
      const active = x.dataset.view === v;
      x.classList.toggle('vt-active', active);
      x.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    const feed = document.getElementById('open-feed');
    const mapView = document.getElementById('map-view');
    if (v === 'map') {
      feed.hidden = true;
      mapView.hidden = false;
      if (!mapInitialized) {
        // Show a brief "loading…" state while Leaflet downloads on first
        // map-view toggle. Most visitors never reach this branch.
        const mapDiv = document.getElementById('map');
        mapDiv.innerHTML = '<div style="padding:20px;color:#7a746a">Loading map…</div>';
        loadLeaflet().then(() => {
          mapDiv.innerHTML = '';
          initMap();
          setTimeout(() => mapInstance && mapInstance.invalidateSize(), 60);
        }).catch(() => {
          mapDiv.innerHTML = '<div style="padding:20px;color:#7a746a">Map library failed to load. Refresh the page to retry.</div>';
        });
        // Also start loading qrcode lib in parallel - it's used inside
        // pin popups for the directions QR, so likely needed shortly.
        loadQrcode().catch(() => { /* QR is non-critical; fail silently */ });
      } else {
        renderMapPins();
        setTimeout(() => mapInstance && mapInstance.invalidateSize(), 60);
      }
    } else {
      feed.hidden = false;
      mapView.hidden = true;
    }
  }

  // View toggle wiring
  document.querySelectorAll('.view-toggle .vt-btn').forEach(b => {
    b.addEventListener('click', () => setView(b.dataset.view));
  });

  // 📍 Near me - visible in the filter row regardless of view. Locate-and-filter
  // works in both list and map view; no auto-switch.
  document.getElementById('locate-btn').addEventListener('click', locateUser);

  // ♡ Saved toggle - filters list + map to only saved entries
  refreshSavedToggle();
  document.getElementById('saved-toggle').addEventListener('click', () => {
    savedOnly = !savedOnly;
    refreshSavedToggle();
    renderFeed();
    renderMapPins();
  });

  // Row "white-space" tap → /r/<slug> profile page. The pic, name, and
  // address keep their existing destinations (Maps / website / Maps);
  // taps anywhere ELSE in the row navigate to the per-listing profile.
  // Delegated on #open-feed so it works after every renderFeed().
  document.getElementById('open-feed').addEventListener('click', (e) => {
    // Bail if the click landed on an interactive element - let its own
    // handler / href win.
    if (e.target.closest('a, button, input, textarea, select, label')) return;
    const row = e.target.closest('.ticket[data-slug]');
    if (!row) return;
    const slug = row.getAttribute('data-slug');
    if (slug) window.location.href = `/r/${slug}`;
  });

}).catch(err => {
  document.getElementById('open-feed').innerHTML = '<div class="empty">error loading data - ' + (err && err.message ? err.message : String(err)) + '</div>';
  console.error('NSTO load error:', err && err.stack ? err.stack : err);
});

// Per-cuisine + per-district real-time alert signup. The form's
// data-kind + data-value attributes are baked in by inject_openings.py
// when the page is generated; no extra JS bundle needed per page.
document.querySelectorAll('form.alert-form').forEach(function(form) {
  var status = form.querySelector('.alert-status');
  var btn = form.querySelector('button');
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    if (form.querySelector('input[name=website]').value) return; // honeypot
    var email = form.querySelector('input[type=email]').value.trim();
    if (!email) return;
    btn.disabled = true; btn.textContent = 'Subscribing…';
    status.className = 'alert-status'; status.textContent = '';
    fetch('/api/subscribe', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: email, kind: form.dataset.kind, value: form.dataset.value}),
    }).then(function(r) { return r.json().then(function(j) { return {ok: r.ok, j: j}; }); })
      .then(function(res) {
        if (res.ok) {
          var msg;
          if (form.dataset.kind === 'digest_all') {
            msg = 'Subscribed. Check your inbox for a welcome note. You\'ll get a Sunday digest of the week\'s newest restaurants - one email a week, never more.';
          } else if (form.dataset.kind === 'cuisine') {
            msg = 'Subscribed. Check your inbox for a welcome note. You\'ll only hear from us when a new ' + form.dataset.label + ' spot is registered with the City.';
          } else {
            msg = 'Subscribed. Check your inbox for a welcome note. You\'ll only hear from us when a new spot in ' + form.dataset.label + ' is registered with the City.';
          }
          form.innerHTML = '<div class="alert-status ok" style="margin:0">' + msg + '</div>';
        } else {
          btn.disabled = false; btn.textContent = 'Subscribe';
          status.className = 'alert-status err';
          status.textContent = (res.j && res.j.error) || 'Something went wrong. Try again?';
        }
      })
      .catch(function() {
        btn.disabled = false; btn.textContent = 'Subscribe';
        status.className = 'alert-status err';
        status.textContent = 'Network error. Try again?';
      });
  });
});

// Sticky header: pin the filter bar (+ a compact wordmark) once the masthead scrolls past.
(function () {
  let ticking = false;
  function upd() {
    const y = window.scrollY || document.documentElement.scrollTop || 0;
    document.body.classList.toggle('sticky-on', y > 120);
    ticking = false;
  }
  window.addEventListener('scroll', function () {
    if (!ticking) { ticking = true; requestAnimationFrame(upd); }
  }, { passive: true });
  upd();
})();
