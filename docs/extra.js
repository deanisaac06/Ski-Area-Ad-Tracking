/* Media viewer (zoom pictures, play saved Meta videos and YouTube videos) and the winner score v2 breakdown.
   Loaded before app.js, which calls window.scoreBlock2() and window.mediaHook() from the ad drawer. */
(function(){
const css = `
dialog.mv{max-width:none;max-height:none;width:100vw;height:100vh;height:100dvh;margin:0;border:0;padding:52px 16px 16px;background:rgba(5,10,16,.94);color:#fff;box-sizing:border-box}
dialog.mv[open]{display:flex;align-items:center;justify-content:center}
dialog.mv::backdrop{background:rgba(5,10,16,.6)}
.mv .mvx{position:absolute;top:10px;right:12px;background:rgba(255,255,255,.16);color:#fff;border:0;border-radius:6px;padding:7px 12px;font-size:14px;cursor:pointer}
.mv .mvx:hover{background:rgba(255,255,255,.28)}
.mv .mvcap{position:absolute;top:16px;left:16px;right:290px;color:#cfd8e2;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mv .mvscroll{width:100%;height:100%;overflow:auto;display:flex;align-items:center;justify-content:center}
.mv .mvscroll img{max-width:100%;max-height:100%;object-fit:contain;cursor:zoom-in;border-radius:4px;background:#fff}
.mv .mvscroll.z{display:block;text-align:center}
.mv .mvscroll.z img{max-width:none;max-height:none;width:auto;cursor:zoom-out}
.mv video{max-width:100%;max-height:100%;border-radius:4px;background:#000;outline:none}
.mv iframe.yt{width:min(1100px,100%);aspect-ratio:16/9;max-height:100%;border:0;border-radius:4px;background:#000}
.mv .mvnav{position:absolute;top:10px;right:110px;display:flex;gap:8px}
.mv .mvnav a,.mv .mvnav button{background:rgba(255,255,255,.16);color:#fff;border:0;border-radius:6px;padding:6px 11px;font-size:13px;text-decoration:none;cursor:pointer}
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
@media (max-width:480px){.score .srow{grid-template-columns:minmax(0,1fr) 70px}}
`;
const style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);
const esc = s => String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ytId = u => { const m = String(u||'').match(/(?:[?&]v=|youtu\.be\/|embed\/|shorts\/)([\w-]{11})/); return m ? m[1] : ''; };

// ---------------------------------------------------------------- viewer
const mv = document.createElement('dialog');
mv.className = 'mv'; mv.setAttribute('aria-label', 'Media viewer');
document.body.appendChild(mv);
mv.addEventListener('click', e => { if (e.target === mv || e.target.classList.contains('mvscroll')) mv.close(); });
mv.addEventListener('close', () => { setTimeout(() => { if (!mv.open) mv.innerHTML = ''; }, 0); });
function show(html, cap, extra){
  mv.innerHTML = `<div class="mvcap">${esc(cap)}</div><button class="mvx" type="button">Close ✕</button>${html}${extra?`<div class="mvnav">${extra}</div>`:''}`;
  mv.querySelector('.mvx').onclick = () => mv.close();
  if (!mv.open) mv.showModal();
}
function openImage(a){
  const src = a.img_l || a.img;
  show(`<div class="mvscroll"><img src="${esc(src)}" alt="Ad from ${esc(a.n)}"></div>`,
       `${a.n} · ${a.img_l ? 'full-size copy' : 'saved copy'} · click the picture to zoom`,
       hasVideo(a) ? `<button type="button" data-go="v">▶ Play video</button>` : '');
  const im = mv.querySelector('.mvscroll img'), sc = mv.querySelector('.mvscroll');
  im.addEventListener('click', e => { e.stopPropagation(); im.classList.toggle('z'); sc.classList.toggle('z'); });
  const b = mv.querySelector('[data-go="v"]'); if (b) b.onclick = () => openVideo(a);
}
function hasVideo(a){ return !!(a.vid || (a.p === 'google' && ytId(a.video_src))); }
function openVideo(a){
  const y = a.p === 'google' ? ytId(a.video_src) : '';
  if (a.vid) {
    show(`<video src="${esc(a.vid)}" controls autoplay playsinline preload="auto"${a.img?` poster="${esc(a.img)}"`:''}></video>`,
         `${a.n} · saved copy of the Meta video`,
         a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener">Meta Ad Library ↗</a>` : '');
  } else if (y) {
    show(`<iframe class="yt" src="https://www.youtube-nocookie.com/embed/${y}?autoplay=1&rel=0&modestbranding=1" title="YouTube video" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe>`,
         `${a.n} · YouTube`,
         `<a href="https://www.youtube.com/watch?v=${y}" target="_blank" rel="noopener">Open on YouTube ↗</a>`);
  }
}
window.openAdMedia = (a, which) => (which === 'v' && hasVideo(a)) ? openVideo(a) : a.img ? openImage(a) : hasVideo(a) && openVideo(a);

// ---------------------------------------------------------------- drawer hook
window.mediaHook = function(a, d){
  const th = d.querySelector('.dthumb'); if (!th) return;
  const vid = hasVideo(a), img = !!a.img;
  if (vid) {
    th.querySelectorAll('.play').forEach(p => p.remove());
    th.insertAdjacentHTML('beforeend', '<span class="play big"></span>');
  }
  if (vid || img) {
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
    wrap.insertAdjacentHTML('beforeend', `<div class="mvbtns">${btns.join('')}</div>`);
    wrap.querySelectorAll('[data-mv]').forEach(b => b.onclick = () => b.dataset.mv === 'v' ? openVideo(a) : openImage(a));
  }
  d.querySelectorAll('.dbody > p.note').forEach(p => {
    if (!/poster frame/.test(p.textContent)) return;
    if (a.vid) p.textContent = 'This video is saved as a small copy, so it keeps playing after the ad stops running.';
    else p.textContent = 'This video wasn’t saved (its Facebook link expired before the tracker reached it), so only the poster frame is shown. The Meta Ad Library link plays it while the ad is running.';
  });
  if (a.p === 'google' && vid) d.querySelectorAll('.dbody a.btn').forEach(x => { if (/Watch on YouTube/.test(x.textContent)) x.remove(); });
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
Each ad shows a confidence level. Confidence rises as the tracker sees ads stop: Meta history starts Nov 10, 2026, so Meta scores firm up over the coming weeks. Google ads shown for over a year are marked Always-on and capped at 70. Ads under a week old show “Too early.” Click any picture to view it larger, or the play button to watch the video.`;
})();
