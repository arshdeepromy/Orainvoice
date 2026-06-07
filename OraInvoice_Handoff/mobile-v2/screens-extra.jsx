// screens-extra.jsx — customer-facing, auth/onboarding, and the screen directory.
const { Ico: I5, money: m5, StatusBadge: SB5, Avatar: AV5, Navbar: NB5, IconBtn: IB5, DATA: D5 } = window;

function Brandmark({ size = 46 }) {
  return (
    <div style={{ width: size, height: size, borderRadius: size * 0.28, background: 'linear-gradient(150deg, var(--accent), color-mix(in srgb, var(--accent) 60%, #6D5AE6))', display: 'grid', placeItems: 'center', color: '#fff', boxShadow: 'var(--shadow-fab)' }}>
      <span style={{ fontWeight: 700, fontSize: size * 0.46, letterSpacing: '-0.04em' }}>O</span>
    </div>
  );
}

/* ───────── CUSTOMER PORTAL ───────── */
function PortalScreen({ nav }) {
  return (
    <div className="scr">
      <NB5 title="Customer portal" onBack={nav.pop} actions={<IB5 name="dots" label="More" />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="card card-pad row" style={{ gap: 13 }}>
          <Brandmark size={42} />
          <div className="body grow"><div className="t" style={{ fontSize: 15 }}>Coastal Fitouts</div><div className="s">Welcome back, Marcus</div></div>
        </div>
        <div className="card card-pad" style={{ textAlign: 'center', background: 'linear-gradient(160deg, var(--ink), color-mix(in srgb, var(--accent) 34%, var(--ink)))', color: '#fff' }}>
          <div style={{ opacity: .8, fontSize: 12.5 }}>Outstanding balance</div>
          <div className="mono" style={{ fontSize: 34, fontWeight: 600, margin: '8px 0' }}>{m5(9650)}</div>
          <button className="btn" style={{ background: '#fff', color: 'var(--accent)', marginTop: 6 }} onClick={() => nav.push('paymentPage')}><I5 name="card" /> Pay now</button>
        </div>
        <div className="section-label">Your documents</div>
        <div className="list">
          {[['invoice', 'INV-2040', 'Due 11 Jun', m5(6450), 'sent'], ['quote', 'QTE-188', 'Accepted', m5(8650), 'accepted'], ['invoice', 'INV-1998', 'Paid', m5(3200), 'paid']].map((r, i) => (
            <div className="li" key={i}><span className="ico blue" style={{ width: 36, height: 36 }}><I5 name={r[0]} style={{ fontSize: 16 }} /></span><div className="body"><div className="t mono" style={{ fontSize: 14 }}>{r[1]}</div><div className="s">{r[2]}</div></div><div className="end"><span className="amt">{r[3]}</span><SB5 status={r[4]} /></div></div>
          ))}
        </div>
        <div className="card card-pad row" style={{ gap: 12 }} onClick={() => nav.push('publicBooking')}><span className="ico green" style={{ width: 38, height: 38, borderRadius: 11 }}><I5 name="calendar" style={{ fontSize: 17 }} /></span><div className="body grow"><div className="t" style={{ fontSize: 14 }}>Book a job</div><div className="s">Request a new booking</div></div><I5 name="chev" className="chev" /></div>
      </div></div>
    </div>
  );
}

/* ───────── PUBLIC BOOKING ───────── */
function PublicBookingScreen({ nav }) {
  const [svc, setSvc] = React.useState('measure');
  const [slot, setSlot] = React.useState('09:30');
  const slots = ['08:00', '09:30', '11:00', '13:30', '15:00'];
  return (
    <div className="scr">
      <NB5 title="Book a job" onBack={nav.pop} />
      <div className="screen"><div className="pad" style={{ paddingBottom: 110 }}>
        <div className="card card-pad row" style={{ gap: 12, marginBottom: 16 }}><Brandmark size={40} /><div className="body grow"><div className="t">Hayes Contracting</div><div className="s muted">Auckland Central</div></div></div>
        <div className="field"><label>Service</label><div className="seg">{[['measure', 'Measure'], ['repair', 'Repair'], ['install', 'Install']].map(([k, l]) => <button key={k} className={svc === k ? 'on' : ''} onClick={() => setSvc(k)}>{l}</button>)}</div></div>
        <div className="field"><label>Date</label><input className="input" value="Wednesday, 4 June" readOnly /></div>
        <div className="field"><label>Available times</label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
            {slots.map(s => <button key={s} className={`chip${slot === s ? ' on' : ''}`} style={{ justifyContent: 'center', height: 44 }} onClick={() => setSlot(s)}>{s}</button>)}
          </div>
        </div>
        <div className="field"><label>Notes <span className="opt">(optional)</span></label><textarea className="textarea" placeholder="Tell us about the job…"></textarea></div>
      </div></div>
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: 'var(--pad)', paddingBottom: 'calc(var(--pad) + var(--safe-bot,0px))', background: 'color-mix(in srgb, var(--card) 90%, transparent)', backdropFilter: 'blur(14px)', borderTop: '1px solid var(--border)' }}>
        <button className="btn btn-primary" onClick={() => nav.pop()}><I5 name="check" /> Confirm booking · {slot}</button>
      </div>
    </div>
  );
}

/* ───────── PAYMENT PAGE ───────── */
function PaymentPageScreen({ nav }) {
  const [method, setMethod] = React.useState('card');
  return (
    <div className="scr">
      <NB5 title="Pay invoice" onBack={nav.pop} />
      <div className="screen"><div className="pad" style={{ paddingBottom: 110 }}>
        <div className="card card-pad" style={{ textAlign: 'center', marginBottom: 16 }}><div className="muted" style={{ fontSize: 12.5 }}>INV-2040 · Coastal Fitouts</div><div className="mono" style={{ fontSize: 34, fontWeight: 600, margin: '6px 0' }}>{m5(6450)}</div><span className="badge sent"><span className="bd"></span>Due 11 Jun</span></div>
        <div className="field"><label>Payment method</label><div className="seg">{[['card', 'Card'], ['bank', 'Bank'], ['apple', 'Apple Pay']].map(([k, l]) => <button key={k} className={method === k ? 'on' : ''} onClick={() => setMethod(k)}>{l}</button>)}</div></div>
        {method === 'card' && <React.Fragment>
          <div className="field"><label>Card number</label><div className="input-group"><span className="pre"><I5 name="card" style={{ fontSize: 16 }} /></span><input placeholder="4242 4242 4242 4242" inputMode="numeric" /></div></div>
          <div className="row" style={{ gap: 12 }}><div className="field grow"><label>Expiry</label><input className="input" placeholder="MM / YY" inputMode="numeric" /></div><div className="field grow"><label>CVC</label><input className="input" placeholder="123" inputMode="numeric" /></div></div>
        </React.Fragment>}
        {method === 'bank' && <div className="card card-pad"><Meta5 k="Account name" v="Hayes Contracting Ltd" /><Meta5 k="Account" v="12-3456-7890123-00" /><Meta5 k="Reference" v="INV-2040" /></div>}
        {method === 'apple' && <div className="card card-pad" style={{ textAlign: 'center', color: 'var(--muted)', fontSize: 13.5 }}>Confirm with Face ID to pay.</div>}
      </div></div>
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: 'var(--pad)', paddingBottom: 'calc(var(--pad) + var(--safe-bot,0px))', background: 'color-mix(in srgb, var(--card) 90%, transparent)', backdropFilter: 'blur(14px)', borderTop: '1px solid var(--border)' }}>
        <button className="btn btn-primary" onClick={() => nav.pop()}><I5 name="lock" /> Pay {m5(6450)}</button>
      </div>
    </div>
  );
}
function Meta5({ k, v }) { return <div className="meta-row"><span className="k">{k}</span><span className="v mono">{v}</span></div>; }

/* ───────── SIGN UP ───────── */
function SignupScreen({ nav }) {
  return (
    <div className="scr">
      <div className="screen"><div className="pad" style={{ paddingTop: 36 }}>
        <div style={{ marginBottom: 24 }}><Brandmark /><h1 style={{ fontSize: 26, marginTop: 18, letterSpacing: '-0.03em' }}>Create your account</h1><p className="muted" style={{ fontSize: 14, marginTop: 4 }}>Start invoicing in minutes.</p></div>
        <div className="field"><label>Business name</label><input className="input" placeholder="e.g. Hayes Contracting" /></div>
        <div className="field"><label>Work email</label><input className="input" placeholder="you@business.co.nz" inputMode="email" /></div>
        <div className="field"><label>Password</label><div className="input-group"><input type="password" placeholder="At least 8 characters" /><span className="pre" style={{ borderRight: 'none', borderLeft: '1px solid var(--border)' }}><I5 name="lock" style={{ fontSize: 16 }} /></span></div></div>
        <button className="btn btn-primary" onClick={() => nav.push('setupWizard')}>Create account</button>
        <div className="row" style={{ gap: 12, margin: '18px 0' }}><div className="divider grow"></div><span className="muted" style={{ fontSize: 12 }}>or</span><div className="divider grow"></div></div>
        <button className="btn btn-ghost"><I5 name="google" /> Continue with Google</button>
        <p className="muted" style={{ textAlign: 'center', fontSize: 13, marginTop: 22 }}>Already have an account? <span style={{ color: 'var(--accent)', fontWeight: 600 }} onClick={() => nav.pop()}>Sign in</span></p>
      </div></div>
    </div>
  );
}

/* ───────── MFA ───────── */
function MfaScreen({ nav }) {
  const [code, setCode] = React.useState(['', '', '', '', '', '']);
  return (
    <div className="scr">
      <NB5 title="" onBack={nav.pop} />
      <div className="screen"><div className="pad" style={{ paddingTop: 20 }}>
        <span className="ico blue" style={{ width: 56, height: 56, borderRadius: 16, marginBottom: 18 }}><I5 name="shield" style={{ fontSize: 26 }} /></span>
        <h1 style={{ fontSize: 24, letterSpacing: '-0.03em' }}>Two-factor verification</h1>
        <p className="muted" style={{ fontSize: 14, marginTop: 6, lineHeight: 1.5 }}>Enter the 6-digit code from your authenticator app.</p>
        <div style={{ display: 'flex', gap: 8, margin: '26px 0' }}>
          {code.map((c, i) => (
            <input key={i} value={c} inputMode="numeric" maxLength={1} onChange={e => { const v = e.target.value.slice(-1); setCode(code.map((x, j) => j === i ? v : x)); }}
              style={{ width: '100%', height: 56, textAlign: 'center', fontSize: 22, fontWeight: 600, fontFamily: 'var(--mono)', background: 'var(--card)', border: `1px solid ${c ? 'var(--accent)' : 'var(--border-strong)'}`, borderRadius: 12, color: 'var(--text)', outline: 'none' }} />
          ))}
        </div>
        <button className="btn btn-primary" onClick={() => nav.reset('home')}><I5 name="check" /> Verify</button>
        <p className="muted" style={{ textAlign: 'center', fontSize: 13, marginTop: 20 }}>Didn't get a code? <span style={{ color: 'var(--accent)', fontWeight: 600 }}>Resend</span></p>
      </div></div>
    </div>
  );
}

/* ───────── PASSWORD RESET ───────── */
function ResetScreen({ nav }) {
  return (
    <div className="scr">
      <NB5 title="" onBack={nav.pop} />
      <div className="screen"><div className="pad" style={{ paddingTop: 20 }}>
        <span className="ico amber" style={{ width: 56, height: 56, borderRadius: 16, marginBottom: 18 }}><I5 name="key" style={{ fontSize: 26 }} /></span>
        <h1 style={{ fontSize: 24, letterSpacing: '-0.03em' }}>Reset password</h1>
        <p className="muted" style={{ fontSize: 14, marginTop: 6, lineHeight: 1.5 }}>Enter your email and we'll send a reset link.</p>
        <div className="field" style={{ marginTop: 24 }}><label>Email</label><input className="input" placeholder="you@business.co.nz" inputMode="email" /></div>
        <button className="btn btn-primary" onClick={() => nav.pop()}><I5 name="send" /> Send reset link</button>
      </div></div>
    </div>
  );
}

/* ───────── SETUP WIZARD ───────── */
function SetupWizardScreen({ nav }) {
  const [step, setStep] = React.useState(0);
  const steps = ['Business', 'Branding', 'Tax', 'Done'];
  const next = () => step < 3 ? setStep(step + 1) : nav.reset('home');
  return (
    <div className="scr">
      <NB5 title="Set up your account" onBack={() => step ? setStep(step - 1) : nav.pop()} />
      <div className="screen"><div className="pad" style={{ paddingBottom: 110 }}>
        <div className="row" style={{ gap: 6, marginBottom: 22 }}>{steps.map((s, i) => <div key={i} style={{ flex: 1, height: 4, borderRadius: 4, background: i <= step ? 'var(--accent)' : 'var(--border)' }}></div>)}</div>
        <div className="section-label" style={{ marginBottom: 4 }}>Step {step + 1} of 4</div>
        <h1 style={{ fontSize: 23, letterSpacing: '-0.03em', marginBottom: 18 }}>{['Tell us about your business', 'Add your branding', 'Tax & GST', "You're all set"][step]}</h1>
        {step === 0 && <React.Fragment>
          <div className="field"><label>Trading name</label><input className="input" defaultValue="Hayes Contracting Ltd" /></div>
          <div className="field"><label>Industry</label><div className="seg"><button className="on">Trades</button><button>Auto</button><button>Services</button></div></div>
          <div className="field"><label>Region</label><input className="input" defaultValue="Auckland Central" /></div>
        </React.Fragment>}
        {step === 1 && <React.Fragment>
          <div className="field"><label>Logo</label><div style={{ border: '1.5px dashed var(--border-strong)', borderRadius: 14, padding: 28, textAlign: 'center', color: 'var(--muted-2)' }}><I5 name="upload" style={{ fontSize: 26 }} /><div style={{ fontSize: 13, marginTop: 8 }}>Upload your logo</div></div></div>
          <div className="field"><label>Accent colour</label><div className="row" style={{ gap: 10 }}>{['#2F62F0', '#1F8A5B', '#6D5AE6', '#C8412F', '#B5740F'].map(c => <span key={c} style={{ width: 38, height: 38, borderRadius: 11, background: c, border: c === '#2F62F0' ? '3px solid var(--text)' : '3px solid transparent' }}></span>)}</div></div>
        </React.Fragment>}
        {step === 2 && <React.Fragment>
          <div className="field"><label>GST registered?</label><div className="seg"><button className="on">Yes</button><button>No</button></div></div>
          <div className="field"><label>GST number</label><div className="input-group"><span className="pre">GST</span><input placeholder="123-456-789" inputMode="numeric" /></div></div>
          <div className="field"><label>Filing frequency</label><div className="seg"><button>Monthly</button><button className="on">2-monthly</button><button>6-monthly</button></div></div>
        </React.Fragment>}
        {step === 3 && <div className="card card-pad" style={{ textAlign: 'center', padding: '36px 24px' }}><span className="ico green" style={{ width: 64, height: 64, borderRadius: 18, margin: '0 auto 16px' }}><I5 name="check" style={{ fontSize: 30 }} /></span><h2 style={{ fontSize: 19 }}>Ready to go</h2><p className="muted" style={{ fontSize: 14, marginTop: 6 }}>Your account is set up. Let's create your first invoice.</p></div>}
      </div></div>
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: 'var(--pad)', paddingBottom: 'calc(var(--pad) + var(--safe-bot,0px))', background: 'color-mix(in srgb, var(--card) 90%, transparent)', backdropFilter: 'blur(14px)', borderTop: '1px solid var(--border)' }}>
        <button className="btn btn-primary" onClick={next}>{step < 3 ? 'Continue' : 'Go to dashboard'}</button>
      </div>
    </div>
  );
}

/* ───────── SCREEN DIRECTORY ───────── */
const DIR_GROUPS = [
  { label: 'Money', items: [['invoice', 'Invoices', 'invoices'], ['quote', 'Quotes', 'quotes'], ['invoice', 'Recurring', 'recurring'], ['card', 'Payments', 'payments'], ['receipt', 'Expenses', 'expenses'], ['bank', 'Banking', 'banking'], ['receipt', 'GST return', 'gst'], ['chart', 'Reports', 'reports'], ['building', 'Accounting', 'accounting']] },
  { label: 'Work', items: [['job', 'Jobs', 'jobs'], ['bookings', 'Bookings', 'bookings'], ['building', 'Projects', 'projects'], ['building', 'Construction', 'construction'], ['shield', 'Claims', 'claims'], ['clock', 'Time clock', 'clock'], ['card', 'Point of sale', 'pos']] },
  { label: 'Catalogue', items: [['box', 'Inventory', 'inventory'], ['box', 'Items & catalogue', 'items'], ['box', 'Purchase orders', 'purchaseOrders'], ['box', 'Assets', 'assets'], ['car', 'Vehicles', 'vehicles']] },
  { label: 'People', items: [['user', 'Staff', 'staff'], ['dollar', 'Payroll', 'payroll'], ['calendar', 'Leave', 'leave'], ['calendar', 'Roster & swaps', 'roster'], ['calendar', 'Schedule', 'schedule']] },
  { label: 'Customers', items: [['customers', 'Customers', 'customers'], ['sms', 'Messages', 'sms'], ['trend', 'Loyalty', 'loyalty'], ['user', 'Customer portal', 'portal'], ['calendar', 'Public booking', 'publicBooking'], ['card', 'Payment page', 'paymentPage']] },
  { label: 'Compliance', items: [['shield', 'Compliance', 'compliance'], ['lock', 'PPSR', 'ppsr']] },
  { label: 'Account & onboarding', items: [['bell', 'Notifications', 'notifications'], ['settings', 'Settings', 'settings'], ['box', 'Component states', 'states'], ['user', 'Sign up', 'signup'], ['shield', 'Two-factor', 'mfa'], ['key', 'Reset password', 'reset'], ['box', 'Setup wizard', 'setupWizard']] },
];

function DirectoryScreen({ nav }) {
  const [q, setQ] = React.useState('');
  const ql = q.trim().toLowerCase();
  return (
    <div className="scr">
      <NB5 title="All screens" onBack={nav.pop} />
      <div className="screen"><div className="pad-x" style={{ paddingTop: 4, paddingBottom: 10 }}><div className="searchbar"><I5 name="search" /><input placeholder="Search screens…" value={q} onChange={e => setQ(e.target.value)} /></div></div>
        <div className="pad-x scroll-pad stack">
          {DIR_GROUPS.map((g, gi) => {
            const items = g.items.filter(it => !ql || it[1].toLowerCase().includes(ql));
            if (!items.length) return null;
            return (
              <div key={gi}>
                <div className="section-label">{g.label}</div>
                <div className="list">{items.map((it, i) => (
                  <div className="li" key={i} onClick={() => nav.push(it[2])}>
                    <span className="ico blue" style={{ width: 34, height: 34 }}><I5 name={it[0]} style={{ fontSize: 16 }} /></span>
                    <div className="body"><div className="t" style={{ fontSize: 14, fontWeight: 500 }}>{it[1]}</div></div>
                    <I5 name="chev" className="chev" />
                  </div>
                ))}</div>
              </div>
            );
          })}
          <p style={{ textAlign: 'center', fontSize: 12 }} className="muted mono">{DIR_GROUPS.reduce((n, g) => n + g.items.length, 0)} screens</p>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, {
  PortalScreen, PublicBookingScreen, PaymentPageScreen, SignupScreen, MfaScreen, ResetScreen, SetupWizardScreen, DirectoryScreen,
});
