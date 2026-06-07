// screens-detail.jsx — detail, create & clock screens.
const { Ico: I2, money: m2, StatusBadge: SB2, Avatar: AV2, Navbar: NB2, IconBtn: IB2, DATA: D2 } = window;

/* ───────────────────────── INVOICE DETAIL ───────────────────────── */
function InvoiceDetailScreen({ nav, params }) {
  const inv = D2.invoices.find(i => i.id === params.id) || D2.invoices[0];
  const [paySheet, setPaySheet] = React.useState(false);
  const subtotal = inv.items.reduce((s, it) => s + it.amt, 0);
  const gst = subtotal * 0.15;
  const statusColor = inv.status === 'overdue' ? 'var(--danger)' : inv.status === 'paid' ? 'var(--ok)' : 'var(--text)';
  return (
    <div className="scr">
      <NB2 title={inv.id} onBack={nav.pop} backLabel="Invoices" actions={<IB2 name="dots" label="More" />} />
      <div className="screen">
        <div className="pad scroll-pad stack" style={{ paddingBottom: 110 }}>
          <div className="card card-pad">
            <div className="amount-hero">
              <div className="lbl">{inv.status === 'paid' ? 'Paid in full' : 'Amount due'}</div>
              <div className="val" style={{ color: statusColor }}>{m2(inv.amount)}</div>
              <div style={{ marginTop: 10 }}><SB2 status={inv.status} /></div>
            </div>
          </div>

          <div className="card">
            <div className="li" onClick={() => { const c = D2.customers.find(x => x.name === inv.customer); if (c) nav.push('customerDetail', { id: c.id }); }}>
              <AV2 name={inv.customer} square />
              <div className="body"><div className="t">{inv.customer}</div><div className="s">Billed to · NZ GST registered</div></div>
              <I2 name="chev" className="chev" />
            </div>
            <div className="card-pad" style={{ paddingTop: 14, paddingBottom: 14 }}>
              <div className="meta-row"><span className="k">Issued</span><span className="v">{inv.date} 2025</span></div>
              <div className="meta-row"><span className="k">Due</span><span className="v">{inv.due} 2025</span></div>
              <div className="meta-row"><span className="k">Reference</span><span className="v mono">PO-{inv.id.slice(-4)}</span></div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h2>Line items</h2><span className="muted mono" style={{ fontSize: 12 }}>{inv.items.length} items</span></div>
            <div className="card-pad">
              {inv.items.map((it, i) => (
                <div className="meta-row" key={i} style={{ alignItems: 'flex-start' }}>
                  <div style={{ flex: 1, paddingRight: 14, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, lineHeight: 1.35 }}>{it.desc}</div>
                    <div className="muted mono" style={{ fontSize: 12, marginTop: 3 }}>{it.qty} × {m2(it.rate)}</div>
                  </div>
                  <span className="mono" style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{m2(it.amt)}</span>
                </div>
              ))}
              <div style={{ height: 6 }}></div>
              <div className="meta-row"><span className="k">Subtotal</span><span className="v mono">{m2(subtotal)}</span></div>
              <div className="meta-row"><span className="k">GST 15%</span><span className="v mono">{m2(gst)}</span></div>
              <div className="meta-row" style={{ fontSize: 16 }}><span className="k" style={{ fontWeight: 700, color: 'var(--text)' }}>Total</span><span className="v mono" style={{ fontSize: 17 }}>{m2(subtotal + gst)}</span></div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h2>History</h2></div>
            <div className="card-pad"><div className="timeline">
              <div className="tl-item on"><div className="t">Invoice {inv.status === 'paid' ? 'paid' : 'viewed by customer'}</div><div className="tm">{inv.status === 'paid' ? '2h ago' : 'Yesterday 4:12pm'}</div></div>
              <div className="tl-item"><div className="t">Sent via email</div><div className="s">{inv.customer}</div><div className="tm">{inv.date}, 9:03am</div></div>
              <div className="tl-item"><div className="t">Created</div><div className="tm">{inv.date}, 8:51am</div></div>
            </div></div>
          </div>
        </div>
      </div>

      {/* sticky action bar */}
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: 'var(--pad)', paddingBottom: 'calc(var(--pad) + var(--safe-bot, 0px))', background: 'color-mix(in srgb, var(--card) 90%, transparent)', backdropFilter: 'blur(14px)', borderTop: '1px solid var(--border)', display: 'flex', gap: 10 }}>
        {inv.status === 'paid'
          ? <button className="btn btn-ghost" onClick={() => nav.pop()}><I2 name="download" /> Download PDF</button>
          : <React.Fragment>
              <button className="btn btn-ghost" style={{ flex: '0 0 auto', width: 52, padding: 0 }} aria-label="Send"><I2 name="send" /></button>
              <button className="btn btn-primary" onClick={() => setPaySheet(true)}><I2 name="dollar" /> Record payment</button>
            </React.Fragment>}
      </div>

      {/* payment sheet */}
      <div className={`sheet-scrim${paySheet ? ' open' : ''}`} onClick={() => setPaySheet(false)}></div>
      <div className={`sheet${paySheet ? ' open' : ''}`}>
        <div className="grab"></div>
        <div className="sheet-head"><h3>Record payment</h3><button className="nav-btn" onClick={() => setPaySheet(false)}><I2 name="x" /></button></div>
        <div className="sheet-body">
          <div className="field"><label>Amount</label><div className="input-group"><span className="pre">$</span><input value={inv.amount.toFixed(2)} readOnly /></div></div>
          <div className="field"><label>Method</label><div className="seg"><button className="on">Bank</button><button>Card</button><button>Cash</button></div></div>
          <div className="field"><label>Date received</label><input className="input" value="4 June 2025" readOnly /></div>
          <button className="btn btn-primary" onClick={() => setPaySheet(false)}><I2 name="check" /> Confirm payment</button>
          <div style={{ height: 8 }}></div>
        </div>
      </div>
    </div>
  );
}

/* ───────────────────────── INVOICE CREATE ───────────────────────── */
function InvoiceCreateScreen({ nav }) {
  const [lines, setLines] = React.useState([{ desc: 'Site labour', qty: 8, rate: 95 }]);
  const subtotal = lines.reduce((s, l) => s + l.qty * l.rate, 0);
  const gst = subtotal * 0.15;
  return (
    <div className="scr">
      <NB2 title="New invoice" onBack={nav.pop} backLabel="" actions={<button className="nav-btn txt" onClick={() => nav.pop()}>Save</button>} />
      <div className="screen">
        <div className="pad scroll-pad" style={{ paddingBottom: 110 }}>
          <div className="field"><label>Customer</label>
            <div className="input row" style={{ alignItems: 'center', cursor: 'pointer' }}><AV2 name="Coastal Fitouts" square /><span style={{ marginLeft: 10, fontWeight: 600 }}>Coastal Fitouts</span><I2 name="chev" className="chev" style={{ marginLeft: 'auto' }} /></div>
          </div>
          <div className="row" style={{ gap: 12 }}>
            <div className="field grow"><label>Issue date</label><input className="input" value="4 Jun 2025" readOnly /></div>
            <div className="field grow"><label>Due</label><input className="input" value="18 Jun 2025" readOnly /></div>
          </div>

          <div className="section-label" style={{ marginTop: 6 }}>Line items</div>
          <div className="card" style={{ marginBottom: 14 }}>
            {lines.map((l, i) => (
              <div className="card-pad" key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                <input className="input" style={{ marginBottom: 8 }} value={l.desc} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, desc: e.target.value } : x))} />
                <div className="row" style={{ gap: 8 }}>
                  <div className="input-group" style={{ flex: 1 }}><span className="pre">Qty</span><input value={l.qty} inputMode="decimal" onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, qty: +e.target.value || 0 } : x))} /></div>
                  <div className="input-group" style={{ flex: 1.4 }}><span className="pre">$</span><input value={l.rate} inputMode="decimal" onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, rate: +e.target.value || 0 } : x))} /></div>
                  <span className="amt mono" style={{ width: 76, textAlign: 'right' }}>{m2(l.qty * l.rate)}</span>
                </div>
              </div>
            ))}
            <button className="card-pad row" style={{ width: '100%', color: 'var(--accent)', fontWeight: 600, fontSize: 14, gap: 8 }} onClick={() => setLines([...lines, { desc: '', qty: 1, rate: 0 }])}><I2 name="plus" /> Add line item</button>
          </div>

          <div className="card card-pad">
            <div className="meta-row"><span className="k">Subtotal</span><span className="v mono">{m2(subtotal)}</span></div>
            <div className="meta-row"><span className="k">GST 15%</span><span className="v mono">{m2(gst)}</span></div>
            <div className="meta-row" style={{ fontSize: 16 }}><span className="k" style={{ fontWeight: 700, color: 'var(--text)' }}>Total</span><span className="v mono" style={{ fontSize: 17 }}>{m2(subtotal + gst)}</span></div>
          </div>
        </div>
      </div>
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: 'var(--pad)', paddingBottom: 'calc(var(--pad) + var(--safe-bot, 0px))', background: 'color-mix(in srgb, var(--card) 90%, transparent)', backdropFilter: 'blur(14px)', borderTop: '1px solid var(--border)', display: 'flex', gap: 10 }}>
        <button className="btn btn-ghost" style={{ flex: '0 0 auto', width: 110 }} onClick={() => nav.pop()}>Draft</button>
        <button className="btn btn-primary" onClick={() => nav.pop()}><I2 name="send" /> Create & send</button>
      </div>
    </div>
  );
}

/* ───────────────────────── CUSTOMER DETAIL ───────────────────────── */
function CustomerDetailScreen({ nav, params }) {
  const c = D2.customers.find(x => x.id === params.id) || D2.customers[0];
  const inv = D2.invoices.filter(i => i.customer === c.name);
  return (
    <div className="scr">
      <NB2 title="Customer" onBack={nav.pop} backLabel="Customers" actions={<IB2 name="edit" label="Edit" />} />
      <div className="screen">
        <div className="pad scroll-pad stack">
          <div className="card card-pad" style={{ textAlign: 'center' }}>
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}><div className="acircle" style={{ width: 64, height: 64, fontSize: 22, background: D2.avatarColor(c.name) }}>{D2.initials(c.name)}</div></div>
            <h2 style={{ fontSize: 19 }}>{c.name}</h2>
            <p className="muted" style={{ fontSize: 13.5, marginTop: 3 }}>{c.contact} · {c.type}</p>
            <div className="btn-row" style={{ marginTop: 16 }}>
              {[['phone', 'Call'], ['sms', 'Text'], ['mail', 'Email']].map(([ic, l]) => (
                <button className="btn btn-ghost" key={l} style={{ flexDirection: 'column', height: 60, gap: 4, fontSize: 12 }}><I2 name={ic} style={{ fontSize: 19, color: 'var(--accent)' }} />{l}</button>
              ))}
            </div>
          </div>

          <div className="kpi-grid">
            <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>Receivables</div><div className="kval" style={{ fontSize: 19, color: c.receivables > 0 ? 'var(--danger)' : 'var(--ok)' }}>{m2(c.receivables)}</div></div>
            <div className="kpi"><div className="klabel" style={{ marginBottom: 8 }}>Total jobs</div><div className="kval" style={{ fontSize: 19 }}>{c.jobs}</div></div>
          </div>

          <div className="card">
            <div className="card-head"><h2>Invoices</h2><span className="muted mono" style={{ fontSize: 12 }}>{inv.length}</span></div>
            {inv.length ? inv.map(i => (
              <div className="li" key={i.id} onClick={() => nav.push('invoiceDetail', { id: i.id })}>
                <span className="ico blue" style={{ width: 36, height: 36 }}><I2 name="invoice" style={{ fontSize: 17 }} /></span>
                <div className="body"><div className="t mono" style={{ fontSize: 14 }}>{i.id}</div><div className="s">due {i.due}</div></div>
                <div className="end"><span className="amt">{m2(i.amount)}</span><SB2 status={i.status} /></div>
              </div>
            )) : <div className="empty"><div className="eico"><I2 name="invoice" /></div><h3>No invoices yet</h3></div>}
          </div>

          <div className="card card-pad">
            <div className="meta-row"><span className="k">Email</span><span className="v">{c.email}</span></div>
            <div className="meta-row"><span className="k">Phone</span><span className="v mono">{c.phone}</span></div>
            <div className="meta-row"><span className="k">Customer since</span><span className="v">{c.since}</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ───────────────────────── CUSTOMER CREATE ───────────────────────── */
function CustomerCreateScreen({ nav }) {
  return (
    <div className="scr">
      <NB2 title="New customer" onBack={nav.pop} actions={<button className="nav-btn txt" onClick={() => nav.pop()}>Save</button>} />
      <div className="screen"><div className="pad">
        <div className="field"><label>Type</label><div className="seg"><button className="on">Business</button><button>Individual</button></div></div>
        <div className="field"><label>Company / Name</label><input className="input" placeholder="e.g. Coastal Fitouts" /></div>
        <div className="field"><label>Contact person</label><input className="input" placeholder="Full name" /></div>
        <div className="field"><label>Email</label><input className="input" placeholder="name@example.co.nz" inputMode="email" /></div>
        <div className="field"><label>Phone</label><input className="input" placeholder="021 000 000" inputMode="tel" /></div>
        <div className="field"><label>Billing address <span className="opt">(optional)</span></label><textarea className="textarea" placeholder="Street, suburb, city"></textarea></div>
        <button className="btn btn-primary" onClick={() => nav.pop()}><I2 name="check" /> Save customer</button>
      </div></div>
    </div>
  );
}

/* ───────────────────────── CLOCK-IN ───────────────────────── */
function ClockScreen({ nav, params }) {
  const [running, setRunning] = React.useState(true);
  const [secs, setSecs] = React.useState(3 * 3600 + 24 * 60 + 8);
  React.useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setSecs(s => s + 1), 1000);
    return () => clearInterval(t);
  }, [running]);
  const hh = String(Math.floor(secs / 3600)).padStart(2, '0');
  const mm = String(Math.floor((secs % 3600) / 60)).padStart(2, '0');
  const ss = String(secs % 60).padStart(2, '0');
  const job = D2.jobs.find(j => j.id === params.job) || D2.jobs[0];
  return (
    <div className="scr">
      <NB2 title="Time clock" onBack={nav.pop} actions={<IB2 name="calendar" label="Timesheet" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="card card-pad" style={{ textAlign: 'center', paddingTop: 26, paddingBottom: 26, background: running ? 'linear-gradient(165deg, var(--ink), color-mix(in srgb, var(--accent) 36%, var(--ink)))' : 'var(--card)' }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: running ? 'rgba(255,255,255,.7)' : 'var(--muted)' }}>
            {running ? 'Clocked in · since 7:30am' : 'Clocked out'}
          </div>
          <div className="mono" style={{ fontSize: 54, fontWeight: 600, letterSpacing: '-0.03em', margin: '10px 0', color: running ? '#fff' : 'var(--text)' }}>{hh}:{mm}<span style={{ fontSize: 30, opacity: .6 }}>:{ss}</span></div>
          <div className="row" style={{ justifyContent: 'center', gap: 8, color: running ? 'rgba(255,255,255,.85)' : 'var(--muted)', fontSize: 13.5, fontWeight: 600 }}>
            <I2 name="wrench" style={{ fontSize: 16 }} /> {job.id} · {job.title}
          </div>
        </div>

        <div className="btn-row">
          <button className="btn btn-ghost" onClick={() => setRunning(r => r)}><I2 name="pause" /> Break</button>
          <button className="btn" style={running ? { background: 'var(--danger-soft)', color: 'var(--danger)' } : { background: 'var(--accent)', color: '#fff' }} onClick={() => setRunning(r => !r)}>
            <I2 name={running ? 'logout' : 'play'} /> {running ? 'Clock out' : 'Clock in'}
          </button>
        </div>

        <div>
          <div className="section-label">Today · 4 June</div>
          <div className="card">
            {[['JOB-318', 'Kitchen refit — Unit 4', '7:30am – now', '3h 24m', true], ['—', 'Travel · depot to site', '7:05 – 7:30am', '25m', false], ['JOB-315', 'Retaining wall — stage 2', 'Yesterday', '6h 10m', false]].map((r, i) => (
              <div className="li" key={i}>
                <span className={`ico ${r[4] ? 'green' : 'blue'}`} style={{ width: 36, height: 36 }}><I2 name={r[4] ? 'play' : 'clock'} style={{ fontSize: 16 }} /></span>
                <div className="body"><div className="t" style={{ fontSize: 14 }}>{r[1]}</div><div className="s mono">{r[0] !== '—' ? r[0] + ' · ' : ''}{r[2]}</div></div>
                <span className="amt mono" style={{ color: r[4] ? 'var(--ok)' : 'var(--text)' }}>{r[3]}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card card-pad between">
          <div><div className="t" style={{ fontWeight: 600 }}>Total today</div><div className="s muted">Across 3 entries</div></div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>9h 59m</div>
        </div>
      </div></div>
    </div>
  );
}

Object.assign(window, { InvoiceDetailScreen, InvoiceCreateScreen, CustomerDetailScreen, CustomerCreateScreen, ClockScreen });
