// Ikon · Epic · Indy on each resort page: which pass the resort is on and how hard its own ads push it.
// On a pass account (Ikon Pass, Epic Pass, Indy Pass): what the pass is pushing and which resorts amplify it.
// Built by passes.py on every run.
(function(){
const L=window.LIB; if(!L) return;
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]);
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const d=s=>s?MON[+s.slice(5,7)-1]+' '+(+s.slice(8,10)):'—';
const COL={Ikon:'#111827',Epic:'#D9480F',Indy:'#B42318','Mountain Collective':'#0F766E'};
const chip=p=>`<span class="pchip" style="background:${COL[p]||'#667085'}">${esc(p)}</span>`;
const css=document.createElement('style');
css.textContent='.passbox{margin:10px 0 4px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font-size:13px;line-height:1.5}.passbox h4{margin:0 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}.passbox .pnow{font-size:15px}.pchip{display:inline-block;color:#fff;font-size:11.5px;font-weight:700;border-radius:999px;padding:1px 8px;margin-right:5px;vertical-align:1px}.passbox ul{margin:6px 0 0;padding-left:18px}.passbox li{margin:2px 0}.passbox .pf{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:6px;color:var(--muted);font-size:12.5px}.passbox .pf b{color:var(--ink);font-weight:600}.passbox .lnk{border:0;background:none;padding:0;color:var(--accent);cursor:pointer;text-decoration:underline;font:inherit}';
document.head.appendChild(css);
const filt=(k,v,label,all)=>`<button type="button" class="lnk" data-pk="${k}" data-pv="${esc(v)}"${all?' data-pall="1"':''}>${label}</button>`;
window.PASSBOX=n=>{
  const r=(L.resorts||[]).find(x=>x.n===n), P=r&&r.pass; if(!P) return '';
  let h='<div class="passbox"><h4>Ikon · Epic · Indy · Mountain Collective</h4>';
  if(P.account){
    const a=P.account;
    h+=`<div class="pnow">${chip(a)}<b>${esc(n)}</b> corporate account · <b>${P.live||0}</b> live ads${P.new7?' · <b>'+P.new7+'</b> new this week':''}</div>`;
    if(P.mix&&P.mix.length) h+=`<div class="note">Pushing now: ${P.mix.map(x=>`${esc(x[0])} <b>${x[1]}</b>`).join(' · ')}</div>`;
    if(P.offers&&P.offers.length) h+=`<div class="note">Offers: ${P.offers.map(esc).join(' · ')}</div>`;
    if(P.deadlines&&P.deadlines.length) h+=`<div class="note">Deadlines in its live ads: <b>${P.deadlines.map(d).join(', ')}</b></div>`;
    if(P.amp&&P.amp.length) h+=`<div style="margin-top:6px"><b>Resorts pushing ${esc(a)} in their own ads</b> <span class="note">(live or launched in the last 60 days · ${P.amp_n} resort${P.amp_n===1?'':'s'})</span><ul>${P.amp.map(x=>`<li><button type="button" class="lnk" data-pgo="${esc(x.n)}">${esc(x.n)}</button> · ${x.c} ad${x.c>1?'s':''}${x.live?' ('+x.live+' live)':''} · last launched ${d(x.last)}${x.on?'':' · <i>not on '+esc(a)+'</i>'}</li>`).join('')}</ul></div>`;
    else h+=`<div class="note">No resort ads pushing ${esc(a)} in the last 60 days yet.</div>`;
    h+=`<div class="pf"><span><b>${P.on_n||0}</b> tracked resorts on ${esc(a)}</span><span>${filt('pp',a+' push','See every '+esc(a)+' push ad, resorts included',1)}</span><span>${filt('rp',a,'See all ads from '+esc(a)+' resorts',1)}</span></div>`;
    return h+'</div>';
  }
  const on=P.on||[], pu=P.push||{}, me=P.mention||{}, tot=P.ads||0;
  h+=`<div class="pnow">${on.length?'On '+on.map(chip).join(''):'Not on Epic, Ikon, Indy or Mountain Collective'}</div><div class="note">${esc(P.src||'')}</div>`;
  const ks=[...new Set(Object.keys(pu).concat(Object.keys(me)))];
  if(ks.length){
    h+='<ul>'+ks.map(p=>{const c=pu[p]||0, m=me[p]||0; return `<li>${chip(p)}${c?`<b>${c}</b> ad${c>1?'s':''} push ${esc(p)}${tot?' ('+Math.round(c/tot*100)+'% of its ads)':''} · ${filt('pp',p+' push','show them')}`:''}${c&&m?' · ':''}${m?`${m} mention ${esc(p)} in passing`:''}</li>`;}).join('')+'</ul>';
    if(P.live) h+=`<div class="note"><b>${P.live}</b> pass-push ad${P.live>1?'s':''} live now · latest launched ${d(P.last)}</div>`;
  } else h+='<div class="note">None of its ads push Epic, Ikon, Indy or Mountain Collective so far.</div>';
  return h+'</div>';
};
document.addEventListener('click',e=>{
  const g=e.target.closest('[data-pgo]'); if(g&&window.RAL){ e.preventDefault(); RAL.go({t:'n',v:g.dataset.pgo}); return; }
  const f=e.target.closest('[data-pk]'); if(f&&window.RAL&&RAL.setF){ e.preventDefault(); if(f.dataset.pall) RAL.go({t:'all'}); RAL.setF(f.dataset.pk,f.dataset.pv); window.scrollTo({top:0}); }
});
})();
