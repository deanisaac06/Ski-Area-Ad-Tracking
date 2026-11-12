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
vals.sort(k==='sn'?(x,y)=>y.localeCompare(x):(x,y)=>{const i=
