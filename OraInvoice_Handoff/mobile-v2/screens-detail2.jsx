// screens-detail2.jsx — detail screens for module records (batch 3).
const { Ico: I3, money: m3, StatusBadge: SB3, Avatar: AV3, Navbar: NB3, IconBtn: IB3, DATA: D3 } = window;

function Meta({ k, v, mono }) {
  return <div className="meta-row"><span className="k">{k}</span><span className={`v${mono ? ' mono' : ''}`}>{v}</span></div>;
}
function StickyBar({ children }) {
  return <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: 'var(--pad)', paddingBottom: 'calc(var(--pad) + var(--safe-bot,0px))', background: 'color-mix(in srgb, var(--card) 90%, transparent)', backdropFilter: 'blur(14px)', borderTop: '1px solid var(--border)', display: 'flex', gap: 10 }}>{children}</div>;
}

/* ───────── QUOTE DETAIL ───────── */
function QuoteDetailScreen({ nav, params }) {
  const q = D3.quotes.find(x => x.id === params.id) || D3.quotes[0];
  const lines = [
    { desc: 'Design & consultation', qty: 1, rate: q.amount * 0.12 },
    { desc: 'Labour estimate', qty: 1, rate: q.amount * 0.46 },
    { desc: 'Materials & supply', qty: 1, rate: q.amount * 0.42 },
  ];
  const subtotal = lines.reduce((s, l) => s + l.qty * l.rate, 0);
  const gst = subtotal * 0.15;
  return (
    <div className="scr">
      <NB3 title={q.id} onBack={nav.pop} backLabel="Quotes" actions={<IB3 name="dots" label="More" />} />
      <div className="screen"><div className="pad scroll-pad stack" style={{ paddingBottom: 110 }}>
        <div className="card card-pad">
          <div className="amount-hero"><div className="lbl">Quoted total</div><div className="val">{m3(q.amount)}</div><div style={{ marginTop: 10 }}><SB3 status={q.status} /></div></div>
        </div>
        <div className="card">
          <div className="li" onClick={() => { const c = D3.customers.find(x => x.name === q.customer); if (c) nav.push('customerDetail', { id: c.id }); }}>
            <AV3 name={q.customer} square />
            <div className="body"><div className="t">{q.customer}</div><div className="s">Quote recipient</div></div>
            <I3 name="chev" className="chev" />
          </div>
          <div className="card-pad" style={{ paddingTop: 14, paddingBottom: 14 }}>
            <Meta k="Issued" v={`${q.date} 2025`} /><Meta k="Expires" v={`${q.expires} 2025`} /><Meta k="Reference" v={`REF-${q.id.slice(-3)}`} mono />
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Line items</h2><span className="muted mono" style={{ fontSize: 12 }}>{lines.length}</span></div>
          <div className="card-pad">
            {lines.map((l, i) => (
              <div className="meta-row" key={i} style={{ alignItems: 'flex-start' }}>
                <div style={{ flex: 1, paddingRight: 14 }}><div style={{ fontWeight: 600, fontSize: 14 }}>{l.desc}</div><div className="muted mono" style={{ fontSize: 12, marginTop: 3 }}>{l.qty} × {m3(l.rate)}</div></div>
                <span className="mono" style={{ fontWeight: 600 }}>{m3(l.qty * l.rate)}</span>
              </div>
            ))}
            <div style={{ height: 6 }}></div>
            <Meta k="Subtotal" v={m3(subtotal)} mono /><Meta k="GST 15%" v={m3(gst)} mono />
            <div className="meta-row" style={{ fontSize: 16 }}><span className="k" style={{ fontWeight: 700, color: 'var(--text)' }}>Total</span><span className="v mono" style={{ fontSize: 17 }}>{m3(subtotal + gst)}</span></div>
          </div>
        </div>
      </div></div>
      <StickyBar>
        <button className="btn btn-ghost" style={{ flex: '0 0 auto', width: 52, padding: 0 }} aria-label="Duplicate"><I3 name="copy" /></button>
        {q.status === 'accepted'
          ? <button className="btn btn-primary" onClick={() => nav.push('invoiceCreate')}><I3 name="invoice" /> Convert to invoice</button>
          : <button className="btn btn-primary" onClick={() => nav.pop()}><I3 name="send" /> Send quote</button>}
      </StickyBar>
    </div>
  );
}

/* ───────── JOB DETAIL ───────── */
function JobDetailScreen({ nav, params }) {
  const j = D3.jobs.find(x => x.id === params.id) || D3.jobs[0];
  const [tab, setTab] = React.useState('tasks');
  const tasks = [
    { t: 'Remove old cabinetry', done: true }, { t: 'Run new plumbing rough-in', done: true },
    { t: 'Install base units', done: true }, { t: 'Fit benchtop', done: false },
    { t: 'Connect appliances', done: false }, { t: 'Final clean & handover', done: false },
  ];
  const materials = [['Framing timber 90×45', '24 lm'], ['Cabinet hinges', '18 ea'], ['Silicone sealant', '3 ea']];
  return (
    <div className="scr">
      <NB3 title={j.id} onBack={nav.pop} backLabel="Jobs" actions={<IB3 name="dots" label="More" />} />
      <div className="screen"><div className="pad scroll-pad stack" style={{ paddingBottom: 110 }}>
        <div className="card card-pad">
          <div className="between" style={{ marginBottom: 8 }}><div className="t" style={{ fontWeight: 700, fontSize: 17 }}>{j.title}</div><SB3 status={j.status} /></div>
          <div className="s muted">{j.customer}</div>
          <div className="progress" style={{ margin: '14px 0 8px' }}><i style={{ width: `${j.progress}%`, background: j.status === 'completed' ? 'var(--ok)' : 'var(--accent)' }}></i></div>
          <div className="between" style={{ fontSize: 12.5 }}><span className="muted mono">{j.tasks}</span><span className="mono">{j.progress}%</span></div>
        </div>
        <div className="kpi-grid">
          <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>Assigned</div><div className="row" style={{ gap: 8 }}>{j.assignee !== 'Unassigned' ? <AV3 name={j.assignee} /> : <span className="av neutral"><I3 name="user" /></span>}<span style={{ fontWeight: 600, fontSize: 13.5 }}>{j.assignee}</span></div></div>
          <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>Due</div><div className="kval" style={{ fontSize: 17 }}>{j.due}</div></div>
        </div>
        <div className="seg">{[['tasks', 'Tasks'], ['materials', 'Materials'], ['notes', 'Notes']].map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
        {tab === 'tasks' && <div className="card">{tasks.map((t, i) => (
          <div className="li" key={i}><span className={`ico ${t.done ? 'green' : 'blue'}`} style={{ width: 32, height: 32 }}><I3 name={t.done ? 'check' : 'clock'} style={{ fontSize: 15 }} /></span><div className="body"><div className="t" style={{ fontSize: 14, fontWeight: 500, textDecoration: t.done ? 'line-through' : 'none', color: t.done ? 'var(--muted)' : 'var(--text)' }}>{t.t}</div></div></div>
        ))}</div>}
        {tab === 'materials' && <div className="card">{materials.map(([n, q], i) => (
          <div className="li" key={i}><span className="av tint"><I3 name="box" style={{ fontSize: 16 }} /></span><div className="body"><div className="t" style={{ fontSize: 14 }}>{n}</div></div><span className="amt mono">{q}</span></div>
        ))}</div>}
        {tab === 'notes' && <div className="card card-pad"><p style={{ fontSize: 14, lineHeight: 1.55, margin: 0, color: 'var(--text)' }}>Customer wants the splashback tiled before benchtop install. Confirm appliance dimensions with supplier — fridge cavity is tight. Access via rear gate, key in lockbox 4821.</p></div>}
      </div></div>
      <StickyBar>
        <button className="btn btn-ghost" style={{ flex: '0 0 auto', width: 52, padding: 0 }} aria-label="Camera"><I3 name="camera" /></button>
        <button className="btn btn-primary" onClick={() => nav.push('clock', { job: j.id })}><I3 name="play" /> Start timer</button>
      </StickyBar>
    </div>
  );
}

/* ───────── BOOKING DETAIL ───────── */
function BookingDetailScreen({ nav, params }) {
  const b = D3.bookings.find(x => x.id === params.id) || D3.bookings[0];
  return (
    <div className="scr">
      <NB3 title="Booking" onBack={nav.pop} backLabel="Bookings" actions={<IB3 name="edit" label="Edit" />} />
      <div className="screen"><div className="pad scroll-pad stack" style={{ paddingBottom: 110 }}>
        <div className="card card-pad" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--muted)' }}>Wednesday, 4 June</div>
          <div className="mono" style={{ fontSize: 36, fontWeight: 600, margin: '6px 0' }}>{b.t}</div>
          <div className="muted" style={{ fontSize: 13 }}>{b.d} · {b.svc}</div>
          <div style={{ marginTop: 12 }}><SB3 status={b.status} /></div>
        </div>
        <div className="card">
          <div className="li" onClick={() => { const c = D3.customers.find(x => x.name === b.cust); if (c) nav.push('customerDetail', { id: c.id }); }}>
            <AV3 name={b.cust} square /><div className="body"><div className="t">{b.cust}</div><div className="s">Customer</div></div><I3 name="chev" className="chev" />
          </div>
          <div className="card-pad" style={{ paddingTop: 14, paddingBottom: 14 }}>
            <Meta k="Assigned to" v={b.who} /><Meta k="Service" v={b.svc} />{b.vehicle && <Meta k="Vehicle" v={b.vehicle} mono />}<Meta k="Duration" v={b.d} />
          </div>
        </div>
        {b.notes && <div className="card card-pad"><div className="section-label" style={{ margin: '0 0 6px' }}>Notes</div><p style={{ fontSize: 14, lineHeight: 1.5, margin: 0 }}>{b.notes}</p></div>}
      </div></div>
      <StickyBar>
        <button className="btn btn-ghost" style={{ flex: '0 0 auto', width: 52, padding: 0 }} aria-label="Call"><I3 name="phone" /></button>
        <button className="btn btn-primary" onClick={() => nav.pop()}><I3 name="check" /> Mark complete</button>
      </StickyBar>
    </div>
  );
}

/* ───────── VEHICLE DETAIL ───────── */
function VehicleDetailScreen({ nav, params }) {
  const v = D3.vehicles.find(x => x.id === params.id) || D3.vehicles[0];
  const history = [
    { t: 'WOF inspection — passed', tm: '12 Dec 2024', on: true }, { t: 'Full service — 60k', tm: '4 Aug 2024', on: false },
    { t: 'Brake pads replaced', tm: '19 Mar 2024', on: false }, { t: 'Registered to customer', tm: '2 Jan 2024', on: false },
  ];
  return (
    <div className="scr">
      <NB3 title="Vehicle" onBack={nav.pop} backLabel="Vehicles" actions={<IB3 name="edit" label="Edit" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="card card-pad" style={{ textAlign: 'center' }}>
          <span className="acircle" style={{ width: 60, height: 60, margin: '0 auto 12px', background: 'var(--accent-soft)', color: 'var(--accent-fg)' }}><I3 name="car" style={{ fontSize: 26 }} /></span>
          <span className="mono" style={{ display: 'inline-block', background: 'var(--card-2)', border: '1px solid var(--border-strong)', borderRadius: 8, padding: '3px 12px', fontSize: 18, fontWeight: 600, letterSpacing: '0.06em' }}>{v.rego}</span>
          <h2 style={{ fontSize: 18, marginTop: 10 }}>{v.mk}</h2>
          <p className="muted" style={{ fontSize: 13.5, marginTop: 2 }}>{v.year} · {v.fuel} · {v.cust}</p>
        </div>
        <div className="kpi-grid">
          <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>WOF</div><span className={`badge ${v.wofcls}`}><span className="bd"></span>{v.wof}</span></div>
          <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>Next service</div><div className="kval" style={{ fontSize: 15 }}>{v.service}</div></div>
        </div>
        <div className="card card-pad"><Meta k="Odometer" v={v.odo} mono /><Meta k="VIN" v={v.vin} mono /><Meta k="Fuel type" v={v.fuel} /></div>
        <div className="card"><div className="card-head"><h2>Service history</h2></div><div className="card-pad"><div className="timeline">
          {history.map((h, i) => <div className={`tl-item${h.on ? ' on' : ''}`} key={i}><div className="t">{h.t}</div><div className="tm">{h.tm}</div></div>)}
        </div></div></div>
      </div></div>
      <CreateFab label="Log service" form="service" />
    </div>
  );
}

/* ───────── INVENTORY ITEM DETAIL ───────── */
function ItemDetailScreen({ nav, params }) {
  const it = D3.items.find(x => x.id === params.id) || D3.items[0];
  const [sheet, setSheet] = React.useState(false);
  const margin = Math.round((1 - it.cost / it.price) * 100);
  return (
    <div className="scr">
      <NB3 title="Item" onBack={nav.pop} backLabel="Inventory" actions={<IB3 name="edit" label="Edit" />} />
      <div className="screen"><div className="pad scroll-pad stack" style={{ paddingBottom: 110 }}>
        <div className="card card-pad">
          <div className="row" style={{ gap: 13 }}>
            <span className="av tint" style={{ width: 52, height: 52, borderRadius: 14 }}><I3 name="box" style={{ fontSize: 22 }} /></span>
            <div className="grow"><div className="t" style={{ fontWeight: 700, fontSize: 16 }}>{it.name}</div><div className="s mono muted" style={{ marginTop: 2 }}>{it.sku} · {it.cat}</div></div>
          </div>
        </div>
        <div className="kpi-grid">
          <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>In stock</div><div className="kval" style={{ fontSize: 22, color: it.low ? 'var(--danger)' : 'var(--text)' }}>{it.stock} <span style={{ fontSize: 13 }} className="muted">{it.unit}</span></div>{it.low && <div className="kdelta down"><I3 name="alert" /> Below reorder</div>}</div>
          <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>Margin</div><div className="kval" style={{ fontSize: 22 }}>{margin}%</div></div>
        </div>
        <div className="card card-pad"><Meta k="Sell price" v={`${m3(it.price)} / ${it.unit}`} mono /><Meta k="Cost price" v={`${m3(it.cost)} / ${it.unit}`} mono /><Meta k="Supplier" v={it.supplier} /><Meta k="Category" v={it.cat} /></div>
      </div></div>
      <StickyBar>
        <button className="btn btn-ghost" onClick={() => setSheet(true)}><I3 name="swap" /> Adjust stock</button>
        <button className="btn btn-primary" onClick={() => nav.push('purchaseOrders')}><I3 name="box" /> Reorder</button>
      </StickyBar>
      <div className={`sheet-scrim${sheet ? ' open' : ''}`} onClick={() => setSheet(false)}></div>
      <div className={`sheet${sheet ? ' open' : ''}`}>
        <div className="grab"></div>
        <div className="sheet-head"><h3>Adjust stock</h3><button className="nav-btn" onClick={() => setSheet(false)}><I3 name="x" /></button></div>
        <div className="sheet-body">
          <div className="field"><label>Reason</label><div className="seg"><button className="on">Received</button><button>Used</button><button>Wastage</button><button>Count</button></div></div>
          <div className="field"><label>Quantity</label><div className="input-group"><span className="pre">{it.unit}</span><input defaultValue="10" inputMode="decimal" /></div></div>
          <div className="field"><label>Note <span className="opt">(optional)</span></label><input className="input" placeholder="e.g. delivery from PlaceMakers" /></div>
          <button className="btn btn-primary" onClick={() => setSheet(false)}><I3 name="check" /> Apply adjustment</button>
          <div style={{ height: 8 }}></div>
        </div>
      </div>
    </div>
  );
}

/* ───────── PURCHASE ORDER DETAIL ───────── */
function PoDetailScreen({ nav, params }) {
  const p = D3.purchaseOrders.find(x => x.id === params.id) || D3.purchaseOrders[0];
  const subtotal = p.lines.reduce((s, l) => s + l.q * l.r, 0);
  const gst = subtotal * 0.15;
  return (
    <div className="scr">
      <NB3 title={p.id} onBack={nav.pop} backLabel="Orders" actions={<IB3 name="dots" label="More" />} />
      <div className="screen"><div className="pad scroll-pad stack" style={{ paddingBottom: 110 }}>
        <div className="card card-pad"><div className="amount-hero"><div className="lbl">Order total</div><div className="val">{m3(subtotal + gst)}</div><div style={{ marginTop: 10 }}><SB3 status={p.status} /></div></div></div>
        <div className="card card-pad"><Meta k="Supplier" v={p.sup} /><Meta k="Ordered" v={`${p.date} 2025`} /><Meta k="Expected" v={p.expected} /></div>
        <div className="card"><div className="card-head"><h2>Lines</h2><span className="muted mono" style={{ fontSize: 12 }}>{p.lines.length}</span></div><div className="card-pad">
          {p.lines.map((l, i) => (
            <div className="meta-row" key={i} style={{ alignItems: 'flex-start' }}><div style={{ flex: 1, paddingRight: 14 }}><div style={{ fontWeight: 600, fontSize: 14 }}>{l.d}</div><div className="muted mono" style={{ fontSize: 12, marginTop: 3 }}>{l.q} {l.u} × {m3(l.r)}</div></div><span className="mono" style={{ fontWeight: 600 }}>{m3(l.q * l.r)}</span></div>
          ))}
          <div style={{ height: 6 }}></div><Meta k="Subtotal" v={m3(subtotal)} mono /><Meta k="GST 15%" v={m3(gst)} mono />
          <div className="meta-row" style={{ fontSize: 16 }}><span className="k" style={{ fontWeight: 700, color: 'var(--text)' }}>Total</span><span className="v mono" style={{ fontSize: 17 }}>{m3(subtotal + gst)}</span></div>
        </div></div>
      </div></div>
      <StickyBar>
        {p.status === 'draft'
          ? <button className="btn btn-primary" onClick={() => nav.pop()}><I3 name="send" /> Send to supplier</button>
          : <button className="btn btn-primary" onClick={() => nav.pop()}><I3 name="check" /> Mark received</button>}
      </StickyBar>
    </div>
  );
}

/* ───────── PROJECT DETAIL ───────── */
function ProjectDetailScreen({ nav, params }) {
  const p = D3.projects.find(x => x.id === params.id) || D3.projects[0];
  const milestones = [
    { t: 'Demolition & strip-out', on: true }, { t: 'Services rough-in', on: true },
    { t: 'Linings & fit-off', on: p.prog > 50 }, { t: 'Finishing & handover', on: p.prog === 100 },
  ];
  return (
    <div className="scr">
      <NB3 title="Project" onBack={nav.pop} backLabel="Projects" actions={<IB3 name="dots" label="More" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="card card-pad">
          <div className="between" style={{ marginBottom: 6 }}><div className="t" style={{ fontWeight: 700, fontSize: 16 }}>{p.name}</div><SB3 status={p.status} /></div>
          <div className="s muted">{p.client}</div>
          <div className="progress" style={{ margin: '14px 0 8px' }}><i style={{ width: `${p.prog}%`, background: p.status === 'completed' ? 'var(--ok)' : 'var(--accent)' }}></i></div>
          <div className="between" style={{ fontSize: 12.5 }}><span className="muted mono">{p.prog}% complete</span><span className="muted">{p.start} – {p.due}</span></div>
        </div>
        <div className="kpi-grid">
          <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>Spent</div><div className="kval" style={{ fontSize: 19 }}>{m3(p.spent, 0)}</div><div className="kdelta">of {m3(p.budget, 0)}</div></div>
          <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>Remaining</div><div className="kval" style={{ fontSize: 19, color: 'var(--ok)' }}>{m3(p.budget - p.spent, 0)}</div></div>
        </div>
        <div className="card"><div className="card-head"><h2>Milestones</h2></div><div className="card-pad"><div className="timeline">
          {milestones.map((mn, i) => <div className={`tl-item${mn.on ? ' on' : ''}`} key={i}><div className="t">{mn.t}</div></div>)}
        </div></div></div>
        <div><div className="section-label">Team</div><div className="list">{p.team.map((n, i) => (
          <div className="li" key={i}><AV3 name={n} /><div className="body"><div className="t" style={{ fontSize: 14 }}>{n}</div></div></div>
        ))}</div></div>
      </div></div>
    </div>
  );
}

/* ───────── EXPENSE DETAIL ───────── */
function ExpenseDetailScreen({ nav, params }) {
  const e = D3.expenses.find(x => x.id === params.id) || D3.expenses[0];
  return (
    <div className="scr">
      <NB3 title="Expense" onBack={nav.pop} backLabel="Expenses" actions={<IB3 name="edit" label="Edit" />} />
      <div className="screen"><div className="pad scroll-pad stack" style={{ paddingBottom: 110 }}>
        <div className="card card-pad"><div className="amount-hero"><div className="lbl">{e.v}</div><div className="val">{m3(e.amt)}</div><div style={{ marginTop: 10 }}><SB3 status={e.status} /></div></div></div>
        <div style={{ borderRadius: 'var(--r-card)', overflow: 'hidden', border: '1px solid var(--border)', background: 'var(--card-2)', aspectRatio: '4 / 3', display: 'grid', placeItems: 'center', color: 'var(--muted-2)' }}>
          <div style={{ textAlign: 'center' }}><I3 name="image" style={{ fontSize: 32 }} /><div style={{ fontSize: 12.5, marginTop: 8 }}>Receipt photo</div></div>
        </div>
        <div className="card card-pad"><Meta k="Category" v={e.cat} /><Meta k="Date" v={`${e.date} 2025`} /><Meta k="Paid with" v={e.method} />{e.job && <Meta k="Job" v={e.job} mono />}<Meta k="GST" v={m3(e.gst)} mono /></div>
      </div></div>
      <StickyBar>
        <button className="btn btn-ghost" style={{ flex: '0 0 auto', width: 52, padding: 0 }} aria-label="Re-snap"><I3 name="camera" /></button>
        <button className="btn btn-primary" onClick={() => nav.pop()}><I3 name="check" /> Reconcile</button>
      </StickyBar>
    </div>
  );
}

/* ───────── STAFF DETAIL ───────── */
function StaffDetailScreen({ nav, params }) {
  const s = D3.staff.find(x => x.id === params.id) || D3.staff[0];
  return (
    <div className="scr">
      <NB3 title="Team member" onBack={nav.pop} backLabel="Staff" actions={<IB3 name="edit" label="Edit" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="card card-pad" style={{ textAlign: 'center' }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}><div className="acircle" style={{ width: 64, height: 64, fontSize: 22, background: D3.avatarColor(s.name) }}>{D3.initials(s.name)}</div></div>
          <h2 style={{ fontSize: 19 }}>{s.name}</h2>
          <p className="muted" style={{ fontSize: 13.5, marginTop: 3 }}>{s.role} · {s.empId}</p>
          <div className="btn-row" style={{ marginTop: 16 }}>
            {[['phone', 'Call'], ['sms', 'Text'], ['mail', 'Email']].map(([ic, l]) => (
              <button className="btn btn-ghost" key={l} style={{ flexDirection: 'column', height: 60, gap: 4, fontSize: 12 }}><I3 name={ic} style={{ fontSize: 19, color: 'var(--accent)' }} />{l}</button>
            ))}
          </div>
        </div>
        <div className="kpi-grid">
          <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>Status</div><span className={`badge ${s.cls}`}><span className="bd"></span>{s.status}</span></div>
          <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>Pay rate</div><div className="kval" style={{ fontSize: 19 }}>{s.rate ? `${m3(s.rate, 0)}/hr` : '—'}</div></div>
        </div>
        <div className="card card-pad"><Meta k="Phone" v={s.phone} mono /><Meta k="Email" v={s.email} /><Meta k="Started" v={s.start} /></div>
        <div><div className="section-label">Skills</div><div className="card card-pad"><div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{s.skills.map((sk, i) => <span key={i} className="badge neutral">{sk}</span>)}</div></div></div>
      </div></div>
    </div>
  );
}

Object.assign(window, {
  QuoteDetailScreen, JobDetailScreen, BookingDetailScreen, VehicleDetailScreen, ItemDetailScreen,
  PoDetailScreen, ProjectDetailScreen, ExpenseDetailScreen, StaffDetailScreen,
});
