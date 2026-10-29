(async()=>{
const app=document.getElementById('app');
const getJSON=async u=>{const r=await fetch(u);if(!r.ok)throw new Error(u+' '+r.status);return r.json()};
let D,SF;
try{D=await getJSON('data/index.json');SF=await Promise.all(D.years.map(y=>getJSON(`data/summary/${y}.json`)))}
catch(e){app.innerHTML='<p>Could not load data/index.json. If you opened index.html by double-clicking, start a local server first (see README.md).</p>';return}
const F={},TF={};
D.game_fields.forEach((f,i)=>F[f]=i);(D.team_fields||[]).forEach((f,i)=>TF[f]=i);
const C=D.config,MIN=C.min_games||15,LEAGUES=C.leagues||C.tier1,EVENTS=C.events||[],EV=new Set(EVENTS),TIER=C.tiers||{},
MAJ=LEAGUES.filter(l=>TIER[l]=='major'),
SHARED=Object.values(C.baseline_groups||{}).filter(g=>g.length>1).map(g=>g.join(', ').replace(/, ([^,]*)$/,' and $1')+' share one').join('; ');
const RL={top:'Top',jng:'Jungle',mid:'Mid',bot:'Bot',sup:'Support'};
const norm=s=>s.normalize('NFD').replace(/[\u0300-\u036f]/g,'');
const slugify=s=>norm(s).toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const f2=x=>x==null||isNaN(x)?'—':x.toFixed(2);
const rc=x=>x>=1.15?'good':x<=0.9?'bad':'';
const INTL='INTL',NAME=l=>(C.names||{})[l]||l,LN=L=>L=='all'?'All leagues':L=='major'?'Major leagues':L==INTL?'International':NAME(L);
const COMB=L=>L=='all'||L=='major';   // the boards that combine leagues
// tier of a league: Major / Tier 1 / Tier 2 / Tier 3 / Event, shown as a small tag
const TT=l=>({major:'Major',tier1:'Tier 1',tier2:'Tier 2',tier3:'Tier 3',event:'Event'})[TIER[l]]||'';
const tag=l=>TT(l)?` <span class="tag">${TT(l)}</span>`:'';
const st={lg:LEAGUES.includes('LEC')?'LEC':LEAGUES[0],role:'all',split:'all',stage:'all',year:'all',plg:'all',all:0,pg:0,tsort:'elo',tall:0,tlg:'all',tpg:0,eg:'all',eyr:'all',eopen:{},estage:'all'};
const yr=g=>g[F.date].slice(0,4),YEARS=D.years.map(String);
const ORD=(yi,seq)=>yi*1e7+seq;   // position in the overall date order (year, then place within the year)
// runs f with the split/stage/year filters cleared (for previews and header ranks), then puts them back
const unfiltered=f=>{const s={split:st.split,stage:st.stage,year:st.year};st.split=st.stage=st.year='all';try{return f()}finally{Object.assign(st,s)}};

// summary rows: one per player x team x league x split x stage, holding the sums rateSums() needs.
// They are shaped like game rows (same F positions for league, kind, period, split, stage, team, date=year) so keep() works on both.
const SUM=[],TS=[];
SF.forEach((f,yi)=>{const S={};f.fields.forEach((k,i)=>S[k]=i);
  for(const r of f.rows){const c=[];for(const k of ['league','kind','period','split','stage','team'])c[F[k]]=r[S[k]];c[F.date]=YEARS[yi];
    c.pi=r[S.player];c.ti=S.ti!=null?r[S.ti]:null;c.games=r[S.games];c.sums={n:r[S.n],sw:r[S.sw],swd:r[S.swd],sw2:r[S.sw2],s1:r[S.s1],s2:r[S.s2]};
    c.first=ORD(yi,r[S.first]);c.last=ORD(yi,r[S.last]);SUM.push(c)}
  // team summary rows, same shape: games, wins, series, gold diff @15, side, Elo after the last game
  if(f.teams){const T={};f.teams.fields.forEach((k,i)=>T[k]=i);
    for(const r of f.teams.rows){const c=[];for(const k of ['league','kind','period','split','stage'])c[F[k]]=r[T[k]];c[F.date]=YEARS[yi];
      Object.assign(c,{ti:r[T.team],games:r[T.games],wins:r[T.wins],sw:r[T.s_won],sl:r[T.s_lost],gdn:r[T.gd_n],gds:r[T.gd_sum],
        first:ORD(yi,r[T.first]),last:ORD(yi,r[T.last]),elo:r[T.elo]});TS.push(c)}}});
SUM.sort((a,b)=>a.first-b.first);TS.sort((a,b)=>a.first-b.first);

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

// players and teams come from the index; their games are loaded on their page only
const PF={};D.players.fields.forEach((k,i)=>PF[k]=i);
const list=D.players.rows.map((r,i)=>({i,name:r[PF.name],role:r[PF.role],team:r[PF.team],league:r[PF.league],ngames:r[PF.games],files:r[PF.files],games:null})),seen={};
list.forEach(p=>{
  let s='p-'+slugify(p.name)+'-'+p.role;
  seen[s]=(seen[s]||0)+1;if(seen[s]>1)s+='-'+seen[s];
  p.slug=s;p.n=norm(p.name).toLowerCase();
});
const XF={};((D.teams||{}).fields||[]).forEach((k,i)=>XF[k]=i);
const teams=((D.teams||{}).rows||[]).map((r,i)=>({i,name:r[XF.name],league:r[XF.league],ngames:r[XF.games],files:r[XF.files],rows:null})),tseen={},byName={};
teams.forEach(t=>{
  let s='t-'+slugify(t.name);
  tseen[s]=(tseen[s]||0)+1;if(tseen[s]>1)s+='-'+tseen[s];
  t.slug=s;t.n=norm(t.name).toLowerCase();(byName[t.name]=byName[t.name]||[]).push(t);
});
// tournaments: a league split, an event or an international event; key = year|league|kind|split (the game-row fields).
// League games without a split label in the data are in no tournament.
const TRF={};((D.tournaments||{}).fields||[]).forEach((k,i)=>TRF[k]=i);
const TOURS=((D.tournaments||{}).rows||[]).map((r,i)=>{const e={i,from:[],to:[],rows:null};for(const k in TRF)e[k]=r[TRF[k]];return e}),TK={},eseen={};
TOURS.forEach(e=>{e.tier=e.tier||TIER[e.league];TK[[e.year,e.league,e.kind,e.split??''].join('|')]=e;e.short=e.name.replace(/\s*\(.*\)$/,'');
  let s='e-'+slugify(e.short+' '+e.year);eseen[s]=(eseen[s]||0)+1;if(eseen[s]>1)s+='-'+eseen[s];
  e.slug=s;e.n=norm(e.name+' '+e.year).toLowerCase();e.ngames=e.games});
// qualification paths: teams that played an earlier tournament and then this one (see tournament_links in the pipeline)
(D.tournament_links||[]).forEach(([a,b,xs])=>{TOURS[a].to.push({e:TOURS[b],xs});TOURS[b].from.push({e:TOURS[a],xs})});
const tourOf=g=>TK[[String(g[F.date]).slice(0,4),g[F.league],g[F.kind],g[F.split]??''].join('|')];
const elink=(g,txt)=>{const e=tourOf(g);return e?`<a href="#${e.slug}">${txt}</a>`:txt};
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],dm=d=>MON[+d.slice(5,7)-1]+' '+(+d.slice(8,10));
const dates=e=>dm(e.first)+(e.last!=e.first?' – '+dm(e.last):'');
// a team name as a link: by its index when known, else by name (the one in the same league if the name is shared)
const teamOf=(name,ti,lg)=>ti!=null&&teams[ti]?teams[ti]:(byName[name]||[]).find(t=>t.league==lg)||(byName[name]||[])[0];
const tlink=(name,ti,lg)=>{const t=teamOf(name,ti,lg);return t?`<a href="#${t.slug}">${esc(name)}</a>`:esc(name||'—')};
const files={},tfiles={};
const loadFile=k=>files[k]||(files[k]=getJSON(`data/games/${k}.json`).catch(e=>{delete files[k];throw e}));
async function gamesOf(p){
  if(p.games)return p.games;
  const fs=await Promise.all(p.files.map(loadFile)),rows=[];
  fs.forEach((f,i)=>{const yi=YEARS.indexOf(p.files[i].slice(0,4));
    f.rows.forEach((r,j)=>{if(F.pi!=null?r[F.pi]==p.i:r[F.player]==p.name&&r[F.role]==p.role)rows.push([ORD(yi,f.seq[j]),r])})});
  return p.games=rows.sort((a,b)=>a[0]-b[0]).map(x=>x[1]);
}
// team files: every team-game of a league, shaped like game rows for keep() (raw row in .r)
const loadTeamFile=k=>tfiles[k]||(tfiles[k]=getJSON(`data/teams/${k}.json`).then(f=>{const yi=YEARS.indexOf(k.slice(0,4));
  return f.rows.map((r,j)=>{const g=[];for(const x of ['league','kind','period','split','stage','date'])g[F[x]]=r[TF[x]];g.r=r;g.o=ORD(yi,f.seq[j]);return g})})
  .catch(e=>{delete tfiles[k];throw e}));
async function teamGames(t){
  if(t.rows)return t.rows;
  const fs=await Promise.all(t.files.map(loadTeamFile));
  t.all=fs.flat().sort((a,b)=>a.o-b.o);           // every team in those leagues (for league averages and the other side of a game)
  return t.rows=t.all.filter(g=>g.r[TF.ti]==t.i);
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
    let a=agg.get(c.pi);if(!a)agg.set(c.pi,a={pi:c.pi,games:0,s:{n:0,sw:0,swd:0,sw2:0,s1:0,s2:0},last:-1,team:null,ti:null});
    a.games+=c.games;addSums(a.s,c.sums);if(c.last>a.last){a.last=c.last;a.team=c[F.team];a.ti=c.ti}}
  const sel=[...agg.values()].sort((a,b)=>a.pi-b.pi);
  const thr=Math.max(1,Math.min(MIN,Math.ceil(sel.reduce((a,x)=>Math.max(a,x.games),0)/2)));
  const rows=sel.filter(x=>x.games>=thr).map(x=>({p:list[x.pi],team:x.team,ti:x.ti,r:rateSums(x.s,list[x.pi].role)}))
    .filter(x=>x.r).sort((a,b)=>b.r.x-a.r.x);
  return lb[k]={rows,thr};
}
// team board: record, series, gold diff @15 and the Elo after each team's last game in the selection
const tb={};
function teamBoard(L){
  const k=[L,st.split,st.stage,st.year].join('|');
  if(tb[k])return tb[k];
  const agg=new Map();
  for(const c of TS){if(!keep(c,L))continue;
    let a=agg.get(c.ti);if(!a)agg.set(c.ti,a={t:teams[c.ti],games:0,wins:0,sw:0,sl:0,gdn:0,gds:0,last:-1,elo:null});
    a.games+=c.games;a.wins+=c.wins;a.sw+=c.sw;a.sl+=c.sl;a.gdn+=c.gdn;a.gds+=c.gds;if(c.last>a.last){a.last=c.last;a.elo=c.elo}}
  let rows=[...agg.values()].filter(a=>a.t);
  if(current()){rows=rows.filter(a=>COMB(L)||L==INTL||!LATEST[L]?ACTIVE.has(a.t.i):LATEST[L].teams.has(a.t.i));rows.forEach(a=>{if(NOW[a.t.i]!=null)a.elo=NOW[a.t.i]})}
  return tb[k]=rows;
}
// latest split of each league: its latest split (by last game) with at least 3/4 of the league's median number of teams;
// final stages (VCS Finals, EBL Finals, LES Final Four) don't count as a split. Ranked now: teams that played in it
// (on a combined board: in their own league's latest split)
const LATEST={},TLAST={},TLASTO={},SPT={},SPO={};
for(const c of TS){const L=c[F.league],P=c[F.period];if(P==null)continue;
  ((SPT[L]=SPT[L]||{})[P]=SPT[L][P]||new Set()).add(c.ti);SPO[L+'|'+P]=Math.max(SPO[L+'|'+P]||-1,c.last);
  const t=teams[c.ti];if(t&&L==t.league&&(!(c.ti in TLASTO)||c.last>TLASTO[c.ti])){TLAST[c.ti]=P;TLASTO[c.ti]=c.last}}
for(const L in SPT){let ps=Object.entries(SPT[L]);const nf=ps.filter(([p])=>!/final/i.test(p));if(nf.length)ps=nf;
  const n=ps.map(([,s])=>s.size).sort((a,b)=>a-b),med=n[Math.floor((n.length-1)/2)];
  const ok=ps.filter(([,s])=>s.size>=0.75*med).sort((a,b)=>SPO[L+'|'+b[0]]-SPO[L+'|'+a[0]]);LATEST[L]={p:ok[0][0],teams:ok[0][1]}}
const ACTIVE=new Set(teams.filter(t=>LATEST[t.league]&&LATEST[t.league].teams.has(t.i)).map(t=>t.i));
// each player's latest team (from the summary rows), to tell subs from former players
const PLAST={};for(const c of SUM){const x=PLAST[c.pi];if(!x||c.last>x.o)PLAST[c.pi]={ti:c.ti,o:c.last}}
const TSORT={elo:a=>a.elo,win:a=>a.wins/a.games,gd:a=>a.gdn?a.gds/a.gdn:-1e9};
const sortTeams=(rows,k=st.tsort)=>rows.slice().sort((a,b)=>TSORT[k](b)-TSORT[k](a)||b.elo-a.elo);
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
const E=D.elo||{},EW=E.weights||{};
const ELO_NOTE=`Elo: team strength from game results, counting the opponents’ strength. ${E.base||1500} is the average team; league levels come from the whole season’s games between leagues, so all teams share one scale. `
  +'Each series (Bo1, Bo3 or Bo5) changes Elo once, at its last game. '+(EW.WLDs?`Series count by where they are played: Worlds ${EW.WLDs}×, MSI ${EW.MSI}×, First Stand and EWC ${EW.FST}×, WSCI ${EW.WSCI}×, leagues 1×, events with major or tier 1 teams (e.g. KeSPA Cup) and qualifiers (EWC, Worlds) ${EW.event_major}×, EMEA Masters and other events ${EW.event}×. Winning a league split or event adds a title bonus.`:'')
  +(E.decay?` A team’s Elo fades towards its league’s level after ${E.decay[0]} days without games (half every ${E.decay[1]} days).`:'');
// Elo now (after decay, on the last day of the data), used when no split or stage is chosen
const NOW=E.now||{},current=()=>st.split=='all'&&st.stage=='all'&&(st.year=='all'||st.year==YEARS[YEARS.length-1]);
// titles per team: [competition, date, bonus]
const TITLES={};(E.titles||[]).forEach(([ti,c,d,b])=>(TITLES[ti]=TITLES[ti]||[]).push([c,d,b]));
// league options, grouped: combined boards, international, major, tier 1, tier 2, tier 3, events
function groups(lgs){
  const G=[['Combined',l=>COMB(l)],['International',l=>l==INTL],['Major',l=>TIER[l]=='major'],['Tier 1',l=>TIER[l]=='tier1'],['Tier 2',l=>TIER[l]=='tier2'],['Tier 3',l=>TIER[l]=='tier3'],['Events',l=>EV.has(l)]];
  return G.map(([t,f])=>[t,lgs.filter(f)]).filter(([,ls])=>ls.length);
}
// shared filter bar: one row of dropdowns (league, split/event, stage, year, and role on the player leaderboard)
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
  ${sl.length&&st.split!='all'&&(note||tourFor(L))?`<div class="mut sm fnote">${note?`${esc(st.split)} = ${esc(note)}`:''}${note&&tourFor(L)?' · ':''}${tourFor(L)?`<a href="#${tourFor(L).slug}">${esc(tourFor(L).short)} ${tourFor(L).year}: standings and results →</a>`:''}</div>`:''}`;
  const ch=(id,f)=>{const s=el.querySelector('#'+id);if(s)s.onchange=()=>{f(s.value);st.all=st.tall=0;redraw()}};
  ch('f-lg',k=>{setL(k);st.split='all'});
  ch('f-sp',k=>st.split=k);ch('f-st',k=>st.stage=k);ch('f-yr',k=>st.year=k);ch('f-rl',k=>st.role=k);
  const r=el.querySelector('#f-reset');if(r)r.onclick=()=>{st.split=st.stage=st.year='all';if(roles)st.role='all';st.all=st.tall=0;redraw()};
}
// the tournament behind a single-league board with one split chosen (the latest one in the chosen year)
const tourFor=L=>{if(st.split=='all'||COMB(L))return null;
  return TOURS.filter(e=>(L==INTL?e.kind=='international'&&e.league==st.split:e.league==L&&e.kind==(EV.has(L)?'event':'domestic')&&(e.period??e.split)==st.split)
    &&(st.year=='all'||String(e.year)==st.year)).pop()||null};
const boardLeagues=()=>{const rest=LEAGUES.filter(l=>TIER[l]!='major').sort((a,b)=>NAME(a).localeCompare(NAME(b)));
  return ['major','all',...MAJ,...rest,...EVENTS,...(HAS_INTL?[INTL]:[])]};

// header on every page: site name, menu, search (players and teams)
function header(cur){
  return `<header class="top"><div><a class="brand" href="#home">Pro Player Ratings<small>v${esc(D.version||'0.1')}</small></a>
  <nav class="menu">${[['home','Home'],['players','Players'],['teams','Teams'],['events','Tournaments']].map(([k,l])=>`<a href="#${k}"${k==cur?' class="on" aria-current="page"':''}>${l}</a>`).join('')}</nav></div>
  <div class="srch"><input id="q" type="search" placeholder="Search a player, team or tournament…" autocomplete="off"><div id="res"></div></div></header>`;
}
function wireSearch(){
  const q=document.getElementById('q'),res=document.getElementById('res');
  q.oninput=()=>{
    const t=norm(q.value).toLowerCase().trim();
    const m=t?[...list,...teams,...TOURS].filter(p=>p.n.includes(t)).sort((a,b)=>(b.n.startsWith(t)-a.n.startsWith(t))||b.ngames-a.ngames).slice(0,8):[];
    res.innerHTML=m.map(p=>p.kind?`<a href="#${p.slug}"><span><b>${esc(p.name)} ${p.year}</b> <span class="mut sm">Tournament</span></span><span class="mut sm">${dates(p)}</span></a>`:p.role?`<a href="#${p.slug}"><span><b>${esc(p.name)}</b> <span class="mut sm">${RL[p.role]}</span></span><span class="mut sm">${esc(p.team)} · ${esc(p.league)}${tag(p.league)}</span></a>`
      :`<a href="#${p.slug}"><span><b>${esc(p.name)}</b> <span class="mut sm">Team</span></span><span class="mut sm">${esc(NAME(p.league))}${tag(p.league)}</span></a>`).join('');
  };
  q.onkeydown=e=>{if(e.key=='Enter'){const a=res.querySelector('a');if(a)location.hash=a.getAttribute('href').slice(1)}};
}

// main page: menu and a short preview of both leaderboards
function home(){
  const pb=unfiltered(()=>board('major')).rows.slice(0,5),top=sortTeams(unfiltered(()=>teamBoard('major')),'elo').slice(0,5);
  app.innerHTML=header('home')+`
  <p class="mut lead">Performance ratings for pro players from per-game stats, and team strength from results, for ${LEAGUES.length} leagues, ${EVENTS.length} events and the international tournaments. A player rating of 1.00 is an average performance in the games counted, not a measure of skill.</p>
  <div class="hub">
    <a class="card hubc" href="#players"><b>Player leaderboards</b><span class="mut sm">Ratings by league, split, stage and role</span></a>
    <a class="card hubc" href="#teams"><b>Team leaderboards</b><span class="mut sm">Elo strength, records and series by league</span></a>
    <a class="card hubc" href="#events"><b>Tournaments</b><span class="mut sm">Standings, results, champions and qualification paths</span></a>
  </div>
  <div class="prev">
    <div><h2>Top players · Major leagues</h2><div class="tw"><table class="lbt">${pb.map((x,i)=>`<tr><td>${i+1}</td><td class="pl"><a href="#${x.p.slug}">${esc(x.p.name)}</a><div class="mut sub">${tlink(x.team,x.ti)} · ${RL[x.p.role]}</div></td><td class="${rc(x.r.x)}"><b class="rt">${f2(x.r.x)}</b></td></tr>`).join('')}</table></div>
      <p><a href="#players">All player leaderboards →</a></p></div>
    <div><h2>Top teams · Major leagues</h2><div class="tw"><table class="lbt">${top.map((a,i)=>`<tr><td>${i+1}</td><td class="pl"><a href="#${a.t.slug}">${esc(a.t.name)}</a><div class="mut sub">${esc(a.t.league)}${tag(a.t.league)}</div></td><td><b class="rt">${Math.round(a.elo)}</b><div class="mut sm">${a.wins}-${a.games-a.wins}</div></td></tr>`).join('')}</table></div>
      <p><a href="#teams">All team leaderboards →</a></p></div>
  </div>
  <p class="mut sm">${esc(ELO_NOTE)}</p>`;
  wireSearch();
}
function playersPage(){
  app.innerHTML=header('players')+`<h2 class="pt">Player leaderboards</h2>
  <div id="fb"></div><div class="tw" id="lb"></div><div id="mb"></div>
  <p class="mut sm" id="fn"></p><p class="mut sm">${esc(legend())}</p>`;
  wireSearch();
  draw();
}
function draw(){
  filters(document.getElementById('fb'),boardLeagues(),st.lg,k=>st.lg=k,draw,1);
  const b=board(st.lg);
  let rows=b.rows.filter(x=>st.role=='all'||x.p.role==st.role);
  const tot=rows.length;if(!st.all)rows=rows.slice(0,20);
  document.getElementById('lb').innerHTML=`<table class="lbt"><tr><th>#</th><th>Player</th><th>Games</th><th>Rating</th></tr>`+
    (rows.length?rows.map((x,i)=>`<tr><td>${i+1}</td><td class="pl"><a href="#${x.p.slug}">${esc(x.p.name)}</a><div class="mut sub">${tlink(x.team,x.ti)} · ${RL[x.p.role]}${COMB(st.lg)?` · ${esc(x.p.league)}${tag(x.p.league)}`:''}</div></td><td>${x.r.n}</td><td class="${rc(x.r.x)}"><b class="rt">${f2(x.r.x)}</b> <span class="mut sm rng">${f2(x.r.lo)}–${f2(x.r.hi)}</span></td></tr>`).join('')
    :`<tr><td colspan="4" class="mut">No players for these filters.</td></tr>`)+`</table>`;
  const mb=document.getElementById('mb');
  mb.innerHTML=tot>20&&!st.all?`<button class="more" id="more">Show all ${tot}</button>`:'';
  if(mb.firstChild)document.getElementById('more').onclick=()=>{st.all=1;draw()};
  document.getElementById('fn').textContent=`${describe(st.lg,b.thr)}. Ranges are a ~90% interval. ${notes(st.lg)}`;
}

function teamsPage(){
  app.innerHTML=header('teams')+`<h2 class="pt">Team leaderboards</h2>
  <div id="fb"></div><div class="tw" id="lb"></div><div id="mb"></div>
  <p class="mut sm" id="fn"></p>`;
  wireSearch();
  drawTeams();
}
function drawTeams(){
  filters(document.getElementById('fb'),boardLeagues(),st.lg,k=>st.lg=k,drawTeams,0);
  let rows=sortTeams(teamBoard(st.lg));
  const tot=rows.length;if(!st.tall)rows=rows.slice(0,20);
  const th=(k,l,cls)=>`<th class="${cls||''}"><button class="sort${st.tsort==k?' on':''}" data-k="${k}">${l}${st.tsort==k?' ↓':''}</button></th>`;
  const gd=a=>a.gdn?Math.round(a.gds/a.gdn):'—';
  document.getElementById('lb').innerHTML=`<table class="lbt tbt"><tr><th>#</th><th>Team</th>${th('elo','Elo')}<th>Record</th><th class="hm">Series</th>${th('win','Win %')}${th('gd','GD@15','hm')}</tr>`+
    (rows.length?rows.map((a,i)=>`<tr><td>${i+1}</td><td class="pl"><a href="#${a.t.slug}">${esc(a.t.name)}</a>${COMB(st.lg)?`<div class="mut sub">${esc(a.t.league)}${tag(a.t.league)}</div>`:''}</td><td><b class="rt">${Math.round(a.elo)}</b></td><td>${a.wins}-${a.games-a.wins}</td><td class="hm">${a.sw}-${a.sl}</td><td>${Math.round(100*a.wins/a.games)}%</td><td class="hm">${gd(a)}</td></tr>`).join('')
    :`<tr><td colspan="7" class="mut">No teams for these filters.</td></tr>`)+`</table>`;
  document.querySelectorAll('button.sort').forEach(b=>b.onclick=()=>{st.tsort=b.dataset.k;drawTeams()});
  const mb=document.getElementById('mb');
  mb.innerHTML=tot>20&&!st.tall?`<button class="more" id="more">Show all ${tot}</button>`:'';
  if(mb.firstChild)document.getElementById('more').onclick=()=>{st.tall=1;drawTeams()};
  document.getElementById('fn').textContent=`${selection(st.lg)}${TT(st.lg)?` (${TT(st.lg)})`:''}. ${current()?`Elo now (${E.as_of||''}, after decay)`:'Elo after each team’s last game in the selection'}. Record counts every game; series are games on the same day between the same two teams; GD@15 only games with full stats.${current()?' Only teams that played in their league’s latest split are ranked.':''} ${ELO_NOTE}`;
}

function playerPage(p){
  const ls=[...LEAGUES,...EVENTS,INTL].filter(l=>p.games.some(g=>inL(g,l)));
  if(st.plg!='all'&&!ls.includes(st.plg))st.plg='all';
  const gs=p.games.filter(g=>keep(g,st.plg)),dom=gs.filter(g=>g[F.kind]=='domestic'),intl=gs.filter(g=>g[F.kind]=='international'),n=gs.length;
  const head=header('players')+`<a href="#players">← Player leaderboards</a>
  <h1 style="margin-top:8px">${esc(p.name)}</h1>
  <div class="mut">${RL[p.role]} · ${tlink(p.team,null,p.league)} · ${esc(p.league)}${tag(p.league)}${(o=>o.length?' · '+esc(o.join(', ')):'')([...new Set(p.games.map(g=>g[F.league]))].filter(l=>l!=p.league))}</div>`;
  const redraw=()=>{st.pg=0;playerPage(p)},bar=()=>filters(document.getElementById('fb'),['all',...ls],st.plg,k=>st.plg=k,redraw);
  if(!n){
    app.innerHTML=head+`<div id="fb" style="margin-top:14px"></div><p class="mut">No games for this player in the selected filters. Change or reset the filters above.</p>`;
    bar();wireSearch();return;
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
  ${shown.map(g=>`<tr><td>${g[F.date]}</td><td class="${rc(g[F.r_overall])}"><b>${f2(g[F.r_overall])}</b></td><td class="${g[F.result]?'good':'bad'}">${g[F.result]?'W':'L'}</td><td>${g[F.opponent]?tlink(g[F.opponent],null,g[F.league]):'—'}</td><td>${esc(g[F.champion])}</td><td>${g[F.kills]}/${g[F.deaths]}/${g[F.assists]}</td><td>${g[F.gd15]==null?'—':Math.round(g[F.gd15])}</td><td>${elink(g,ev(g))}</td></tr>`).join('')}</table></div>
  ${!st.pg&&rec.length>20?`<button class="more" id="mg">Show all ${rec.length}</button>`:''}`;
  bar();wireSearch();
  const mg=document.getElementById('mg');if(mg)mg.onclick=()=>{st.pg=1;playerPage(p)};
}

// Elo over the selected games: one 2px line, hairline grid, crosshair + tooltip snapping to the nearest game
function eloChart(el,gs){
  const W=Math.max(260,el.clientWidth-16),H=180,pl=44,pr=12,pt=10,pb=22;
  const v=gs.map(g=>g.r[TF.elo_after]),lo=Math.min(...v,...gs.map(g=>g.r[TF.elo_before])),hi=Math.max(...v);
  const step=[25,50,100,200,250,500].find(s=>(hi-lo)/s<=4)||1000,y0=Math.floor(lo/step)*step,y1=Math.ceil(hi/step)*step||y0+step;
  const X=i=>pl+(gs.length>1?i*(W-pl-pr)/(gs.length-1):(W-pl-pr)/2),Y=e=>pt+(H-pt-pb)*(1-(e-y0)/((y1-y0)||1));
  const ticks=[];for(let t=y0;t<=y1;t+=step)ticks.push(t);
  el.innerHTML=`<svg width="${W}" height="${H}" role="img" aria-label="Elo after each game, from ${Math.round(v[0])} to ${Math.round(v[v.length-1])}">
    ${ticks.map(t=>`<line x1="${pl}" x2="${W-pr}" y1="${Y(t)}" y2="${Y(t)}" class="grid"/><text x="${pl-6}" y="${Y(t)+4}" text-anchor="end" class="ax">${t}</text>`).join('')}
    <text x="${pl}" y="${H-6}" class="ax">${gs[0][F.date]}</text><text x="${W-pr}" y="${H-6}" text-anchor="end" class="ax">${gs[gs.length-1][F.date]}</text>
    <polyline class="ln" points="${v.map((e,i)=>X(i)+','+Y(e)).join(' ')}"/>
    <circle class="dot" cx="${X(v.length-1)}" cy="${Y(v[v.length-1])}" r="4"/>
    <line class="xh" x1="0" x2="0" y1="${pt}" y2="${H-pb}" visibility="hidden"/>
    <rect x="${pl}" y="0" width="${W-pl-pr}" height="${H}" fill="transparent" class="hit"/></svg><div class="tip" hidden></div>`;
  const svg=el.querySelector('svg'),xh=el.querySelector('.xh'),tip=el.querySelector('.tip');
  const show=e=>{const b=svg.getBoundingClientRect(),x=e.clientX-b.left;
    const i=Math.max(0,Math.min(gs.length-1,Math.round((x-pl)/((W-pl-pr)/Math.max(1,gs.length-1)))));
    const r=gs[i].r,dx=r[TF.elo_after]-r[TF.elo_before];
    xh.setAttribute('x1',X(i));xh.setAttribute('x2',X(i));xh.setAttribute('visibility','visible');
    tip.hidden=false;tip.innerHTML=`<b>${Math.round(r[TF.elo_after])}</b> <span class="${dx>=0?'good':'bad'}">${dx>=0?'+':''}${Math.round(dx)}</span><br><span class="mut">${r[TF.date]} · ${r[TF.result]?'W':'L'} vs ${esc(r[TF.opponent])}</span>`;
    tip.style.left=Math.min(W-tip.offsetWidth,Math.max(0,X(i)-tip.offsetWidth/2))+'px'};
  svg.addEventListener('pointermove',show);svg.addEventListener('pointerdown',show);
  svg.addEventListener('pointerleave',()=>{tip.hidden=true;xh.setAttribute('visibility','hidden')});
}

function teamPage(t){
  const ls=[...LEAGUES,...EVENTS,INTL].filter(l=>t.rows.some(g=>inL(g,l)));
  if(st.tlg!='all'&&!ls.includes(st.tlg))st.tlg='all';
  const gs=t.rows.filter(g=>keep(g,st.tlg)),n=gs.length,R=g=>g.r;
  const others=[...new Set(t.rows.map(g=>g[F.league]))].filter(l=>l!=t.league);
  // rank by each team's latest Elo, among the teams of its league and among all teams
  const latest=sortTeams(unfiltered(()=>teamBoard('all')),'elo'),mates=latest.filter(a=>a.t.league==t.league);
  const rank={lg:mates.findIndex(a=>a.t==t)+1,of:mates.length,all:latest.findIndex(a=>a.t==t)+1,ofAll:latest.length};
  const last=t.rows[t.rows.length-1];
  const head=header('teams')+`<a href="#teams">← Team leaderboards</a>
  <h1 style="margin-top:8px">${esc(t.name)}</h1>
  <div class="mut">${esc(NAME(t.league))}${tag(t.league)}${others.length?' · '+esc(others.join(', ')):''} · Elo now ${Math.round(NOW[t.i]??last.r[TF.elo_after])} · ${rank.lg?`#${rank.lg} of ${rank.of} in ${esc(t.league)} · #${rank.all} of ${rank.ofAll} teams`:`not ranked (no games in the latest ${esc(t.league)} split${LATEST[t.league]?', '+esc(LATEST[t.league].p):''})`}</div>
  ${(TITLES[t.i]||[]).length?`<div class="sm" style="margin-top:4px"><b>Titles:</b> ${TITLES[t.i].map(([c,d])=>{const e=TOURS.find(e=>e.champ==t.i&&e.first<=d&&d<=e.last&&c.startsWith(e.league));return e?`<a href="#${e.slug}">${esc(c)}</a>`:esc(c)}).join(' · ')}</div>`:''}`;
  const redraw=()=>{st.tpg=0;teamPage(t)},bar=()=>filters(document.getElementById('fb'),['all',...ls],st.tlg,k=>st.tlg=k,redraw);
  if(!n){
    app.innerHTML=head+`<div id="fb" style="margin-top:14px"></div><p class="mut">No games for this team in the selected filters. Change or reset the filters above.</p>`;
    bar();wireSearch();return;
  }
  const W=gs.filter(g=>R(g)[TF.result]).length,ser=gs.map(R).filter(r=>r[TF.s_result]!=null),sw=ser.filter(r=>r[TF.s_result]==1).length;
  const side=s=>{const x=gs.filter(g=>R(g)[TF.side]==s),w=x.filter(g=>R(g)[TF.result]).length;return x.length?{rec:`${w}-${x.length-w}`,pct:Math.round(100*w/x.length)+'%'}:{rec:'—',pct:'—'}};
  const sb=side('Blue'),sr=side('Red');
  const e1=R(gs[gs.length-1])[TF.elo_after],dE=e1-R(gs[0])[TF.elo_before];
  // league comparison: the selected league, or the team's own league when all leagues are selected
  const CL=st.tlg=='all'?t.league:st.tlg,comp=t.all.filter(g=>keep(g,CL));
  const mean=(rows,k)=>{const x=rows.map(r=>r[TF[k]]).filter(v=>v!=null);return x.length?x.reduce((a,b)=>a+b,0)/x.length:null};
  const lenW=rows=>mean(rows.filter(r=>r[TF.result]),'minutes'),lenL=rows=>mean(rows.filter(r=>!r[TF.result]),'minutes');
  const STATS=[['Gold diff @15',r=>mean(r,'gd15'),0,1],['CS diff @15',r=>mean(r,'csd15'),0,1],['XP diff @15',r=>mean(r,'xpd15'),0,1],
    ['Kills per game',r=>mean(r,'kills'),1,1],['Deaths per game',r=>mean(r,'deaths'),1,-1],
    ['First blood',r=>mean(r,'fb'),'%',1],['First dragon',r=>mean(r,'fd'),'%',1],['First herald',r=>mean(r,'fh'),'%',1],['First tower',r=>mean(r,'ft'),'%',1],
    ['Dragons per game',r=>mean(r,'dragons'),2,1],['Void grubs per game',r=>mean(r,'grubs'),2,1],['Barons per game',r=>mean(r,'barons'),2,1],['Towers per game',r=>mean(r,'towers'),1,1],
    ['Game length (min)',r=>mean(r,'minutes'),1,0],['Length of wins (min)',lenW,1,0],['Length of losses (min)',lenL,1,0],
    ['Damage per minute',r=>mean(r,'dpm'),0,1],['Wards per minute',r=>mean(r,'wpm'),2,1],['Vision score per minute',r=>mean(r,'vspm'),2,1]];
  const byTeam={};comp.forEach(g=>(byTeam[g.r[TF.ti]]=byTeam[g.r[TF.ti]]||[]).push(g.r));
  const fmt=(v,d)=>v==null||isNaN(v)?'—':d=='%'?Math.round(100*v)+'%':v.toFixed(d);
  const mine=gs.map(R),all=comp.map(R),nT=Object.keys(byTeam).length;
  const srows=STATS.map(([l,f,d,dir])=>{const v=f(mine),a=/diff/.test(l)?null:f(all);if(v==null&&a==null)return'';
    let rk='';if(dir&&v!=null){const vals=Object.values(byTeam).map(f).filter(x=>x!=null);rk=`${1+vals.filter(x=>dir>0?x>v+1e-9:x<v-1e-9).length} of ${vals.length}`}
    return`<tr><td>${l}</td><td><b>${fmt(v,d)}</b></td><td>${fmt(a,d)}</td><td class="mut">${rk}</td></tr>`}).join('');
  // roster: the players' ratings for this team in the selection (from the summary)
  const ros=new Map();
  for(const c of SUM){if(c.ti!=t.i||!keep(c,st.tlg))continue;const a=ros.get(c.pi)||ros.set(c.pi,{p:list[c.pi],games:0,s:{n:0,sw:0,swd:0,sw2:0,s1:0,s2:0}}).get(c.pi);a.games+=c.games;addSums(a.s,c.sums)}
  const RO=Object.keys(RL);
  const roster=[...ros.values()].map(a=>({...a,r:rateSums(a.s,a.p.role)})).sort((a,b)=>RO.indexOf(a.p.role)-RO.indexOf(b.p.role)||b.games-a.games);
  // current players: played for the team in its latest split and still play for it (their latest team);
  // starting lineup: per role the current player with the most games in that split; other current players are subs
  const TS_=TLAST[t.i],inLast={};
  for(const c of SUM)if(c.ti==t.i&&c[F.league]==t.league&&c[F.period]==TS_)inLast[c.pi]=(inLast[c.pi]||0)+c.games;
  const cur=a=>inLast[a.p.i]&&PLAST[a.p.i].ti==t.i;
  const starters=RO.map(r=>roster.filter(a=>a.p.role==r&&cur(a)).sort((a,b)=>inLast[b.p.i]-inLast[a.p.i])[0]).filter(Boolean);
  // not current: former (played league games for the team) or event stand-ins (only events, e.g. academy players at a cup)
  const lg={};for(const c of SUM)if(c.ti==t.i&&c[F.kind]=='domestic')lg[c.pi]=1;
  const subs=roster.filter(a=>cur(a)&&!starters.includes(a)),former=roster.filter(a=>!cur(a)&&lg[a.p.i]),standin=roster.filter(a=>!cur(a)&&!lg[a.p.i]);
  const prow=a=>`<tr><td><a href="#${a.p.slug}">${esc(a.p.name)}</a></td><td>${RL[a.p.role]}</td><td>${a.games}</td><td class="${a.r?rc(a.r.x):''}">${a.r?`<b>${f2(a.r.x)}</b> <span class="mut sm">${f2(a.r.lo)}–${f2(a.r.hi)}</span>`:'—'}</td></tr>`;
  // draft: picks (with win rate), bans by the team, bans against it (the other side's bans in the same game)
  const other={};t.all.forEach(g=>other[g.r[TF.series]+'|'+g.r[TF.game]+'|'+g.r[TF.ti]]=g.r);
  const count=(arr)=>{const c={};arr.forEach(([ch,w])=>{const x=c[ch]=c[ch]||{n:0,w:0};x.n++;x.w+=w});return Object.entries(c).sort((a,b)=>b[1].n-a[1].n).slice(0,8)};
  const picks=count(mine.flatMap(r=>(r[TF.picks]||[]).map(ch=>[ch,r[TF.result]])));
  const bans=count(mine.flatMap(r=>(r[TF.bans]||[]).map(ch=>[ch,0])));
  const bansVs=count(mine.flatMap(r=>((other[r[TF.series]+'|'+r[TF.game]+'|'+r[TF.oi]]||{})[TF.bans]||[]).map(ch=>[ch,0])));
  const dl=(title,rows,wr)=>`<div><h3>${title}</h3><table>${rows.map(([c,x])=>`<tr><td>${esc(c)}</td><td>${x.n}</td>${wr?`<td class="mut">${Math.round(100*x.w/x.n)}%</td>`:''}</tr>`).join('')||'<tr><td class="mut">—</td></tr>'}</table></div>`;
  const rec=gs.slice().reverse(),shown=st.tpg?rec:rec.slice(0,20);
  const fin=new Map();(TITLES[t.i]||[]).forEach(([c,d,b])=>{const g=rec.find(g=>g.r[TF.date]==d&&c.startsWith(g.r[TF.league]));if(g)fin.set(g,b)});
  const ev=r=>r[TF.league]+(r[TF.split]||r[TF.period]?' '+esc(r[TF.split]||r[TF.period]):'')+(r[TF.stage]=='playoffs'?' (playoffs)':'');
  const card=(l,v,s,big)=>`<div class="card ${big?'main':''}"><div class="mut sm">${l}</div><div class="${big?'num':'num2 nw'}">${v}</div><div class="mut sm">${s}</div></div>`;
  app.innerHTML=head+`
  <div id="fb" style="margin-top:14px"></div>
  <div class="cards">${card('Elo after last game · '+esc(selection(st.tlg)),Math.round(e1),`${dE>=0?'+':''}${Math.round(dE)} over ${n} games`,1)}
    ${card('Record',`${W}-${n-W}`,`${Math.round(100*W/n)}% of games`)}${card('Series',`${sw}-${ser.length-sw}`,'same day, same opponent')}
    ${card('Win % blue / red',`${sb.pct} / ${sr.pct}`,`${sb.rec} · ${sr.rec}`)}</div>
  <h2>Roster</h2><div class="tw"><table><tr><th>Starting lineup</th><th>Role</th><th>Games</th><th>Rating</th></tr>
  ${starters.map(prow).join('')||'<tr><td colspan="4" class="mut">No rated player games.</td></tr>'}
  ${subs.length?`<tr class="subh"><th>Subs</th><th></th><th></th><th></th></tr>${subs.map(prow).join('')}`:''}
  ${former.length?`<tr class="subh"><th>Former</th><th></th><th></th><th></th></tr>${former.map(prow).join('')}`:''}
  ${standin.length?`<tr class="subh"><th>Event stand-ins</th><th></th><th></th><th></th></tr>${standin.map(prow).join('')}`:''}</table></div>
  <p class="mut sm">Player performance ratings in this team’s games (not a measure of skill). Starting lineup and subs: players in the team’s latest split${TS_?` (${esc(t.league)} ${esc(TS_)})`:''} who still play for it; the starter is the one with the most games in each role there. Former: played league games for the team and no longer play for it. Event stand-ins: played only events for it (e.g. academy players at a cup).</p>
  <h2>Elo</h2><div class="card chart" id="elo"></div>
  <p class="mut sm">${esc(ELO_NOTE)}</p>
  <h2>Stats vs ${esc(LN(CL))} average</h2><div class="tw"><table><tr><th>Stat</th><th>${esc(t.name)}</th><th>${esc(LN(CL))} average</th><th>Rank</th></tr>${srows}</table></div>
  <p class="mut sm">Per game. Rank among the ${nT} teams in ${esc(selection(CL))}. @15 stats only from games with full stats.</p>
  <h2>Draft</h2><div class="draft">${dl('Most picked · win %',picks,1)}${dl('Most banned by them',bans)}${dl('Most banned against them',bansVs)}</div>
  <h2>Games</h2><div class="tw"><table><tr><th>Date</th><th></th><th>vs</th><th>Side</th><th>Length</th><th>K-D</th><th>GD@15</th><th>Drg / Bar / Tow</th><th>Elo</th><th>Event</th></tr>
  ${shown.map(g=>{const r=g.r,dx=r[TF.elo_after]-r[TF.elo_before];return`<tr><td>${r[TF.date]}</td><td class="${r[TF.result]?'good':'bad'}">${r[TF.result]?'W':'L'}</td><td>${tlink(r[TF.opponent],r[TF.oi])}</td><td>${r[TF.side]}</td><td>${r[TF.minutes]==null?'—':r[TF.minutes].toFixed(1)}</td><td>${r[TF.kills]??'—'}-${r[TF.deaths]??'—'}</td><td>${r[TF.gd15]==null?'—':Math.round(r[TF.gd15])}</td><td>${r[TF.dragons]??'—'} / ${r[TF.barons]??'—'} / ${r[TF.towers]??'—'}</td><td>${Math.round(r[TF.elo_after])}${Math.round(dx)?` <span class="${dx>0?'good':'bad'} sm">${dx>0?'+':''}${Math.round(dx)}</span>`:''}</td><td>${elink(g,ev(r))}${fin.has(g)?` · <b>title</b> <span class="mut sm">(+${fin.get(g)} included)</span>`:''}</td></tr>`}).join('')}</table></div>
  ${!st.tpg&&rec.length>20?`<button class="more" id="mg">Show all ${rec.length}</button>`:''}`;
  bar();wireSearch();
  eloChart(document.getElementById('elo'),gs);
  const mg=document.getElementById('mg');if(mg)mg.onclick=()=>{st.tpg=1;teamPage(t)};
}

// tournaments list: grouped like the league dropdown, newest first
const EG=[['International',e=>e.kind=='international'],['Major',e=>e.kind=='domestic'&&e.tier=='major'],['Tier 1',e=>e.kind=='domestic'&&e.tier=='tier1'],
  ['Tier 2',e=>e.kind=='domestic'&&e.tier=='tier2'],['Tier 3',e=>e.kind=='domestic'&&e.tier=='tier3'],['Events',e=>e.kind=='event']];
const TTAG={major:'Major',tier1:'Tier 1',tier2:'Tier 2',tier3:'Tier 3'},etag=e=>TTAG[e.tier]?` <span class="tag">${TTAG[e.tier]}</span>`:'';
const champOf=e=>e.champ!=null&&teams[e.champ]?tlink(teams[e.champ].name,e.champ):`<span class="mut">${e.done?'—':'In progress'}</span>`;
function eventsPage(){
  const ys=[...new Set(TOURS.map(e=>String(e.year)))];
  if(st.eyr!='all'&&!ys.includes(st.eyr))st.eyr='all';
  const sel=TOURS.filter(e=>st.eyr=='all'||String(e.year)==st.eyr).sort((a,b)=>b.last.localeCompare(a.last)||b.first.localeCompare(a.first));
  const gs=EG.map(([l,f])=>[l,sel.filter(f)]).filter(([l,x])=>x.length&&(st.eg=='all'||st.eg==l));
  const opt=(items,cur)=>items.map(([k,l])=>`<option value="${esc(k)}"${k==cur?' selected':''}>${esc(l)}</option>`).join('');
  app.innerHTML=header('events')+`<h2 class="pt">Tournaments</h2>
  <div class="fbar"><select id="f-eg" aria-label="Group" class="${st.eg!='all'?'on':''}">${opt([['all','All tournaments'],...EG.map(([l])=>[l,l])],st.eg)}</select>
  <select id="f-ey" aria-label="Year" class="${st.eyr!='all'?'on':''}">${opt([['all','All years'],...ys.map(y=>[y,y])],st.eyr)}</select></div>
  ${gs.map(([l,x])=>`<h2>${l}</h2><div class="tw"><table class="lbt evt"><tr><th>Tournament</th><th>Dates</th><th class="hm">Teams</th><th>Champion</th></tr>
    ${x.map(e=>`<tr><td class="pl"><a href="#${e.slug}">${esc(e.name)}</a>${ys.length>1?` <span class="mut sm">${e.year}</span>`:''}</td><td>${dates(e)}</td><td class="hm">${e.teams}</td><td class="pl">${champOf(e)}</td></tr>`).join('')}</table></div>`).join('')||'<p class="mut">No tournaments for these filters.</p>'}
  <p class="mut sm">A tournament is a league split, an event or an international event. League games without a split name in the data are in no tournament. Champion: the winner of the last playoff series (the last series if there are no playoffs) when it was a best of 5; otherwise —.</p>`;
  wireSearch();
  const ch=(id,f)=>{const x=document.getElementById(id);x.onchange=()=>{f(x.value);eventsPage()}};
  ch('f-eg',v=>st.eg=v);ch('f-ey',v=>st.eyr=v);
}
async function tourGames(e){
  if(e.rows)return e.rows;
  const k=`${e.year}/${e.league}`,[all,pf]=await Promise.all([loadTeamFile(k),D.files[k]?loadFile(k):null]);
  e.pg=pf?pf.rows.filter(g=>tourOf(g)==e):[];
  return e.rows=all.filter(g=>tourOf(g)==e).sort((a,b)=>a.o-b.o);
}
function tourPage(e){
  const R=e.rows.map(g=>g.r),N=R.length/2;
  // series: teams, games won, date, stage
  const S=new Map();
  for(const r of R){let s=S.get(r[TF.series]);if(!s)S.set(r[TF.series],s={id:r[TF.series],date:r[TF.date],r0:r,po:0,w:{},nm:{},n:0});
    s.po|=r[TF.stage]=='playoffs';s.w[r[TF.ti]]=(s.w[r[TF.ti]]||0)+r[TF.result];s.nm[r[TF.ti]]=r[TF.team];s.n++}
  const series=[...S.values()].map(s=>{const [a,b]=Object.keys(s.w).map(Number).sort((x,y)=>s.w[y]-s.w[x]);return{...s,a,b,wa:s.w[a],wb:s.w[b]}});
  // standings: series and games won, gold diff @15, Elo change over the whole tournament
  const elo={};for(const r of R){const x=elo[r[TF.ti]]=elo[r[TF.ti]]||{e0:r[TF.elo_before]};x.e1=r[TF.elo_after]}
  const stand=rows=>{const m=new Map();for(const r of rows){const ti=r[TF.ti];let a=m.get(ti);if(!a)m.set(ti,a={ti,name:r[TF.team],gw:0,gl:0,sw:0,sl:0,gdn:0,gds:0});
      a.name=r[TF.team];if(r[TF.result])a.gw++;else a.gl++;if(r[TF.s_result]===1)a.sw++;else if(r[TF.s_result]===0)a.sl++;if(r[TF.gd15]!=null){a.gdn++;a.gds+=r[TF.gd15]}}
    return[...m.values()].sort((a,b)=>b.sw-a.sw||(b.gw-b.gl)-(a.gw-a.gl)||b.gw-a.gw||a.name.localeCompare(b.name))};
  // a table stage marks the teams that went on to the next stage (e.g. "Playoffs")
  // (only stages up to the one with the final: not e.g. LCS games after the final)
  const nextOf=(g,ti)=>{const fk=stages.findIndex(h=>h.ser.some(x=>x.id==e.final)),x=stages.slice(g.k+1,fk<0?undefined:fk+1).find(h=>h.rows.some(r=>r[TF.ti]==ti));return x?` <span class="tag q">${esc(x.name)}</span>`:''};
  const stable=(g,rows)=>`<div class="tw"><table class="lbt tbt"><tr><th>#</th><th>Team</th><th>Series</th><th>Games</th><th class="hm">Win %</th><th class="hm">GD@15</th><th>Elo ±</th></tr>
    ${stand(rows).map((a,i)=>{const d=elo[a.ti]?Math.round(elo[a.ti].e1-elo[a.ti].e0):0;return`<tr><td>${i+1}</td><td class="pl">${tlink(a.name,a.ti)}${nextOf(g,a.ti)}</td><td>${a.sw}-${a.sl}</td><td>${a.gw}-${a.gl}</td><td class="hm">${Math.round(100*a.gw/Math.max(1,a.gw+a.gl))}%</td><td class="hm">${a.gdn?Math.round(a.gds/a.gdn):'—'}</td><td class="${d>0?'good':d<0?'bad':''}">${d>0?'+':''}${d}</td></tr>`}).join('')}</table></div>`;
  // stages (from the format, else regular season + playoffs or one list): which games belong to each
  const inStage=(g,r)=>(!g.flag||r[TF.stage]==g.flag)&&(!g.from||(d=>d>=g.from&&d<=g.to)(r[TF.date].slice(5)));
  const stages=(e.stages||[{name:'Results',type:'bracket'}]).map((g,k)=>({...g,k,rows:R.filter(r=>inStage(g,r)),ser:series.filter(x=>inStage(g,x.r0))}));
  // match history: every series, newest first (latest 5 days, then all), with its stage; the final is marked
  const bo=s=>s.wa==s.wb?'unfinished':'Bo'+(2*s.wa-1);
  const stageOf=x=>stages.find(g=>inStage(g,x.r0));
  const history=()=>{const days=[...new Set(series.map(x=>x.date))].sort().reverse(),open=st.eopen.h,showD=open?days:days.slice(0,5),many=stages.length>1;
    return`<div class="tw"><table class="lbt">${showD.map(d=>`<tr class="subh"><th colspan="${many?3:2}">${dm(d)}</th></tr>`+series.filter(x=>x.date==d).sort((a,b)=>b.id-a.id).map(x=>`<tr${x.id==e.final?' class="fin"':''}><td class="pl">${tlink(x.nm[x.a],x.a)} <b>${x.wa}–${x.wb}</b> ${tlink(x.nm[x.b],x.b)}${x.id==e.final?' <span class="tag">Final</span>':''}</td><td class="mut">${bo(x)}</td>${many?`<td class="mut hm">${esc((stageOf(x)||{}).name||'')}</td>`:''}</tr>`).join('')).join('')}</table></div>
    ${!open&&days.length>5?`<button class="more" data-open="h">Show all ${days.length} days</button>`:''}`};
  // a bracket stage without the final: its teams, marking those that went on to the next stage
  const stageTeams=g=>{const ts=[...new Set(g.rows.map(r=>r[TF.ti]))],nm={};g.rows.forEach(r=>nm[r[TF.ti]]=r[TF.team]);
    return`<div class="chips">${ts.map(ti=>{const n=nextOf(g,ti);return`<span class="chip${n?' on':''}">${tlink(nm[ti],ti)}${n?' <span class="mut sm">→ '+n.replace(/<[^>]+>/g,'').trim()+'</span>':''}</span>`}).join('')}</div>`};
  const stageHtml=g=>`<h2>${esc(g.name)}</h2>${g.desc?`<p class="sd">${esc(g.desc)}</p>`:''}`+(!g.rows.length?`<p class="mut">Not in the data${e.done?'':' yet'}.</p>`
    :g.type=='table'?stable(g,g.rows):g.ser.some(x=>x.id==e.final)&&(e.places||[]).length?placeTable(g):stageTeams(g));
  // the stage with the final: each team's place, and the tournament it qualified for with its place (or stage reached) there
  const PL=new Map((e.places||[]).map(([ti,p],i)=>[ti,{p,i}]));
  const placeOf=(x,ti)=>{const f=(x.places||[]).find(([i])=>i==ti);return f?f[1]:''};
  const placeTable=g=>{const ts=[...new Set(g.rows.map(r=>r[TF.ti]))].filter(ti=>PL.has(ti)).sort((a,b)=>PL.get(a).i-PL.get(b).i);
    const q=ti=>e.to.filter(({xs})=>xs.includes(ti)).map(({e:x})=>`<a href="#${x.slug}">${esc(x.short)}</a>${placeOf(x,ti)?` <span class="mut">· ${esc(placeOf(x,ti))}${x.done?'':' (playing)'}</span>`:''}`).join('<br>');
    const any=ts.some(ti=>q(ti));
    return`<div class="tw"><table class="lbt"><tr><th>Place</th><th>Team</th>${any?'<th>Qualified for</th>':''}</tr>${ts.map(ti=>`<tr${ti==e.champ?' class="fin"':''}><td>${PL.get(ti).p}</td><td class="pl">${tlink(teams[ti]?teams[ti].name:'?',ti)}</td>${any?`<td class="pl">${q(ti)||'<span class="mut">—</span>'}</td>`:''}</tr>`).join('')}</table></div>`};
  // players: performance ratings in this tournament (same formula and minimum games as the leaderboards)
  // (from the player games, so any stage can be chosen)
  const pStage=(g,r)=>(!g.flag||r[F.stage]==g.flag)&&(!g.from||(d=>d>=g.from&&d<=g.to)(r[F.date].slice(5)));
  const pst=stages.filter(g=>(e.pg||[]).some(r=>pStage(g,r)));
  if(st.estage!='all'&&!pst.some(g=>g.k==st.estage))st.estage='all';
  const ag=new Map();
  for(const r of e.pg||[]){if(st.estage!='all'&&!pStage(stages[st.estage],r))continue;const a=ag.get(r[F.pi])||ag.set(r[F.pi],{p:list[r[F.pi]],gs:[]}).get(r[F.pi]);a.gs.push(r)}
  const pl=[...ag.values()].map(a=>({...a,games:a.gs.length,team:a.gs[a.gs.length-1][F.team],lg:a.gs[a.gs.length-1][F.league]}));
  const thr=Math.max(1,Math.min(MIN,Math.ceil(pl.reduce((m,x)=>Math.max(m,x.games),0)/2)));
  const rated=pl.filter(x=>x.games>=thr).map(x=>({...x,r:rate(x.gs,F.r_overall)})).filter(x=>x.r).sort((a,b)=>b.r.x-a.r.x);
  const best=Object.keys(RL).map(r=>rated.find(x=>x.p.role==r)).filter(Boolean);
  const prow=(x,i)=>`<tr><td>${i+1}</td><td class="pl"><a href="#${x.p.slug}">${esc(x.p.name)}</a><div class="mut sub">${tlink(x.team,null,x.lg)} · ${RL[x.p.role]}</div></td><td>${x.r.n}</td><td class="${rc(x.r.x)}"><b class="rt">${f2(x.r.x)}</b> <span class="mut sm rng">${f2(x.r.lo)}–${f2(x.r.hi)}</span></td></tr>`;
  const ptab=(rows,first)=>`<div class="tw"><table class="lbt"><tr><th>${first}</th><th>Player</th><th>Games</th><th>Rating</th></tr>${rows.map(prow).join('')||'<tr><td colspan="4" class="mut">No rated player games.</td></tr>'}</table></div>`;
  // draft and records, per game (each game has two team rows)
  const G=new Map();for(const r of R){const k=r[TF.series]+'|'+r[TF.game];(G.get(k)||G.set(k,[]).get(k)).push(r)}
  const pk={},bn={},pr={};
  for(const rs of G.values()){const seen=new Set();for(const r of rs){for(const c of r[TF.picks]||[]){const x=pk[c]=pk[c]||{n:0,w:0};x.n++;x.w+=r[TF.result];seen.add(c)}
    for(const c of r[TF.bans]||[]){bn[c]=(bn[c]||0)+1;seen.add(c)}}seen.forEach(c=>pr[c]=(pr[c]||0)+1)}
  const top=(o,f)=>Object.entries(o).sort((a,b)=>f(b[1])-f(a[1])).slice(0,8);
  const dl=(title,rows,cell)=>`<div><h3>${title}</h3><table>${rows.map(([c,x])=>`<tr><td>${esc(c)}</td>${cell(x)}</tr>`).join('')||'<tr><td class="mut">—</td></tr>'}</table></div>`;
  const gl=[...G.values()].filter(rs=>rs.length==2);
  const ext=(f,k)=>gl.filter(rs=>f(rs)!=null).sort((a,b)=>k*(f(b)-f(a)))[0];
  const len=rs=>rs[0][TF.minutes],kills=rs=>rs[0][TF.kills]==null?null:rs[0][TF.kills]+rs[1][TF.kills];
  const vs=rs=>`${tlink(rs[0][TF.team],rs[0][TF.ti])} vs ${tlink(rs[1][TF.team],rs[1][TF.ti])} · ${dm(rs[0][TF.date])}`;
  const rec=(l,rs,v)=>rs?`<div class="card"><div class="mut sm">${l}</div><div class="st">${v}</div><div class="mut sm">${vs(rs)}</div></div>`:'';
  const lmean=gl.map(len).filter(x=>x!=null),blue=R.filter(r=>r[TF.side]=='Blue'),bw=blue.filter(r=>r[TF.result]).length;
  // where the teams came from, grouped by region (the team's home league), with the tournaments they came through
  const REG=new Map();for(const{e:x,xs}of e.from)for(const ti of xs){const t=teams[ti];if(!t)continue;
    const g=REG.get(t.league)||REG.set(t.league,{teams:[],via:new Map()}).get(t.league);g.teams.push(t);g.via.set(x.slug,x)}
  const regs=[...REG.entries()].sort((a,b)=>b[1].teams.length-a[1].teams.length||NAME(a[0]).localeCompare(NAME(b[0])));
  const qualified=regs.length?`<h2>Qualified from</h2><div class="regions">${regs.map(([L,g])=>`<div class="card"><div class="rh"><b>${esc(NAME(L))}</b>${tag(L)}</div>
    <div class="chips">${g.teams.map(t=>`<a class="chip" href="#${t.slug}">${esc(t.name)}</a>`).join('')}</div>
    <div class="mut sm via">via ${[...g.via.values()].map(x=>`<a href="#${x.slug}">${esc(x.short)}${x.year!=e.year?' '+x.year:''}</a>`).join(', ')}</div></div>`).join('')}</div>`:'';
  // leaderboards for the same games
  const per=e.rows[0]?e.rows[0][F.period]:null;
  const BL=e.kind=='international'?INTL:e.league,SP=e.kind=='international'?e.league:per??'all',canBoard=boardLeagues().includes(BL);
  const kind=e.kind=='international'?'International event':e.kind=='event'?'Event':esc(NAME(e.league))+(/promotion/i.test(e.split||'')?' promotion tournament':' split');
  app.innerHTML=header('events')+`<a href="#events">← Tournaments</a>
  <h1 style="margin-top:8px">${esc(e.name)} ${e.year}</h1>
  <div class="mut">${kind}${e.kind=='domestic'?etag(e):''} · ${dates(e)} · ${e.teams} teams${canBoard?` · <button class="link sm" data-go="players">Player leaderboard</button><button class="link sm" data-go="teams">Team leaderboard</button>`:''}</div>
  <div class="cards"><div class="card main"><div class="mut sm">Champion</div><div class="num2">${champOf(e)}</div><div class="mut sm">${e.runner!=null&&teams[e.runner]?'Runner-up '+tlink(teams[e.runner].name,e.runner):e.done?'No best-of-5 final in the data':'Still being played in the data'}</div></div>
    <div class="card"><div class="mut sm">Games</div><div class="num2">${N}</div><div class="mut sm">${series.length} series</div></div>
    <div class="card"><div class="mut sm">Blue side wins</div><div class="num2">${blue.length?Math.round(100*bw/blue.length)+'%':'—'}</div><div class="mut sm">${bw}-${blue.length-bw}</div></div>
    <div class="card"><div class="mut sm">Average game</div><div class="num2">${lmean.length?(lmean.reduce((a,b)=>a+b,0)/lmean.length).toFixed(1):'—'}</div><div class="mut sm">minutes</div></div></div>
  ${stages.map(stageHtml).join('')}
  ${qualified}
  ${stages.some(g=>g.type=='table')?'<p class="mut sm">Tables: sorted by series won, then game difference; Elo ± is the change over the whole tournament (with title bonus and decay).</p>':''}
  <h2>Players</h2>${pst.length>1?`<div class="fbar"><select id="f-es" aria-label="Stage" class="${st.estage!='all'?'on':''}">${[['all','All stages'],...pst.map(g=>[g.k,g.name])].map(([k,l])=>`<option value="${k}"${String(k)==String(st.estage)?' selected':''}>${esc(l)}</option>`).join('')}</select></div>`:''}
  <h3 class="sh">Best player per role</h3>${ptab(best,'#')}
  <h3 class="sh">Top 10 players</h3>${ptab(rated.slice(0,10),'#')}
  <p class="mut sm">Player performance ratings in this tournament’s games${st.estage!='all'?' ('+esc(stages[st.estage].name)+')':''} (relative to the games counted, not a measure of skill); players with ${thr}+ games. Ranges are a ~90% interval.</p>
  <h2>Draft</h2><div class="draft">${dl('Most picked · win %',top(pk,x=>x.n),x=>`<td>${x.n}</td><td class="mut">${Math.round(100*x.w/x.n)}%</td>`)}${dl('Most banned',top(bn,x=>x),x=>`<td>${x}</td>`)}${dl('Presence (picked or banned)',top(pr,x=>x),x=>`<td>${Math.round(100*x/Math.max(1,G.size))}%</td>`)}</div>
  <h2>Records</h2><div class="cards">${rec('Longest game',ext(len,1),lmean.length?ext(len,1)[0][TF.minutes].toFixed(1)+' min':'')}${rec('Shortest game',ext(len,-1),lmean.length?ext(len,-1)[0][TF.minutes].toFixed(1)+' min':'')}${(g=>rec('Most kills in a game',g,g?kills(g)+' kills':''))(ext(kills,1))}</div>
  <h2>Match history</h2>${history()}
  <p class="mut sm">Series: games on the same day between the same two teams.${e.format?' Stages from Riot’s announcements and press coverage, dated from the games in the data.':e.kind!='domestic'?' The data has no stage information for this tournament.':''}</p>`;
  wireSearch();
  document.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>{st.lg=BL;st.split=SP;st.stage='all';st.year=String(e.year);st.role='all';st.all=st.tall=0;location.hash=b.dataset.go});
  document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>{st.eopen[b.dataset.open]=1;tourPage(e)});
  const fe=document.getElementById('f-es');if(fe)fe.onchange=()=>{const y=scrollY;st.estage=fe.value=='all'?'all':+fe.value;tourPage(e);scrollTo(0,y)};
}

let nav=0;
async function route(){
  const h=location.hash.slice(1),my=++nav;
  st.pg=st.tpg=0;
  st.eopen={};st.estage='all';
  const p=h.startsWith('p-')&&list.find(x=>x.slug==h),t=h.startsWith('t-')&&teams.find(x=>x.slug==h),e=h.startsWith('e-')&&TOURS.find(x=>x.slug==h);
  const load=async(x,f)=>{if(Array.isArray(x.games)||x.rows)return true;app.innerHTML='<p class="mut">Loading…</p>';
    try{await f(x)}catch(e){if(my==nav)app.innerHTML='<p>Could not load this page’s games. <a href="#home">Back to the main page</a></p>';return false}
    return my==nav};
  if(p){
    if(!await load(p,gamesOf))return;
    // a chosen split only makes sense with its league, so carry the league over in that case
    st.plg=st.split!='all'&&p.games.some(g=>inL(g,st.lg))?st.lg:'all';playerPage(p);
  }else if(t){
    if(!await load(t,teamGames))return;
    st.tlg=st.split!='all'&&t.rows.some(g=>inL(g,st.lg))?st.lg:'all';teamPage(t);
  }else if(e){
    if(!await load(e,tourGames))return;
    tourPage(e);
  }else if(h=='events')eventsPage();
  else if(h=='players')playersPage();
  else if(h=='teams')teamsPage();
  else home();
  window.scrollTo(0,0);
}
window.addEventListener('hashchange',route);route();
})();
