// screens-modules.jsx — v2 module screens (batch 2).
const { Ico: IM, money: mm, StatusBadge: SBm, Avatar: AVm, Navbar: NBm, IconBtn: IBm, DATA: DM } = window;

/* small shared bits */
function MiniKPI({ label, val, tint, icon, sub, subcls }) {
  return (
    <div className="kpi">
      <div className="ktop"><span className="klabel">{label}</span>{icon && <span className={`ico ${tint}`}><IM name={icon} /></span>}</div>
      <div className="kval" style={{ fontSize: 20 }}>{val}</div>
      {sub && <div className={`kdelta ${subcls || ''}`}>{sub}</div>}
    </div>
  );
}
function Chips({ items, value, onChange }) {
  return <div className="chips">{items.map(([k, l, n]) => (
    <button key={k} className={`chip${value === k ? ' on' : ''}`} onClick={() => onChange(k)}>{l}{n != null && <span className="n">{n}</span>}</button>
  ))}</div>;
}
function ModHeader({ title, sub, actions, onBack }) {
  return onBack
    ? <NBm title={title} onBack={onBack} actions={actions} />
    : <NBm title={title} sub={sub} big actions={actions} />;
}

/* ───────── BOOKINGS ───────── */
function BookingsScreen({ nav }) {
  const days = ['Mon 2', 'Tue 3', 'Wed 4', 'Thu 5', 'Fri 6'];
  const [day, setDay] = React.useState('Wed 4');
  const bookings = DM.bookings;
  return (
    <div className="scr">
      <ModHeader title="Bookings" sub="Wednesday, 4 June" actions={<React.Fragment><IBm name="calendar" label="Calendar" /><SearchBtn nav={nav} /></React.Fragment>} />
      <div className="screen">
        <div className="pad-x"><Chips items={days.map(d => [d, d])} value={day} onChange={setDay} /></div>
        <div className="pad scroll-pad stack" style={{ paddingTop: 12 }}>
          {bookings.map((b, i) => (
            <div className="card card-pad row" key={i} style={{ gap: 13, alignItems: 'stretch' }} onClick={() => nav.push('bookingDetail', { id: b.id })}>
              <div style={{ textAlign: 'center', minWidth: 52 }}>
                <div className="mono" style={{ fontWeight: 700, fontSize: 15 }}>{b.t}</div>
                <div className="muted" style={{ fontSize: 11 }}>{b.d}</div>
              </div>
              <div style={{ width: 3, borderRadius: 3, background: b.status === 'inprogress' ? 'var(--accent)' : b.status === 'completed' ? 'var(--ok)' : 'var(--border-strong)' }}></div>
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="between"><div className="t" style={{ fontWeight: 700 }}>{b.svc}</div><SBm status={b.status} /></div>
                <div className="s muted" style={{ marginTop: 3 }}>{b.cust}</div>
                <div className="row muted" style={{ fontSize: 12, gap: 6, marginTop: 7 }}><IM name="user" style={{ fontSize: 14 }} /> {b.who}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
      <CreateFab label="New" form="booking" />
    </div>
  );
}

/* ───────── SCHEDULE (staff) ───────── */
function ScheduleScreen({ nav }) {
  const staff = [
    { name: 'Tom Rua', role: 'Senior tech', shift: '7:30 – 16:30', status: 'In', hrs: '8.5h' },
    { name: 'Mia Kemp', role: 'Technician', shift: '8:00 – 17:00', status: 'In', hrs: '8.0h' },
    { name: 'Sefa Lautele', role: 'Apprentice', shift: '9:00 – 15:00', status: 'Break', hrs: '5.0h' },
    { name: 'Ruby Nott', role: 'Front desk', shift: '8:30 – 16:00', status: 'Off', hrs: '—' },
  ];
  return (
    <div className="scr">
      <ModHeader title="Schedule" onBack={nav.pop} actions={<IBm name="calendar" label="Week" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="kpi-grid">
          <MiniKPI label="On shift" val="3 / 4" tint="green" icon="user" />
          <MiniKPI label="Hours today" val="29.5h" tint="blue" icon="clock" />
        </div>
        <div className="section-label">Today · 4 June</div>
        <div className="list">
          {staff.map((s, i) => (
            <div className="li" key={i}>
              <AVm name={s.name} />
              <div className="body"><div className="t">{s.name}</div><div className="s">{s.role} · {s.shift}</div></div>
              <div className="end"><span className={`badge ${s.status === 'In' ? 'active' : s.status === 'Break' ? 'pending' : 'neutral'}`}><span className="bd"></span>{s.status}</span><span className="muted mono" style={{ fontSize: 12 }}>{s.hrs}</span></div>
            </div>
          ))}
        </div>
      </div></div>
    </div>
  );
}

/* ───────── VEHICLES ───────── */
function VehiclesScreen({ nav }) {
  const v = DM.vehicles;
  return (
    <div className="scr">
      <ModHeader title="Vehicles" sub={`${v.length} on file`} onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div className="pad scroll-pad">
        <div className="list">
          {v.map((x, i) => (
            <div className="li" key={i} onClick={() => nav.push('vehicleDetail', { id: x.id })}>
              <span className="av neutral"><IM name="car" style={{ fontSize: 18 }} /></span>
              <div className="body"><div className="t row" style={{ gap: 8 }}><span className="mono" style={{ background: 'var(--card-2)', border: '1px solid var(--border)', borderRadius: 6, padding: '1px 6px', fontSize: 12 }}>{x.rego}</span></div><div className="s" style={{ marginTop: 3 }}>{x.mk} · {x.cust}</div></div>
              <div className="end"><span className={`badge ${x.wofcls}`}><span className="bd"></span>{x.wof}</span></div>
            </div>
          ))}
        </div>
      </div></div>
      <CreateFab label="Add shift" form="shift" />
    </div>
  );
}

/* ───────── INVENTORY / ITEMS ───────── */
function InventoryScreen({ nav }) {
  const items = DM.items;
  return (
    <div className="scr">
      <ModHeader title="Inventory" sub="2 low stock" onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div className="pad-x" style={{ paddingTop: 4, paddingBottom: 10 }}><div className="searchbar"><IM name="search" /><input placeholder="Search items or SKU…" /></div></div>
        <div className="pad-x scroll-pad"><div className="list">
          {items.map((it, i) => (
            <div className="li" key={i} onClick={() => nav.push('itemDetail', { id: it.id })}>
              <span className="av tint"><IM name="box" style={{ fontSize: 18 }} /></span>
              <div className="body"><div className="t">{it.name}</div><div className="s mono">{it.sku} · {mm(it.price)}/{it.unit}</div></div>
              <div className="end">
                <span className="amt" style={{ color: it.low ? 'var(--danger)' : 'var(--text)' }}>{it.stock} {it.unit}</span>
                {it.low && <span className="badge overdue"><span className="bd"></span>Low</span>}
              </div>
            </div>
          ))}
        </div></div>
      </div>
      <CreateFab label="Item" form="item" />
    </div>
  );
}

/* ───────── EXPENSES ───────── */
function ExpensesScreen({ nav }) {
  const ex = DM.expenses;
  return (
    <div className="scr">
      <ModHeader title="Expenses" sub="June" onBack={nav.pop} actions={<FilterBtn />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="kpi-grid">
          <MiniKPI label="This month" val="$1,164" tint="amber" icon="receipt" />
          <MiniKPI label="Unreconciled" val="2" tint="red" icon="alert" />
        </div>
        <div className="list">
          {ex.map((e, i) => (
            <div className="li" key={i} onClick={() => nav.push('expenseDetail', { id: e.id })}>
              <span className="av neutral"><IM name="receipt" style={{ fontSize: 17 }} /></span>
              <div className="body"><div className="t">{e.v}</div><div className="s">{e.cat} · {e.date}</div></div>
              <div className="end"><span className="amt">{mm(e.amt)}</span><SBm status={e.status} /></div>
            </div>
          ))}
        </div>
      </div></div>
      <CreateFab icon="camera" label="Snap" form="expense" />
    </div>
  );
}

/* ───────── PURCHASE ORDERS ───────── */
function PurchaseOrdersScreen({ nav }) {
  const po = DM.purchaseOrders;
  return (
    <div className="scr">
      <ModHeader title="Purchase orders" onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div className="pad scroll-pad"><div className="list">
        {po.map((p, i) => (
          <div className="li" key={i} onClick={() => nav.push('poDetail', { id: p.id })}>
            <span className="av tint"><IM name="box" style={{ fontSize: 17 }} /></span>
            <div className="body"><div className="t mono" style={{ fontSize: 14 }}>{p.id}</div><div className="s">{p.sup} · {p.date}</div></div>
            <div className="end"><span className="amt">{mm(p.amt)}</span><SBm status={p.status} /></div>
          </div>
        ))}
      </div></div></div>
      <CreateFab label="New PO" form="po" />
    </div>
  );
}

/* ───────── PROJECTS ───────── */
function ProjectsScreen({ nav }) {
  const pr = DM.projects;
  return (
    <div className="scr">
      <ModHeader title="Projects" sub="2 active" onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div className="pad scroll-pad stack">
        {pr.map((p, i) => (
          <div className="card card-pad" key={i} onClick={() => nav.push('projectDetail', { id: p.id })}>
            <div className="between" style={{ marginBottom: 8 }}><div className="t" style={{ fontWeight: 700, fontSize: 15.5 }}>{p.name}</div><SBm status={p.status} /></div>
            <div className="s muted">{p.client}</div>
            <div className="progress" style={{ margin: '13px 0 7px' }}><i style={{ width: `${p.prog}%`, background: p.status === 'completed' ? 'var(--ok)' : 'var(--accent)' }}></i></div>
            <div className="between" style={{ fontSize: 12.5 }}><span className="muted mono">{p.prog}% complete</span><span className="mono">{mm(p.spent, 0)} <span className="muted">/ {mm(p.budget, 0)}</span></span></div>
          </div>
        ))}
      </div></div>
      <CreateFab label="New" form="project" />
    </div>
  );
}

/* ───────── STAFF ───────── */
function StaffScreen({ nav }) {
  const st = DM.staff;
  return (
    <div className="scr">
      <ModHeader title="Staff" sub={`${st.length} team members`} onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div className="pad scroll-pad"><div className="list">
        {st.map((s, i) => (
          <div className="li" key={i} onClick={() => nav.push('staffDetail', { id: s.id })}>
            <AVm name={s.name} />
            <div className="body"><div className="t">{s.name}</div><div className="s">{s.role}</div></div>
            <div className="end"><span className={`badge ${s.cls}`}><span className="bd"></span>{s.status}</span></div>
          </div>
        ))}
      </div></div></div>
      <CreateFab label="Invite" form="staff" />
    </div>
  );
}

/* ───────── REPORTS ───────── */
function ReportsScreen({ nav }) {
  const groups = [
    { label: 'Financial', items: [['chart', 'Profit & Loss', 'pl'], ['bank', 'Balance Sheet', 'balance'], ['dollar', 'Cash Flow', 'cashflow']] },
    { label: 'Sales', items: [['invoice', 'Revenue summary', 'revenue'], ['trend', 'Top services', 'topservices'], ['customers', 'Aged receivables', 'aged']] },
    { label: 'Tax', items: [['receipt', 'GST return', 'gstreturn'], ['shield', 'Tax position', 'taxposition']] },
  ];
  return (
    <div className="scr">
      <ModHeader title="Reports" sub="Library" onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div className="pad scroll-pad stack">
        {groups.map((g, gi) => (
          <div key={gi}>
            <div className="section-label">{g.label}</div>
            <div className="list">
              {g.items.map(([ic, l, slug], i) => (
                <div className="li" key={i} onClick={() => nav.push('reportDetail', { id: slug })}>
                  <span className="ico blue" style={{ width: 34, height: 34 }}><IM name={ic} style={{ fontSize: 16 }} /></span>
                  <div className="body"><div className="t" style={{ fontSize: 14, fontWeight: 500 }}>{l}</div></div>
                  <IM name="chev" className="chev" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div></div>
    </div>
  );
}

/* ───────── ACCOUNTING ───────── */
function AccountingScreen({ nav }) {
  return (
    <div className="scr">
      <ModHeader title="Accounting" onBack={nav.pop} actions={<IBm name="dots" label="More" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="kpi-grid">
          <MiniKPI label="Net profit (MTD)" val="$18,420" tint="green" icon="trend" sub="↑ 11%" subcls="up" />
          <MiniKPI label="GST due" val="$4,210" tint="amber" icon="receipt" sub="Due 28 Jun" />
        </div>
        <div className="section-label">Ledgers</div>
        <div className="list">
          {[['chart', 'Chart of accounts'], ['receipt', 'Journal entries'], ['bank', 'Reconciliation', '3'], ['dollar', 'Tax position'], ['calendar', 'GST periods']].map(([ic, l, n], i) => (
            <div className="li" key={i}>
              <span className="ico blue" style={{ width: 34, height: 34 }}><IM name={ic} style={{ fontSize: 16 }} /></span>
              <div className="body"><div className="t" style={{ fontSize: 14, fontWeight: 500 }}>{l}</div></div>
              {n && <span className="badge warn" style={{ marginRight: 8 }}>{n}</span>}
              <IM name="chev" className="chev" />
            </div>
          ))}
        </div>
      </div></div>
    </div>
  );
}

/* ───────── BANKING ───────── */
function BankingScreen({ nav }) {
  const tx = [
    { d: 'Mórné Property Group', s: 'Payment · INV-2036', amt: 3300.00, in: true },
    { d: 'PlaceMakers', s: 'Card purchase', amt: -642.00, in: false },
    { d: 'Te Awa Cafe', s: 'Payment · INV-2039', amt: 890.00, in: true },
    { d: 'Z Energy', s: 'Card purchase', amt: -110.20, in: false },
  ];
  return (
    <div className="scr">
      <ModHeader title="Banking" onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="card card-pad" style={{ background: 'linear-gradient(160deg, var(--ink), color-mix(in srgb, var(--accent) 38%, var(--ink)))', color: '#fff' }}>
          <div className="between"><span style={{ opacity: .8, fontSize: 13 }}>ASB Business · ••4821</span><IM name="bank" style={{ fontSize: 20, opacity: .8 }} /></div>
          <div className="mono" style={{ fontSize: 32, fontWeight: 600, margin: '14px 0 4px' }}>$42,318.55</div>
          <div style={{ opacity: .7, fontSize: 12.5 }}>Available balance</div>
        </div>
        <div className="between"><div className="section-label" style={{ margin: 0 }}>Recent transactions</div><span className="link" style={{ color: 'var(--accent)', fontWeight: 600, fontSize: 13 }}>Reconcile</span></div>
        <div className="list">
          {tx.map((t, i) => (
            <div className="li" key={i}>
              <span className={`ico ${t.in ? 'green' : 'neutral'}`} style={{ width: 36, height: 36 }}><IM name={t.in ? 'download' : 'card'} style={{ fontSize: 16 }} /></span>
              <div className="body"><div className="t" style={{ fontSize: 14 }}>{t.d}</div><div className="s">{t.s}</div></div>
              <span className="amt mono" style={{ color: t.in ? 'var(--ok)' : 'var(--text)' }}>{t.in ? '+' : ''}{mm(t.amt)}</span>
            </div>
          ))}
        </div>
      </div></div>
    </div>
  );
}

/* ───────── COMPLIANCE ───────── */
function ComplianceScreen({ nav }) {
  const docs = [
    { name: 'Public liability insurance', exp: 'Expires 18 Jun', cls: 'warn' },
    { name: 'Site safety plan — Coastal', exp: 'Valid', cls: 'active' },
    { name: 'Electrical WoF certificate', exp: 'Expired 2 Jun', cls: 'overdue' },
    { name: 'Hazardous substances reg.', exp: 'Valid to 2026', cls: 'active' },
  ];
  return (
    <div className="scr">
      <ModHeader title="Compliance" sub="1 expired · 1 expiring" onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="kpi-grid">
          <MiniKPI label="Valid" val="2" tint="green" icon="check" />
          <MiniKPI label="Action needed" val="2" tint="red" icon="alert" />
        </div>
        <div className="list">
          {docs.map((d, i) => (
            <div className="li" key={i}>
              <span className={`ico ${d.cls === 'overdue' ? 'red' : d.cls === 'warn' ? 'amber' : 'green'}`} style={{ width: 36, height: 36 }}><IM name="shield" style={{ fontSize: 17 }} /></span>
              <div className="body"><div className="t" style={{ fontSize: 14 }}>{d.name}</div></div>
              <div className="end"><span className={`badge ${d.cls}`}><span className="bd"></span>{d.exp}</span></div>
            </div>
          ))}
        </div>
      </div></div>
      <CreateFab icon="upload" label="Upload" form="compliance" />
    </div>
  );
}

/* ───────── POS ───────── */
function PosScreen({ nav }) {
  const cats = ['Popular', 'Labour', 'Parts', 'Fluids', 'Tyres'];
  const [cat, setCat] = React.useState('Popular');
  const prods = [
    { n: 'Standard service', p: 189 }, { n: 'WOF check', p: 70 }, { n: 'Oil change', p: 95 },
    { n: 'Brake pads', p: 145 }, { n: 'Wiper blades', p: 38 }, { n: 'Wheel align', p: 89 },
  ];
  return (
    <div className="scr">
      <ModHeader title="Point of Sale" onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div style={{ paddingBottom: 96 }}>
        <div className="pad-x" style={{ paddingTop: 4 }}><Chips items={cats.map(c => [c, c])} value={cat} onChange={setCat} /></div>
        <div className="pad" style={{ paddingTop: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--gap)' }}>
            {prods.map((p, i) => (
              <button key={i} className="card card-pad" style={{ textAlign: 'left', minHeight: 96, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div className="t" style={{ fontWeight: 600, fontSize: 14 }}>{p.n}</div>
                <div className="mono" style={{ fontWeight: 600, fontSize: 16 }}>{mm(p.p, 0)}</div>
              </button>
            ))}
          </div>
        </div>
      </div></div>
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: 'var(--pad)', paddingBottom: 'calc(var(--pad) + var(--safe-bot,0px))', background: 'color-mix(in srgb, var(--card) 92%, transparent)', backdropFilter: 'blur(14px)', borderTop: '1px solid var(--border)' }}>
        <button className="btn btn-primary" style={{ justifyContent: 'space-between' }}><span className="row" style={{ gap: 8 }}><IM name="card" /> Charge · 3 items</span><span className="mono">{mm(354)}</span></button>
      </div>
    </div>
  );
}

/* ───────── NOTIFICATIONS ───────── */
function NotificationsScreen({ nav }) {
  const items = [
    { ic: 'dollar', cls: 'green', t: 'Payment received', s: 'Mórné Property Group paid INV-2036', tm: '2h ago', unread: true },
    { ic: 'alert', cls: 'red', t: 'Invoice overdue', s: 'INV-2041 · Hayes Contracting, 9 days', tm: '5h ago', unread: true },
    { ic: 'quote', cls: 'blue', t: 'Quote accepted', s: 'Coastal Fitouts accepted QTE-188', tm: 'Yesterday', unread: false },
    { ic: 'shield', cls: 'amber', t: 'Compliance expiring', s: 'Public liability insurance — 14 days', tm: 'Yesterday', unread: false },
    { ic: 'job', cls: 'purple', t: 'Job assigned to you', s: 'JOB-317 · Brake & WOF — Hilux', tm: '2 days ago', unread: false },
  ];
  return (
    <div className="scr">
      <ModHeader title="Notifications" onBack={nav.pop} actions={<IBm name="check" label="Mark read" />} />
      <div className="screen"><div className="pad scroll-pad"><div className="list">
        {items.map((n, i) => (
          <div className="li" key={i} style={{ background: n.unread ? 'var(--accent-soft)' : '' }}>
            <span className={`ico ${n.cls}`} style={{ width: 38, height: 38 }}><IM name={n.ic} style={{ fontSize: 17 }} /></span>
            <div className="body"><div className="t" style={{ fontSize: 14 }}>{n.t}</div><div className="s" style={{ whiteSpace: 'normal' }}>{n.s}</div><div className="tm mono" style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 3 }}>{n.tm}</div></div>
            {n.unread && <span style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--accent)', flexShrink: 0 }}></span>}
          </div>
        ))}
      </div></div></div>
    </div>
  );
}

/* ───────── SETTINGS ───────── */
function SettingsScreen({ nav, dark, onToggleDark }) {
  const groups = [
    { label: 'Organisation', items: [['building', 'Business details', 'business'], ['pin', 'Branches & locations', 'branches'], ['box', 'Modules', 'modules'], ['edit', 'Branding & templates', 'branding']] },
    { label: 'People', items: [['user', 'Team & roles', 'team'], ['clock', 'Timesheets & payroll', 'timesheets']] },
    { label: 'System', items: [['card', 'Billing & plan', 'billing'], ['bank', 'Integrations', 'integrations'], ['shield', 'Security', 'security'], ['download', 'Data & export', 'data']] },
  ];
  return (
    <div className="scr">
      <ModHeader title="Settings" onBack={nav.pop} />
      <div className="screen"><div className="pad scroll-pad stack">
        {groups.map((g, gi) => (
          <div key={gi}>
            <div className="section-label">{g.label}</div>
            <div className="list">
              {g.items.map(([ic, l, slug], i) => (
                <div className="li" key={i} onClick={() => nav.push('settingsDetail', { id: slug })}>
                  <span className="ico blue" style={{ width: 34, height: 34 }}><IM name={ic} style={{ fontSize: 16 }} /></span>
                  <div className="body"><div className="t" style={{ fontSize: 14, fontWeight: 500 }}>{l}</div></div>
                  <IM name="chev" className="chev" />
                </div>
              ))}
            </div>
          </div>
        ))}
        <div>
          <div className="section-label">Appearance</div>
          <div className="list"><div className="li">
            <span className="ico amber" style={{ width: 34, height: 34 }}><IM name={dark ? 'moon' : 'sun'} style={{ fontSize: 16 }} /></span>
            <div className="body"><div className="t" style={{ fontSize: 14, fontWeight: 500 }}>Dark mode</div></div>
            <span className={`toggle${dark ? ' on' : ''}`} onClick={onToggleDark}></span>
          </div></div>
        </div>
      </div></div>
    </div>
  );
}

Object.assign(window, {
  BookingsScreen, ScheduleScreen, VehiclesScreen, InventoryScreen, ExpensesScreen, PurchaseOrdersScreen,
  ProjectsScreen, StaffScreen, ReportsScreen, AccountingScreen, BankingScreen, ComplianceScreen,
  PosScreen, NotificationsScreen, SettingsScreen,
});
