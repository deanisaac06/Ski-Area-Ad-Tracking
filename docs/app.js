(function(){
const L = window.LIB, ADS = L.ads, TODAY = L.today, TAX = L.tax || {};
const $ = s => document.querySelector(s);
const esc = s => String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const fmtDate = d => d ? MON[+d.slice(5,7)-1]+' '+(+d.slice(8,10))+', '+d.slice(0,4) : '—';
const shortDate = d => d ? MON[+d.slice(5,7)-1]+' '+(+d.slice(8,10))+(d.slice(0,4)!==TODAY.slice(0,4)?' ’'+d.slice(2,4):'') : '—';
const addDays=(d,n)=>{const x=new Date(d+'T00:00:00Z'); x.setUTCDate(x.getUTCDate()+n); return x.toISOString().slice(0,10);};
const STATE={WA:'Washington',OR:'Oregon',ID:'Idaho',MT:'Montana',WY:'Wyoming',UT:'Utah',CO:'Colorado',NM:'New Mexico',AZ:'Arizona',CA:'California',NV:'Nevada',AK:'Alaska',SD:'South Dakota',MN:'Minnesota',WI:'Wisconsin',MI:'Michigan',IA:'Iowa',MO:'Missouri',IL:'Illinois',IN:'Indiana',OH:'Ohio',PA:'Pennsylvania',NY:'New York',VT:'Vermont',NH:'New Hampshire',ME:'Maine',MA:'Massachusetts',CT:'Connecticut',NJ:'New Jersey',WV:'West Virginia',VA:'Virginia',NC:'North Carolina',TN:'Tennessee',MD:'Maryland'};
const COLORS=['#2F6FB5','#5B8DCB','#2E8B6A','#7A9A3A','#B26B2E','#A34C7A','#C2873A','#2A9BA0','#6D6A8C','#4E6476'];
const CC=Object.fromEntries(L.campaigns.map((c,i)=>[c,COLORS[i%COLORS.length]]));
if(!CC.Unknown) CC.Unknown='#8895A3';
const PN={meta:'Meta',google:'Google'};
const WEEK_AGO=addDays(TODAY,-7);
const LNK='border:0;background:none;padding:0;color:var(--accent);cursor:pointer;text-decoration:underline;font:inherit';
// agency funnel shorthand, so searching "tofu" or "bofu" works
const FUN={Awareness:'tofu top of funnel awareness brand',Consideration:'mofu middle of funnel consideration',Conversion:'bofu bottom of funnel conversion sales'};

ADS.forEach(a=>{
a.isnew=(a.start||'')>=WEEK_AGO;
a.copy=[a.title,a.body,a.desc,a.seen_text,a.arc&&a.arc.note&&[a.arc.note.summary,a.arc.note.voiceover,a.arc.note.onscreen,a.arc.note.offer].filter(Boolean).join(' ')].filter(Boolean).join(' — ');
a.camp=a.camp&&a.camp.length?a.camp:[a.gone?'Unknown':'Brand & general'];
a.themes=a.themes||[]; a.prices=a.prices||[]; a.aud=a.aud||[]; a.ot=a.ot||[];
});
const median=v=>{const s=[...v].sort((x,y)=>x-y),m=s.length>>1;return s.length?(s.length%2?s[m]:(s[m-1]+s[m])/2):0;};
const tier=s=>s==null?'early':s>=70?'hi':s>=45?'mid':'lo';
const why=a=>(a.q&&(a.q.why||a.q.msg))||'error page, blank or empty';

let saved=new Set(); try{saved=new Set(JSON.parse(localStorage.getItem('ral-saved')||'[]'))}catch(e){}
const persist=()=>{try{localStorage.setItem('ral-saved',JSON.stringify([...saved]))}catch(e){}};

const st={folder:{t:'all'}, camp:null, d:'all', kind:'all', plat:'all', status:'all', obj:'all', aud:'all', ot:'all', fl:'all', sn:'all', sort:'new', view:'grid', open:{}};
try{const p=JSON.parse(localStorage.getItem('ral-view')||'{}'); if(p.view) st.view=p.view;}catch(e){}

// agency labels: [state key, label, preferred order, getter]
const nm=x=>typeof x==='string'?x:(x&&(x.name||x.label||x[0]))||'';
const FACETS=[
['obj','Funnel stage',TAX.funnel||['Awareness','Consideration','Conversion'],a=>a.obj?[a.obj]:[]],
['aud','Audience',TAX.audiences,a=>a.aud],
['ot','Offer type',TAX.offers,a=>a.ot],
['fl','Flight',TAX.flights,a=>a.fl?[a.fl]:[]],
['sn','Season',null,a=>a.sn?[a.sn]:[]]
];
const HAS_TAX=ADS.some(a=>a.obj||a.aud.length||a.ot.length||a.fl);

// resort tree
const tree={}; ADS.forEach(a=>{ (tree[a.rg]??={}); (tree[a.rg][a.s]??={}); tree[a.rg][a.s][a.n]=(tree[a.rg][a.s][a.n]||0)+1; });
const RG=['West','Midwest','East','Canada'].filter(r=>tree[r]).concat(Object.keys(tree).filter(r=>!['West','Midwest','East','Canada'].includes(r)));

function inFolder(a,f=st.folder){
switch(f.t){
case 'all': return true; case 'live': return a.live; case 'new': return a.isnew;
case 'saved': return saved.has(a.key); case 'stand': return !!a.stand; case 'gone': return !!a.gone;
case 'rg': return a.rg===f.v; case 's': return a.s===f.v; case 'n': return a.n===f.v;
} return true;
}
function inDates(a){
if(st.d==='all') return true;
if(!a.start) return false;
if(st.d==='7') return a.start>=addDays(TODAY,-7);
if(st.d==='30') return a.start>=addDays(TODAY,-30);
if(st.d==='season') return a.start>=(TODAY.slice(5)>='09-01'?TODAY.slice(0,4):String(+TODAY.slice(0,4)-1))+'-09-01';
const f=$('#dfrom').value, t=$('#dto').value;
return (!f||a.start>=f)&&(!t||a.start<=t);
}
function inSearch(a){
const q=$('#q').value.trim().toLowerCase(); if(!q) return true;
const hay=(a.n+' '+(STATE[a.s]||a.s)+' '+a.s+' '+a.copy+' '+(a.headlines||[]).join(' ')+' '+(a.cta||'')+' '+(a.offer||'')+' '+a.camp.join(' ')+' '+a.themes.join(' ')+' '+a.prices.join(' ')+' '+a.kind+' '+PN[a.p]+' '+(a.advertiser||'')+' '+(a.link||'')+' '+(a.obj||'')+' '+(FUN[a.obj]||'')+' '+a.aud.join(' ')+' '+a.ot.join(' ')+' '+(a.fl||'')+' '+(a.sn||'')+' '+(a.health||'')+(a.gone?' unavailable broken missing':'')).toLowerCase();
return q.split(/\s+/).every(w=>hay.includes(w));
}
// Unavailable ads live in their own bucket: hidden from normal views, shown when Status = Unavailable.
// The resort timeline passes withGone=true so they appear there as hatched bars.
function inStatus(a,withGone){
if(st.status==='gone') return !!a.gone;
if(a.gone) return !!withGone&&st.status==='all';
return st.status==='all'||(st.status==='live')===!!a.live;
}
const inFacets=a=>FACETS.every(([k,,,get])=>st[k]==='all'||get(a).includes(st[k]));
const base = withGone => ADS.filter(a=>inFolder(a)&&inDates(a)&&inSearch(a)&&(st.kind==='all'||a.kind===st.kind)&&(st.plat==='all'||a.p===st.plat)&&inStatus(a,withGone)&&inFacets(a));

const ico={
folder:'<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 4.5a1 1 0 0 1 1-1h3.6l1.4 1.5h5.9a1 1 0 0 1 1 1v6.5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z" fill="currentColor" opacity=".85"/></svg>',
all:'<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="1.5" width="5.5" height="5.5" rx="1" fill="currentColor"/><rect x="9" y="1.5" width="5.5" height="5.5" rx="1" fill="currentColor" opacity=".6"/><rect x="1.5" y="9" width="5.5" height="5.5" rx="1" fill="currentColor" opacity=".6"/><rect x="9" y="9" width="5.5" height="5.5" rx="1" fill="currentColor"/></svg>',
live:'<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" style="color:var(--good)"><circle cx="8" cy="8" r="4" fill="currentColor"/><circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" opacity=".45"/></svg>',
newi:'<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v12M2 8h12" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
star:'<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5l1.9 4 4.4.5-3.3 3 .9 4.4L8 11.2 4.1 13.4l.9-4.4-3.3-3 4.4-.5z" fill="currentColor"/></svg>',
spark:'<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" style="color:var(--gold)"><path d="M8 1l1.6 4.9L14.5 8l-4.9 1.6L8 14.5 6.4 9.6 1.5 8l4.9-2.1z" fill="currentColor"/></svg>',
warn:'<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" style="color:#B42318"><path d="M8 1.8l6.6 12H1.4z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6.2v3.6M8 11.4v.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
doc:'<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 1.5h6l3 3v10h-9z" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M5.5 8h5M5.5 10.5h5M5.5 5.5h2.5" stroke="currentColor" stroke-width="1.2"/></svg>'
};
const same=f=>f.t==='gone'?st.status==='gone':st.status!=='gone'&&st.folder.t===f.t&&st.folder.v===f.v;
function node(f,label,count,icon,cls='',tw=''){
return `<button class="node ${cls}" data-f='${esc(JSON.stringify(f))}' aria-current="${same(f)}">${tw}${icon}<span class="lab">${esc(label)}</span><span class="c">${count}</span></button>`;
}
function renderSide(){
const cnt=f=>ADS.filter(a=>!a.gone&&inFolder(a,f)).length;
let h=`<div class="sh">Library</div>`+
node({t:'all'},'All ads',cnt({t:'all'}),ico.all)+
node({t:'live'},'Live now',cnt({t:'live'}),ico.live)+
node({t:'new'},'New this week',cnt({t:'new'}),ico.newi)+
node({t:'stand'},'Standouts',cnt({t:'stand'}),ico.spark)+
node({t:'saved'},'Saved',saved.size,ico.star)+
node({t:'gone'},'Unavailable',ADS.filter(a=>a.gone).length,ico.warn);
if(L.reports.length){
h+=`<div class="sh">Weekly reports</div>`+L.reports.slice(0,8).map(r=>`<a class="node" href="${esc(r.file)}">${ico.doc}<span class="lab">${esc(fmtDate(r.date))}</span><span class="c">${r.new} new</span></a>`).join('');
}
h+=`<div class="sh">Resorts</div>`;
for(const rg of RG){
const rn=Object.values(tree[rg]).reduce((s,o)=>s+Object.values(o).reduce((x,y)=>x+y,0),0);
const ro=st.open['rg:'+rg]!==false;
h+=node({t:'rg',v:rg},rg,rn,ico.folder,'d1',`<span class="tw ${ro?'open':''}" data-tog="rg:${rg}" role="button" aria-label="Expand ${rg}">▶</span>`);
if(ro) for(const s of Object.keys(tree[rg]).sort((a,b)=>(STATE[a]||a).localeCompare(STATE[b]||b))){
const sn=Object.values(tree[rg][s]).reduce((x,y)=>x+y,0), so=st.open['s:'+s];
h+=node({t:'s',v:s},STATE[s]||s,sn,ico.folder,'d2',`<span class="tw ${so?'open':''}" data-tog="s:${s}" role="button" aria-label="Expand ${STATE[s]||s}">▶</span>`);
if(so) for(const n of Object.keys(tree[rg][s]).sort()) h+=node({t:'n',v:n},n,tree[rg][s][n],ico.folder,'d3','<span class="tw"></span>');
}
}
$('#side').innerHTML=h;
}
function folderInfo(){
const f=st.folder, T={all:st.status==='gone'?'Unavailable ads':'All ads',live:'Live now',new:'New this week',saved:'Saved',stand:'Standouts'};
if(T[f.t]) return {title:T[f.t],crumbs:[]};
if(f.t==='rg') return {title:f.v,crumbs:[]};
if(f.t==='s'){ const rg=ADS.find(a=>a.s===f.v).rg; return {title:STATE[f.v]||f.v,crumbs:[[{t:'rg',v:rg},rg]]}; }
const a0=ADS.find(a=>a.n===f.v); return {title:f.v,crumbs:[[{t:'rg',v:a0.rg},a0.rg],[{t:'s',v:a0.s},STATE[a0.s]||a0.s]]};
}

// agency-label dropdowns (Funnel stage, Audience, Offer type, Flight, Season)
function renderFacets(){
if(!HAS_TAX){ $('#facets').innerHTML='<span class="note">Agency labels (funnel stage, audience, offer type, flight) appear here after the next data build.</span>'; return; }
const pool=ADS.filter(a=>!a.gone&&inFolder(a));
$('#facets').innerHTML=FACETS.map(([k,lab,order,get])=>{
const c={}, all={};
pool.forEach(a=>get(a).forEach(v=>c[v]=(c[v]||0)+1));
ADS.forEach(a=>get(a).forEach(v=>all[v]=1));
const ord=(order||[]).map(nm), vals=Object.keys(all);
vals.sort(k==='sn'?(x,y)=>y.localeCompare(x):(x,y)=>{const i=ord.indexOf(x),j=ord.indexOf(y);return (i<0?999:i)-(j<0?999:j)||x.localeCompare(y);});
if(!vals.length) return '';
return `<label class="ctl">${lab}<select data-fa="${k}"><option value="all">All</option>${vals.map(v=>`<option value="${esc(v)}"${st[k]===v?' selected':''}>${esc(v)} (${c[v]||0})</option>`).join('')}</select></label>`;
}).join('');
}
// removable chips for every active filter
const DL={'7':'Last 7 days','30':'Last 30 days',season:'This season',custom:'Custom dates'};
const SL={live:'Live',ended:'Stopped',gone:'Unavailable'};
function renderActive(){
const c=[], q=$('#q').value.trim();
if(q) c.push(['q','Search',q]);
if(st.camp) c.push(['camp','Campaign',st.camp]);
FACETS.forEach(([k,lab])=>{ if(st[k]!=='all') c.push([k,lab,st[k]]); });
if(st.plat!=='all') c.push(['plat','Platform',PN[st.plat]]);
if(st.status!=='all') c.push(['status','Status',SL[st.status]||st.status]);
if(st.d!=='all') c.push(['d','Launched',DL[st.d]||st.d]);
if(st.kind!=='all') c.push(['kind','Format',st.kind]);
$('#active').innerHTML=c.length?`<span class="note">Filters:</span>`+c.map(([k,l,v])=>`<button type="button" class="chip" data-x="${k}" title="Remove this filter">${esc(l)}: <b>${esc(v)}</b> ×</button>`).join('')+(c.length>1?`<button type="button" class="clr" data-x="*">Clear all</button>`:''):'';
}

function perf(a){
if(a.gone) return `<span class="ws early" title="No score: the ad's content couldn't be captured">n/a</span>`;
return a.ws==null ? `<span class="ws early" title="Under a week old">Too early</span>` : `<span class="ws ${tier(a.ws)}" title="Winner score ${a.ws} of 100">${a.ws}</span>`;
}
function visual(a,big){
if(a.gone) return `<div class="art gone" title="${esc(why(a))}"><div class="g"><b>⚠</b><i>Content unavailable</i><i>${esc(String(why(a)).slice(0,60))}</i></div></div>`;
if(a.img) return `<img class="pic" src="${esc(a.img)}" alt="" loading="lazy">${a.kind==='Video'?'<span class="play"></span>':''}`;
const txt=a.title||a.seen_text||(a.headlines||[])[0]||a.body||'';
if(txt) return `<div class="txtad${big?' big':''}"><b>${esc(txt.slice(0,90))}</b>${a.body&&a.body!==txt?`<span>${esc(a.body.slice(0,120))}</span>`:''}<i>${esc(a.link?a.link.replace(/^https?:\/\/(www\.)?/,'').split(/[/?]/)[0]:PN[a.p]+' '+a.kind)}</i></div>`;
let hue=0; for(const c of a.n) hue=(hue*31+c.charCodeAt(0))%360;
return `<div class="art" style="background:linear-gradient(155deg,hsl(${hue} 40% 40%),hsl(${(hue+40)%360} 46% 24%))"><div class="g">${a.kind==='Video'?'<span class="play static"></span>':''}<i>${esc(a.kind)}</i></div></div>`;
}
function campLine(a,full){
const c=(st.camp&&a.camp.includes(st.camp))?st.camp:a.camp[0];
const txt=full?a.camp.join(', '):c+(a.camp.length>1?' +'+(a.camp.length-1):'');
return `<div class="ccamp" title="${esc(a.camp.join(', '))}"><i class="dot" style="background:${CC[c]||'#999'}"></i><span>${esc(txt)}</span>${a.src==='button'?'<span class="guess">· guess</span>':''}</div>`;
}
function tagLine(a){
const t=[a.obj,a.ot.find(x=>x!=='No offer'),a.aud.find(x=>x!=='General audience')].filter(Boolean);
return t.length?`<div class="ctag" title="${esc(t.join(' · '))}">${esc(t.join(' · '))}</div>`:'';
}
function qline(a){
if(a.gone) return `<div class="qnote" title="${esc(why(a))}">Unavailable · ${esc(why(a))}</div>`;
if(a.q&&a.q.st==='text') return `<div class="qnote">Picture unavailable · text only</div>`;
return '';
}
const pbadge=a=>`<span class="badge tl plat ${a.p}">${PN[a.p]}</span>`;

function render(){
renderSide(); renderFacets(); renderActive();
const fi=folderInfo();
$('#crumbs').innerHTML=[`<button data-f='{"t":"all"}'>All ads</button>`].concat(fi.crumbs.map(([f,l])=>`<button data-f='${esc(JSON.stringify(f))}'>${esc(l)}</button>`)).join('<span>›</span>')+(st.folder.t!=='all'?`<span>›</span><span class="cur">${esc(fi.title)}</span>`:'');
$('#ftitle').textContent=fi.title;
const b=base();
const cc={}; b.forEach(a=>a.camp.forEach(c=>cc[c]=(cc[c]||0)+1));
$('#tabs').innerHTML=`<button class="tab" data-c="" aria-pressed="${!st.camp}">All campaigns <span class="c">${b.length}</span></button>`+
L.campaigns.map(c=>`<button class="tab ${cc[c]?'':'zero'}" data-c="${esc(c)}" aria-pressed="${st.camp===c}"><i class="dot" style="background:${CC[c]}"></i>${esc(c)} <span class="c">${cc[c]||0}</span></button>`).join('');
const inCamp=a=>!st.camp||a.camp.includes(st.camp);
// resort playbook + interactive timeline; the timeline gets exactly the ads the filters below select
if(st.folder.t==='n'){
$('#playbook').innerHTML=playbook(st.folder.v);
const el=$('#tlx');
if(el&&window.TLX){
try{ window.TLX.mount(el, base(true).filter(inCamp), {key:st.folder.v, today:TODAY, camps:L.campaigns, CC, PN, selCamp:st.camp, total:ADS.filter(a=>a.n===st.folder.v).length, onOpen:openAd}); }
catch(e){ console.error(e); el.innerHTML='<p class="note">The timeline could not be drawn.</p>'; }
}
} else $('#playbook').innerHTML='';
const list=b.filter(inCamp);
const by={perf:(x,y)=>(y.ws??-1)-(x.ws??-1)||(y.days-x.days),new:(x,y)=>(y.start||'').localeCompare(x.start||''),long:(x,y)=>y.days-x.days,resort:(x,y)=>x.n.localeCompare(y.n)||(y.start||'').localeCompare(x.start||'')};
list.sort(by[st.sort]);
const resorts=new Set(list.map(a=>a.n)).size, live=list.filter(a=>a.live).length;
const ds=list.map(a=>a.start).filter(Boolean).sort();
const hid=st.status==='all'?base(true).filter(a=>a.gone&&inCamp(a)).length:0;
const hidTxt=hid?` · <button type="button" data-go="gone" style="${LNK}" title="Ads we know ran but whose content came back broken">${hid} unavailable</button>`:'';
$('#fstats').innerHTML=(list.length?(st.status==='gone'?`<b>${list.length}</b> unavailable ${list.length===1?'ad':'ads'} · <b>${resorts}</b> ${resorts===1?'resort':'resorts'}`:`<b>${list.length}</b> ads · <b>${live}</b> live · <b>${resorts}</b> ${resorts===1?'resort':'resorts'} · launched ${shortDate(ds[0])} – ${fmtDate(ds[ds.length-1])}`):'')+hidTxt;
if(!list.length){ $('#results').innerHTML=`<p class="empty">${st.status==='gone'?'No unavailable ads here. Every ad in this view loaded correctly.':st.folder.t==='saved'&&!saved.size?'No saved ads yet. Open any ad and select Save.':'No ads match. Remove a filter above, try “All campaigns”, a wider date range, or a shorter search.'}</p>`; return; }
const shown=list.slice(0,st.limit||240);
if(st.view==='grid'){
$('#results').innerHTML=`<div class="grid">`+shown.map(a=>`<button class="card${a.gone?' gone':a.live?'':' ended'}" data-id="${a.key}">
<div class="thumb">${visual(a)}${pbadge(a)}${a.gone?'<span class="badge tr warn">Unavailable</span>':a.isnew?'<span class="badge tr new">New</span>':!a.live?'<span class="badge tr">Stopped</span>':''}${a.stand?'<span class="badge bl stand">Standout</span>':''}${saved.has(a.key)?'<span class="badge br">★</span>':''}</div>
<div class="cbody"><div class="cname">${esc(a.n)}</div>${campLine(a)}${tagLine(a)}
${a.offer?`<div class="coffer">${esc(a.offer)}</div>`:''}${qline(a)}
<div class="crow"><span>${shortDate(a.start)} · ${a.days}d ${a.live?'live':'ran'}</span>${perf(a)}</div></div></button>`).join('')+`</div>`;
} else {
$('#results').innerHTML=`<div class="tblwrap"><table><thead><tr><th></th><th>Resort</th><th>Campaign</th><th>Funnel</th><th>Platform</th><th>Format</th><th>Launched</th><th>Days</th><th>Score</th></tr></thead><tbody>`+
shown.map(a=>`<tr data-id="${a.key}"><td><div class="mini">${a.img?`<img src="${esc(a.img)}" alt="" loading="lazy">`:''}</div></td>
<td><div style="font-weight:600">${esc(a.n)}${a.stand?' <span class="badge stand" style="position:static">Standout</span>':''}${a.gone?' <span class="badge warn" style="position:static">Unavailable</span>':''}</div><div class="copyline">${esc(a.gone?'Content unavailable: '+why(a):(a.offer||a.copy||'No copy captured'))}</div>${tagLine(a)}</td>
<td>${campLine(a)}</td><td class="num">${esc(a.obj||'—')}</td><td class="num">${PN[a.p]}</td><td class="num">${esc(a.kind)}</td><td class="num">${fmtDate(a.start)}</td><td class="num">${a.days}d ${a.live?'':'(stopped)'}</td>
<td>${perf(a)}</td></tr>`).join('')+`</tbody></table></div>`;
}
if(list.length>shown.length) $('#results').insertAdjacentHTML('beforeend',`<div style="text-align:center;margin:18px 0"><button class="btn" id="more">Show ${Math.min(240,list.length-shown.length)} more of ${list.length-shown.length}</button></div>`);
}

function scoreBlock(a){if(window.scoreBlock2)return window.scoreBlock2(a,{esc,tier,PN});
const pp=a.parts||[null,null,null];
const rows=[
['Run length vs this resort’s normal',pp[0],60,`${a.days}d ${a.live?'live so far':'total'} vs this resort’s typical ${a.norm||'—'}d on ${PN[a.p]}.${a.live?' Still running, so this is a minimum.':''}`],
['Staying power',pp[1],20,`${a.days} days. Full points at 90+ days.`],
['Multiple versions',pp[2],20,(a.versions>1?`${a.versions} versions run together.`:a.kind==='Dynamic'?'Dynamic creative (Meta mixes several versions).':'Runs a single version.')],
];
return `<div class="sec score"><div class="schead"><h3>Winner score</h3>${a.ws==null?'<span class="ws early">Too early</span>':`<span class="ws big ${tier(a.ws)}">${a.ws}</span><span class="note">of 100 · estimated from how the resort runs it</span>`}</div>
${a.ws==null?'<p class="note">Launched under a week ago. Ads get a score after a week.</p>':''}
<div class="sgrid">${rows.map(([k,v,max,txt])=>`<div class="srow"><div class="sl"><b>${k}</b><span>${esc(txt)}</span></div><div class="sbar"><i style="width:${v==null?0:Math.round(v/max*100)}%"></i></div><div class="sv">${v==null?'—':v}<small>/${max}</small></div></div>`).join('')}</div></div>`;
}

const pct=x=>Math.round(x*100)+'%';
function playbook(n){
const ALL=ADS.filter(a=>a.n===n), A=ALL.filter(a=>!a.gone), X=ALL.length-A.length;
const M=A.filter(a=>a.p==='meta'), G=A.filter(a=>a.p==='google');
const ML=M.filter(a=>a.live), GL=G.filter(a=>a.live);
const allMed=p=>median(ADS.filter(a=>a.p===p&&!a.gone).map(a=>a.days));
const medM=median(M.map(a=>a.days)), medG=median(G.map(a=>a.days));
const batches={}; M.forEach(a=>batches[a.start]=(batches[a.start]||0)+1);
const big=Object.entries(batches).sort((x,y)=>y[1]-x[1])[0];
const multi=M.length?M.filter(a=>a.versions>1||a.kind==='Dynamic').length/M.length:0;
const camp={}; A.forEach(a=>{const c=a.camp[0]; camp[c]=(camp[c]||0)+1;});
const fmt={}; A.forEach(a=>{const k=PN[a.p]+' '+a.kind; fmt[k]=(fmt[k]||0)+1;});
const fmts=Object.entries(fmt).sort((x,y)=>y[1]-x[1]);
const fun={}; A.forEach(a=>{ if(a.obj) fun[a.obj]=(fun[a.obj]||0)+1; });
const top=A.filter(a=>a.ws!=null&&a.live).sort((x,y)=>y.ws-x.ws)[0];
const advs=[...new Set(G.map(a=>a.advertiser).filter(Boolean))];
const reads=[];
if(M.length) reads.push(`Meta: <b>${ML.length} live ads</b>; median run <b>${Math.round(medM)} days</b> vs ${Math.round(allMed('meta'))} across tracked resorts.`);
if(big&&big[1]>2) reads.push(`Biggest Meta launch: <b>${big[1]} ads on ${shortDate(big[0])}</b>, likely a creative test or a big push.`);
if(M.length) reads.push(`<b>${pct(multi)}</b> of Meta ads run several versions or dynamic creative.`);
if(G.length) reads.push(`Google: <b>${G.length} ads</b> on record (${GL.length} shown in the last few days); median ${Math.round(medG)} days served.`);
if(fmts.length) reads.push(`Leans on <b>${esc(fmts[0][0])}</b> (${fmts[0][1]} of ${A.length} ads).`);
const funs=Object.entries(fun).sort((x,y)=>y[1]-x[1]);
if(funs.length) reads.push(`Funnel mix: ${funs.map(([k,v])=>`<b>${esc(k)}</b> ${pct(v/A.length)}`).join(' · ')}.`);
const past=A.filter(a=>a.live&&a.deadline&&a.deadline<TODAY).length;
if(past) reads.push(`<b>${past} ${past===1?'ad is':'ads are'} still running past the deadline in ${past===1?'its':'their'} copy</b> — the offer was likely extended.`);
if(advs.length) reads.push(`Google ads run under <b>${esc(advs.join(', '))}</b>${advs.length>1?' (more than one advertiser — possibly an agency change)':''}.`);
if(X) reads.push(`<b>${X} ${X===1?'ad':'ads'}</b> could not be captured (error page, blank or empty) and ${X===1?'is':'are'} kept in the Unavailable bucket.`);
const r=L.resorts.find(x=>x.n===n)||{};
return `<section class="pb" aria-label="Resort playbook">
<div class="pbh"><h2>Playbook</h2><span class="note">Meta checked ${shortDate(r.checked_meta)||'—'} · Google checked ${shortDate(r.checked_google)||'—'}</span></div>
<div class="pbstats">
<div><span>Live on Meta</span><b>${ML.length}</b><small>${M.length} seen in total</small></div>
<div><span>Meta median run</span><b>${M.length?Math.round(medM)+'d':'—'}</b><small>all resorts ${Math.round(allMed('meta'))}d</small></div>
<div><span>Google ads</span><b>${G.length}</b><small>${GL.length} recently shown</small></div>
<div><span>New this week</span><b>${A.filter(a=>a.isnew).length}</b></div>
<div><span>Unavailable</span><b>${X}</b><small>${X?'<button type="button" class="lnk" data-go="gone">Show them</button>':'every ad loaded'}</small></div>
</div>
<div class="pbtl"><h3>Timeline · follows the campaign tabs and filters below</h3><div id="tlx"></div></div>
<div class="pbgrid">
<div class="pbcol">
<h3>Campaign mix</h3>
<div class="mix">${Object.entries(camp).sort((x,y)=>y[1]-x[1]).map(([c,v])=>`<i style="flex:${v};background:${CC[c]||'#999'}" title="${esc(c)}: ${v}"></i>`).join('')}</div>
<div class="legend">${Object.entries(camp).sort((x,y)=>y[1]-x[1]).map(([c,v])=>`<span><i class="dot" style="background:${CC[c]||'#999'}"></i>${esc(c)} ${v}</span>`).join('')}</div>
<h3>Formats</h3><div class="legend">${fmts.map(([k,v])=>`<span class="fchip">${esc(k)} ×${v}</span>`).join('')}</div>
</div>
<div class="pbcol">
<h3>What it does</h3><ul class="reads">${reads.map(x=>`<li>${x}</li>`).join('')}</ul>
${top?`<h3>Top-scoring live ad</h3><button class="topad" data-id="${top.key}"><div class="mini">${top.img?`<img src="${esc(top.img)}" alt="">`:''}</div><div style="min-width:0"><div style="font-weight:600">${esc(top.camp[0])} · ${PN[top.p]} ${esc(top.kind)}</div><div class="note">${shortDate(top.start)} · ${top.days}d live${top.offer?' · '+esc(top.offer):''}</div></div>${perf(top)}</button>`:''}
${r.domain?`<h3>Links</h3><div class="legend"><a href="https://${esc(r.domain)}" target="_blank" rel="noopener">${esc(r.domain)}</a>${r.meta_page_id?` · <a href="https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&view_all_page_id=${esc(r.meta_page_id)}" target="_blank" rel="noopener">Meta Ad Library</a>`:''} · <a href="https://adstransparency.google.com/?domain=${esc(r.domain)}&region=US" target="_blank" rel="noopener">Google Transparency</a></div>`:''}
</div>
</div></section>`;
}

// what we know about an ad's capture health (set by quality.py on every run)
function qbox(a){
const q=a.q||{}, when=q.d?(/^\d{4}-\d\d-\d\d/.test(q.d)?fmtDate(String(q.d).slice(0,10)):esc(q.d)):'';
if(a.gone) return `<div class="qbox gone"><b>Unavailable · content couldn’t be captured</b><span>We know this ad ran${a.start?' from '+fmtDate(a.start):''} on ${PN[a.p]}, but its creative came back broken: ${esc(why(a))}${q.msg&&q.msg!==q.why?' ('+esc(q.msg)+')':''}. Everything below is what we do know about it. The ${PN[a.p]} link may still show the original.${when?' Flagged '+when+'.':''}</span></div>`;
if(q.st==='text') return `<div class="qbox text"><b>Picture unavailable</b><span>The image or video frame was broken${q.why?' ('+esc(q.why)+')':''}, so this ad is shown with the text we captured.${when?' Checked '+when+'.':''}</span></div>`;
if(q.st==='fixed') return `<div class="qbox fixed"><b>Picture repaired</b><span>The first copy was broken${q.why?' ('+esc(q.why)+')':''} and was fetched again${q.src?' from '+esc(q.src):''}.${when?' '+when+'.':''}</span></div>`;
return '';
}
function labels(a){
const L2=[['obj','Funnel stage',a.obj?[a.obj]:[]],['aud','Audience',a.aud],['ot','Offer type',a.ot],['fl','Flight',a.fl?[a.fl]:[]],['sn','Season',a.sn?[a.sn]:[]]].filter(x=>x[2].length);
if(!L2.length) return '';
return `<div class="sec"><h3>Labels</h3><dl class="tags">${L2.map(([k,l,v])=>`<div><dt>${l}</dt><dd>${v.map(x=>`<button type="button" class="tagbtn" data-tk="${k}" data-tv="${esc(x)}" title="Show every ad labeled ${esc(x)}">${esc(x)}</button>`).join('')}</dd></div>`).join('')}</dl><p class="note">Click a label to see every ad with it.</p></div>`;
}

function openAd(id){
const a=ADS.find(x=>x.key===id); if(!a) return;
const d=$('#drawer');
const libLink=a.p==='meta'?'Open in Meta Ad Library ↗':'Open in Google Ads Transparency ↗';
const yt=a.yt?'https://www.youtube.com/watch?v='+a.yt:'';
d.innerHTML=`<div class="dhead"><div><h2 id="dtitle">${esc(a.n)}</h2><div class="sub">${esc(STATE[a.s]||a.s)} · ${PN[a.p]} ${esc(a.kind)}${a.advertiser?' · '+esc(a.advertiser):''}${a.gone?' · <b style="color:#B42318">Unavailable</b>':''}</div></div>
<div class="acts"><button class="btn" id="saveBtn">${saved.has(a.key)?'★ Saved':'☆ Save'}</button><button class="btn" id="closeBtn">Close</button></div></div>
<div class="dbody">
${qbox(a)}
<div class="dtop"><div class="thumb dthumb">${visual(a,true)}</div>
<div style="display:grid;gap:10px;min-width:0;align-content:start">
<div>${campLine(a,true)}</div>
${a.offer?`<div class="offerbig">${esc(a.offer)}</div>`:''}
${(a.themes.length||a.prices.length)?`<div class="chips">${a.themes.map(t=>`<span class="chip">${esc(t)}</span>`).join('')}${a.prices.map(p=>`<span class="chip price">${esc(p)}</span>`).join('')}</div>`:''}
<dl class="perfrow">
<dt>Launched</dt><dd>${fmtDate(a.start)}</dd>
<dt>${a.live?'Live':'Ran'}</dt><dd>${a.days} ${a.days===1?'day':'days'}${a.live?' so far':` · stopped ${shortDate(a.end)}`}</dd>
${a.deadline?(a.deadline<TODAY&&a.live?`<dt>Deadline</dt><dd><b>Still running past its stated deadline (${shortDate(a.deadline)}).</b> The offer was probably extended.</dd>`:`<dt>Deadline</dt><dd>${shortDate(a.deadline)}</dd>`):''}
</dl>
</div></div>
${a.gone?'':scoreBlock(a)}
${a.stand?`<div class="why"><b>Why it stands out</b><span>${esc(a.stand)}</span></div>`:''}
${labels(a)}
<div class="sec"><h3>Ad copy</h3>${a.title?`<p class="copyhead">${esc(a.title)}</p>`:''}${a.body?`<p class="copyblk">${esc(a.body)}</p>`:''}${a.desc?`<p class="note">${esc(a.desc)}</p>`:''}
${(a.headlines||[]).length>1?`<p class="note"><b>Other headlines:</b> ${a.headlines.slice(1).map(esc).join(' · ')}</p>`:''}
${a.seen_text?`<p class="copyblk"><span class="note">Text on the image (read by AI):</span><br>${esc(a.seen_text)}</p>`:''}
${!a.title&&!a.body&&!a.seen_text?`<p class="copyblk note">${a.gone?'No copy could be captured because the ad content was unavailable.':'No copy captured for this ad yet.'}</p>`:''}</div>
<dl class="facts">
<div><dt>Platform</dt><dd>${PN[a.p]}${a.plats?' · '+esc(a.plats.join(', ')):''}</dd></div>
<div><dt>Format</dt><dd>${esc(a.kind)}${a.fmt&&a.fmt!==a.kind.toUpperCase()?' ('+esc(a.fmt)+')':''}${a.versions>1?' · '+a.versions+' versions':''}</dd></div>
<div><dt>Button</dt><dd>${esc(a.cta||'—')}</dd></div>
<div><dt>Landing page</dt><dd>${a.link?`<a href="${esc(a.link)}" target="_blank" rel="noopener">${esc(a.link.replace(/^https?:\/\//,'').slice(0,60))}</a>`:'—'}</dd></div>
${a.regions?`<div><dt>Regions</dt><dd>${esc(a.regions.join(', '))}</dd></div>`:''}
${a.surfaces?`<div><dt>Shown on</dt><dd>${esc(a.surfaces.join(', '))}</dd></div>`:''}
<div><dt>First seen by tracker</dt><dd>${fmtDate(a.first_seen)}</dd></div><div><dt>Last seen</dt><dd>${fmtDate(a.last_seen)}</dd></div>
</dl>
<div style="display:flex;gap:8px;flex-wrap:wrap">${a.url?`<a class="btn" href="${esc(a.url)}" target="_blank" rel="noopener">${libLink}</a>`:''}${yt?`<a class="btn" href="${esc(yt)}" target="_blank" rel="noopener">Watch on YouTube ↗</a>`:''}<button class="btn" id="goResort">All ads from ${esc(a.n)}</button></div>
${a.p==='meta'&&a.kind==='Video'&&!a.gone?'<p class="note">Video ads show their poster frame here; the Meta Ad Library link plays the video while the ad is running.</p>':''}
</div>`;
if(!d.open) d.showModal(); d.scrollTop=0; if(window.mediaHook&&!a.gone)window.mediaHook(a,d);
$('#closeBtn').onclick=()=>d.close();
$('#saveBtn').onclick=()=>{saved.has(a.key)?saved.delete(a.key):saved.add(a.key);persist();render();openAd(a.key);};
$('#goResort').onclick=()=>{d.close();go({t:'n',v:a.n});};
}

const SEGS=[['#dates','d','d'],['#kinds','kind','k'],['#plats','plat','p'],['#status','status','s']];
function syncSegs(){ SEGS.forEach(([id,key,attr])=>$(id).querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',x.dataset[attr]===st[key]))); $('#custom').hidden=st.d!=='custom'; }
function setF(k,v){ st[k]=v; st.limit=0; syncSegs(); render(); }
function clearF(k){
if(k==='q'||k==='*') $('#q').value='';
if(k==='camp'||k==='*') st.camp=null;
['d','kind','plat','status'].concat(FACETS.map(f=>f[0])).forEach(x=>{ if(k===x||k==='*') st[x]='all'; });
st.limit=0; syncSegs(); render();
}
function go(f){
st.limit=0;
if(f.t==='gone'){ st.folder={t:'all'}; st.status='gone'; syncSegs(); closeSide(); render(); window.scrollTo({top:0}); return; }
if(st.status==='gone'){ st.status='all'; syncSegs(); }
st.folder=f;
if(f.t==='s'||f.t==='n'){ const a0=ADS.find(a=>f.t==='s'?a.s===f.v:a.n===f.v); st.open['rg:'+a0.rg]=true; st.open['s:'+a0.s]=true; }
closeSide(); render(); window.scrollTo({top:0});
}
function closeSide(){ $('#side').classList.remove('open'); $('#scrim').classList.remove('on'); $('#browseBtn').setAttribute('aria-expanded','false'); }

// header counts
$('#srcs').innerHTML=`<span class="src on">Meta · ${ADS.filter(a=>a.p==='meta'&&!a.gone).length}</span><span class="src on g">Google · ${ADS.filter(a=>a.p==='google'&&!a.gone).length}</span>`;
$('#updated').textContent='updated '+shortDate(L.last_check||L.today);

$('#side').addEventListener('click',e=>{
const t=e.target.closest('[data-tog]'); if(t){ e.preventDefault(); e.stopPropagation(); const k=t.dataset.tog; st.open[k]=k.startsWith('rg:')?st.open[k]===false:!st.open[k]; renderSide(); return; }
const n=e.target.closest('[data-f]'); if(n) go(JSON.parse(n.dataset.f));
});
$('#crumbs').addEventListener('click',e=>{const n=e.target.closest('[data-f]'); if(n) go(JSON.parse(n.dataset.f));});
$('#tabs').addEventListener('click',e=>{const t=e.target.closest('[data-c]'); if(t){ st.camp=t.dataset.c||null; st.limit=0; render(); }});
$('#facets').addEventListener('change',e=>{const s=e.target.closest('[data-fa]'); if(s){ st[s.dataset.fa]=s.value; st.limit=0; render(); }});
$('#active').addEventListener('click',e=>{const b=e.target.closest('[data-x]'); if(b) clearF(b.dataset.x);});
document.addEventListener('click',e=>{const g=e.target.closest('[data-go]'); if(g){ e.preventDefault(); setF('status',g.dataset.go); window.scrollTo({top:0}); }});
function seg(id,key,attr,after){ $(id).addEventListener('click',e=>{const b=e.target.closest('button'); if(!b) return; st[key]=b.dataset[attr]; st.limit=0; $(id).querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',x===b)); after&&after(); render();}); }
seg('#dates','d','d',()=>{$('#custom').hidden=st.d!=='custom';});
seg('#kinds','kind','k'); seg('#plats','plat','p'); seg('#status','status','s');
seg('#views','view','v',()=>{try{localStorage.setItem('ral-view',JSON.stringify({view:st.view}))}catch(e){}});
document.querySelectorAll('#views button').forEach(x=>x.setAttribute('aria-pressed',x.dataset.v===st.view));
$('#dfrom').value=addDays(TODAY,-60); $('#dto').value=TODAY;
$('#dfrom').addEventListener('change',render); $('#dto').addEventListener('change',render);
$('#sort').addEventListener('change',e=>{st.sort=e.target.value;render();});
let qt; $('#q').addEventListener('input',()=>{clearTimeout(qt); qt=setTimeout(()=>{st.limit=0;render();},120);});
$('#helpBtn').addEventListener('click',e=>{const h=$('#helpbox'); h.hidden=!h.hidden; e.currentTarget.setAttribute('aria-expanded',!h.hidden);});
$('#results').addEventListener('click',e=>{ if(e.target.id==='more'){ st.limit=(st.limit||240)+240; render(); return; } const c=e.target.closest('[data-id]'); if(c) openAd(c.dataset.id);});
$('#playbook').addEventListener('click',e=>{ if(e.target.closest('#tlx')) return; const c=e.target.closest('[data-id]'); if(c) openAd(c.getAttribute('data-id'));});
$('#drawer').addEventListener('click',e=>{
if(e.target.id==='drawer'){ e.target.close(); return; }
const t=e.target.closest('.tagbtn'); if(t){ $('#drawer').close(); setF(t.dataset.tk,t.dataset.tv); window.scrollTo({top:0}); }
});
$('#browseBtn').addEventListener('click',()=>{const o=!$('#side').classList.contains('open'); $('#side').classList.toggle('open',o); $('#scrim').classList.toggle('on',o); $('#browseBtn').setAttribute('aria-expanded',o);});
$('#scrim').addEventListener('click',closeSide);
render();
})();

