// screens-settings.jsx — parametrized Settings sub-pages + component-states demo.
const { Ico: IS2, money: ms2, Navbar: NBs, IconBtn: IBs, Avatar: AVs, DATA: DS2 } = window;

function Row({ k, v, mono, last }) {
  return <div className="meta-row" style={{ borderBottom: last ? 'none' : '1px solid var(--border)' }}><span className="k">{k}</span><span className={`v${mono ? ' mono' : ''}`}>{v}</span></div>;
}
function ToggleRow({ label, sub, on: onInit = true }) {
  const [on, setOn] = React.useState(onInit);
  return (
    <div className="li">
      <div className="body"><div className="t" style={{ fontSize: 14, fontWeight: 500 }}>{label}</div>{sub && <div className="s">{sub}</div>}</div>
      <span className={`toggle${on ? ' on' : ''}`} onClick={() => setOn(o => !o)}></span>
    </div>
  );
}

function SettingsField({ label, value, opt }) {
  return <div className="field"><label>{label}{opt && <span className="opt"> (optional)</span>}</label><input className="input" defaultValue={value} /></div>;
}

function SettingsDetailScreen({ nav, params, dark, onToggleDark }) {
  const id = params.id;
  const save = () => { nav.pop(); window.toast('Changes saved'); };
  const titles = {
    business: 'Business details', branches: 'Branches & locations', modules: 'Modules', branding: 'Branding & templates',
    team: 'Team & roles', timesheets: 'Timesheets & payroll', billing: 'Billing & plan', integrations: 'Integrations',
    security: 'Security', data: 'Data & export',
  };
  let body = null;

  if (id === 'business') body = (
    <React.Fragment>
      <SettingsField label="Trading name" value="Hayes Contracting Ltd" />
      <SettingsField label="NZBN" value="9429041234567" />
      <SettingsField label="GST number" value="123-456-789" />
      <SettingsField label="Email" value="accounts@hayes.co.nz" />
      <SettingsField label="Phone" value="09 407 1200" />
      <SettingsField label="Address" value="14 Kerikeri Rd, Kerikeri 0230" />
      <button className="btn btn-primary" onClick={save}><IS2 name="check" /> Save changes</button>
    </React.Fragment>
  );
  else if (id === 'branches') body = (
    <React.Fragment>
      <div className="list">
        {[['Kerikeri', 'BR-01', true], ['Whangārei', 'BR-02', false], ['Mobile unit', 'BR-03', false]].map(([n, code, main], i) => (
          <div className="li" key={i}>
            <span className="ico blue" style={{ width: 36, height: 36 }}><IS2 name="pin" style={{ fontSize: 16 }} /></span>
            <div className="body"><div className="t">{n}</div><div className="s mono">{code}</div></div>
            {main && <span className="badge active"><span className="bd"></span>Primary</span>}
            <IS2 name="chev" className="chev" />
          </div>
        ))}
      </div>
      <button className="btn btn-ghost"><IS2 name="plus" /> Add branch</button>
    </React.Fragment>
  );
  else if (id === 'modules') body = (
    <div className="list">
      {[['Invoicing', 'Core', true], ['Quotes', 'Core', true], ['Jobs & bookings', 'Pro', true], ['Inventory', 'Pro', true], ['Payroll', 'Pro', true], ['Construction', 'Add-on', false], ['Loyalty', 'Add-on', false], ['POS', 'Add-on', true]].map(([n, tier, on], i) => (
        <div className="li" key={i}>
          <div className="body"><div className="t" style={{ fontSize: 14, fontWeight: 500 }}>{n}</div><div className="s">{tier}</div></div>
          <ToggleInline on={on} />
        </div>
      ))}
    </div>
  );
  else if (id === 'branding') body = (
    <React.Fragment>
      <div className="field"><label>Logo</label><div className="upload-box"><IS2 name="image" style={{ fontSize: 26 }} /><div style={{ fontSize: 13, marginTop: 8 }}>Upload your logo</div></div></div>
      <div className="field"><label>Accent colour</label><div className="row" style={{ gap: 10 }}>{['#2F62F0', '#1F8A5B', '#6D5AE6', '#C8412F', '#B5740F'].map((c, i) => <span key={c} style={{ width: 38, height: 38, borderRadius: 11, background: c, border: i === 0 ? '3px solid var(--text)' : '3px solid transparent' }}></span>)}</div></div>
      <SettingsField label="Invoice footer" value="Thank you for your business." />
      <button className="btn btn-primary" onClick={save}><IS2 name="check" /> Save branding</button>
    </React.Fragment>
  );
  else if (id === 'team') body = (
    <React.Fragment>
      <div className="list">{DS2.staff.map(s => (
        <div className="li" key={s.id} onClick={() => nav.push('staffDetail', { id: s.id })}>
          <AVs name={s.name} />
          <div className="body"><div className="t">{s.name}</div><div className="s">{s.role}</div></div>
          <span className="badge neutral">{s.empId === 'EMP-001' ? 'Owner' : 'Member'}</span>
        </div>
      ))}</div>
      <button className="btn btn-ghost" onClick={() => nav.push('staff')}><IS2 name="user" /> Manage staff</button>
    </React.Fragment>
  );
  else if (id === 'timesheets') body = (
    <React.Fragment>
      <div className="card card-pad"><Row k="Pay cycle" v="Weekly" /><Row k="Pay day" v="Wednesday" /><Row k="Default rate" v="$36.00/hr" mono /><Row k="Overtime after" v="40 hrs/week" last /></div>
      <div className="section-label">Options</div>
      <div className="list"><ToggleRow label="Auto-approve timesheets" sub="Under 40 hrs/week" on={false} /><ToggleRow label="Track breaks" /><ToggleRow label="Require job on clock-in" /></div>
      <button className="btn btn-ghost" onClick={() => nav.push('payroll')}><IS2 name="dollar" /> Open payroll</button>
    </React.Fragment>
  );
  else if (id === 'billing') body = (
    <React.Fragment>
      <div className="card card-pad" style={{ background: 'linear-gradient(160deg, var(--ink), color-mix(in srgb, var(--accent) 34%, var(--ink)))', color: '#fff' }}>
        <div className="between"><span style={{ opacity: .8, fontSize: 13 }}>Current plan</span><span className="badge active" style={{ background: 'rgba(255,255,255,.16)', color: '#fff' }}>PRO</span></div>
        <div style={{ fontSize: 26, fontWeight: 700, margin: '12px 0 2px' }}>$89<span style={{ fontSize: 14, fontWeight: 500, opacity: .8 }}>/mo</span></div>
        <div style={{ opacity: .7, fontSize: 12.5 }}>12 seats · renews 1 Jul 2025</div>
      </div>
      <div className="card card-pad"><Row k="Payment method" v="Visa ••4821" /><Row k="Next charge" v="1 Jul 2025" /><Row k="Billing email" v="accounts@hayes.co.nz" last /></div>
      <button className="btn btn-ghost"><IS2 name="card" /> Manage subscription</button>
    </React.Fragment>
  );
  else if (id === 'integrations') body = (
    <div className="list">
      {[['Xero', 'Accounting sync', true], ['Stripe', 'Card payments', true], ['Google Calendar', 'Bookings sync', true], ['Twilio', 'SMS', true], ['CarJam', 'Vehicle lookups', false], ['IRD', 'GST filing', true]].map(([n, s, on], i) => (
        <div className="li" key={i}>
          <span className="ico blue" style={{ width: 36, height: 36 }}><IS2 name="bank" style={{ fontSize: 16 }} /></span>
          <div className="body"><div className="t">{n}</div><div className="s">{s}</div></div>
          <span className={`badge ${on ? 'active' : 'neutral'}`}><span className="bd"></span>{on ? 'Connected' : 'Off'}</span>
        </div>
      ))}
    </div>
  );
  else if (id === 'security') body = (
    <React.Fragment>
      <div className="list"><ToggleRow label="Two-factor authentication" sub="Authenticator app" /><ToggleRow label="Require 2FA for all staff" on={false} /><ToggleRow label="Biometric unlock" /></div>
      <div className="section-label">Sessions</div>
      <div className="card card-pad"><Row k="iPhone 15 · Auckland" v="Now" /><Row k="MacBook · Office" v="2h ago" /><Row k="iPad · Workshop" v="Yesterday" last /></div>
      <button className="btn btn-ghost"><IS2 name="logout" /> Sign out all other devices</button>
      <button className="btn btn-ghost" onClick={() => nav.push('mfa')}><IS2 name="shield" /> Set up two-factor</button>
    </React.Fragment>
  );
  else if (id === 'data') body = (
    <React.Fragment>
      <div className="list">
        {[['download', 'Export invoices (CSV)'], ['download', 'Export customers (CSV)'], ['download', 'Export full backup'], ['file', 'Download GST audit file']].map(([ic, l], i) => (
          <div className="li" key={i} onClick={() => window.toast('Export started')}><span className="ico blue" style={{ width: 34, height: 34 }}><IS2 name={ic} style={{ fontSize: 16 }} /></span><div className="body"><div className="t" style={{ fontSize: 14, fontWeight: 500 }}>{l}</div></div><IS2 name="chev" className="chev" /></div>
        ))}
      </div>
      <div className="section-label" style={{ color: 'var(--danger)' }}>Danger zone</div>
      <button className="btn btn-ghost" style={{ color: 'var(--danger)', borderColor: 'var(--danger-soft)' }}><IS2 name="alert" /> Delete organisation</button>
    </React.Fragment>
  );
  else body = <div className="card card-pad muted" style={{ textAlign: 'center', fontSize: 13.5 }}>Settings for “{id}”.</div>;

  return (
    <div className="scr">
      <NBs title={titles[id] || 'Settings'} onBack={nav.pop} backLabel="Settings" />
      <div className="screen"><div className="pad scroll-pad stack" style={{ paddingTop: 14 }}>{body}</div></div>
    </div>
  );
}
function ToggleInline({ on: onInit }) { const [on, setOn] = React.useState(onInit); return <span className={`toggle${on ? ' on' : ''}`} onClick={() => setOn(o => !o)}></span>; }

/* ───────── component states demo ───────── */
function StatesScreen({ nav }) {
  const [view, setView] = React.useState('loading');
  return (
    <div className="scr">
      <NBs title="Component states" onBack={nav.pop} />
      <div className="screen"><div className="pad-x" style={{ paddingTop: 4, paddingBottom: 8 }}>
        <div className="seg">{[['loading', 'Loading'], ['empty', 'Empty'], ['error', 'Error'], ['data', 'Data']].map(([k, l]) => <button key={k} className={view === k ? 'on' : ''} onClick={() => setView(k)}>{l}</button>)}</div>
      </div>
        <div className="pad-x scroll-pad">
          {view === 'loading' && <window.Skeleton rows={6} />}
          {view === 'empty' && <window.EmptyState icon="invoice" title="No invoices yet" sub="Create your first invoice and it’ll show up here." action="New invoice" onAction={() => nav.push('invoiceCreate')} />}
          {view === 'error' && <window.ErrorState onRetry={() => window.toast('Retrying…')} />}
          {view === 'data' && <div className="list">{DS2.invoices.slice(0, 6).map(i => (
            <div className="li" key={i.id} onClick={() => nav.push('invoiceDetail', { id: i.id })}><span className="ico blue" style={{ width: 36, height: 36 }}><IS2 name="invoice" style={{ fontSize: 16 }} /></span><div className="body"><div className="t mono" style={{ fontSize: 14 }}>{i.id}</div><div className="s">{i.customer}</div></div><span className="amt">{ms2(i.amount)}</span></div>
          ))}</div>}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { SettingsDetailScreen, StatesScreen });
