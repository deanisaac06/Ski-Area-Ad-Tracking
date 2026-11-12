// Who buys the media: each resort's likely media buyer right now (Google's verified advertiser on its latest ads),
// any switches, and the Ski Area Ad Atlas context. Rebuilt by agency.py on every run; shown on each resort page.
(function(){
const L=window.LIB; if(!L) return;
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]);
const K=v=>v==null||v===''||isNaN(+v)?'':+v>=1000?'$'+(+v/1000).toFixed(1)+'M':'$'+Math.round(+v)+'K';
const KIND={resort:"resort's own account",agency:'agency',person:'freelancer / individual',other:'third party'};
const OP={A:'Open opportunity',B:'Incumbent agency or group decision',C:'Small budget',D:'Parent company (Vail/Alterra)'};
const d=s=>{if(!s) return ''; const x=new Date(s+'T12:00:00Z'); return isNaN(x)?s:x.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'});};
const css=document.createElement('style');
css.textContent='.buyer{margin:10px 0 4px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font-size:13px;line-height:1.5}.buyer h4{margin:0 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}.buyer .bnow{font-size:15px}.buyer .bkind{display:inline-block;font-size:11px;border:1px solid var(--line);border-radius:999px;padding:0 7px;margin-left:6px;color:var(--muted);vertical-align:1px}.buyer .bsw{color:#b4651a;font-weight:600}.buyer ul{margin:6px 0 0;padding-left:18px}.buyer .bfacts{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:6px;color:var(--muted);font-size:12.5px}.buyer .bfacts b{color:var(--ink);font-weight:600}';
document.head.appendChild(css);
window.BUYER=n=>{
  const r=(L.resorts||[]).find(x=>x.n===n); const b=r&&r.buyer; if(!b) return '';
  const c=b.cur, A=b.atlas||{};
  let h='<div class="buyer"><h4>Who buys the media</h4>';
  if(c){
    h+=`<div class="bnow">Likely buyer now: <b>${esc(c.name)}</b><span class="bkind">${esc(KIND[c.kind]||c.kind)}</span></div>`;
    h+=`<div class="note">Google's verified advertiser on ${c.recent?c.recent+' of its Google ads shown in the last 60 days':'its latest Google ads (none shown in the last 60 days)'} · last shown ${d(c.last)}${c.first?' · paying since '+d(c.first):''}</div>`;
  } else h+=`<div class="note">No Google ads with a named advertiser yet, so the buyer can't be read (Meta doesn't disclose who places ads).</div>`;
  const sw=(b.changes||[]).slice().reverse();
  if(sw.length) h+='<ul>'+sw.map(x=>`<li><span class="bsw">Switch spotted ${d(x.date)}:</span> ${x.from?esc(x.from)+' → ':''}<b>${esc(x.to)}</b> (${esc(KIND[x.to_kind]||x.to_kind)})${x.still?', old advertiser still running too':''}</li>`).join('')+'</ul>';
  if(b.others&&b.others.length) h+=`<div class="note">Also seen: ${b.others.map(o=>`${esc(o.name)} (${esc(KIND[o.kind]||o.kind)}, ${o.n} ad${o.n>1?'s':''}, last ${d(o.last)})`).join(' · ')}</div>`;
  const f=[];
  if(K(A.mm)) f.push(`Est. paid media <b>${K(A.mm)}</b>/yr${K(A.mml)?' ('+K(A.mml)+'–'+K(A.mmh)+')':''}`);
  if(A.o) f.push(`Owner <b>${esc(A.o)}</b>${A.ot?' ('+esc(A.ot)+')':''}`);
  if(A.st) f.push(`Atlas: <b>${esc(A.st)}</b>`);
  if(A.ag) f.push(`Atlas agency <b>${esc(A.ag)}</b>`);
  if(A.ga&&(!c||String(A.ga).toLowerCase()!==String(c.name).toLowerCase())) f.push(`Atlas Google advertiser (Nov 2026) <b>${esc(A.ga)}</b>`);
  if(A.op) f.push(`Opportunity <b>${esc(String(A.op)[0])}</b> ${esc(OP[String(A.op)[0]]||'')}`);
  if(f.length) h+='<div class="bfacts">'+f.map(x=>'<span>'+x+'</span>').join('')+'</div>';
  return h+'</div>';
};
})();
