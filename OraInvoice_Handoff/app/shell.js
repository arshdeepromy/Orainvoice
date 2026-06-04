/* ============================================================
   OraInvoice Redesign — Shared App Shell
   Renders the sidebar + top bar into every page.
   Usage: <script src="shell.js" data-active="invoices" data-title="Invoices"></script>
   Page provides: <div class="app"><div id="sidebar"></div>
     <div class="main"><div id="topbar"></div><main class="content">…</main></div></div>
   ============================================================ */
(function () {
  const ICON = {
    dash:'M3 12l2-2 7-7 7 7 2 2M5 10v10a1 1 0 001 1h3m10-11v11a1 1 0 01-1 1h-3m-6 0h6m-6 0v-6h6v6',
    reports:'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z',
    inv:'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2z',
    quote:'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2',
    recur:'M4 4v5h.6M20 20v-5h-.6m0 0a8 8 0 01-15.3-2m15.4 2H15M4.6 9A8 8 0 0119.9 11M4.6 9H9',
    pos:'M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.3 2.3c-.6.6-.2 1.7.7 1.7H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z',
    job:'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.4-9.4a2 2 0 112.8 2.8L11.8 15H9v-2.8l8.6-8.6z',
    booking:'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
    schedule:'M8 7V3m8 4V3M3 11h18M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
    project:'M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z',
    time:'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
    cust:'M17 20h5v-2a3 3 0 00-5.4-1.9M17 20H7m10 0v-2c0-.7-.1-1.3-.4-1.9M7 20H2v-2a3 3 0 015.4-1.9M7 20v-2c0-.7.1-1.3.4-1.9m0 0a5 5 0 019.3 0M15 7a3 3 0 11-6 0 3 3 0 016 0z',
    car:'M5 11l1.5-4.5A2 2 0 018.4 5h7.2a2 2 0 011.9 1.5L19 11m-14 0h14m-14 0a2 2 0 00-2 2v3a1 1 0 001 1h1m14-6a2 2 0 012 2v3a1 1 0 01-1 1h-1M7 17v1a1 1 0 01-1 1H5a1 1 0 01-1-1v-1m3 0h10m0 0v1a1 1 0 001 1h1a1 1 0 001-1v-1M7 14h.01M17 14h.01',
    staff:'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
    inventory:'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4',
    items:'M12 6.3v13m0-13C10.8 5.5 9.2 5 7.5 5S4.2 5.5 3 6.3v13C4.2 18.5 5.8 18 7.5 18s3.3.5 4.5 1.3m0-13C13.2 5.5 14.8 5 16.5 5s3.3.5 4.5 1.3v13C19.8 18.5 18.2 18 16.5 18s-3.3.5-4.5 1.3',
    po:'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01',
    accounting:'M4 4h16v16H4zM12 6v12m0-9H9m6 6H9',
    banking:'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z',
    tax:'M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2z',
    expense:'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2z',
    settings:'M10.3 4.3c.4-1.8 2.9-1.8 3.3 0a1.7 1.7 0 002.6 1.1c1.5-.9 3.3.8 2.4 2.4a1.7 1.7 0 001 2.5c1.8.5 1.8 3 0 3.4a1.7 1.7 0 00-1 2.6c.9 1.5-.8 3.3-2.4 2.4a1.7 1.7 0 00-2.6 1c-.4 1.8-2.9 1.8-3.3 0a1.7 1.7 0 00-2.6-1c-1.5.9-3.3-.8-2.4-2.4a1.7 1.7 0 00-1-2.6c-1.8-.4-1.8-3 0-3.4a1.7 1.7 0 001-2.5C4.7 6.2 6.5 4.5 8 5.4a1.7 1.7 0 002.5-1zM15 12a3 3 0 11-6 0 3 3 0 016 0z',
    server:'M5 3h14a2 2 0 012 2v4a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2zm0 10h14a2 2 0 012 2v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4a2 2 0 012-2zm3-6h.01M8 17h.01',
    payroll:'M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6'
  };
  const NAV = [
    { label:'Overview', items:[
      { id:'dashboard', k:'dash', t:'Dashboard', href:'Dashboard.html' },
      { id:'reports', k:'reports', t:'Reports', href:'Reports.html' },
    ]},
    { label:'Sales', items:[
      { id:'invoices', k:'inv', t:'Invoices', count:'18', href:'Invoices.html' },
      { id:'quotes', k:'quote', t:'Quotes', count:'7', href:'Quotes.html' },
      { id:'recurring', k:'recur', t:'Recurring', href:'Recurring.html' },
      { id:'pos', k:'pos', t:'POS', href:'POS.html' },
    ]},
    { label:'Work', items:[
      { id:'jobs', k:'job', t:'Job Cards', count:'14', href:'JobCards.html' },
      { id:'bookings', k:'booking', t:'Bookings', dot:true, href:'Bookings.html' },
      { id:'schedule', k:'schedule', t:'Schedule', href:'Schedule.html' },
      { id:'staffschedule', k:'staff', t:'Staff Schedule', href:'StaffSchedule.html' },
      { id:'projects', k:'project', t:'Projects', href:'Projects.html' },
      { id:'time', k:'time', t:'Time Tracking', href:'TimeTracking.html' },
      { id:'payroll', k:'payroll', t:'Payroll', href:'Payroll.html' },
    ]},
    { label:'People & Stock', items:[
      { id:'customers', k:'cust', t:'Customers', href:'Customers.html' },
      { id:'vehicles', k:'car', t:'Vehicles', href:'Vehicles.html' },
      { id:'staff', k:'staff', t:'Staff', href:'Staff.html' },
      { id:'inventory', k:'inventory', t:'Inventory', href:'Inventory.html' },
      { id:'items', k:'items', t:'Items', href:'Items.html' },
      { id:'po', k:'po', t:'Purchase Orders', href:'PurchaseOrders.html' },
    ]},
    { label:'Money', items:[
      { id:'accounting', k:'accounting', t:'Accounting', href:'Accounting.html' },
      { id:'banking', k:'banking', t:'Banking', href:'Banking.html' },
      { id:'tax', k:'tax', t:'Tax / GST', href:'Tax.html' },
      { id:'expenses', k:'expense', t:'Expenses', href:'Expenses.html' },
    ]},
  ];
  const FOOT = [
    { id:'settings', k:'settings', t:'Settings', href:'Settings.html' },
    { id:'admin', k:'server', t:'Admin Console', href:'AdminConsole.html' },
  ];

  function svg(d, sw) { return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw||1.9}" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`; }
  function navItem(it, active) {
    return `<a class="nav-item ${it.id===active?'active':''}" href="${it.href||'#'}" data-nav="${it.id}">
      ${svg(ICON[it.k])}${it.t}
      ${it.count?`<span class="count">${it.count}</span>`:''}${it.dot?`<span class="dot"></span>`:''}
    </a>`;
  }

  const me = document.currentScript;
  const active = me.getAttribute('data-active') || '';
  const title = me.getAttribute('data-title') || '';
  document.title = (title?title+' · ':'') + 'OraInvoice';

  // ----- Sidebar -----
  const sb = document.getElementById('sidebar');
  if (sb) {
    sb.className = 'sidebar';
    sb.innerHTML = `
      <div class="sb-head">
        <div class="logo-mark">${svg(ICON.inv, 2.2)}</div>
        <div class="logo-name"><b>Ora</b><span class="dim">Invoice</span></div>
      </div>
      <div class="sb-scroll">
        ${NAV.map(g => `<div class="nav-group"><div class="nav-label">${g.label}</div>${g.items.map(it=>navItem(it,active)).join('')}</div>`).join('')}
        <div class="nav-group" style="margin-top:6px">${FOOT.map(it=>navItem(it,active)).join('')}</div>
      </div>
      <div class="sb-foot">
        <div class="org-switch">
          <div class="org-av">KM</div>
          <div class="org-meta"><div class="n">Kerikeri Motors</div><div class="p">PRO · 12 SEATS</div></div>
          <svg class="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 9l4-4 4 4M8 15l4 4 4-4"/></svg>
        </div>
      </div>`;
  }

  // ----- Top bar -----
  const tb = document.getElementById('topbar');
  if (tb) {
    tb.className = 'topbar';
    const primary = me.getAttribute('data-primary');
    tb.innerHTML = `
      <button class="icon-btn hamburger" id="__ham" aria-label="Menu">${svg('M4 6h16M4 12h16M4 18h16',2)}</button>
      <div class="search" id="__cmdkOpen" style="cursor:text">${svg('M21 21l-5-5m2-5a7 7 0 11-14 0 7 7 0 0114 0z',2)}<span>Search customers, invoices, jobs…</span><kbd>⌘K</kbd></div>
      <div class="spacer"></div>
      <div class="branch"><span class="pin"></span>Kerikeri <span class="mono">· BR-01</span></div>
      <button class="icon-btn" aria-label="Notifications">${svg('M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 00-4-5.7V5a2 2 0 10-4 0v.3C7.7 6.2 6 8.4 6 11v3.2c0 .5-.2 1-.6 1.4L4 17h5m6 0v1a3 3 0 11-6 0v-1',2)}<span class="bdg"></span></button>
      ${primary!==null ? `<a class="btn btn-primary" href="${me.getAttribute('data-primary-href')||'#'}">${svg('M12 5v14M5 12h14',2.2)}<span>${primary||'New'}</span></a>` : ''}
      <button class="avatar" aria-label="Account">AR</button>`;
  }

  // ----- Mobile drawer -----
  const app = document.querySelector('.app');
  const ham = document.getElementById('__ham');
  if (ham && app) {
    let scrim = document.querySelector('.scrim');
    if (!scrim) { scrim = document.createElement('div'); scrim.className = 'scrim'; app.prepend(scrim); }
    ham.addEventListener('click', () => app.classList.toggle('nav-open'));
    scrim.addEventListener('click', () => app.classList.remove('nav-open'));
  }

  // ----- Command palette (⌘K) -----
  (function cmdk(){
    const st = document.createElement('style');
    st.textContent = `
    .cmdk-scrim{position:fixed;inset:0;background:rgba(11,18,32,.5);z-index:200;display:none;}
    .cmdk-scrim.open{display:block;}
    .cmdk{position:fixed;left:50%;top:13%;transform:translateX(-50%);width:min(580px,92vw);background:var(--card);border-radius:var(--r-card);box-shadow:var(--shadow-pop);overflow:hidden;}
    .cmdk-in{display:flex;align-items:center;gap:11px;padding:0 16px;border-bottom:1px solid var(--border);}
    .cmdk-in svg{width:18px;height:18px;color:var(--muted-2);flex-shrink:0;}
    .cmdk-in input{flex:1;border:none;outline:none;background:none;font-family:inherit;font-size:15px;padding:15px 0;color:var(--text);}
    .cmdk-in kbd{font-family:var(--mono);font-size:11px;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:2px 6px;}
    .cmdk-list{max-height:344px;overflow-y:auto;padding:6px;}
    .cmdk-grp{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted-2);padding:10px 12px 5px;}
    .cmdk-item{display:flex;align-items:center;gap:11px;padding:9px 12px;border-radius:8px;cursor:pointer;font-size:13.5px;}
    .cmdk-item .ic{width:28px;height:28px;border-radius:7px;background:var(--canvas);display:grid;place-items:center;color:var(--muted);flex-shrink:0;}
    .cmdk-item .ic svg{width:15px;height:15px;}
    .cmdk-item .lab{font-weight:500;color:var(--text);}
    .cmdk-item .det{color:var(--muted);font-size:12px;margin-left:auto;white-space:nowrap;}
    .cmdk-item.on{background:var(--accent-soft);}
    .cmdk-item.on .lab{color:var(--accent);}
    .cmdk-empty{padding:34px;text-align:center;color:var(--muted);font-size:13px;}
    .cmdk-foot{display:flex;gap:16px;padding:9px 14px;border-top:1px solid var(--border);background:var(--canvas);font-size:11.5px;color:var(--muted);}
    .cmdk-foot kbd{font-family:var(--mono);border:1px solid var(--border);border-radius:5px;padding:1px 5px;background:var(--card);margin-right:5px;}`;
    document.head.appendChild(st);

    const DATA = [
      { g:'Customers', k:'cust', items:[
        {l:'Northland Freight',d:'BR-01 · fleet',h:'CustomerDetail.html'},
        {l:'Kane Williams',d:'021 447 9920',h:'CustomerDetail.html'},
        {l:'Coastal Builders',d:'Whangarei',h:'CustomerDetail.html'},
      ]},
      { g:'Vehicles', k:'car', items:[
        {l:'KMR-218',d:'Toyota Corolla 2019',h:'VehicleDetail.html'},
        {l:'NPR-447',d:'Isuzu NPR 400',h:'VehicleDetail.html'},
      ]},
      { g:'Invoices', k:'inv', items:[
        {l:'INV-2039',d:'Northland Freight · Overdue',h:'InvoiceDetail.html'},
        {l:'INV-2031',d:'Coastal Builders · Sent',h:'InvoiceDetail.html'},
      ]},
      { g:'Jump to', k:'go', items:[
        {l:'Dashboard',d:'',h:'Dashboard.html'},{l:'Invoices',d:'',h:'Invoices.html'},
        {l:'Quotes',d:'',h:'Quotes.html'},{l:'Job cards',d:'',h:'JobCards.html'},
        {l:'Customers',d:'',h:'Customers.html'},{l:'Vehicles',d:'',h:'Vehicles.html'},
        {l:'Reports',d:'',h:'Reports.html'},{l:'Settings',d:'',h:'Settings.html'},
        {l:'New invoice',d:'create',h:'InvoiceCreate.html'},{l:'New job card',d:'create',h:'JobCardCreate.html'},
        {l:'Payroll',d:'',h:'Payroll.html'},{l:'PPSR search',d:'vehicle security',h:'PPSRSearch.html'},
        {l:'SMS conversations',d:'',h:'SmsChat.html'},{l:'Leave approvals',d:'',h:'LeaveApprovals.html'},
        {l:'Shift swaps',d:'',h:'ShiftSwaps.html'},{l:'My payslips',d:'',h:'MyPayslips.html'},
      ]},
    ];
    const ICO = { cust:ICON.cust, car:ICON.car, inv:ICON.inv, go:'M5 12h14M13 6l6 6-6 6' };

    const wrap = document.createElement('div');
    wrap.className = 'cmdk-scrim';
    wrap.innerHTML = `<div class="cmdk" role="dialog" aria-label="Search">
      <div class="cmdk-in">${svg('M21 21l-5-5m2-5a7 7 0 11-14 0 7 7 0 0114 0z',2)}<input id="__cmdkInput" placeholder="Search customers, vehicles, invoices…" aria-label="Search"><kbd>Esc</kbd></div>
      <div class="cmdk-list" id="__cmdkList"></div>
      <div class="cmdk-foot"><span><kbd>↑↓</kbd>navigate</span><span><kbd>↵</kbd>select</span><span><kbd>esc</kbd>close</span></div>
    </div>`;
    document.body.appendChild(wrap);
    const input = wrap.querySelector('#__cmdkInput');
    const list = wrap.querySelector('#__cmdkList');
    let flat = [], active = 0;

    function render(){
      const q = input.value.trim().toLowerCase();
      flat = [];
      let html = '';
      DATA.forEach(sec => {
        const items = sec.items.filter(it => !q || it.l.toLowerCase().includes(q) || (it.d||'').toLowerCase().includes(q));
        if(!items.length) return;
        html += `<div class="cmdk-grp">${sec.g}</div>`;
        items.forEach(it => {
          const i = flat.length; flat.push(it);
          html += `<div class="cmdk-item ${i===active?'on':''}" data-i="${i}" data-h="${it.h}"><span class="ic">${svg(ICO[sec.k])}</span><span class="lab">${it.l}</span>${it.d?`<span class="det">${it.d}</span>`:''}</div>`;
        });
      });
      list.innerHTML = html || `<div class="cmdk-empty">No results for “${input.value}”</div>`;
      list.querySelectorAll('.cmdk-item').forEach(el=>{
        el.addEventListener('mouseenter',()=>{active=+el.dataset.i;paint();});
        el.addEventListener('click',()=>{location.href=el.dataset.h;});
      });
    }
    function paint(){ list.querySelectorAll('.cmdk-item').forEach(el=>el.classList.toggle('on',+el.dataset.i===active)); const on=list.querySelector('.cmdk-item.on'); if(on)on.scrollIntoView({block:'nearest'}); }
    function open(){ wrap.classList.add('open'); input.value=''; active=0; render(); requestAnimationFrame(()=>input.focus()); }
    function close(){ wrap.classList.remove('open'); }

    input.addEventListener('input',()=>{active=0;render();});
    input.addEventListener('keydown',e=>{
      if(e.key==='ArrowDown'){e.preventDefault();active=Math.min(active+1,flat.length-1);paint();}
      else if(e.key==='ArrowUp'){e.preventDefault();active=Math.max(active-1,0);paint();}
      else if(e.key==='Enter'){e.preventDefault();if(flat[active])location.href=flat[active].h;}
      else if(e.key==='Escape'){close();}
    });
    wrap.addEventListener('click',e=>{if(e.target===wrap)close();});
    document.addEventListener('keydown',e=>{ if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();wrap.classList.contains('open')?close():open();} });
    const opener = document.getElementById('__cmdkOpen');
    if(opener) opener.addEventListener('click',open);
  })();
})();
