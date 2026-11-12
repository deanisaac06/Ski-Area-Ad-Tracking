// Peer benchmarks: reads the Ski Area Ad Atlas (atlas.html) for each resort's estimated paid media, sorts resorts into budget classes, and compares every ad with the same ad type at similar-budget resorts.
(function(){
const P=window.PEERS={ok:false,n:0};
const L=window.LIB; if(!L||!window.fetch) return;
const ADS=L.ads;
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]);
const nk=s=>String(s||'').split('(')[0].toLowerCase().replace(/[^a-z0-9]/g,'');
const K=v=>v==null?'—':v>=1000?'$'+(v/1000).toFixed(1)+'M':'$'+Math.round(v)+'K';
const CL=[['Major','$1M+ a year',1000],['Large','$500K–$1M a year',500],['Mid','$200K–$500K a year',200],['Small','under $200K a year',0]];
const cls=mm=>mm==null?null:CL.findIndex(c=>mm>=c[2]);
const PN={meta:'Meta',google:'Google'};
const fl=a=>PN[a.p]+' '+String(a.kind||'').toLowerCase()+' ads';
const med=v=>{const s=[...v].sort((x,y)=>x-y),m=s.length>>1;return s.length?(s.length%2?s[m]:(s[m-1]+s[m])/2):null;};
const pct=(v,arr)=>{let b=0,e=0;arr.forEach(x=>{if(x<v)b++;else if(x===v)e++;});return Math.round((b+e/2)/arr.length*100);};
const tierC=v=>v>=70?'hi':v>=45?'mid':'lo';
const css=document.createElement('style');
css.textContent='.cpeer{font-size:11.5px;color:var(--muted);margin-top:2px}.cpeer b{color:var(--ink)}.pbpeer{margin:10px 0 4px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font-size:13px;line-height:1.5}.rkh{margin:18px 0 6px;font-size:15px}.rkh span{font-weight:400;color:var(--muted);font-size:12.5px;margin-left:6px}.rkt{min-width:0!important}.rkt td,.rkt th{padding:7px 8px}.rkt td.num,.rkt th{white-space:nowrap}.rkt td .note{display:block;font-size:11px}.rkt tr.off td{color:var(--muted)}.lnk2{border:0;background:none;padding:0;color:var(--accent);cursor:pointer;font:inherit;font-weight:600;text-align:left;text-decoration:underline}';
document.head.appendChild(css);
function build(rows){
const idx={},idn={};
rows.forEach(r=>{idx[nk(r.n)+'|'+r.s]=r; if(!idn[nk(r.n)]) idn[nk(r.n)]=r;});
const R={};
[...new Set(ADS.map(a=>a.n))].forEach(n=>{
const a0=ADS.find(a=>a.n===n);
const r=idx[nk(n)+'|'+a0.s]||idn[nk(n)];
R[n]={n:n,r:r,mm:r&&r.mm!=null?r.mm:null,c:r&&r.mm!=null?cls(r.mm):null,rg:a0.rg,s:a0.s};
});
const el=ADS.filter(a=>!a.gone&&a.ws!=null&&a.days!=null);
el.forEach(a=>{a._fk=a.p+'|'+a.kind; a._c=R[a.n]?R[a.n].c:null;});
const pick=(a,f)=>{const v=el.filter(x=>x._fk===a._fk&&f(x)); return v.length>=8&&new Set(v.map(x=>x.n)).size>=3?v:null;};
el.forEach(a=>{
const c=a._c; let g=null,lab='';
if(c!=null){
g=pick(a,x=>x._c===c); lab=CL[c][0]+'-budget resorts ('+CL[c][1]+')';
if(!g){g=pick(a,x=>x._c!=null&&Math.abs(x._c-c)<=1); lab='similar-budget resorts ('+CL[Math.max(0,c-1)][0]+' to '+CL[Math.min(3,c+1)][0]+' classes)';}
}
const all=el.filter(x=>x._fk===a._fk);
if(!g){g=all; lab='all tracked resorts';}
if(g.length<5) return;
const reg=pick(a,x=>x.rg===a.rg);
a.pr=pct(a.days,g.map(x=>x.days));
a.pg={lab:lab,n:g.length,rs:new Set(g.map(x=>x.n)).size,all:pct(a.days,all.map(x=>x.days)),reg:reg?pct(a.days,reg.map(x=>x.days)):null};
});
Object.values(R).forEach(q=>{
const A=ADS.filter(a=>a.n===q.n&&!a.gone);
q.live=A.filter(a=>a.live).length; q.tot=A.length;
const m=med(A.filter(a=>a.pr!=null).map(a=>a.pr)); q.pr=m==null?null:Math.round(m);
});
const T=Object.values(R).filter(q=>q.mm!=null).sort((x,y)=>y.mm-x.mm);
T.forEach(q=>{const cc=T.filter(z=>z.c===q.c); q.ci=cc.indexOf(q)+1; q.cn=cc.length; const m=med(cc.map(z=>z.pr).filter(v=>v!=null)); q.cmed=m==null?null:Math.round(m);});
P.R=R; P.rows=rows.filter(r=>r.mm!=null); P.n=Object.keys(R).length; P.ok=true;
document.dispatchEvent(new Event('peers-ready'));
}
P.card=a=>a.pr==null?'':`<div class="cpeer" title="Ran longer than ${a.pr}% of ${esc(fl(a))} from ${esc(a.pg.lab)}">vs peers: beats <b>${a.pr}%</b>${a.live?' so far':''}</div>`;
P.block=a=>{
if(a.pr==null) return '';
const q=P.R[a.n]||{};
return `<div class="sec"><h3>Versus similar resorts</h3><p>Ran longer than <b>${a.pr}%</b> of ${esc(fl(a))} from ${esc(a.pg.lab)}: ${a.pg.n} ads from ${a.pg.rs} resorts.</p><p class="note">Against all tracked resorts: ${a.pg.all}%${a.pg.reg!=null?' · '+esc(a.rg)+' only: '+a.pg.reg+'%':''}${q.mm!=null?' · '+esc(a.n)+' spends about '+K(q.mm)+' a year on paid media ('+CL[q.c][0]+' class, Ski Area Ad Atlas estimate)':''}. Run length is the best public signal of performance, because resorts keep paying for ads that work. Live ads are still adding days.</p></div>`;
};
P.resort=n=>{
const q=P.R&&P.R[n]; if(!q) return '';
const btn='<button type="button" class="lnk2" data-rank="1">See resort rankings</button>';
if(q.mm==null) return `<div class="pbpeer">No spend estimate for this resort in the Ski Area Ad Atlas. ${btn}</div>`;
return `<div class="pbpeer"><b>Est. paid media ${K(q.mm)} a year</b> (${K(q.r.mml)}–${K(q.r.mmh)}) · <b>${CL[q.c][0]}</b> budget class (${CL[q.c][1]}), #${q.ci} of ${q.cn} tracked resorts in its class${q.pr!=null?' · its ads beat <b>'+q.pr+'%</b> of similar-budget peers on run length'+(q.cmed!=null?' (class typical '+q.cmed+'%)':''):''}. ${btn}</div>`;
};
P.rank=all=>{
const TR=Object.values(P.R), mine=TR.filter(q=>q.r&&q.mm!=null);
const rows=all?P.rows.slice():mine.map(q=>q.r);
const tracked=r=>TR.find(q=>q.r===r);
rows.sort((x,y)=>(y.mm||0)-(x.mm||0));
let h=`<div class="dhead"><div><h2 id="dtitle">Resort rankings</h2><div class="sub">Estimated paid media a year (Ski Area Ad Atlas, Nov 2026), grouped into budget classes. Vs peers = how long the resort's typical ad runs compared with the same ad types at similar-budget resorts (50 = typical).</div></div><div class="acts"><button class="btn" id="rkClose">Close</button></div></div><div class="dbody"><label class="note" style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="rkAll"${all?' checked':''}> Show all ${P.rows.length} ski areas in the atlas, not just the ${mine.length} tracked here</label>`;
CL.forEach((c,ci)=>{
const g=rows.filter(r=>cls(r.mm)===ci); if(!g.length) return;
h+=`<h3 class="rkh">${c[0]}<span>${c[1]} · ${g.length} ${g.length===1?'resort':'resorts'}</span></h3><div class="tblwrap"><table class="rkt"><thead><tr><th>#</th><th>Resort</th><th>Region</th><th>Est. paid media</th><th>Live ads</th><th>Vs peers</th></tr></thead><tbody>`+g.map(r=>{const q=tracked(r);return `<tr class="${q?'':'off'}"><td class="num">${rows.indexOf(r)+1}</td><td>${q?`<button type="button" class="lnk2" data-goto="${esc(q.n)}">${esc(r.n)}</button>`:esc(r.n)}</td><td>${esc(r.rg)} · ${esc(r.s)}</td><td class="num">${K(r.mm)} <span class="note">${K(r.mml)}–${K(r.mmh)}</span></td><td class="num">${q?q.live+' of '+q.tot:'not tracked'}</td><td>${q&&q.pr!=null?`<span class="ws ${tierC(q.pr)}">${q.pr}</span>`:'—'}</td></tr>`;}).join('')+`</tbody></table></div>`;
});
return h+'</div>';
};
P.openRank=all=>{
const d=document.getElementById('drawer'); if(!d||!P.ok) return;
d.innerHTML=P.rank(!!all); if(!d.open) d.showModal(); d.scrollTop=0;
document.getElementById('rkClose').onclick=()=>d.close();
document.getElementById('rkAll').onchange=e=>P.openRank(e.target.checked);
};
document.addEventListener('click',e=>{
const r=e.target.closest('[data-rank]'); if(r){e.preventDefault(); P.openRank(false); return;}
const g=e.target.closest('[data-goto]'); if(g&&window.RAL){document.getElementById('drawer').close(); window.RAL.go({t:'n',v:g.dataset.goto});}
});
fetch('atlas.html').then(r=>r.text()).then(t=>{
const i=t.indexOf('window.ATLAS='); if(i<0) return;
let s=t.slice(i+13,t.indexOf('</script>',i)).trim(); if(s.slice(-1)===';') s=s.slice(0,-1);
build(JSON.parse(s).rows);
}).catch(e=>console.warn('atlas not loaded',e));
})();
