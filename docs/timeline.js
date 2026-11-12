/* Resort timeline: a zoomable, scrollable flight chart. One bar per ad, from its start date to its end date (or
   today if still active), in lanes by campaign. Ads launched within 10 days of each other in the same lane form a
   launch wave (a flight); click a wave's label to zoom into it. Pinch / Ctrl+scroll zooms, drag pans.
   app.js calls window.TLX.mount(el, ads, opts) whenever the resort page is drawn; view state survives re-draws. */
(function(){
const css = `
.tlx{display:grid;gap:8px;min-width:0}
.tl-tools{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center}
.tl-tools .seg button{padding:4px 9px}
.tl-tools .ctl select{padding:3px 6px}
.tl-hint{font-size:11.5px;color:var(--muted)}
.tl-count{font-size:12px;color:var(--muted);margin-left:auto}
.tl-count b{color:var(--ink)}
.tl-vp{position:relative;overflow:auto;max-height:min(560px,72vh);touch-action:pan-x pan-y;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:6px;background:var(--surface);overscroll-behavior-x:contain;cursor:grab}
.tl-vp.drag{cursor:grabbing;user-select:none}
.tl-c{position:relative}
.tl-grid{position:absolute;top:0;bottom:0;pointer-events:none;z-index:0}
.tl-grid i{position:absolute;top:0;bottom:0;width:1px;background:var(--line)}
.tl-grid i.gw{opacity:.45}
.tl-grid i.gy{background:var(--muted);opacity:.6}
.tl-grid i.gt{background:#E0485A;width:2px;z-index:1}
.tl-ax{position:sticky;top:0;z-index:4;display:flex;height:38px;background:var(--surface);border-bottom:1px solid var(--line)}
.tl-corner{position:sticky;left:0;z-index:5;flex:none;background:var(--surface);border-right:1px solid var(--line);font-family:var(--mono);font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;padding:4px 8px;display:flex;align-items:flex-end}
.tl-axt{position:relative;flex:none}
.tl-axt span{position:absolute;font-family:var(--mono);color:var(--muted);white-space:nowrap;padding-left:4px;border-left:1px solid var(--line);line-height:14px}
.tl-axt span.m{top:3px;font-size:11px;color:var(--ink);font-weight:500}
.tl-axt span.w{top:20px;font-size:9.5px}
.tl-axt span.td{top:20px;font-size:9.5px;color:#E0485A;border-left:2px solid #E0485A;font-weight:600;background:var(--surface);z-index:1}
.tl-lane{display:flex;position:relative;z-index:1;border-bottom:1px solid var(--line)}
.tl-lab{position:sticky;left:0;z-index:3;flex:none;background:var(--surface);border:0;border-right:1px solid var(--line);padding:6px 8px;font-size:12.5px;cursor:pointer;display:flex;gap:6px;align-items:flex-start;text-align:left;color:var(--ink);line-height:1.25}
.tl-lab:hover{background:var(--hover)}
.tl-lab.sel{box-shadow:inset 3px 0 0 var(--accent);background:var(--accent-soft)}
.tl-lab .dot{margin-top:4px}
.tl-lab small{display:block;font-family:var(--mono);font-size:10.5px;color:var(--muted)}
.tl-trk{position:relative;flex:none}
.tb{position:absolute;border:0;padding:0;border-radius:3px;background-color:var(--c);cursor:pointer;overflow:hidden;display:flex;align-items:center;gap:5px;color:#fff;font-size:11px;white-space:nowrap;text-align:left;transition:opacity .12s,box-shadow .12s}
.tb.g{background-image:repeating-linear-gradient(135deg,rgba(255,255,255,.34) 0 3px,transparent 3px 7px)}
.tb.live::after{content:"";position:absolute;right:0;top:0;bottom:0;width:8px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.8))}
.tb:hover,.tb:focus-visible{box-shadow:0 0 0 2px var(--ink);z-index:2;outline:0}
.tb img{height:100%;aspect-ratio:1;object-fit:cover;flex:none;background:#fff}
.tb span{overflow:hidden;text-overflow:ellipsis;padding:0 8px 0 4px;text-shadow:0 1px 2px rgba(0,0,0,.5)}
.tw{position:absolute;top:3px;height:15px;border:0;border-radius:3px;background:color-mix(in srgb,var(--c) 22%,transparent);border-left:2px solid var(--c);font-family:var(--mono);font-size:10px;color:var(--ink);padding:0 5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:zoom-in;text-align:left;line-height:15px}
.tw:hover,.tw.hl{background:color-mix(in srgb,var(--c) 45%,transparent)}
.tl-c.dim .tb:not(.hl){opacity:.14}
.tl-c.dim .tw:not(.hl){opacity:.3}
.tl-c.dim .tb.hl{box-shadow:0 0 0 1.5px var(--ink)}
.tl-leg{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--muted);align-items:center}
.tl-leg i{display:inline-block;width:18px;height:9px;border-radius:2px;vertical-align:-1px;margin-right:5px}
.tl-leg i.g{background-image:repeating-linear-gradient(135deg,rgba(255,255,255,.45) 0 3px,transparent 3px 7px)}
.tl-tip{position:fixed;z-index:60;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.28);padding:8px 10px;font-size:12.5px;width:290px;display:grid;grid-template-columns:auto minmax(0,1fr);gap:3px 10px;align-items:start}
.tl-tip img{width:64px;height:64px;object-fit:cover;border-radius:4px;grid-row:span 4;background:#fff}
.tl-tip b{font-weight:600}
.tl-tip .note{font-size:11.5px}
.tb.x{background:repeating-linear-gradient(135deg,var(--sunken) 0 4px,transparent 4px 8px)!important;outline:1px dashed var(--muted);outline-offset:-1px;color:var(--muted)}
.tl-c{transform-origin:0 0}
.tb.od{border-radius:50%;box-shadow:0 0 0 1.5px var(--surface);transition:opacity .12s,box-shadow .12s,transform .12s}
.tb.od::after{display:none}
.tb.od.g{background-image:none;box-shadow:inset 0 0 0 2px var(--ink),0 0 0 1px var(--surface)}
.tb.od:hover,.tb.od:focus-visible{box-shadow:0 0 0 2px var(--ink);transform:scale(1.4);z-index:3}
.tb.od img{width:100%;height:100%;border-radius:50%}
.orun{position:absolute;bottom:3px;height:5px;border-radius:3px;pointer-events:none;opacity:.9}
.oc{position:absolute;font-family:var(--mono);font-size:10px;color:var(--muted);transform:translateX(-50%);pointer-events:none}
@media (max-width:600px){.tl-count{margin-left:0;width:100%}.tl-tools{gap:6px 8px}}
`;
const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
const esc = s => String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const DAY = 864e5, t = d => Math.floor(Date.parse(d+'T00:00:00Z')/DAY), ds = n => new Date(n*DAY).toISOString().slice(0,10);
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const md = n => { const d = ds(n); return MON[+d.slice(5,7)-1]+' '+(+d.slice(8)); };
const mdy = n => { const d = ds(n); return md(n)+', '+d.slice(0,4); };
const PLC = {meta:'#3B7DD8', google:'#2E9B5F'};
const FMC = {Video:'#D9622B', Static:'#2F6FB5', Carousel:'#8B5CF6', Dynamic:'#0E9F9A', Text:'#6B7A8A'};
const FNC = {Awareness:'#7A5CC2', Consideration:'#2A9BA0', Conversion:'#D9622B'};
const MINP = 0.25, MAXP = 60, WAVE_GAP = 10;
const S = {};
let TIP = null;
let MODE = 'bars'; try { MODE = localStorage.getItem('ral-tlmode') || 'bars'; } catch (_) {}
function tip(){ if (!TIP) { TIP = document.createElement('div'); TIP.className = 'tl-tip'; TIP.hidden = true; document.body.appendChild(TIP); } return TIP; }

function mount(el, ads, o){
  if (!el) return;
  const s = S[o.key] || (S[o.key] = {ppd: null, day: null, color: 'camp'});
  const today = t(o.today);
  const items = ads.filter(a => a.start).map(a => {
    const a0 = t(a.start); let a1 = a.live ? today : t(a.end || a.last_shown || a.start); if (a1 < a0) a1 = a0;
    return {a, s: a0, e: a1, lane: (o.selCamp && a.camp.includes(o.selCamp)) ? o.selCamp : a.camp[0]};
  });
  if (!items.length) { el.innerHTML = '<p class="note">No ads match the current filters, so the timeline is empty. Try “All campaigns” or a wider date range.</p>'; return; }
  const byKey = Object.fromEntries(items.map(i => [i.a.key, i]));
  const min = Math.min(...items.map(i => i.s)) - 4, max = today + 12;
  const order = o.camps.concat(['Unknown']);
  const lanes = [...new Set(items.map(i => i.lane))].sort((x, y) => order.indexOf(x) - order.indexOf(y)).map((c, li) => {
    const L = items.filter(i => i.lane === c).sort((p, q) => p.s - q.s || q.e - p.e);
    const rows = [];
    L.forEach(i => { let r = rows.findIndex(end => end < i.s - 1); if (r < 0) { r = rows.length; rows.push(0); } rows[r] = i.e; i.row = r; });
    const waves = [];
    L.forEach(i => {
      const w = waves[waves.length - 1];
      if (w && i.s - w.last <= WAVE_GAP) { w.last = i.s; w.end = Math.max(w.end, i.e); w.n++; w.items.push(i); }
      else waves.push({s: i.s, last: i.s, end: i.e, n: 1, items: [i]});
      i.w = li + '-' + (waves.length - 1);
    });
    return {c, items: L, rows: rows.length, waves};
  });
  const LABEL = el.clientWidth < 600 ? 104 : 156;
  el.innerHTML = `<div class="tlx">
<div class="tl-tools">
<div class="seg" aria-label="Zoom"><button type="button" data-z="0.5" title="Zoom out">−</button><button type="button" data-z="2" title="Zoom in">+</button></div>
<div class="seg" aria-label="Range"><button type="button" data-r="all">All</button><button type="button" data-r="365">1 yr</button><button type="button" data-r="season">Season</button><button type="button" data-r="90">90 days</button><button type="button" data-r="30">30 days</button></div>
<div class="seg" aria-label="Timeline view"><button type="button" data-m="ov" aria-pressed="${MODE === 'ov'}" title="Broad view: one dot per ad at its launch date">Overview</button><button type="button" data-m="bars" aria-pressed="${MODE !== 'ov'}" title="Granular view: one bar per ad from start to end date">Detailed</button></div>
<label class="ctl">Color by <select class="tl-col"><option value="camp">Campaign</option><option value="plat">Platform</option><option value="fmt">Format</option><option value="obj">Funnel stage</option></select></label>
<span class="tl-count"><b>${items.length}</b> ads${o.total && o.total !== items.length ? ` of ${o.total} (filters applied)` : ''}</span>
</div>
<div class="tl-vp" tabindex="0" aria-label="Ad timeline. Use + and − to zoom, arrow keys to scroll."><div class="tl-c"></div></div>
<div class="tl-leg"></div>
<div class="tl-hint">${MODE === 'ov' ? 'Overview: one dot per ad at its launch date, stacked when several launch close together (numbers show how many). Hover a dot to preview the ad and see a line for how long it ran; click to open it. Pinch or Ctrl+scroll to zoom, drag or Shift+scroll to move, or pick a range above. Switch to Detailed for one bar per ad.' : `Each bar is one ad, from start to end date; a light fade at the end means it's still running. Labels above the bars are launch waves (flights): click one to zoom in. Pinch or Ctrl+scroll to zoom, drag or Shift+scroll to move, click a bar to open the ad, click a campaign name to filter.`}</div>
</div>`;
  const vp = el.querySelector('.tl-vp'), C = el.querySelector('.tl-c'), sel = el.querySelector('.tl-col');
  sel.value = s.color;
  const vw = () => Math.max(200, vp.clientWidth - LABEL - 2);
  const clamp = p => Math.min(MAXP, Math.max(MINP, p));
  if (s.ppd == null) {
    const span = Math.min(max - min, MODE === 'ov' ? 365 : 200);
    s.ppd = clamp(vw() / span); s.day = max - span;
  }
  const color = i => s.color === 'obj' ? (FNC[i.a.obj] || '#8895A3') : s.color === 'plat' ? PLC[i.a.p] : s.color === 'fmt' ? (FMC[i.a.kind] || '#888') : (o.CC[i.lane] || '#8895A3');

  function draw(){
    const p = s.ppd, W = Math.ceil((max - min) * p), x = n => (n - min) * p;
    const rich = p >= 5, rowH = rich ? 26 : 9, gap = rich ? 4 : 3, head = 21;
    let grid = '', ax = '';
    const monthPx = 30.4 * p, every = monthPx >= 46 ? 1 : monthPx >= 22 ? 2 : monthPx >= 11 ? 3 : 6;
    let d = new Date(ds(min).slice(0, 8) + '01T00:00:00Z');
    while (d.getTime() / DAY <= max) {
      const n = Math.round(d.getTime() / DAY), m = d.getUTCMonth(), X = x(n);
      if (X >= 0) {
        grid += `<i class="${m === 0 ? 'gy' : ''}" style="left:${X}px"></i>`;
        if (m % every === 0) ax += `<span class="m" style="left:${X}px">${MON[m]}${m === 0 || every >= 3 || p >= 2 ? ' ' + d.getUTCFullYear() : ''}</span>`;
      }
      d.setUTCMonth(m + 1);
    }
    if (p >= 2.2) {
      let n = min + ((4 - ((min % 7) + 7) % 7) + 7) % 7;  // first Monday (day 0 = Thursday)
      const lab = p * 7 >= 44;
      for (; n <= max; n += 7) { grid += `<i class="gw" style="left:${x(n)}px"></i>`; if (lab) ax += `<span class="w" style="left:${x(n)}px">${md(n)}</span>`; }
      if (p >= 26) for (let k = min; k <= max; k++) if ((((k % 7) + 7) % 7) !== 4) ax += `<span class="w" style="left:${x(k)}px;border-left-color:transparent">${+ds(k).slice(8)}</span>`;
    }
    grid += `<i class="gt" style="left:${x(today)}px"></i>`;
    ax += `<span class="td" style="left:${x(today)}px">Today</span>`;
    // Overview: the broad launch chart. One dot per ad at its launch date, stacked when launches land close together.
if (MODE === 'ov') {
const D = p >= 10 ? 22 : p >= 3 ? 12 : 8, bd = Math.max(1, Math.ceil((D + 2) / p)), cols = {};
let mx = 1;
[...items].sort((a, b) => a.s - b.s || (a.a.p < b.a.p ? -1 : 1)).forEach(i => { i.k = Math.floor((i.s - min) / bd); i.h = cols[i.k] = (cols[i.k] || 0) + 1; if (i.h > mx) mx = i.h; });
const step = Math.max(3, Math.min(D + 2, 240 / mx)), H = Math.max(110, Math.ceil(D + 30 + (mx - 1) * step)), by = H - D - 10, cx = k => x(min + k * bd) + bd * p / 2;
const dots = items.map(i => { const a = i.a; return `<button type="button" class="tb od${a.gone ? ' x' : ''}${a.p === 'google' ? ' g' : ''}" data-id="${esc(a.key)}" data-w="${i.w}" style="left:${cx(i.k) - D / 2}px;top:${by - (i.h - 1) * step}px;width:${D}px;height:${D}px;--c:${color(i)}" aria-label="${esc(o.PN[a.p] + ' ' + a.kind + ', launched ' + mdy(i.s))}">${D >= 22 && a.img && !a.gone ? `<img src="${esc(a.img)}" alt="" loading="lazy">` : ''}</button>`; }).join('');
const cnt = Object.entries(cols).filter(e => e[1] >= 3).map(([k, n]) => `<span class="oc" style="left:${cx(+k)}px;top:${by - (n - 1) * step - 14}px">${n}</span>`).join('');
C.style.width = (LABEL + W) + 'px';
C.innerHTML = `<div class="tl-grid" style="left:${LABEL}px;width:${W}px">${grid}</div><div class="tl-ax" style="width:${LABEL + W}px"><div class="tl-corner" style="width:${LABEL}px">Launches</div><div class="tl-axt" style="width:${W}px">${ax}</div></div><div class="tl-lane" style="height:${H}px;width:${LABEL + W}px"><div class="tl-lab" style="width:${LABEL}px;cursor:default"><span>${esc(o.selCamp || 'All campaigns')}<small>${items.length} ${items.length === 1 ? 'ad' : 'ads'}</small></span></div><div class="tl-trk" style="width:${W}px;height:${H}px"><i class="orun" hidden></i>${cnt}${dots}</div></div>`;
vp.scrollLeft = (s.day - min) * p;
legend();
return;
}
const lanesHtml = lanes.map((L, li) => {
      const h = head + L.rows * (rowH + gap) + 6, lc = o.CC[L.c] || '#8895A3';
      const chips = L.waves.map((w, wi) => {
        const X = x(w.s), nx = L.waves[wi + 1], room = nx ? x(nx.s) - X - 3 : 1e6;
        const lab = `${md(w.s)}${w.last > w.s ? '–' + md(w.last) : ''} · ${w.n} ${w.n === 1 ? 'ad' : 'ads'}`;
        const need = lab.length * 6.3 + 12, base = Math.max(6, (w.last - w.s + 1) * p);
        const wd = Math.min(room, Math.max(base, need));
        return `<button type="button" class="tw" data-w="${li}-${wi}" style="left:${X}px;width:${Math.max(4, wd)}px;--c:${lc}" title="Launch wave: ${esc(lab)}, running to ${esc(md(w.end))}. Click to zoom in.">${wd >= need ? esc(lab) : ''}</button>`;
      }).join('');
      const bars = L.items.map(i => {
        const a = i.a, X = x(i.s), w = Math.max(rich ? 8 : 3, (i.e - i.s + 1) * p), y = head + i.row * (rowH + gap);
        const txt = a.offer || a.title || (a.headlines || [])[0] || (o.PN[a.p] + ' ' + a.kind);
        const inner = rich ? `${a.img && w > 40 ? `<img src="${esc(a.img)}" alt="" loading="lazy">` : ''}${w > 60 ? `<span>${esc(txt)}</span>` : ''}` : '';
        return `<button type="button" class="tb${a.gone ? ' x' : ''}${a.p === 'google' ? ' g' : ''}${a.live ? ' live' : ''}" data-id="${esc(a.key)}" data-w="${i.w}" style="left:${X}px;top:${y}px;width:${w}px;height:${rowH}px;--c:${color(i)}" aria-label="${esc(o.PN[a.p] + ' ' + a.kind + ', ' + txt + ', ' + mdy(i.s))}">${inner}</button>`;
      }).join('');
      return `<div class="tl-lane" style="height:${h}px;width:${LABEL + W}px"><button type="button" class="tl-lab${o.selCamp === L.c ? ' sel' : ''}" data-c="${esc(L.c)}" style="width:${LABEL}px" title="${o.selCamp === L.c ? 'Show all campaigns' : 'Show only ' + esc(L.c)}"><i class="dot" style="background:${lc}"></i><span>${esc(L.c)}<small>${L.items.length} ads · ${L.waves.length} ${L.waves.length === 1 ? 'wave' : 'waves'}</small></span></button><div class="tl-trk" style="width:${W}px;height:${h}px">${chips}${bars}</div></div>`;
    }).join('');
    C.style.width = (LABEL + W) + 'px';
    C.innerHTML = `<div class="tl-grid" style="left:${LABEL}px;width:${W}px">${grid}</div><div class="tl-ax" style="width:${LABEL + W}px"><div class="tl-corner" style="width:${LABEL}px">Campaign</div><div class="tl-axt" style="width:${W}px">${ax}</div></div>${lanesHtml}`;
    vp.scrollLeft = (s.day - min) * p;
    legend();
  }
  function legend(){
    const L = el.querySelector('.tl-leg'); let h = '';
    if (s.color === 'plat') h = Object.entries(PLC).map(([k, c]) => `<span><i style="background:${c}"></i>${o.PN[k]}</span>`).join('');
    else if (s.color === 'obj') h = Object.entries(FNC).map(([k, c]) => `<span><i style="background:${c}"></i>${k}</span>`).join('');
else if (s.color === 'fmt') h = [...new Set(items.map(i => i.a.kind))].map(k => `<span><i style="background:${FMC[k] || '#888'}"></i>${esc(k)}</span>`).join('');
    else h = lanes.map(Lx => `<span><i style="background:${o.CC[Lx.c] || '#8895A3'}"></i>${esc(Lx.c)}</span>`).join('');
    h += MODE === 'ov' ? `<span>One dot = one ad, at its launch date</span><span><i style="background:#8895A3;width:10px;height:10px;border-radius:50%;box-shadow:inset 0 0 0 2px var(--ink)"></i>Google = dark ring</span><span><i style="background:#E0485A;width:2px"></i>Today</span>` : `<span><i style="background:#8895A3"></i>Meta = solid</span><span><i class="g" style="background-color:#8895A3"></i>Google = striped</span><span><i style="background:#E0485A;width:2px"></i>Today</span>`;
    L.innerHTML = h;
  }
  function zoomTo(np, px){
    if (px == null) px = vw() / 2;
    const day = min + (vp.scrollLeft + px) / s.ppd;
    s.ppd = clamp(np); s.day = day - px / s.ppd; draw();
  }
  function range(a, b){ s.ppd = clamp(vw() / Math.max(3, b - a)); s.day = a; draw(); }
  draw();

  vp.addEventListener('scroll', () => { s.day = min + vp.scrollLeft / s.ppd; });
  vp.addEventListener('wheel', e => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    const r = vp.getBoundingClientRect();
    zoomTo(s.ppd * Math.exp(-e.deltaY * 0.01), Math.max(0, e.clientX - r.left - LABEL));
  }, {passive: false});
  vp.addEventListener('keydown', e => {
    if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomTo(s.ppd * 1.5); }
    else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomTo(s.ppd / 1.5); }
  });
  let drag = null;
  vp.addEventListener('pointerdown', e => {
    if (e.button !== 0 || e.pointerType === 'touch' || e.target.closest('.tb,.tw,.tl-lab')) return;
    drag = {x: e.clientX, y: e.clientY, l: vp.scrollLeft, t: vp.scrollTop, id: e.pointerId, moved: false};
  });
  vp.addEventListener('pointermove', e => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.abs(dx) + Math.abs(dy) > 4) { drag.moved = true; vp.classList.add('drag'); try { vp.setPointerCapture(drag.id); } catch (_) {} }
    if (drag.moved) { vp.scrollLeft = drag.l - dx; vp.scrollTop = drag.t - dy; }
  });
  const end = () => { if (drag) { vp.classList.remove('drag'); drag = null; } };
  vp.addEventListener('pointerup', end); vp.addEventListener('pointercancel', end);
// phones and tablets: pinch to zoom (previewed with a stretch, redrawn when the fingers lift); one finger scrolls
let pinch = null;
const gap2 = T => Math.hypot(T[0].clientX - T[1].clientX, T[0].clientY - T[1].clientY);
vp.addEventListener('touchstart', e => { if (e.touches.length !== 2) return; const r = vp.getBoundingClientRect(); pinch = {d: gap2(e.touches) || 1, p: s.ppd, k: 1, x: Math.max(0, (e.touches[0].clientX + e.touches[1].clientX) / 2 - r.left - LABEL)}; }, {passive: true});
vp.addEventListener('touchmove', e => { if (!pinch || e.touches.length !== 2) return; e.preventDefault(); pinch.k = clamp(pinch.p * gap2(e.touches) / pinch.d) / pinch.p; C.style.transformOrigin = (LABEL + vp.scrollLeft + pinch.x) + 'px 0'; C.style.transform = 'scaleX(' + pinch.k + ')'; }, {passive: false});
const pinchEnd = () => { if (!pinch) return; const k = pinch.k, x = pinch.x; pinch = null; C.style.transform = ''; if (Math.abs(k - 1) > 0.02) zoomTo(s.ppd * k, x); };
vp.addEventListener('touchend', e => { if (e.touches.length < 2) pinchEnd(); });
vp.addEventListener('touchcancel', pinchEnd);

  el.querySelectorAll('[data-z]').forEach(b => b.onclick = () => zoomTo(s.ppd * Number(b.dataset.z)));
  el.querySelectorAll('[data-r]').forEach(b => b.onclick = () => {
    const r = b.dataset.r;
    if (r === 'all') range(min, max);
    else if (r === 'season') { const y = +o.today.slice(0, 4) - (o.today.slice(5) < '08-01' ? 1 : 0); range(t(y + '-08-01'), max); }
    else range(max - Number(r), max);
  });
  sel.onchange = () => { s.color = sel.value; draw(); };
el.querySelectorAll('[data-m]').forEach(b => b.onclick = () => { if (MODE === b.dataset.m) return; MODE = b.dataset.m; try { localStorage.setItem('ral-tlmode', MODE); } catch (_) {} if (MODE === 'ov') s.ppd = null; if (TIP) TIP.hidden = true; mount(el, ads, o); });

  const hl = w => { C.classList.add('dim'); C.querySelectorAll(`[data-w="${w}"]`).forEach(n => n.classList.add('hl')); };
  const unhl = () => { C.classList.remove('dim'); C.querySelectorAll('.hl').forEach(n => n.classList.remove('hl')); };
  C.addEventListener('mouseover', e => {
    const b = e.target.closest('.tb,.tw'); if (!b) return;
    unhl(); hl(b.dataset.w);
    if (b.classList.contains('tb')) {
      const i = byKey[b.dataset.id]; if (!i) return; const a = i.a, T = tip();
      T.innerHTML = `${a.img ? `<img src="${esc(a.img)}" alt="">` : '<span></span>'}<b>${esc(a.offer || a.title || (a.headlines || [])[0] || a.camp[0])}</b>
<span class="note">${esc(a.camp.join(', '))}${a.obj ? ' · ' + esc(a.obj) : ''}${a.gone ? ' · unavailable (content couldn’t be captured)' : ''}</span>
<span class="note">${esc((o.place ? o.place(a).label : o.PN[a.p]) + ' · ' + a.kind)}</span>
<span class="note">${mdy(i.s)} → ${a.live ? 'still active' : mdy(i.e)} · ${a.days || (i.e - i.s + 1)}d${a.ws != null ? ' · score ' + a.ws : ''}</span>`;
      T.hidden = false; place(e);
if (MODE === 'ov') { const r = C.querySelector('.orun'); if (r) { r.hidden = false; r.style.left = (i.s - min) * s.ppd + 'px'; r.style.width = Math.max(3, (i.e - i.s + 1) * s.ppd) + 'px'; r.style.background = color(i); } }
    }
  });
  C.addEventListener('mousemove', e => { if (TIP && !TIP.hidden) place(e); });
  C.addEventListener('mouseout', e => { const b = e.target.closest('.tb,.tw'); if (b && !b.contains(e.relatedTarget)) { unhl(); if (TIP) TIP.hidden = true; const r = C.querySelector('.orun'); if (r) r.hidden = true; } });
  function place(e){ const T = tip(), w = 292, h = T.offsetHeight || 90; let X = e.clientX + 14, Y = e.clientY + 14; if (X + w > innerWidth - 8) X = e.clientX - w - 14; if (Y + h > innerHeight - 8) Y = e.clientY - h - 14; T.style.left = X + 'px'; T.style.top = Y + 'px'; }
  C.addEventListener('click', e => {
    const b = e.target.closest('.tb'); if (b) { if (TIP) TIP.hidden = true; o.onOpen(b.dataset.id); return; }
    const w = e.target.closest('.tw');
    if (w) {
      const [li, wi] = w.dataset.w.split('-').map(Number), W = lanes[li].waves[wi];
      range(W.s - 3, Math.min(W.end, W.s + 120) + 4);
      const top = w.closest('.tl-lane'); if (top) vp.scrollTop = Math.max(0, top.offsetTop - 40);
      return;
    }
    const l = e.target.closest('.tl-lab');
    if (l) {
      const c = l.dataset.c, tabs = document.getElementById('tabs');
      const btn = tabs && [...tabs.querySelectorAll('[data-c]')].find(x => x.dataset.c === (o.selCamp === c ? '' : c));
      if (btn) btn.click();
    }
  });
}
window.TLX = {mount};
})();
