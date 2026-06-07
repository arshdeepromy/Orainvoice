// screens-modules2.jsx — new module list screens (batch 4).
const { Ico: I4, money: m4, StatusBadge: SB4, Avatar: AV4, Navbar: NB4, IconBtn: IB4, DATA: D4 } = window;

function K4({ label, val, tint, icon, sub, subcls }) {
  return <div className="kpi"><div className="ktop"><span className="klabel">{label}</span>{icon && <span className={`ico ${tint}`}><I4 name={icon} /></span>}</div><div className="kval" style={{ fontSize: 20 }}>{val}</div>{sub && <div className={`kdelta ${subcls || ''}`}>{sub}</div>}</div>;
}
function Chips4({ items, value, onChange }) {
  return <div className="chips">{items.map(([k, l, n]) => <button key={k} className={`chip${value === k ? ' on' : ''}`} onClick={() => onChange(k)}>{l}{n != null && <span className="n">{n}</span>}</button>)}</div>;
}

/* ───────── ITEMS & CATALOGUE ───────── */
function ItemsScreen({ nav }) {
  const cats = [['all', 'All'], ['Timber', 'Timber'], ['Fixings', 'Fixings'], ['Paint', 'Paint'], ['Labour', 'Labour']];
  const [cat, setCat] = React.useState('all');
  const services = [{ name: 'Standard labour', price: 95, unit: 'hr' }, { name: 'Callout fee', price: 89, unit: 'ea' }, { name: 'WOF inspection', price: 70, unit: 'ea' }];
  return (
    <div className="scr">
      <NB4 title="Items & catalogue" sub="Price book" onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div className="pad-x" style={{ paddingTop: 4 }}><Chips4 items={cats} value={cat} onChange={setCat} /></div>
        <div className="pad scroll-pad stack" style={{ paddingTop: 12 }}>
          <div className="section-label">Products</div>
          <div className="list">{D4.items.map(it => (
            <div className="li" key={it.id} onClick={() => nav.push('itemDetail', { id: it.id })}>
              <span className="av tint"><I4 name="box" style={{ fontSize: 17 }} /></span>
              <div className="body"><div className="t">{it.name}</div><div className="s mono">{it.sku} · {it.cat}</div></div>
              <div className="end"><span className="amt">{m4(it.price)}</span><span className="muted mono" style={{ fontSize: 11 }}>/{it.unit}</span></div>
            </div>
          ))}</div>
          <div className="section-label">Services</div>
          <div className="list">{services.map((s, i) => (
            <div className="li" key={i}><span className="ico blue" style={{ width: 36, height: 36 }}><I4 name="wrench" style={{ fontSize: 16 }} /></span><div className="body"><div className="t">{s.name}</div></div><div className="end"><span className="amt">{m4(s.price)}</span><span className="muted mono" style={{ fontSize: 11 }}>/{s.unit}</span></div></div>
          ))}</div>
        </div>
      </div>
      <CreateFab label="Item" form="item" />
    </div>
  );
}

/* ───────── RECURRING INVOICES ───────── */
function RecurringScreen({ nav }) {
  return (
    <div className="scr">
      <NB4 title="Recurring invoices" onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="kpi-grid"><K4 label="Active schedules" val="2" tint="blue" icon="invoice" /><K4 label="Monthly value" val="$3,499" tint="green" icon="trend" /></div>
        <div className="list">{D4.recurring.map(r => (
          <div className="li" key={r.id}>
            <AV4 name={r.customer} square />
            <div className="body"><div className="t">{r.customer}</div><div className="s">{r.every} · next {r.next}</div></div>
            <div className="end"><span className="amt">{m4(r.amount)}</span><SB4 status={r.status === 'active' ? 'active' : 'pending'} /></div>
          </div>
        ))}</div>
      </div></div>
      <CreateFab label="Schedule" form="recurring" />
    </div>
  );
}

/* ───────── CLAIMS ───────── */
function ClaimsScreen({ nav }) {
  return (
    <div className="scr">
      <NB4 title="Claims" sub="Insurance & warranty" onBack={nav.pop} actions={<FilterBtn />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="kpi-grid"><K4 label="Open" val="2" tint="blue" icon="shield" /><K4 label="Value" val="$5,060" tint="amber" icon="dollar" /></div>
        <div className="list">{D4.claims.map(c => (
          <div className="li" key={c.id}>
            <span className="av tint"><I4 name="shield" style={{ fontSize: 17 }} /></span>
            <div className="body"><div className="t mono" style={{ fontSize: 14 }}>{c.id}</div><div className="s">{c.cust} · {c.insurer}</div></div>
            <div className="end"><span className="amt">{m4(c.amt)}</span><SB4 status={c.status} /></div>
          </div>
        ))}</div>
      </div></div>
      <CreateFab label="New claim" form="claim" />
    </div>
  );
}

/* ───────── CONSTRUCTION — progress claims & variations ───────── */
function ConstructionScreen({ nav }) {
  const [tab, setTab] = React.useState('claims');
  const claims = [
    { id: 'PC-07', proj: 'Coastal Apartments', amt: 38400, pct: '64%', status: 'sent' },
    { id: 'PC-06', proj: 'Coastal Apartments', amt: 31200, pct: '52%', status: 'completed' },
    { id: 'PC-03', proj: 'Te Awa cafe', amt: 12000, pct: '28%', status: 'draft' },
  ];
  const variations = [
    { id: 'VO-12', proj: 'Coastal Apartments', desc: 'Additional GPO circuits', amt: 2840, status: 'pending' },
    { id: 'VO-11', proj: 'Coastal Apartments', desc: 'Upgrade benchtop to stone', amt: 4100, status: 'completed' },
    { id: 'VO-09', proj: 'Te Awa cafe', desc: 'Extra waterproofing', amt: 1650, status: 'sent' },
  ];
  return (
    <div className="scr">
      <NB4 title="Construction" sub="Progress claims" onBack={nav.pop} actions={<IB4 name="dots" label="More" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="seg">{[['claims', 'Progress claims'], ['vary', 'Variations'], ['ret', 'Retentions']].map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
        {tab === 'claims' && <div className="list">{claims.map(c => (
          <div className="li" key={c.id}><span className="av tint"><I4 name="building" style={{ fontSize: 17 }} /></span><div className="body"><div className="t mono" style={{ fontSize: 14 }}>{c.id} · {c.pct}</div><div className="s">{c.proj}</div></div><div className="end"><span className="amt">{m4(c.amt, 0)}</span><SB4 status={c.status} /></div></div>
        ))}</div>}
        {tab === 'vary' && <div className="list">{variations.map(v => (
          <div className="li" key={v.id}><span className="av tint"><I4 name="edit" style={{ fontSize: 16 }} /></span><div className="body"><div className="t" style={{ fontSize: 14 }}>{v.desc}</div><div className="s mono">{v.id} · {v.proj}</div></div><div className="end"><span className="amt">{m4(v.amt, 0)}</span><SB4 status={v.status} /></div></div>
        ))}</div>}
        {tab === 'ret' && <div className="card card-pad stack" style={{ gap: 0 }}>
          <div className="amount-hero"><div className="lbl">Retentions held</div><div className="val">{m4(14820, 0)}</div></div>
          <div style={{ height: 10 }}></div>
          <div className="meta-row"><span className="k">Coastal Apartments (5%)</span><span className="v mono">{m4(9420, 0)}</span></div>
          <div className="meta-row"><span className="k">Te Awa cafe (5%)</span><span className="v mono">{m4(5400, 0)}</span></div>
          <div className="meta-row"><span className="k">Next release</span><span className="v">29 Aug 2025</span></div>
        </div>}
      </div></div>
      <CreateFab label="New" form="construction" />
    </div>
  );
}

/* ───────── ASSETS ───────── */
function AssetsScreen({ nav }) {
  return (
    <div className="scr">
      <NB4 title="Assets" sub={`${D4.assets.length} tracked`} onBack={nav.pop} actions={<IB4 name="qr" label="Scan" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="kpi-grid"><K4 label="Total value" val="$6,280" tint="blue" icon="box" /><K4 label="In use" val="3 / 4" tint="green" icon="check" /></div>
        <div className="list">{D4.assets.map(a => (
          <div className="li" key={a.id}><span className="av neutral"><I4 name="box" style={{ fontSize: 17 }} /></span><div className="body"><div className="t">{a.name}</div><div className="s mono">{a.tag} · {a.loc}</div></div><div className="end"><span className="amt">{m4(a.value, 0)}</span><span className={`badge ${a.status}`}><span className="bd"></span>{a.status === 'active' ? 'In use' : a.status === 'pending' ? 'On site' : 'Idle'}</span></div></div>
        ))}</div>
      </div></div>
      <CreateFab label="Add asset" form="asset" />
    </div>
  );
}

/* ───────── PPSR ───────── */
function PpsrScreen({ nav }) {
  const regs = [
    { id: 'FS-99201', debtor: 'Coastal Fitouts', coll: 'Cabinetry & fixtures', exp: 'Expires 2029', cls: 'active' },
    { id: 'FS-99188', debtor: 'Hayes Contracting', coll: 'Hilux KLN294', exp: 'Expires 2027', cls: 'active' },
    { id: 'FS-99102', debtor: 'Greenline', coll: 'Landscaping equipment', exp: 'Expiring 22 Jun', cls: 'warn' },
  ];
  return (
    <div className="scr">
      <NB4 title="PPSR" sub="Security register" onBack={nav.pop} actions={<SearchBtn nav={nav} />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="kpi-grid"><K4 label="Registered" val="3" tint="blue" icon="shield" /><K4 label="Expiring soon" val="1" tint="amber" icon="alert" /></div>
        <div className="list">{regs.map(r => (
          <div className="li" key={r.id}><span className={`ico ${r.cls === 'warn' ? 'amber' : 'blue'}`} style={{ width: 36, height: 36 }}><I4 name="lock" style={{ fontSize: 16 }} /></span><div className="body"><div className="t mono" style={{ fontSize: 13.5 }}>{r.id}</div><div className="s">{r.debtor} · {r.coll}</div></div><div className="end"><span className={`badge ${r.cls === 'warn' ? 'warn' : 'active'}`}><span className="bd"></span>{r.exp}</span></div></div>
        ))}</div>
      </div></div>
      <CreateFab label="Register" form="ppsr" />
    </div>
  );
}

/* ───────── LOYALTY ───────── */
function LoyaltyScreen({ nav }) {
  const members = [
    { name: 'Coastal Fitouts', pts: 4280, tier: 'Gold' }, { name: 'Mórné Property Group', pts: 2150, tier: 'Silver' },
    { name: 'Te Awa Cafe', pts: 890, tier: 'Bronze' }, { name: 'Aroha Whitiora', pts: 340, tier: 'Bronze' },
  ];
  const tierCls = { Gold: 'warn', Silver: 'neutral', Bronze: 'pending' };
  return (
    <div className="scr">
      <NB4 title="Loyalty" onBack={nav.pop} actions={<IB4 name="dots" label="More" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="card card-pad" style={{ background: 'linear-gradient(160deg, var(--ink), color-mix(in srgb, var(--accent) 38%, var(--ink)))', color: '#fff' }}>
          <div className="between"><span style={{ opacity: .8, fontSize: 13 }}>Rewards programme</span><I4 name="gift" style={{ fontSize: 20, opacity: .8 }} /></div>
          <div className="mono" style={{ fontSize: 30, fontWeight: 600, margin: '14px 0 4px' }}>7,660 pts</div>
          <div style={{ opacity: .7, fontSize: 12.5 }}>Issued this quarter</div>
        </div>
        <div className="section-label">Members</div>
        <div className="list">{members.map((mb, i) => (
          <div className="li" key={i}><AV4 name={mb.name} /><div className="body"><div className="t">{mb.name}</div><div className="s">{mb.pts.toLocaleString()} points</div></div><span className={`badge ${tierCls[mb.tier]}`}><I4 name="star" style={{ fontSize: 11 }} />{mb.tier}</span></div>
        ))}</div>
      </div></div>
    </div>
  );
}

/* ───────── PAYROLL / PAYSLIPS ───────── */
function PayrollScreen({ nav }) {
  return (
    <div className="scr">
      <NB4 title="Payroll" sub="Pay run · 26 May – 1 Jun" onBack={nav.pop} actions={<IB4 name="dots" label="More" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="kpi-grid"><K4 label="Total gross" val="$4,080" tint="blue" icon="dollar" /><K4 label="PAYE" val="$674" tint="amber" icon="receipt" /></div>
        <div className="section-label">Payslips</div>
        <div className="list">{D4.payslips.map(p => (
          <div className="li" key={p.id}><AV4 name={p.name} /><div className="body"><div className="t">{p.name}</div><div className="s">Net {m4(p.net)}</div></div><div className="end"><span className="amt">{m4(p.gross)}</span><SB4 status={p.status === 'paid' ? 'paid' : 'pending'} /></div></div>
        ))}</div>
        <button className="btn btn-primary"><I4 name="check" /> Approve pay run</button>
      </div></div>
    </div>
  );
}

/* ───────── LEAVE ───────── */
function LeaveScreen({ nav }) {
  const reqs = [
    { name: 'Mia Kemp', type: 'Annual leave', dates: '14–18 Jul', days: '5d', status: 'pending' },
    { name: 'Sefa Lautele', type: 'Sick leave', dates: '3 Jun', days: '1d', status: 'completed' },
    { name: 'Tom Rua', type: 'Annual leave', dates: '22–26 Jun', days: '5d', status: 'sent' },
  ];
  return (
    <div className="scr">
      <NB4 title="Leave" onBack={nav.pop} actions={<IB4 name="calendar" label="Calendar" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="kpi-grid"><K4 label="Pending" val="1" tint="amber" icon="clock" /><K4 label="Out this week" val="0" tint="blue" icon="user" /></div>
        <div className="list">{reqs.map((r, i) => (
          <div className="li" key={i}><AV4 name={r.name} /><div className="body"><div className="t">{r.name}</div><div className="s">{r.type} · {r.dates}</div></div><div className="end"><span className="amt">{r.days}</span><SB4 status={r.status === 'pending' ? 'pending' : r.status === 'sent' ? 'sent' : 'completed'} /></div></div>
        ))}</div>
      </div></div>
      <CreateFab label="Request" form="leave" />
    </div>
  );
}

/* ───────── ROSTER & SHIFT SWAPS ───────── */
function RosterScreen({ nav }) {
  const [tab, setTab] = React.useState('roster');
  const week = [
    { name: 'Tom Rua', mon: '7:30', tue: '7:30', wed: '7:30', thu: 'Off', fri: '7:30' },
    { name: 'Mia Kemp', mon: '8:00', tue: '8:00', wed: '8:00', thu: '8:00', fri: 'Off' },
    { name: 'Sefa Lautele', mon: '9:00', tue: 'Off', wed: '9:00', thu: '9:00', fri: '9:00' },
  ];
  const swaps = [
    { from: 'Sefa Lautele', to: 'Mia Kemp', day: 'Thu 5 Jun', status: 'pending' },
    { from: 'Tom Rua', to: 'Sefa Lautele', day: 'Sat 7 Jun', status: 'completed' },
  ];
  return (
    <div className="scr">
      <NB4 title="Roster" sub="Week of 2 Jun" onBack={nav.pop} actions={<IB4 name="calendar" label="Week" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="seg">{[['roster', 'Roster'], ['swaps', 'Shift swaps']].map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
        {tab === 'roster' && <div className="card" style={{ overflow: 'hidden' }}>
          <div className="card-pad" style={{ display: 'grid', gridTemplateColumns: '1.4fr repeat(5, 1fr)', gap: 4, fontSize: 11, fontWeight: 600, color: 'var(--muted)', borderBottom: '1px solid var(--border)', paddingBottom: 10 }}>
            <span></span><span>M</span><span>T</span><span>W</span><span>T</span><span>F</span>
          </div>
          {week.map((w, i) => (
            <div key={i} className="card-pad" style={{ display: 'grid', gridTemplateColumns: '1.4fr repeat(5, 1fr)', gap: 4, alignItems: 'center', fontSize: 11.5, borderBottom: i < week.length - 1 ? '1px solid var(--border)' : 'none', paddingTop: 11, paddingBottom: 11 }}>
              <span style={{ fontWeight: 600, fontSize: 12.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{w.name.split(' ')[0]}</span>
              {[w.mon, w.tue, w.wed, w.thu, w.fri].map((d, j) => <span key={j} className="mono" style={{ textAlign: 'center', color: d === 'Off' ? 'var(--muted-2)' : 'var(--text)', fontWeight: d === 'Off' ? 400 : 600 }}>{d}</span>)}
            </div>
          ))}
        </div>}
        {tab === 'swaps' && <div className="list">{swaps.map((s, i) => (
          <div className="li" key={i}><span className="av tint"><I4 name="swap" style={{ fontSize: 16 }} /></span><div className="body"><div className="t" style={{ fontSize: 13.5 }}>{s.from.split(' ')[0]} → {s.to.split(' ')[0]}</div><div className="s">{s.day}</div></div><SB4 status={s.status === 'pending' ? 'pending' : 'completed'} /></div>
        ))}</div>}
      </div></div>
      <CreateFab label="Shift" form="shift" />
    </div>
  );
}

/* ───────── SMS INBOX ───────── */
function SmsScreen({ nav }) {
  const threads = [
    { name: 'Daniel Hayes', msg: 'Cheers, that works for Thursday 👍', tm: '2m', unread: true },
    { name: 'Marcus Bell', msg: 'Can you push the measure to 10am?', tm: '1h', unread: true },
    { name: 'Aroha Whitiora', msg: 'Invoice received, paying today.', tm: '3h', unread: false },
    { name: 'Niko Patel', msg: 'Machine sounds much better now.', tm: 'Yesterday', unread: false },
  ];
  return (
    <div className="scr">
      <NB4 title="Messages" onBack={nav.pop} actions={<IB4 name="edit" label="New" />} />
      <div className="screen"><div className="pad-x" style={{ paddingTop: 4, paddingBottom: 10 }}><div className="searchbar"><I4 name="search" /><input placeholder="Search messages…" /></div></div>
        <div className="pad-x scroll-pad"><div className="list">{threads.map((t, i) => (
          <div className="li" key={i}><AV4 name={t.name} /><div className="body"><div className="t">{t.name}</div><div className="s" style={{ color: t.unread ? 'var(--text)' : 'var(--muted)', fontWeight: t.unread ? 500 : 400 }}>{t.msg}</div></div><div className="end"><span className="muted mono" style={{ fontSize: 11 }}>{t.tm}</span>{t.unread && <span style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--accent)' }}></span>}</div></div>
        ))}</div></div>
      </div>
      <CreateFab icon="edit" round form="message" />
    </div>
  );
}

/* ───────── PAYMENTS ───────── */
function PaymentsScreen({ nav }) {
  return (
    <div className="scr">
      <NB4 title="Payments" onBack={nav.pop} actions={<FilterBtn />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="kpi-grid"><K4 label="Received (7d)" val="$4,190" tint="green" icon="download" sub="↑ 8%" subcls="up" /><K4 label="Pending" val="$6,450" tint="amber" icon="clock" /></div>
        <div className="list">{D4.payments.map(p => (
          <div className="li" key={p.id}><span className={`ico ${p.status === 'completed' ? 'green' : 'amber'}`} style={{ width: 36, height: 36 }}><I4 name={p.method === 'Card' ? 'card' : 'bank'} style={{ fontSize: 16 }} /></span><div className="body"><div className="t">{p.customer}</div><div className="s mono">{p.inv} · {p.method}</div></div><div className="end"><span className="amt mono" style={{ color: p.status === 'completed' ? 'var(--ok)' : 'var(--text)' }}>{m4(p.amt)}</span><SB4 status={p.status === 'completed' ? 'paid' : 'pending'} /></div></div>
        ))}</div>
      </div></div>
    </div>
  );
}

/* ───────── GST / TAX RETURN ───────── */
function GstScreen({ nav }) {
  return (
    <div className="scr">
      <NB4 title="GST return" sub="Apr – May 2025" onBack={nav.pop} actions={<IB4 name="dots" label="More" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="card card-pad"><div className="amount-hero"><div className="lbl">GST payable</div><div className="val">{m4(4210)}</div><div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>Due 28 Jun 2025</div></div></div>
        <div className="card card-pad">
          <div className="meta-row"><span className="k">Sales (incl. GST)</span><span className="v mono">{m4(58420)}</span></div>
          <div className="meta-row"><span className="k">GST on sales</span><span className="v mono">{m4(7620)}</span></div>
          <div className="meta-row"><span className="k">GST on purchases</span><span className="v mono">−{m4(3410)}</span></div>
          <div className="meta-row" style={{ fontSize: 16 }}><span className="k" style={{ fontWeight: 700, color: 'var(--text)' }}>Net GST</span><span className="v mono" style={{ fontSize: 17 }}>{m4(4210)}</span></div>
        </div>
        <div className="card card-pad row" style={{ gap: 12 }}><span className="ico blue" style={{ width: 38, height: 38, borderRadius: 11 }}><I4 name="file" style={{ fontSize: 17 }} /></span><div className="body grow"><div className="t" style={{ fontSize: 14 }}>GST101A form</div><div className="s">Ready to file with IRD</div></div><I4 name="chev" className="chev" /></div>
        <button className="btn btn-primary"><I4 name="send" /> File with IRD</button>
      </div></div>
    </div>
  );
}

/* ───────── QUOTE CREATE ───────── */
function QuoteCreateScreen({ nav }) {
  const [lines, setLines] = React.useState([{ desc: 'Labour estimate', qty: 1, rate: 1800 }]);
  const subtotal = lines.reduce((s, l) => s + l.qty * l.rate, 0);
  const gst = subtotal * 0.15;
  return (
    <div className="scr">
      <NB4 title="New quote" onBack={nav.pop} actions={<button className="nav-btn txt" onClick={() => nav.pop()}>Save</button>} />
      <div className="screen"><div className="pad" style={{ paddingBottom: 110 }}>
        <div className="field"><label>Customer</label><div className="input row" style={{ alignItems: 'center', cursor: 'pointer' }}><AV4 name="Mórné Property Group" square /><span style={{ marginLeft: 10, fontWeight: 600 }}>Mórné Property Group</span><I4 name="chev" className="chev" style={{ marginLeft: 'auto' }} /></div></div>
        <div className="row" style={{ gap: 12 }}><div className="field grow"><label>Issued</label><input className="input" value="4 Jun 2025" readOnly /></div><div className="field grow"><label>Expires</label><input className="input" value="18 Jun 2025" readOnly /></div></div>
        <div className="section-label" style={{ marginTop: 6 }}>Line items</div>
        <div className="card" style={{ marginBottom: 14 }}>
          {lines.map((l, i) => (
            <div className="card-pad" key={i} style={{ borderBottom: '1px solid var(--border)' }}>
              <input className="input" style={{ marginBottom: 8 }} value={l.desc} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, desc: e.target.value } : x))} />
              <div className="row" style={{ gap: 8 }}>
                <div className="input-group" style={{ flex: 1 }}><span className="pre">Qty</span><input value={l.qty} inputMode="decimal" onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, qty: +e.target.value || 0 } : x))} /></div>
                <div className="input-group" style={{ flex: 1.4 }}><span className="pre">$</span><input value={l.rate} inputMode="decimal" onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, rate: +e.target.value || 0 } : x))} /></div>
                <span className="amt mono" style={{ width: 76, textAlign: 'right' }}>{m4(l.qty * l.rate)}</span>
              </div>
            </div>
          ))}
          <button className="card-pad row" style={{ width: '100%', color: 'var(--accent)', fontWeight: 600, fontSize: 14, gap: 8 }} onClick={() => setLines([...lines, { desc: '', qty: 1, rate: 0 }])}><I4 name="plus" /> Add line item</button>
        </div>
        <div className="card card-pad"><div className="meta-row"><span className="k">Subtotal</span><span className="v mono">{m4(subtotal)}</span></div><div className="meta-row"><span className="k">GST 15%</span><span className="v mono">{m4(gst)}</span></div><div className="meta-row" style={{ fontSize: 16 }}><span className="k" style={{ fontWeight: 700, color: 'var(--text)' }}>Total</span><span className="v mono" style={{ fontSize: 17 }}>{m4(subtotal + gst)}</span></div></div>
      </div></div>
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: 'var(--pad)', paddingBottom: 'calc(var(--pad) + var(--safe-bot,0px))', background: 'color-mix(in srgb, var(--card) 90%, transparent)', backdropFilter: 'blur(14px)', borderTop: '1px solid var(--border)', display: 'flex', gap: 10 }}>
        <button className="btn btn-ghost" style={{ flex: '0 0 auto', width: 110 }} onClick={() => nav.pop()}>Draft</button>
        <button className="btn btn-primary" onClick={() => nav.pop()}><I4 name="send" /> Create & send</button>
      </div>
    </div>
  );
}

Object.assign(window, {
  ItemsScreen, RecurringScreen, ClaimsScreen, ConstructionScreen, AssetsScreen, PpsrScreen,
  LoyaltyScreen, PayrollScreen, LeaveScreen, RosterScreen, SmsScreen, PaymentsScreen, GstScreen, QuoteCreateScreen,
});
