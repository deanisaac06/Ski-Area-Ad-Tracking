/* Media viewer (zoom pictures, play saved Meta videos and YouTube videos), the ad archive (saved frames, every
   card/version, AI video notes, landing-page snapshots) and the winner score v2 breakdown.
   Loaded before app.js, which calls window.scoreBlock2() and window.mediaHook() from the ad drawer. */
(function(){
const css = `
dialog.mv{max-width:none;max-height:none;width:100vw;height:100vh;height:100dvh;margin:0;border:0;padding:52px 16px 16px;background:rgba(5,10,16,.94);color:#fff;box-sizing:border-box}
dialog.mv[open]{display:flex;align-items:center;justify-content:center}
dialog.mv::backdrop{background:rgba(5,10,16,.6)}
.mv .mvx{position:absolute;top:10px;right:12px;background:rgba(255,255,255,.16);color:#fff;border:0;border-radius:6px;padding:7px 12px;font-size:14px;cursor:pointer}
.mv .mvx:hover{background:rgba(255,255,255,.28)}
.mv .mvcap{position:absolute;top:16px;left:16px;right:330px;color:#cfd8e2;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mv .mvscroll{width:100%;height:100%;overflow:auto;display:flex;align-items:center;justify-content:center}
.mv .mvscroll img{max-width:100%;max-height:100%;object-fit:contain;cursor:zoom-in;border-radius:4px;background:#fff}
.mv .mvscroll.z{display:block;text-align:center}
.mv .mvscroll.z img{max-width:none;max-height:none;width:auto;cursor:zoom-out}
.mv video{max-width:100%;max-height:100%;border-radius:4px;background:#000;outline:none}
.mv iframe.yt{width:min(1100px,100%);aspect-ratio:16/9;max-height:100%;border:0;border-radius:4px;background:#000}
.mv .mvnav{position:absolute;top:10px;right:110px;display:flex;gap:8px}
.mv .mvnav a,.mv .mvnav button{background:rgba(255,255,255,.16);color:#fff;border:0;border-radius:6px;padding:6px 11px;font-size:13px;text-decoration:none;cursor:pointer}
.mv .mvnav a:hover,.mv .mvnav button:hover{background:rgba(255,255,255,.28)}
.dthumb.clk{cursor:zoom-in}
.dthumb.clk.vid{cursor:pointer}
.dthumb.clk:hover{outline:2px solid var(--accent);outline-offset:-2px}
.dthumb .play.big{width:56px;height:56px;background:rgba(0,0,0,.6)}
.dthumb .play.big::before{border-left-width:17px;border-top-width:11px;border-bottom-width:11px}
.dthumb .zhint{position:absolute;right:8px;bottom:8px;font-family:var(--mono);font-size:10px;background:rgba(0,0,0,.55);color:#fff;border-radius:4px;padding:1px 6px;pointer-events:none}
.mvbtns{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.conf{font-family:var(--mono);font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;border-radius:4px;padding:1px 6px;border:1px solid var(--line);color:var(--muted)}
.conf.High{color:var(--good);border-color:var(--good)}
.conf.Medium{color:var(--accent);border-color:var(--accent)}
.score .srow{grid-template-columns:minmax(0,1fr) 80px 86px}
.srow.bonus .sbar i{background:var(--gold)}
.sv small{white-space:nowrap}
.sctx{font-size:12.5px;color:var(--muted);margin:10px 0 0;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px 10px}
.arcsec p{margin:0 0 6px}
.strip{display:flex;gap:6px;overflow-x:auto;padding:2px 0 6px}
.strip img{height:96px;width:auto;flex:none;border-radius:4px;border:1px solid var(--line);cursor:zoom-in;background:#fff}
.strip img:hover{outline:2px solid var(--accent);outline-offset:-2px}
.vn{display:grid;grid-template-columns:120px minmax(0,1fr);gap:5px 12px;margin:8px 0;font-size:13.5px}
.vn dt{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;padding-top:2px}
.vn dd{margin:0}
.arcsec details{margin:6px 0;font-size:13.5px}
.arcsec summary{cursor:pointer;color:var(--accent)}
.arcsec ol{margin:6px 0 0;padding-left:20px}
.lpbox{display:grid;grid-template-columns:130px minmax(0,1fr);gap:12px;align-items:start}
.lpbox img{width:130px;height:170px;object-fit:cover;object-position:top;border:1px solid var(--line);border-radius:4px;cursor:zoom-in;background:#fff}
.lpbox pre{white-space:pre-wrap;font-family:inherit;font-size:12.5px;max-height:280px;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin:8px 0 0}
@media (max-width:480px){.score .srow{grid-template-columns:minmax(0,1fr) 70px}.vn{grid-template-columns:1fr}.lpbox{grid-template-columns:90px minmax(0,1fr)}.lpbox img{width:90px;height:120px}}
`;
const style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);
const esc = s => String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ytId = u => { const m = String(u||'').match(/(?:[?&]v=|youtu\.be\/|embed\/|shorts\/)([\w-]{11})/); return m ? m[1] : ''; };
const ytOf = a => a.p === 'google' ? (a.yt || ytId(a.video_src)) : '';

// ---------------------------------------------------------------- viewer
const mv = document.createElement('dialog');
mv.className = 'mv'; mv.setAttribute('aria-label', 'Media viewer');
document.body.appendChild(mv);
mv.addEventListener('click', e => { if (e.target === mv || e.target.classList.contains('mvscroll')) mv.close(); });
mv.addEventListener('close', () => { setTimeout(() => { if (!mv.open) { mv.innerHTML = ''; mv._nav = null; } }, 0); });
mv.addEventListener('keydown', e => {
  if (mv._nav && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) { e.preventDefault(); mv._nav(e.key === 'ArrowRight' ? 1 : -1); }
});
function show(html, cap, extra){
  mv._nav = null;
  mv.innerHTML = `<div class="mvcap">${esc(cap)}</div><button class="mvx" type="button">Close ✕</button>${html}${extra?`<div class="mvnav">${extra}</div>`:''}`;
  mv.querySelector('.mvx').onclick = () => mv.close();
  if (!mv.open) mv.showModal();
}
function zoomable(){
  const im = mv.querySelector('.mvscroll img'), sc = mv.querySelector('.mvscroll');
  if (im) im.addEventListener('click', e => { e.stopPropagation(); im.classList.toggle('z'); sc.classList.toggle('z'); });
}
function hasVideo(a){ return !!(a.vid || ytOf(a)); }
function frames(a){ return ((a.arc || {}).frames || []).map((s, i) => ({src: s, label: i ? `frame ${i}` : 'cover frame'})); }
function cardList(a){
  const c = (a.arc || {}).cards || [];
  return (a.img ? [{src: a.img_l || a.img, label: 'version 1'}] : []).concat(c.map((s, i) => ({src: s, label: `version ${i + (a.img ? 2 : 1)}`})));
}
function openImage(a){
  const src = a.img_l || a.img;
  show(`<div class="mvscroll"><img src="${esc(src)}" alt="Ad from ${esc(a.n)}"></div>`,
       `${a.n} · ${a.img_l ? 'full-size copy' : 'saved copy'} · click the picture to zoom`,
       hasVideo(a) ? `<button type="button" data-go="v">▶ Play video</button>` : '');
  zoomable();
  const b = mv.querySelector('[data-go="v"]'); if (b) b.onclick = () => openVideo(a);
}
function openGallery(list, i, cap){
  const n = list.length; if (!n) return;
  i = ((i % n) + n) % n;
  show(`<div class="mvscroll"><img src="${esc(list[i].src)}" alt="${esc(list[i].label)}"></div>`,
       `${cap} · ${list[i].label}${n > 1 ? ` (${i + 1} of ${n}, ← → to browse)` : ''} · click to zoom`,
       n > 1 ? `<button type="button" data-g="-1">‹ Prev</button><button type="button" data-g="1">Next ›</button>` : '');
  zoomable();
  mv.querySelectorAll('[data-g]').forEach(b => b.onclick = () => openGallery(list, i + Number(b.dataset.g), cap));
  if (n > 1) mv._nav = d => openGallery(list, i + d, cap);
}
function openVideo(a){
  const y = ytOf(a);
  if (a.vid) {
    show(`<video src="${esc(a.vid)}" controls autoplay playsinline preload="auto"${a.img?` poster="${esc(a.img)}"`:''}></video>`,
         `${a.n} · saved copy of the Meta video`,
         a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener">Meta Ad Library ↗</a>` : '');
  } else if (y) {
    const f = frames(a);
    show(`<iframe class="yt" src="https://www.youtube-nocookie.com/embed/${y}?autoplay=1&rel=0&modestbranding=1" title="YouTube video" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe>`,
         `${a.n} · YouTube`,
         (f.length ? `<button type="button" data-go="f">Saved frames</button>` : '') +
         `<a href="https://www.youtube.com/watch?v=${y}" target="_blank" rel="noopener">Open on YouTube ↗</a>`);
    const b = mv.querySelector('[data-go="f"]'); if (b) b.onclick = () => openGallery(f, 0, a.n + ' · saved frames');
  }
}
window.openAdMedia = (a, which) => (which === 'v' && hasVideo(a)) ? openVideo(a) : a.img ? openImage(a) : hasVideo(a) && openVideo(a);

// ---------------------------------------------------------------- archive section in the drawer
const NOTE_ROWS = [['hook', 'First 3 seconds'], ['voiceover', 'Voiceover'], ['onscreen', 'On screen'], ['offer', 'Offer'], ['music', 'Music']];
function archiveBlock(a){
  const r = a.arc || {}; let h = '';
  const nt = r.note;
  if (nt) h += `<div class="sec arcsec"><h3>What's in the video</h3>${nt.summary ? `<p>${esc(nt.summary)}</p>` : ''}` +
    `<dl class="vn">${NOTE_ROWS.filter(([k]) => nt[k]).map(([k, l]) => `<dt>${l}</dt><dd>${esc(nt[k])}</dd>`).join('')}${nt.len ? `<dt>Length</dt><dd>about ${nt.len}s</dd>` : ''}</dl>` +
    (nt.scenes && nt.scenes.length ? `<details><summary>Scene by scene (${nt.scenes.length})</summary><ol>${nt.scenes.map(s => `<li>${esc(s)}</li>`).join('')}</ol></details>` : '') +
    `<p class="note">Written by AI from the ${esc(nt.src || 'video')}${nt.d ? ' on ' + esc(nt.d) : ''}. Kept even if the video is taken down.</p></div>`;
  if (r.frames && r.frames.length) h += `<div class="sec arcsec"><h3>Saved frames</h3><div class="strip">${r.frames.map((s, i) => `<img src="${esc(s)}" alt="Frame ${i}" loading="lazy" data-gal="f" data-i="${i}">`).join('')}</div><p class="note">Still frames YouTube publishes for this video, saved in case it's removed.</p></div>`;
  if (r.cards && r.cards.length) { const all = cardList(a); h += `<div class="sec arcsec"><h3>All versions · ${all.length}</h3><div class="strip">${all.map((c, i) => `<img src="${esc(c.src)}" alt="${esc(c.label)}" loading="lazy" data-gal="c" data-i="${i}">`).join('')}</div><p class="note">Every card or version this ad ran, saved when the tracker first saw it.</p></div>`; }
  if (r.lp) { const u = r.lp.u || ''; h += `<div class="sec arcsec"><h3>Landing page · snapshot ${esc(r.lp.d)}</h3><div class="lpbox"><img src="${esc(r.lp.img)}" alt="Landing page snapshot" loading="lazy" data-gal="lp" data-i="0"><div style="min-width:0">${r.lp.t ? `<b>${esc(r.lp.t)}</b><br>` : ''}${u ? `<a href="${esc(u)}" target="_blank" rel="noopener" class="note">${esc(u.replace(/^https?:\/\//, '').slice(0, 70))} ↗</a>` : ''}<div class="mvbtns"><button class="btn" type="button" data-lptxt>Show page text</button></div><pre hidden></pre></div></div><p class="note">What the page looked like and said around when the tracker first saw this ad.</p></div>`; }
  return h;
}

// ---------------------------------------------------------------- drawer hook
window.mediaHook = function(a, d){
  const th = d.querySelector('.dthumb');
  const vid = hasVideo(a), img = !!a.img;
  if (th && vid) {
    th.querySelectorAll('.play').forEach(p => p.remove());
    th.insertAdjacentHTML('beforeend', '<span class="play big"></span>');
  }
  if (th && (vid || img)) {
    th.classList.add('clk'); if (vid) th.classList.add('vid');
    th.setAttribute('role', 'button'); th.tabIndex = 0;
    th.setAttribute('aria-label', vid ? 'Play video' : 'View larger');
    if (!vid) th.insertAdjacentHTML('beforeend', '<span class="zhint">🔍 view larger</span>');
    const go = () => vid ? openVideo(a) : openImage(a);
    th.addEventListener('click', go);
    th.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    const wrap = document.createElement('div');
    th.parentNode.insertBefore(wrap, th); wrap.appendChild(th);
    const btns = [];
    if (vid) btns.push(`<button class="btn" type="button" data-mv="v">▶ Play video</button>`);
    if (img) btns.push(`<button class="btn" type="button" data-mv="i">🔍 ${vid ? 'Poster' : 'View larger'}</button>`);
    if (frames(a).length) btns.push(`<button class="btn" type="button" data-mv="f">Saved frames</button>`);
    wrap.insertAdjacentHTML('beforeend', `<div class="mvbtns">${btns.join('')}</div>`);
    wrap.querySelectorAll('[data-mv]').forEach(b => b.onclick = () => b.dataset.mv === 'v' ? openVideo(a) : b.dataset.mv === 'f' ? openGallery(frames(a), 0, a.n + ' · saved frames') : openImage(a));
  }
  d.querySelectorAll('.dbody > p.note').forEach(p => {
    if (!/poster frame/.test(p.textContent)) return;
    if (a.vid) p.textContent = 'This video is saved as a small copy, so it keeps playing after the ad stops running.';
    else p.textContent = 'This video wasn’t saved (its Facebook link expired before the tracker reached it), so only the poster frame is shown. The Meta Ad Library link plays it while the ad is running.';
  });
  if (a.p === 'google' && a.kind === 'Video' && !vid) {
    const top = d.querySelector('.dtop');
    if (top) top.insertAdjacentHTML('afterend', `<p class="note">Google didn't share a YouTube link for this video, so it can't play here. ${a.url ? 'Google Ads Transparency plays it while it runs.' : ''}</p>`);
  }
  if (a.p === 'google' && vid) d.querySelectorAll('.dbody a.btn').forEach(x => { if (/Watch on YouTube/.test(x.textContent)) x.remove(); });
  const ah = archiveBlock(a);
  if (ah) {
    const box = document.createElement('div'); box.innerHTML = ah;
    const facts = d.querySelector('.dbody dl.facts'), body = d.querySelector('.dbody');
    [...box.children].forEach(n => facts ? facts.before(n) : body && body.appendChild(n));
    d.querySelectorAll('[data-gal]').forEach(im => im.addEventListener('click', () => {
      const g = im.dataset.gal, i = Number(im.dataset.i);
      if (g === 'f') openGallery(frames(a), i, a.n + ' · saved frames');
      else if (g === 'c') openGallery(cardList(a), i, a.n + ' · all versions');
      else openGallery([{src: a.arc.lp.img, label: 'landing page snapshot ' + a.arc.lp.d}], 0, a.n);
    }));
    const tb = d.querySelector('[data-lptxt]');
    if (tb) tb.onclick = () => {
      const pre = tb.closest('.lpbox').querySelector('pre');
      if (!pre.hidden) { pre.hidden = true; tb.textContent = 'Show page text'; return; }
      pre.hidden = false; tb.textContent = 'Hide page text';
      if (!pre.textContent) {
        pre.textContent = 'Loading…';
        fetch(a.arc.lp.txt).then(r => r.ok ? r.text() : Promise.reject()).then(t => { pre.textContent = t || '(no text on the page)'; })
          .catch(() => { pre.textContent = 'Couldn’t load the page text.'; });
      }
    };
  }
};

// ---------------------------------------------------------------- winner score v2
const LBL = {batch:'Outlasted its launch batch', run:'Run length vs this resort', invest:'Extra investment',
             steady:'Steady serving', reuse:'Reused creative', extend:'Extended offer'};
window.scoreBlock2 = function(a, h){
  const tier = h.tier, PN = h.PN;
  if (a.ws == null) return `<div class="sec score"><div class="schead"><h3>Winner score</h3><span class="ws early">Too early</span></div><p class="note">Launched under a week ago. Ads get a score after a week.</p></div>`;
  const head = `<span class="ws big ${tier(a.ws)}">${a.ws}</span><span class="note">of 100</span>` +
    (a.conf ? `<span class="conf ${a.conf}" title="How much evidence is behind this score">${a.conf} confidence</span>` : '') +
    (a.evergreen ? `<span class="conf" title="Shown for over a year (brand or always-on ad); capped at 70 so it doesn't crowd out campaign winners">Always-on</span>` : '');
  const rows = (a.sig || []).map(([k, v, w, t]) => {
    const bonus = k === 'reuse' || k === 'extend';
    return `<div class="srow${v == null ? ' pend' : ''}${bonus ? ' bonus' : ''}"><div class="sl"><b>${esc(LBL[k] || k)}${bonus ? ' <small class="note">bonus</small>' : ''}</b><span>${esc(t || 'Not enough data yet.')}</span></div>` +
      `<div class="sbar"><i style="width:${v == null ? 0 : v}%"></i></div><div class="sv">${v == null ? '—' : v}<small> /100 · ×${w}</small></div></div>`;
  }).join('');
  const r = (window.LIB.resorts.find(x => x.slug === a.slug) || {}).stats || {}, s = r[a.p];
  const ctx = s ? `<p class="sctx"><b>${esc(a.n)} on ${PN[a.p]}:</b> ${s.tier || '—'} ad volume vs other tracked resorts (${s.active} ads active in the last 120 days, new launches in ${s.weeks} of those weeks). ` +
    (s.kill != null ? `Switches off ${Math.round(s.kill * 100)}% of its ads within 3 weeks, so run length counts ${Math.round(s.info * 100)}% here. ` : `Not enough stopped ads yet to read its habits, so run length counts ${Math.round(s.info * 100)}%. `) +
    `Typical run ${s.med}d.</p>` : '';
  return `<div class="sec score"><div class="schead"><h3>Winner score</h3>${head}</div><div class="sgrid">${rows}</div>${ctx}` +
    `<p class="note" style="margin-top:6px">Each signal is scored 0–100 and weighted (×). Run length is weighted down at resorts that leave most ads running, since a big budget makes a long run cheap. Scores with few signals are pulled toward 50.</p></div>`;
};

// ---------------------------------------------------------------- help box
const hb = document.getElementById('helpbox');
if (hb) hb.innerHTML = `<b>Winner score (0–100).</b> Neither Meta nor Google shows spend or results, so the score reads what each resort reveals by how it treats an ad, adjusted for budget: big-budget resorts can leave everything running, so a long run means less there.
<ul>
<li><b>Outlasted its launch batch (×25).</b> Did it keep running after the resort switched off the other ads it launched the same week? Same resort, same budget, same moment, so it's the fairest test.</li>
<li><b>Run length vs this resort (×20, scaled).</b> Percentile against the resort's own ads of the same kind. Counts fully only at resorts that regularly switch ads off.</li>
<li><b>Extra investment (×20).</b> Several versions, dynamic creative, or versions added while it runs.</li>
<li><b>Steady serving (×10, Google).</b> Share of days in its run that Google actually showed it.</li>
<li><b>Bonuses:</b> reused creative (the same picture or copy relaunched later or used on the other platform, ×15) and extended offers (still running a week past its own deadline, ×10).</li>
</ul>
Each ad shows a confidence level. Confidence rises as the tracker sees ads stop: Meta history starts Nov 10, 2026, so Meta scores firm up over the coming weeks. Google ads shown for over a year are marked Always-on and capped at 70. Ads under a week old show “Too early.” Click any picture to view it larger, or the play button to watch the video.
<p style="margin-top:8px"><b>Archive.</b> Stopped ads stay here for good: pictures, every carousel card and version, Meta videos (small saved copies), YouTube frames, an AI write-up of each video (voiceover, on-screen text, offer, scenes; searchable) and a snapshot of the landing page.</p>`;
const H = window.LIB && window.LIB.health;
if (hb && H) hb.insertAdjacentHTML('beforeend', `<p class="note" style="margin-top:6px">Archive so far: ${H.videos} Meta videos saved${H.videos_missed ? ` (${H.videos_missed} missed, link expired first)` : ''} · ${H.notes} videos described · ${H.frames} YouTube ads with frames · ${H.cards} extra versions · ${H.pages} landing-page snapshots.</p>`);
})();
