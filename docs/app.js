(async()=>{
const app=document.getElementById('app');
const getJSON=async u=>{const r=await fetch(u);if(!r.ok)throw new Error(u+' '+r.status);return r.json()};
let D,SF;
try{D=await getJSON('data/index.json');SF=await Promise.all(D.years.map(y=>getJSON(`data/summary/${y}.json`)))}
catch(e){app.innerHTML='<p>Could not load data/index.json. If you opened index.html by double-clicking, start a local server first (see README.md).</p>';return}
const F={};
D.game_fields.forEach((f,i)=>F[f]=i);
const C=D.config,MIN=C.min_games||15,LEAGUES=C.leagues||C.tier1,EVENTS=C.events||[],EV=new Set(EVENTS),TIER=C.tiers||{},
MAJ=LEAGUES.filter(l=>TIER[l]=='major'),
SHARED=Object.values(C.baseline_groups||{}).filter(g=>g.length>1).map(g=>g.join(', ').replace(/, ([^,]*)$/,' and $1')+' share one').join('; ');
const RL={top:'Top',jng:'Jungle',mid:'Mid',bot:'Bot',sup:'Support'};
const norm=s=>s.normalize('NFD').replace(/[\u0300-\u036f]/g,'');
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const f2=x=>x==null||isNaN(x)?'—':x.toFixed(2);
const rc=x=>x>=1.15?'good':x<=0.9?'bad':'';
const INTL='INTL',NAME=l=>(C.names||{})[l]||l,LN=L=>L=='all'?'All leagues':L=='major'?'Major leagues':L==INTL?'International':NAME(L);
const COMB=L=>L=='all'||L=='major';   // the boards that combine leagues
// tier of a league: Major / Tier 2 / Tier 3 / Event, shown as a small tag
const TT=l=>({major:'Major',tier2:'Tier 2',tier3:'Tier 3',event:'Event'})[TIER[l]]||'';
const tag=l=>TT(l)?` <span class="tag">${TT(l)}</span>`:'';
const st={lg:LEAGUES.includes('LEC')?'LEC':LEAGUES[0],role:'all',split:'all',stage:'all',year:'all',plg:'all',all:0,pg:0};
const yr=g=>g[F.date].slice(0,4),YEARS=D.years.map(String);
const ORD=(yi,seq)=>yi*1e7+seq;   // position in the overall date order (year, then place within the year)

// summary rows: one per player x league x split x stage, holding the sums rateSums() needs.
// They are shaped like game rows (same F positions for league, kind, period, split, stage, team, date=year) so keep() works on both.
const SUM=[];
SF.forEach((f,yi)=>{const S={};f.fields.forEach((k,i)=>S[k]=i);
  for(const r of f.rows){const c=[];for(const k of ['league','kind','period','split','stage','team'])c[F[k]]=r[S[k]];c[F.date]=YEARS[yi];
    c.pi=r[S.player];c.games=r[S.games];c.sums={n:r[S.n],sw:r[S.sw],swd:r[S.swd],sw2:r[S.sw2],s1:r[S.s1],s2:r[S.s2]};
    c.first=ORD(yi,r[S.first]);c.last=ORD(yi,r[S.last]);SUM.push(c)}});
SUM.sort((a,b)=>a.first-b.first);

// which games a league choice covers, and whether a game (or summary row) passes the current filters
// Major leagues: domestic games of the major leagues plus international games. All leagues: every game.
// On the combined boards a split means the common split name, so only major-league games match one.
const inL=(g,L)=>L=='all'||(L=='major'?g[F.kind]=='international'||g[F.kind]=='domestic'&&TIER[g[F.league]]=='major'
  :L==INTL?g[F.kind]=='international':g[F.league]==L&&g[F.kind]==(EV.has(L)?'event':'domestic'));
const keep=(g,L)=>inL(g,L)&&(st.split=='all'||(L==INTL?g[F.league]:g[F.period])==st.split&&(!COMB(L)||TIER[g[F.league]]=='major'))
  &&(st.stage=='all'||g[F.stage]==st.stage)&&(st.year=='all'||yr(g)==st.year);
const sp={};
const splits=L=>sp[L]||(sp[L]=[...new Set(SUM.filter(g=>inL(g,L)&&(!COMB(L)||TIER[g[F.league]]=='major')).map(g=>L==INTL?g[F.league]:g[F.period]).filter(x=>x!=null))]);
const HAS_INTL=SUM.some(g=>g[F.kind]=='international');
// regional split names behind each common split name ("Winter" = LEC Versus, LCK Cup, ...)
const RN={};
for(const g of SUM)if(g[F.kind]=='domestic'&&g[F.period]&&g[F.split]){const a=((RN[g[F.league]]=RN[g[F.league]]||{})[g[F.period]]=RN[g[F.league]][g[F.period]]||[]);if(!a.includes(g[F.split]))a.push(g[F.split])}
const rname=(L,s)=>{const a=(RN[L]||{})[s];return a&&a.join('/')!=s?a.join('/'):''};
const regions=s=>MAJ.filter(l=>(RN[l]||{})[s]).map(l=>l+' '+RN[l][s].join('/')).join(', ');
const legend=()=>{const ss=[...new Set(MAJ.flatMap(splits))];
  return ss.length&&Object.keys(RN).length?'Splits: '+ss.map(s=>s+' = '+regions(s)).join(' · ')+'.':''};

// players come from the index; their games are loaded on their page only
const PF={};D.players.fields.forEach((k,i)=>PF[k]=i);
const list=D.players.rows.map((r,i)=>({i,name:r[PF.name],role:r[PF.role],team:r[PF.team],league:r[PF.league],ngames:r[PF.games],files:r[PF.files],games:null})),seen={};
list.forEach(p=>{
  let s='p-'+norm(p.name).toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')+'-'+p.role;
  seen[s]=(seen[s]||0)+1;if(seen[s]>1)s+='-'+seen[s];
  p.slug=s;p.n=norm(p.name).toLowerCase();
});
const files={};
const loadFile=k=>files[k]||(files[k]=getJSON(`data/games/${k}.json`).catch(e=>{delete files[k];throw e}));
async function gamesOf(p){
  if(p.games)return p.games;
  const fs=await Promise.all(p.files.map(loadFile)),rows=[];
  fs.forEach((f,i)=>{const yi=YEARS.indexOf(p.files[i].slice(0,4));
    f.rows.forEach((r,j)=>{if(F.pi!=null?r[F.pi]==p.i:r[F.player]==p.name&&r[F.role]==p.role)rows.push([ORD(yi,f.seq[j]),r])})});
  return p.games=rows.sort((a,b)=>a[0]-b[0]).map(x=>x[1]);
}

// rating for a set of games, from sums: weighted count, weighted deviation, squared weights, and the deviations' sum and square sum (spread)
function sumsOf(gs,m){
  const s={n:0,sw:0,swd:0,sw2:0,s1:0,s2:0};
  for(const g of gs){const r=g[m];if(r==null)continue;const w=g[F.kind]=='international'?C.intl_weight:1;s.n++;s.sw+=w;s.swd+=w*(r-1);s.sw2+=w*w;s.s1+=r-1;s.s2+=(r-1)**2}
  return s;
}
const addSums=(a,b)=>{for(const k in b)a[k]+=b[k];return a};
function rateSums(s,role){
  if(!s.n)return null;
  const c=C.c_by_role[role],den=s.sw+C.K;
  const sd=s.n>1?Math.sqrt(Math.max(0,(s.s2-s.s1*s.s1/s.n)/(s.n-1))):0;
  const x=1+c*s.swd/den,h=1.645*c*sd*Math.sqrt(s.sw2)/den;
  return{x,lo:x-h,hi:x+h,n:s.n};
}
const rate=(gs,m)=>gs.length?rateSums(sumsOf(gs,m),gs[0][F.role]):null;
// min games: the configured minimum, lowered for small selections (one split) to half the most games anyone has in it
const lb={};
function board(L){
  const k=[L,st.split,st.stage,st.year].join('|');
  if(lb[k])return lb[k];
  const agg=new Map();
  for(const c of SUM){if(!keep(c,L))continue;
    let a=agg.get(c.pi);if(!a)agg.set(c.pi,a={pi:c.pi,games:0,s:{n:0,sw:0,swd:0,sw2:0,s1:0,s2:0},last:-1,team:null});
    a.games+=c.games;addSums(a.s,c.sums);if(c.last>a.last){a.last=c.last;a.team=c[F.team]}}
  const sel=[...agg.values()].sort((a,b)=>a.pi-b.pi);
  const thr=Math.max(1,Math.min(MIN,Math.ceil(sel.reduce((a,x)=>Math.max(a,x.games),0)/2)));
  const rows=sel.filter(x=>x.games>=thr).map(x=>({p:list[x.pi],team:x.team,r:rateSums(x.s,list[x.pi].role)}))
    .filter(x=>x.r).sort((a,b)=>b.r.x-a.r.x);
  return lb[k]={rows,thr};
}
// short label of the current selection, e.g. "LEC · Winter (Versus) · Playoffs · 2026"
function selection(L){
  const s=[LN(L)];
  if(st.split!='all'){const r=L==INTL?'':rname(L,st.split);s.push(st.split+(r?` (${r})`:''))}
  if(st.stage!='all')s.push(st.stage=='playoffs'?'Playoffs':'Regular season');
  if(st.year!='all')s.push(st.year);
  return s.join(' · ');
}
function describe(L,thr){
  return selection(L)+(TT(L)?` (${TT(L)})`:'')+(st.stage=='all'?' · regular season and playoffs':' only')+(thr?` · players with ${thr}+ games`:'');
}
// footnote: how the games are weighted and rated, and which leagues have partial data
function notes(L){
  const s=[],part=Object.entries(C.complete||{}).filter(([l])=>L=='all'||l==L||L=='major'&&TIER[l]=='major');
  if(L==INTL)s.push('International games are rated against their own baseline.');
  else if(COMB(L)){
    if(st.split=='all')s.push(`International games count ${C.intl_weight}×`+(L=='all'?', events and qualifiers count 1× (not as international games).':'.'));
    else s.push(`A split covers the major leagues only (other leagues use their own split names).`);
    s.push(`Every league is rated against its own baseline${SHARED?' ('+SHARED+')':''}, so ratings from different leagues are not directly comparable.`);
  }else if(EV.has(L))s.push('Each team is rated against its home league’s baseline.');
  if(part.length)s.push('Only games with full stats count ('+part.map(([l,v])=>`${l}: ${Math.round(v*100)}% of games`).join(', ')+').');
  return s.join(' ');
}
// league options, grouped: combined boards, major, tier 2, tier 3, events, international
function groups(lgs){
  const G=[['Combined',l=>COMB(l)],['Major',l=>TIER[l]=='major'],['Tier 2',l=>TIER[l]=='tier2'],['Tier 3',l=>TIER[l]=='tier3'],['Events',l=>EV.has(l)],['International',l=>l==INTL]];
  return G.map(([t,f])=>[t,lgs.filter(f)]).filter(([,ls])=>ls.length);
}
// shared filter bar: one row of dropdowns (league, split/event, stage, year, and role on the leaderboard)
function filters(el,lgs,L,setL,redraw,roles){
  const sl=splits(L),on=st.split!='all'||st.stage!='all'||st.year!='all'||(roles&&st.role!='all');
  const note=COMB(L)?regions(st.split):L!=INTL&&rname(L,st.split)?L+' '+rname(L,st.split):'';
  const opt=(items,cur)=>items.map(([k,l,t])=>`<option value="${esc(k)}"${k==cur?' selected':''}${t?` title="${esc(t)}"`:''}>${esc(l)}</option>`).join('');
  const sel=(id,label,items,cur)=>`<select id="${id}" aria-label="${label}" class="${cur!='all'&&id!='f-lg'?'on':''}">${opt(items,cur)}</select>`;
  el.innerHTML=`<div class="fbar">
  <select id="f-lg" aria-label="League">${groups(lgs).map(([t,ls])=>`<optgroup label="${t}">${opt(ls.map(l=>[l,LN(l)]),L)}</optgroup>`).join('')}</select>
  ${sl.length?sel('f-sp',L==INTL?'Event':'Split',[['all',L==INTL?'All events':'All splits'],...sl.map(s=>{const r=L==INTL?'':rname(L,s);return[s,s,COMB(L)?regions(s):r?`${L} calls it ${r}`:'']})],st.split):''}
  ${sel('f-st','Stage',[['all','All stages'],['regular','Regular season'],['playoffs','Playoffs']],st.stage)}
  ${sel('f-yr','Year',[['all','All years'],...YEARS.map(y=>[y,y])],st.year)}
  ${roles?sel('f-rl','Role',[['all','All roles'],...Object.entries(RL)],st.role):''}
  ${on?'<button class="link" id="f-reset">Reset</button>':''}</div>
  ${sl.length&&st.split!='all'&&note?`<div class="mut sm fnote">${esc(st.split)} = ${esc(note)}</div>`:''}`;
  const ch=(id,f)=>{const s=el.querySelector('#'+id);if(s)s.onchange=()=>{f(s.value);st.all=0;redraw()}};
  ch('f-lg',k=>{setL(k);st.split='all'});
  ch('f-sp',k=>st.split=k);ch('f-st',k=>st.stage=k);ch('f-yr',k=>st.year=k);ch('f-rl',k=>st.role=k);
  const r=el.querySelector('#f-reset');if(r)r.onclick=()=>{st.split=st.stage=st.year='all';if(roles)st.role='all';st.all=0;redraw()};
}

function home(){
  app.innerHTML=`<header class="top"><div><h1>Pro Player Ratings<small>v${esc(D.version||'0.1')}</small></h1>
  <div class="mut sm">Performance ratings from per-game stats. 1.00 is an average performance in the games counted, not a measure of skill.</div></div>
  <div class="srch"><input id="q" type="search" placeholder="Search a player…" autocomplete="off"><div id="res"></div></div></header>
  <div id="fb"></div><div class="tw" id="lb"></div><div id="mb"></div>
  <p class="mut sm" id="fn"></p><p class="mut sm">${esc(legend())}</p>`;
  const q=document.getElementById('q'),res=document.getElementById('res');
  q.oninput=()=>{
    const t=norm(q.value).toLowerCase().trim();
    const m=t?list.filter(p=>p.n.includes(t)).sort((a,b)=>(b.n.startsWith(t)-a.n.startsWith(t))||b.ngames-a.ngames).slice(0,8):[];
    res.innerHTML=m.map(p=>`<a href="#${p.slug}"><span><b>${esc(p.name)}</b> <span class="mut sm">${RL[p.role]}</span></span><span class="mut sm">${esc(p.team)} · ${esc(p.league)}${tag(p.league)}</span></a>`).join('');
  };
  q.onkeydown=e=>{if(e.key=='Enter'){const a=res.querySelector('a');if(a)location.hash=a.getAttribute('href').slice(1)}};
  draw();
}
function draw(){
  const rest=LEAGUES.filter(l=>TIER[l]!='major').sort((a,b)=>NAME(a).localeCompare(NAME(b)));
  filters(document.getElementById('fb'),['major','all',...MAJ,...rest,...EVENTS,...(HAS_INTL?[INTL]:[])],st.lg,k=>st.lg=k,draw,1);
  const b=board(st.lg);
  let rows=b.rows.filter(x=>st.role=='all'||x.p.role==st.role);
  const tot=rows.length;if(!st.all)rows=rows.slice(0,20);
  document.getElementById('lb').innerHTML=`<table class="lbt"><tr><th>#</th><th>Player</th><th>Games</th><th>Rating</th></tr>`+
    (rows.length?rows.map((x,i)=>`<tr><td>${i+1}</td><td class="pl"><a href="#${x.p.slug}">${esc(x.p.name)}</a><div class="mut sub">${esc(x.team)} · ${RL[x.p.role]}${COMB(st.lg)?` · ${esc(x.p.league)}${tag(x.p.league)}`:''}</div></td><td>${x.r.n}</td><td class="${rc(x.r.x)}"><b class="rt">${f2(x.r.x)}</b> <span class="mut sm rng">${f2(x.r.lo)}–${f2(x.r.hi)}</span></td></tr>`).join('')
    :`<tr><td colspan="4" class="mut">No players for these filters.</td></tr>`)+`</table>`;
  const mb=document.getElementById('mb');
  mb.innerHTML=tot>20&&!st.all?`<button class="more" id="more">Show all ${tot}</button>`:'';
  if(mb.firstChild)document.getElementById('more').onclick=()=>{st.all=1;draw()};
  document.getElementById('fn').textContent=`${describe(st.lg,b.thr)}. Ranges are a ~90% interval. ${notes(st.lg)}`;
}

function playerPage(p){
  const ls=[...LEAGUES,...EVENTS,INTL].filter(l=>p.games.some(g=>inL(g,l)));
  if(st.plg!='all'&&!ls.includes(st.plg))st.plg='all';
  const gs=p.games.filter(g=>keep(g,st.plg)),dom=gs.filter(g=>g[F.kind]=='domestic'),intl=gs.filter(g=>g[F.kind]=='international'),n=gs.length;
  const head=`<a href="#home">← All players</a>
  <h1 style="margin-top:8px">${esc(p.name)}</h1>
  <div class="mut">${RL[p.role]} · ${esc(p.team)} · ${esc(p.league)}${tag(p.league)}${(o=>o.length?' · '+esc(o.join(', ')):'')([...new Set(p.games.map(g=>g[F.league]))].filter(l=>l!=p.league))}</div>`;
  const redraw=()=>{st.pg=0;playerPage(p)},bar=()=>filters(document.getElementById('fb'),['all',...ls],st.plg,k=>st.plg=k,redraw);
  if(!n){
    app.innerHTML=head+`<div id="fb" style="margin-top:14px"></div><p class="mut">No games for this player in the selected filters. Change or reset the filters above.</p>`;
    bar();return;
  }
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
  const ev=g=>g[F.league]+(g[F.split]||g[F.period]?' '+esc(g[F.split]||g[F.period]):'')+(g[F.stage]=='playoffs'?' (playoffs)':'');
  app.innerHTML=head+`
  <div id="fb" style="margin-top:14px"></div>
  <div class="cards">${card('Overall rating · '+esc(selection(st.plg)),o,1)}${card('Domestic',d)}${card('International',i)}</div>
  <p class="mut sm">Ranges are a ~90% interval. Overall counts international games ${C.intl_weight}×${p.games.some(g=>g[F.kind]=='event')?', events and qualifiers 1× (they are not in the International rating)':''}. Early game ${f2(e&&e.x)} · Late game ${f2(l&&l.x)}.</p>
  <h2>Stats</h2><div class="cards">
  ${stat('Games',n)}${stat('Win rate',(100*W/n).toFixed(0)+'%')}${stat('KDA',((K+A)/Math.max(De,1)).toFixed(2))}
  ${stat('K / D / A per game',(K/n).toFixed(1)+' / '+(De/n).toFixed(1)+' / '+(A/n).toFixed(1))}
  ${stat('Gold diff @15',gd.length?Math.round(gd.reduce((a,g)=>a+g[F.gd15],0)/gd.length):'—')}</div>
  <h2>Champions</h2><div class="tw"><table><tr><th>Champion</th><th>Games</th><th>Win rate</th><th>KDA</th></tr>
  ${champs.map(([c,v])=>`<tr><td>${esc(c)}</td><td>${v.n}</td><td>${(100*v.w/v.n).toFixed(0)}%</td><td>${((v.k+v.a)/Math.max(v.d,1)).toFixed(2)}</td></tr>`).join('')}</table></div>
  <h2>Games</h2><div class="tw"><table><tr><th>Date</th><th>Rating</th><th></th><th>vs</th><th>Champion</th><th>K/D/A</th><th>GD@15</th><th>Event</th></tr>
  ${shown.map(g=>`<tr><td>${g[F.date]}</td><td class="${rc(g[F.r_overall])}"><b>${f2(g[F.r_overall])}</b></td><td class="${g[F.result]?'good':'bad'}">${g[F.result]?'W':'L'}</td><td>${esc(g[F.opponent]||'—')}</td><td>${esc(g[F.champion])}</td><td>${g[F.kills]}/${g[F.deaths]}/${g[F.assists]}</td><td>${g[F.gd15]==null?'—':Math.round(g[F.gd15])}</td><td>${ev(g)}</td></tr>`).join('')}</table></div>
  ${!st.pg&&rec.length>20?`<button class="more" id="mg">Show all ${rec.length}</button>`:''}`;
  bar();
  const mg=document.getElementById('mg');if(mg)mg.onclick=()=>{st.pg=1;playerPage(p)};
}

let nav=0;
async function route(){
  const h=location.hash.slice(1),p=list.find(x=>x.slug==h),my=++nav;
  st.pg=0;
  if(p){
    if(!p.games){
      app.innerHTML='<p class="mut">Loading…</p>';
      try{await gamesOf(p)}catch(e){if(my==nav)app.innerHTML='<p>Could not load this player’s games. <a href="#home">Back to all players</a></p>';return}
      if(my!=nav)return;
    }
    // a chosen split only makes sense with its league, so carry the league over in that case
    st.plg=st.split!='all'&&p.games.some(g=>inL(g,st.lg))?st.lg:'all';playerPage(p);
  }else home();
  window.scrollTo(0,0);
}
window.addEventListener('hashchange',route);route();
})();
