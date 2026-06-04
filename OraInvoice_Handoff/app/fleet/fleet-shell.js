/* ============================================================
   OraInvoice Fleet Portal — shared shell (sidebar + topbar)
   Usage: <script src="fleet-shell.js" data-active="vehicles" data-title="Vehicles"></script>
   Page provides: <div class="app"><div id="sidebar"></div>
     <div class="main"><div id="topbar"></div><main class="content">…</main></div></div>
   ============================================================ */
(function () {
  const ICON = {
    dash:'M3 12l2-2 7-7 7 7 2 2M5 10v10a1 1 0 001 1h3m10-11v11a1 1 0 01-1 1h-3m-6 0h6m-6 0v-6h6v6',
    car:'M5 11l1.5-4.5A2 2 0 018.4 5h7.2a2 2 0 011.9 1.5L19 11m-14 0h14m-14 0a2 2 0 00-2 2v3a1 1 0 001 1h1m14-6a2 2 0 012 2v3a1 1 0 01-1 1h-1M7 17v1a1 1 0 01-1 1H5a1 1 0 01-1-1v-1m3 0h10m0 0v1a1 1 0 001 1h1a1 1 0 001-1v-1',
    check:'M9 11l3 3L22 4M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11',
    booking:'M8 7V3m8 4V3M3 11h18M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
    bell:'M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 00-4-5.7V5a2 2 0 10-4 0v.3C7.7 6.2 6 8.4 6 11v3.2c0 .5-.2 1-.6 1.4L4 17h5m6 0v1a3 3 0 11-6 0v-1',
    driver:'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
    admin:'M9 12l2 2 4-4M12 3l8 4v5a8 8 0 01-16 0V7z',
    quote:'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2',
    inv:'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2z',
    remind:'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
    profile:'M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M16 7a4 4 0 11-8 0 4 4 0 018 0z',
    lock:'M5 11h14a2 2 0 012 2v7a2 2 0 01-2 2H5a2 2 0 01-2-2v-7a2 2 0 012-2zm2 0V7a5 5 0 0110 0v4',
    out:'M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4m7 14l5-5-5-5m5 5H9',
    doc:'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z'
  };
  const NAV = [
    { label:'Overview', items:[ {id:'dashboard',k:'dash',t:'Dashboard',href:'Dashboard.html'} ]},
    { label:'Fleet', items:[
      {id:'vehicles',k:'car',t:'Vehicles',href:'Vehicles.html'},
      {id:'checklists',k:'check',t:'Checklists',href:'Checklists.html'},
      {id:'bookings',k:'booking',t:'Bookings',href:'Bookings.html'},
      {id:'reminders',k:'remind',t:'Reminders',href:'Reminders.html'},
    ]},
    { label:'Manage', items:[
      {id:'drivers',k:'driver',t:'Drivers',href:'Drivers.html'},
      {id:'admins',k:'admin',t:'Admins',href:'Admins.html'},
      {id:'quotes',k:'quote',t:'Quotes',href:'Quotes.html'},
      {id:'invoices',k:'inv',t:'Invoices',href:'Invoices.html'},
    ]},
  ];
  const FOOT = [
    {id:'notifications',k:'bell',t:'Notifications',href:'Notifications.html',count:'3'},
    {id:'profile',k:'profile',t:'My profile',href:'Profile.html'},
    {id:'security',k:'lock',t:'Security',href:'Security.html'},
  ];
  function svg(d,sw){return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw||1.9}" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;}
  function item(it,active){return `<a class="nav-item ${it.id===active?'active':''}" href="${it.href}" data-nav="${it.id}">${svg(ICON[it.k])}${it.t}${it.count?`<span class="count">${it.count}</span>`:''}</a>`;}

  document.body.classList.add('portal');
  const me=document.currentScript;
  const active=me.getAttribute('data-active')||'';
  const title=me.getAttribute('data-title')||'';
  document.title=(title?title+' · ':'')+'Fleet Portal';

  const sb=document.getElementById('sidebar');
  if(sb){ sb.className='sidebar'; sb.innerHTML=`
    <div class="sb-head">
      <div class="logo-mark">${svg(ICON.car,2)}</div>
      <div class="logo-name"><b>Fleet</b><span class="dim"> Portal</span></div>
    </div>
    <div class="sb-scroll">
      ${NAV.map(g=>`<div class="nav-group"><div class="nav-label">${g.label}</div>${g.items.map(it=>item(it,active)).join('')}</div>`).join('')}
      <div class="nav-group">${FOOT.map(it=>item(it,active)).join('')}</div>
    </div>
    <div class="sb-foot">
      <div class="acct"><div class="n">Northland Freight</div><div class="e">dean@northlandfreight.co.nz</div></div>
      <button class="signout">${svg(ICON.out,2)}Sign out</button>
    </div>`;
  }
  const tb=document.getElementById('topbar');
  if(tb){ tb.className='topbar'; tb.innerHTML=`
    <button class="icon-btn hamburger" id="__ham" aria-label="Menu">${svg('M4 6h16M4 12h16M4 18h16',2)}</button>
    <span class="tb-title">${title}</span>
    <div class="spacer"></div>
    <span class="tb-acct"><span class="pin"></span>Northland Freight · 38 vehicles</span>
    <button class="icon-btn" aria-label="Notifications">${svg(ICON.bell,2)}<span class="bdg"></span></button>
    <button class="avatar" style="background:linear-gradient(135deg,#2F62F0,#6D5AE6)">DW</button>`;
  }
  const app=document.querySelector('.app'), ham=document.getElementById('__ham');
  if(ham&&app){ let s=document.querySelector('.scrim'); if(!s){s=document.createElement('div');s.className='scrim';app.prepend(s);} ham.addEventListener('click',()=>app.classList.toggle('nav-open')); s.addEventListener('click',()=>app.classList.remove('nav-open')); }
  document.querySelectorAll('.signout').forEach(b=>b.addEventListener('click',()=>location.href='Login.html'));
})();
