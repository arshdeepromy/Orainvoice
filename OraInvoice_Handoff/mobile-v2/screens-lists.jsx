// screens-lists.jsx — auth, dashboard, list & overview screens.
const { Ico, money, StatusBadge, Avatar, Navbar, IconBtn, DATA } = window;

/* ───────────────────────── LOGIN ───────────────────────── */
function LoginScreen({ nav }) {
  const [email, setEmail] = React.useState('jordan@hayes.co.nz');
  const [pw, setPw] = React.useState('••••••••••');
  return (
    <div className="scr">
      <div className="screen" style={{ display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '64px 28px 40px', textAlign: 'center', background: 'linear-gradient(165deg, var(--ink), color-mix(in srgb, var(--accent) 40%, var(--ink)))' }}>
          <div style={{ width: 66, height: 66, borderRadius: 19, background: 'rgba(255,255,255,.12)', display: 'grid', placeItems: 'center', margin: '0 auto 16px', backdropFilter: 'blur(8px)' }}>
            <Ico name="receipt" style={{ fontSize: 32, color: '#fff' }} />
          </div>
          <h1 style={{ color: '#fff', fontSize: 26, fontWeight: 700 }}>OraInvoice</h1>
          <p style={{ color: 'rgba(255,255,255,.7)', fontSize: 14, marginTop: 5 }}>Sign in to your workspace</p>
        </div>
        <div className="pad" style={{ marginTop: -18, background: 'var(--canvas)', borderRadius: '22px 22px 0 0', flex: 1, paddingTop: 26 }}>
          <div className="field">
            <label>Email</label>
            <input className="input" value={email} onChange={e => setEmail(e.target.value)} inputMode="email" name="email" autoComplete="username" />
          </div>
          <div className="field">
            <label>Password</label>
            <input className="input" type="password" value={pw} onChange={e => setPw(e.target.value)} name="password" autoComplete="current-password" />
          </div>
          <div className="between" style={{ marginBottom: 22 }}>
            <label className="row" style={{ fontSize: 14, color: 'var(--muted)' }}>
              <span className="toggle on" style={{ pointerEvents: 'none' }}></span> Remember me
            </label>
            <span style={{ color: 'var(--accent)', fontWeight: 600, fontSize: 14 }}>Forgot?</span>
          </div>
          <button className="btn btn-primary" onClick={() => nav.reset('home')}>Sign In</button>
          <div className="row" style={{ margin: '20px 0', gap: 12 }}>
            <span className="grow divider"></span><span className="muted" style={{ fontSize: 12 }}>or</span><span className="grow divider"></span>
          </div>
          <button className="btn btn-ghost" style={{ marginBottom: 10 }} onClick={() => nav.reset('home')}>
            <Ico name="google" style={{ fontSize: 19 }} /> Continue with Google
          </button>
          <button className="btn btn-ghost" onClick={() => nav.reset('home')}>
            <Ico name="fingerprint" style={{ fontSize: 19 }} /> Sign in with passkey
          </button>
          <p style={{ textAlign: 'center', marginTop: 26, fontSize: 14, color: 'var(--muted)' }}>
            New here? <span style={{ color: 'var(--accent)', fontWeight: 600 }}>Create account</span>
          </p>
        </div>
      </div>
    </div>
  );
}

/* ───────────────────────── DASHBOARD ───────────────────────── */
function KPI({ label, val, cents, icon, tint, delta, dir }) {
  return (
    <div className="kpi">
      <div className="ktop">
        <span className="klabel">{label}</span>
        <span className={`ico ${tint}`}><Ico name={icon} /></span>
      </div>
      <div className="kval">{val}{cents != null && <span className="c">.{cents}</span>}</div>
      {delta && <div className={`kdelta ${dir}`}><Ico name="trend" />{delta}</div>}
    </div>
  );
}

function HomeScreen({ nav }) {
  const overdue = DATA.invoices.filter(i => i.status === 'overdue');
  return (
    <div className="scr">
      <Navbar title="Kia ora, Jordan" sub="Wednesday, 4 June" big actions={
        <React.Fragment>
          <SearchBtn nav={nav} />
          <IconBtn name="bell" badge label="Notifications" onClick={() => nav.push('notifications')} />
        </React.Fragment>
      } />
      <div className="screen">
        <div className="pad scroll-pad stack">
          <div className="row" style={{ gap: 8 }}>
            <span className="badge sent" style={{ padding: '5px 11px' }}><span className="bd"></span>Auckland Central</span>
            <div className="seg" style={{ width: 'auto', marginLeft: 'auto' }}>
              <button className="on">30d</button><button>QTD</button><button>YTD</button>
            </div>
          </div>

          <div className="kpi-grid">
            <KPI label="Outstanding" val="$17,138" cents="00" icon="dollar" tint="blue" delta="8.2%" dir="up" />
            <KPI label="Overdue" val="$2,792" cents="00" icon="alert" tint="red" delta="2 invoices" dir="down" />
            <KPI label="Paid (30d)" val="$24,610" icon="checkc" tint="green" delta="14%" dir="up" />
            <KPI label="Quotes out" val="$22,850" icon="quote" tint="purple" delta="3 open" dir="up" />
          </div>

          <div>
            <div className="section-label">Quick actions</div>
            <div className="chips">
              <button className="chip on" onClick={() => nav.push('invoiceCreate')}><Ico name="plus" /> New invoice</button>
              <button className="chip" onClick={() => nav.push('quotes')}><Ico name="quote" /> New quote</button>
              <button className="chip" onClick={() => nav.push('clock')}><Ico name="clock" /> Clock in</button>
              <button className="chip" onClick={() => nav.switchTab('customers')}><Ico name="customers" /> Customer</button>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h2>Needs attention</h2><span className="link" onClick={() => nav.switchTab('invoices')}>View all</span></div>
            {overdue.map(inv => (
              <div className="li" key={inv.id} onClick={() => nav.push('invoiceDetail', { id: inv.id })}>
                <Avatar name={inv.customer} square />
                <div className="body">
                  <div className="t">{inv.customer}</div>
                  <div className="s">{inv.id} · {inv.days} days overdue</div>
                </div>
                <div className="end"><span className="amt" style={{ color: 'var(--danger)' }}>{money(inv.amount)}</span><StatusBadge status="overdue" /></div>
              </div>
            ))}
          </div>

          <div className="card">
            <div className="card-head"><h2>Recent activity</h2></div>
            <div className="card-pad">
              <div className="timeline">
                {DATA.activity.map((a, i) => (
                  <div className={`tl-item${a.on ? ' on' : ''}`} key={i}>
                    <div className="between">
                      <div className="t">{a.t}</div>
                      {a.amt && <div className="amt mono" style={{ fontSize: 13, fontWeight: 600, color: a.cls === 'green' ? 'var(--ok)' : 'var(--text)' }}>{a.amt}</div>}
                    </div>
                    <div className="s">{a.s}</div>
                    <div className="tm">{a.tm}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ───────────────────────── INVOICES LIST ───────────────────────── */
function InvoicesScreen({ nav }) {
  const [filter, setFilter] = React.useState('all');
  const counts = { overdue: DATA.invoices.filter(i => i.status === 'overdue').length };
  const list = filter === 'all' ? DATA.invoices : DATA.invoices.filter(i => i.status === filter);
  const outstanding = DATA.invoices.filter(i => i.status !== 'paid' && i.status !== 'draft').reduce((s, i) => s + i.amount, 0);
  return (
    <div className="scr">
      <Navbar title="Invoices" big sub={`${money(outstanding)} outstanding`} actions={
        <React.Fragment><SearchBtn nav={nav} /><FilterBtn /></React.Fragment>
      } />
      <div className="screen">
        <div className="pad-x" style={{ paddingTop: 4, paddingBottom: 10 }}>
          <div className="searchbar"><Ico name="search" /><input placeholder="Search invoices…" /></div>
        </div>
        <div className="pad-x"><div className="chips">
          {[['all', 'All', DATA.invoices.length], ['overdue', 'Overdue', counts.overdue], ['sent', 'Sent'], ['paid', 'Paid'], ['draft', 'Draft']].map(([k, l, n]) => (
            <button key={k} className={`chip${filter === k ? ' on' : ''}`} onClick={() => setFilter(k)}>{l}{n != null && <span className="n">{n}</span>}</button>
          ))}
        </div></div>
        <div className="pad scroll-pad" style={{ paddingTop: 12 }}>
          <div className="list">
            {list.map(inv => (
              <div className="li" key={inv.id} onClick={() => nav.push('invoiceDetail', { id: inv.id })}>
                <Avatar name={inv.customer} square />
                <div className="body">
                  <div className="t">{inv.customer}</div>
                  <div className="s mono">{inv.id} · due {inv.due}</div>
                </div>
                <div className="end"><span className="amt">{money(inv.amount)}</span><StatusBadge status={inv.status} /></div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <button className="fab" onClick={() => nav.push('invoiceCreate')}><Ico name="plus" /> New</button>
    </div>
  );
}

/* ───────────────────────── CUSTOMERS LIST ───────────────────────── */
function CustomersScreen({ nav }) {
  return (
    <div className="scr">
      <Navbar title="Customers" big sub={`${DATA.customers.length} active`} actions={<SearchBtn nav={nav} />} />
      <div className="screen">
        <div className="pad-x" style={{ paddingTop: 4, paddingBottom: 12 }}>
          <div className="searchbar"><Ico name="search" /><input placeholder="Search customers…" /></div>
        </div>
        <div className="pad-x scroll-pad">
          <div className="list">
            {DATA.customers.map(c => (
              <div className="li" key={c.id} onClick={() => nav.push('customerDetail', { id: c.id })}>
                <Avatar name={c.name} />
                <div className="body">
                  <div className="t">{c.name}</div>
                  <div className="s">{c.contact} · {c.phone}</div>
                </div>
                <div className="end">
                  {c.receivables > 0
                    ? <span className="amt" style={{ color: 'var(--danger)' }}>{money(c.receivables)}</span>
                    : <span className="muted" style={{ fontSize: 12.5, fontWeight: 600 }}>Settled</span>}
                  <Ico name="chev" className="chev" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <button className="fab" onClick={() => nav.push('customerCreate')}><Ico name="plus" /> Add</button>
    </div>
  );
}

/* ───────────────────────── JOBS LIST ───────────────────────── */
function JobsScreen({ nav }) {
  const [filter, setFilter] = React.useState('all');
  const list = filter === 'all' ? DATA.jobs : DATA.jobs.filter(j => j.status === filter);
  return (
    <div className="scr">
      <Navbar title="Jobs" big sub="2 in progress · 2 scheduled" actions={<SearchBtn nav={nav} />} />
      <div className="screen">
        <div className="pad-x"><div className="chips">
          {[['all', 'All'], ['inprogress', 'In progress'], ['pending', 'Scheduled'], ['completed', 'Done']].map(([k, l]) => (
            <button key={k} className={`chip${filter === k ? ' on' : ''}`} onClick={() => setFilter(k)}>{l}</button>
          ))}
        </div></div>
        <div className="pad scroll-pad stack" style={{ paddingTop: 12 }}>
          {list.map(j => (
            <div className="card card-pad" key={j.id} onClick={() => nav.push('jobDetail', { id: j.id })}>
              <div className="between" style={{ marginBottom: 9 }}>
                <span className="mono muted" style={{ fontSize: 12, fontWeight: 600 }}>{j.id}{j.vehicle && ` · ${j.vehicle}`}</span>
                <StatusBadge status={j.status} />
              </div>
              <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 3 }}>{j.title}</div>
              <div className="s muted" style={{ fontSize: 13 }}>{j.customer}</div>
              <div className="progress" style={{ margin: '13px 0 9px' }}><i style={{ width: `${j.progress}%`, background: j.status === 'completed' ? 'var(--ok)' : 'var(--accent)' }}></i></div>
              <div className="between">
                <span className="row muted" style={{ fontSize: 12.5, gap: 6 }}><Ico name="user" style={{ fontSize: 15 }} /> {j.assignee}</span>
                <span className="row muted" style={{ fontSize: 12.5, gap: 6 }}><Ico name="clock" style={{ fontSize: 15 }} /> {j.due} · {j.tasks}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
      <CreateFab label="New job" form="job" />
    </div>
  );
}

/* ───────────────────────── QUOTES LIST ───────────────────────── */
function QuotesScreen({ nav }) {
  return (
    <div className="scr">
      <Navbar title="Quotes" onBack={nav.pop} backLabel="More" actions={<IconBtn name="plus" label="New" onClick={() => nav.push('quoteCreate')} />} />
      <div className="screen">
        <div className="pad scroll-pad stack" style={{ paddingTop: 14 }}>
          <div className="list">
            {DATA.quotes.map(q => (
              <div className="li" key={q.id} onClick={() => nav.push('quoteDetail', { id: q.id })}>
                <Avatar name={q.customer} square />
                <div className="body">
                  <div className="t">{q.customer}</div>
                  <div className="s mono">{q.id} · expires {q.expires}</div>
                </div>
                <div className="end"><span className="amt">{money(q.amount)}</span><StatusBadge status={q.status} /></div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <button className="fab" onClick={() => nav.push('quoteCreate')}><Ico name="plus" /> New quote</button>
    </div>
  );
}

/* ───────────────────────── MORE ───────────────────────── */
function MoreScreen({ nav, dark, onToggleDark }) {
  return (
    <div className="scr">
      <Navbar title="More" big />
      <div className="screen">
        <div className="pad scroll-pad stack">
          <div className="card card-pad row" style={{ gap: 13 }}>
            <Avatar name="Jordan Hayes" />
            <div className="body grow">
              <div className="t" style={{ fontSize: 15 }}>Jordan Hayes</div>
              <div className="s">jordan@hayes.co.nz</div>
            </div>
            <span className="badge neutral">Owner</span>
          </div>

          <div className="card card-pad row" style={{ gap: 12 }}>
            <span className="ico blue" style={{ width: 38, height: 38, borderRadius: 11 }}><Ico name="building" style={{ fontSize: 18 }} /></span>
            <div className="body grow">
              <div className="t" style={{ fontSize: 14 }}>Hayes Contracting Ltd</div>
              <div className="s">Auckland Central · switch org</div>
            </div>
            <Ico name="chev" className="chev" />
          </div>

          <div className="card card-pad row" style={{ gap: 12 }} onClick={() => nav.push('directory')}>
            <span className="ico blue" style={{ width: 38, height: 38, borderRadius: 11 }}><Ico name="search" style={{ fontSize: 18 }} /></span>
            <div className="body grow">
              <div className="t" style={{ fontSize: 14 }}>Browse all screens</div>
              <div className="s">Jump to any of 55+ screens</div>
            </div>
            <Ico name="chev" className="chev" />
          </div>

          <div>
            <div className="section-label">Modules</div>
            <div className="card card-pad">
              <div className="mod-grid">
                {DATA.modules.slice(0, 11).map((m, i) => (
                  <div className="mod" key={i} onClick={() => nav.push(m.go)}>
                    <span className="micon"><Ico name={m.icon} /></span>
                    <span className="ml">{m.label}</span>
                  </div>
                ))}
                <div className="mod" onClick={() => nav.push('directory')}>
                  <span className="micon"><Ico name="more" /></span>
                  <span className="ml">All</span>
                </div>
              </div>
            </div>
          </div>

          <div>
            <div className="section-label">Account</div>
            <div className="list">
              {[['settings', 'Settings', 'settings'], ['bell', 'Notifications', 'notifications'], ['shield', 'Security & passkeys', 'mfa'], ['card', 'Billing & plan', 'settings']].map(([ic, l, go]) => (
                <div className="li" key={l} onClick={() => nav.push(go)}>
                  <span className="ico blue" style={{ width: 34, height: 34 }}><Ico name={ic} style={{ fontSize: 17 }} /></span>
                  <div className="body"><div className="t" style={{ fontSize: 14, fontWeight: 500 }}>{l}</div></div>
                  <Ico name="chev" className="chev" />
                </div>
              ))}
              <div className="li">
                <span className="ico amber" style={{ width: 34, height: 34 }}><Ico name={dark ? 'moon' : 'sun'} style={{ fontSize: 17 }} /></span>
                <div className="body"><div className="t" style={{ fontSize: 14, fontWeight: 500 }}>Dark mode</div></div>
                <span className={`toggle${dark ? ' on' : ''}`} onClick={onToggleDark}></span>
              </div>
            </div>
          </div>

          <button className="btn btn-danger" onClick={() => nav.reset('login')}><Ico name="logout" /> Sign out</button>
          <p style={{ textAlign: 'center', fontSize: 12 }} className="muted mono">OraInvoice · v2.0.0</p>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { LoginScreen, HomeScreen, InvoicesScreen, CustomersScreen, JobsScreen, QuotesScreen, MoreScreen });
