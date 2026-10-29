(async()=>{
let D;
try{D=await (await fetch('data/site_data.json')).json()}catch(e){document.getElementById('app').innerHTML='<p>Could not load data/site_data.json. If you opened index.html by double-clicking, start a local server first (see README.md).</p>';return}
const F={};
(D.fields||D.game_fields).forEach((f,i)=>F[f]=i);
const C=D.config,MIN=C.min_games||15,LEAGUES=C.leagues||C.tier1,app=document.getElementById('app'),
BG=Object.keys(C.baseline_groups||{}).length>1?' Baseline groups: '+Object.values(C.baseline_groups).map(g=>g.join(', ')).join(' | ')+'. Ratings are not directly comparable between groups.':'';
const RL={top:'Top',jng:'Jungle',mid:'Mid',bot:'Bot',sup:'Support'};
const norm=s=>s.normalize('NFD').replace(/[\u0300-\u036f]/g,'');
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const f2=x=>x==null||isNaN(x)?'—':x.toFixed(2);
const rc=x=>x>=1.15?'good':x<=0.9?'bad':'';
const st={lg:LEAGUES.includes('LEC')?'LEC':LEAGUES[0],role:'all',all:0,pg:0};

const P={};
for(const r of D.games){const k=r[F.player]+'|'+r[F.role];(P[k]=P[k]||{name:r[F.player],role:r[F.role],games:[]}).games.push(r)}
const list=Object.values(P),seen={};
list.forEach(p=>{
  let s='p-'+norm(p.name).toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')+'-'+p.role;
  seen[s]=(seen[s]||0)+1;if(seen[s]>1)s+='-'+seen[s];
  p.slug=s;p.n=norm(p.name).toLowerCase();
  const last=p.games[p.games.length-1],dg=p.games.filter(g=>g[F.kind]=='domestic');
  p.team=last[F.team];p.league=(dg.length?dg[dg.length-1]:last)[F.league];
});

function rate(gs,m){
  let n=0,s=0,w2=0;const v=[];
  for(const g of gs){const r=g[m];if(r==null)continue;const w=g[F.kind]=='international'?C.intl_weight:1;n+=w;s+=w*(r-1);w2+=w*w;v.push(r)}
  if(!v.length)return null;
  const c=C.c_by_role[gs[0][F.role]],den=n+C.K,mu=v.reduce((a,b)=>a+b)/v.length;
  const sd=v.length>1?Math.sqrt(v.reduce((a,b)=>a+(b-mu)**2,0)/(v.length-1)):0;
  const x=1+c*s/den,h=1.645*c*sd*Math.sqrt(w2)/den;
  return{x,lo:x-h,hi:x+h,n:v.length};
}
const lb={};
function board(L){
  return lb[L]||(lb[L]=list.map(p=>{
    const gs=p.games.filter(g=>g[F.league]==L&&g[F.kind]=='domestic');
    return gs.length>=MIN?{p,team:gs[gs.length-1][F.team],r:rate(gs,F.r_overall)}:null;
  }).filter(Boolean).sort((a,b)=>b.r.x-a.r.x));
}
function tabs(el,items,cur,fn){
  el.innerHTML=items.map(([k,l])=>`<button class="${k==cur?'on':''}" data-k="${k}">${l}</button>`).join('');
  el.onclick=e=>{const k=e.target.dataset.k;if(k)fn(k)};
}

function home(){
  app.innerHTML=`<h1>Pro Player Ratings<small>v0.1</small></h1>
  <div class="mut">Performance ratings built from per-game stats. 1.00 is an average performance in the games counted. This is not a measure of skill.</div>
  <input id="q" type="search" placeholder="Search a player…" autocomplete="off"><div id="res"></div>
  <h2>Regional leaderboard</h2><div class="tabs" id="lt"></div><div class="tabs" id="rt"></div><div class="tw" id="lb"></div><div id="mb"></div>
  <p class="mut sm">Each board uses only that league’s games (regular season and playoffs) and players with ${MIN}+ games. Ranges are a ~90% interval.${BG}</p>`;
  const q=document.getElementById('q'),res=document.getElementById('res');
  q.oninput=()=>{
    const t=norm(q.value).toLowerCase().trim();
    const m=t?list.filter(p=>p.n.includes(t)).sort((a,b)=>(b.n.startsWith(t)-a.n.startsWith(t))||b.games.length-a.games.length).slice(0,8):[];
    res.innerHTML=m.map(p=>`<a href="#${p.slug}"><span><b>${esc(p.name)}</b> <span class="mut sm">${RL[p.role]}</span></span><span class="mut sm">${esc(p.team)} · ${p.league}</span></a>`).join('');
  };
  q.onkeydown=e=>{if(e.key=='Enter'){const a=res.querySelector('a');if(a)location.hash=a.getAttribute('href').slice(1)}};
  draw();
}
function draw(){
  tabs(document.getElementById('lt'),LEAGUES.map(l=>[l,l]),st.lg,k=>{st.lg=k;st.all=0;draw()});
  tabs(document.getElementById('rt'),[['all','All'],...Object.entries(RL)],st.role,k=>{st.role=k;st.all=0;draw()});
  let rows=board(st.lg).filter(x=>st.role=='all'||x.p.role==st.role);
  const tot=rows.length;if(!st.all)rows=rows.slice(0,20);
  document.getElementById('lb').innerHTML=`<table><tr><th>#</th><th>Player</th><th>Team</th><th>Role</th><th>Games</th><th>Rating</th></tr>`+
    rows.map((x,i)=>`<tr><td>${i+1}</td><td><a href="#${x.p.slug}">${esc(x.p.name)}</a></td><td>${esc(x.team)}</td><td>${RL[x.p.role]}</td><td>${x.r.n}</td><td class="${rc(x.r.x)}"><b>${f2(x.r.x)}</b> <span class="mut sm">${f2(x.r.lo)}–${f2(x.r.hi)}</span></td></tr>`).join('')+`</table>`;
  const mb=document.getElementById('mb');
  mb.innerHTML=tot>20&&!st.all?`<button class="more" id="more">Show all ${tot}</button>`:'';
  if(mb.firstChild)document.getElementById('more').onclick=()=>{st.all=1;draw()};
}

function playerPage(p){
  const gs=p.games,dom=gs.filter(g=>g[F.kind]=='domestic'),intl=gs.filter(g=>g[F.kind]!='domestic'),n=gs.length;
  const o=rate(gs,F.r_overall),d=dom.length?rate(dom,F.r_overall):null,i=intl.length?rate(intl,F.r_overall):null;
  const e=rate(gs,F.r_early),l=rate(gs,F.r_late);
  const sum=k=>gs.reduce((a,g)=>a+(g[F[k]]||0),0),gd=gs.filter(g=>g[F.gd15]!=null);
  const K=sum('kills'),De=sum('deaths'),A=sum('assists'),W=sum('result');
  const card=(t,r,big)=>r?`<div class="card ${big?'main':''}"><div class="mut sm">${t}</div><div class="${big?'num':'num2'} ${rc(r.x)}">${f2(r.x)}</div><div class="mut sm">${f2(r.lo)}–${f2(r.hi)} · ${r.n} games</div></div>`:'';
  const stat=(l,v)=>`<div class="card"><div class="mut sm">${l}</div><div class="st">${v}</div></div>`;
  const ch={};
  gs.forEach(g=>{const c=ch[g[F.champion]]=ch[g[F.champion]]||{n:0,w:0,k:0,d:0,a:0};c.n++;c.w+=g[F.result];c.k+=g[F.kills];c.d+=g[F.deaths];c.a+=g[F.assists]});
  const champs=Object.entries(ch).sort((a,b)=>b[1].n-a[1].n).slice(0,8);
  const rec=gs.slice().reverse(),shown=st.pg?rec:rec.slice(0,20);
  const leagues=[...new Set(gs.map(g=>g[F.league]))].join(', ');
  app.innerHTML=`<a href="#home">← All players</a>
  <h1 style="margin-top:12px">${esc(p.name)}</h1>
  <div class="mut">${RL[p.role]} · ${esc(p.team)} · ${leagues}</div>
  <div class="cards">${card('Overall rating',o,1)}${card('Domestic',d)}${card('International',i)}</div>
  <p class="mut sm">Ranges are a ~90% interval. Overall counts international games ${C.intl_weight}× . Early game ${f2(e&&e.x)} · Late game ${f2(l&&l.x)}.</p>
  <h2>Stats</h2><div class="cards">
  ${stat('Games',n)}${stat('Win rate',(100*W/n).toFixed(0)+'%')}${stat('KDA',((K+A)/Math.max(De,1)).toFixed(2))}
  ${stat('K / D / A per game',(K/n).toFixed(1)+' / '+(De/n).toFixed(1)+' / '+(A/n).toFixed(1))}
  ${stat('Gold diff @15',gd.length?Math.round(gd.reduce((a,g)=>a+g[F.gd15],0)/gd.length):'—')}
  ${stat('Avg game length',(sum('minutes')/n).toFixed(0)+' min')}</div>
  <h2>Champions</h2><div class="tw"><table><tr><th>Champion</th><th>Games</th><th>Win rate</th><th>KDA</th></tr>
  ${champs.map(([c,v])=>`<tr><td>${esc(c)}</td><td>${v.n}</td><td>${(100*v.w/v.n).toFixed(0)}%</td><td>${((v.k+v.a)/Math.max(v.d,1)).toFixed(2)}</td></tr>`).join('')}</table></div>
  <h2>Games</h2><div class="tw"><table><tr><th>Date</th><th>Event</th><th>vs</th><th>Champion</th><th></th><th>K/D/A</th><th>GD@15</th><th>Rating</th></tr>
  ${shown.map(g=>`<tr><td>${g[F.date]}</td><td>${g[F.league]}${g[F.stage]=='playoffs'?' (playoffs)':''}</td><td>${esc(g[F.opponent]||'—')}</td><td>${esc(g[F.champion])}</td><td class="${g[F.result]?'good':'bad'}">${g[F.result]?'W':'L'}</td><td>${g[F.kills]}/${g[F.deaths]}/${g[F.assists]}</td><td>${g[F.gd15]==null?'—':Math.round(g[F.gd15])}</td><td class="${rc(g[F.r_overall])}"><b>${f2(g[F.r_overall])}</b></td></tr>`).join('')}</table></div>
  ${!st.pg&&rec.length>20?`<button class="more" id="mg">Show all ${rec.length}</button>`:''}
  <p class="mut sm">Time and tournament filters are coming later.</p>`;
  const mg=document.getElementById('mg');if(mg)mg.onclick=()=>{st.pg=1;playerPage(p)};
}

function route(){
  const h=location.hash.slice(1),p=list.find(x=>x.slug==h);
  st.pg=0;p?playerPage(p):home();window.scrollTo(0,0);
}
window.addEventListener('hashchange',route);route();
})();
