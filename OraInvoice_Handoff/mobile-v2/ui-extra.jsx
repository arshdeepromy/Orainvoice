// ui-extra.jsx — reusable interactive primitives: form sheets, create FABs,
// filter sheets, global search, and loading/empty/error states.
// Loaded after ui.jsx; everything attaches to window.
const { Ico: IX, money: mx, Avatar: AVx, DATA: DX } = window;

/* ───────── toast ───────── */
function toast(msg) {
  const root = document.querySelector('.app-root') || document.body;
  const el = document.createElement('div');
  el.className = 'toast';
  el.innerHTML = `<span class="dot"></span>${msg}`;
  root.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 240); }, 1900);
}

/* ───────── field controls ───────── */
function SelectField({ value, options, onChange }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div style={{ position: 'relative' }}>
      <button type="button" className="input row" style={{ alignItems: 'center', width: '100%', textAlign: 'left' }} onClick={() => setOpen(o => !o)}>
        <span style={{ fontWeight: 500 }}>{value}</span>
        <IX name="chev" className="chev" style={{ marginLeft: 'auto', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }} />
      </button>
      {open && (
        <div className="select-pop">
          {options.map(o => (
            <button type="button" key={o} className={`select-opt${o === value ? ' on' : ''}`} onClick={() => { onChange(o); setOpen(false); }}>
              {o}{o === value && <IX name="check" style={{ marginLeft: 'auto', fontSize: 15 }} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Field({ f, value, onChange }) {
  const lab = <label>{f.label}{f.optional && <span className="opt"> (optional)</span>}</label>;
  if (f.type === 'seg') return <div className="field">{lab}<div className="seg">{f.options.map(o => <button type="button" key={o} className={value === o ? 'on' : ''} onClick={() => onChange(o)}>{o}</button>)}</div></div>;
  if (f.type === 'select') return <div className="field">{lab}<SelectField value={value} options={f.options} onChange={onChange} /></div>;
  if (f.type === 'textarea') return <div className="field">{lab}<textarea className="textarea" placeholder={f.placeholder} value={value} onChange={e => onChange(e.target.value)} /></div>;
  if (f.type === 'picker') return <div className="field">{lab}<button type="button" className="input row" style={{ alignItems: 'center', width: '100%' }}><AVx name={value} square /><span style={{ marginLeft: 10, fontWeight: 600 }}>{value}</span><IX name="chev" className="chev" style={{ marginLeft: 'auto' }} /></button></div>;
  if (f.type === 'date') return <div className="field">{lab}<button type="button" className="input row" style={{ alignItems: 'center', width: '100%' }}><span style={{ fontWeight: 500 }}>{value}</span><IX name="calendar" style={{ marginLeft: 'auto', fontSize: 17, color: 'var(--muted)' }} /></button></div>;
  if (f.type === 'photo') return <div className="field">{lab}<div className="upload-box"><IX name={f.icon || 'camera'} style={{ fontSize: 26 }} /><div style={{ fontSize: 13, marginTop: 8 }}>{f.placeholder || 'Add a photo'}</div></div></div>;
  if (f.type === 'money' || f.type === 'number') return <div className="field">{lab}<div className="input-group">{f.type === 'money' && <span className="pre">$</span>}<input inputMode="decimal" placeholder={f.placeholder} value={value} onChange={e => onChange(e.target.value)} />{f.suffix && <span className="pre" style={{ borderLeft: '1px solid var(--border)', borderRight: 'none' }}>{f.suffix}</span>}</div></div>;
  return <div className="field">{lab}<input className="input" placeholder={f.placeholder} value={value} onChange={e => onChange(e.target.value)} /></div>;
}

/* ───────── form sheet ───────── */
function FormSheet({ open, onClose, title, fields = [], submit = 'Save', done = 'Saved' }) {
  const init = React.useCallback(() => Object.fromEntries(fields.map(f => [f.key, f.value ?? ((f.type === 'seg' || f.type === 'select') ? f.options[0] : '')])), [fields]);
  const [vals, setVals] = React.useState(init);
  React.useEffect(() => { if (open) setVals(init()); }, [open]);
  const set = (k, v) => setVals(s => ({ ...s, [k]: v }));
  return (
    <React.Fragment>
      <div className={`sheet-scrim${open ? ' open' : ''}`} onClick={onClose}></div>
      <div className={`sheet${open ? ' open' : ''}`}>
        <div className="grab"></div>
        <div className="sheet-head"><h3>{title}</h3><button className="nav-btn" onClick={onClose} aria-label="Close"><IX name="x" /></button></div>
        <div className="sheet-body">
          {fields.map(f => <Field key={f.key} f={f} value={vals[f.key] ?? ''} onChange={v => set(f.key, v)} />)}
          <button className="btn btn-primary" style={{ marginTop: 4 }} onClick={() => { onClose(); toast(done); }}><IX name="check" /> {submit}</button>
          <div style={{ height: 8 }}></div>
        </div>
      </div>
    </React.Fragment>
  );
}

/* ───────── create FAB (self-contained) ───────── */
const CREATE_FORMS = {
  job: { title: 'New job', submit: 'Create job', done: 'Job created', fields: [
    { key: 'title', label: 'Job title', placeholder: 'e.g. Kitchen fit-out' },
    { key: 'cust', label: 'Customer', type: 'picker', value: 'Coastal Fitouts' },
    { key: 'assignee', label: 'Assign to', type: 'select', options: ['Tom Rua', 'Mia Kemp', 'Sefa Lautele', 'Unassigned'] },
    { key: 'priority', label: 'Priority', type: 'seg', options: ['Low', 'Normal', 'Urgent'], value: 'Normal' },
    { key: 'due', label: 'Due date', type: 'date', value: '18 Jun 2025' },
  ] },
  booking: { title: 'New booking', submit: 'Create booking', done: 'Booking created', fields: [
    { key: 'cust', label: 'Customer', type: 'picker', value: 'Hayes Contracting Ltd' },
    { key: 'svc', label: 'Service', type: 'seg', options: ['Measure', 'Repair', 'Install'], value: 'Measure' },
    { key: 'date', label: 'Date', type: 'date', value: 'Wed, 4 Jun 2025' },
    { key: 'time', label: 'Time', placeholder: '09:30' },
    { key: 'who', label: 'Assign to', type: 'select', options: ['Tom Rua', 'Mia Kemp', 'Unassigned'] },
    { key: 'notes', label: 'Notes', type: 'textarea', optional: true, placeholder: 'Anything the tech should know…' },
  ] },
  shift: { title: 'Add shift', submit: 'Add shift', done: 'Shift added', fields: [
    { key: 'staff', label: 'Staff member', type: 'select', options: ['Tom Rua', 'Mia Kemp', 'Sefa Lautele'] },
    { key: 'date', label: 'Date', type: 'date', value: 'Mon, 2 Jun 2025' },
    { key: 'start', label: 'Start', placeholder: '07:30' },
    { key: 'end', label: 'Finish', placeholder: '16:00' },
    { key: 'branch', label: 'Branch', type: 'select', options: ['Kerikeri · BR-01', 'Whangārei · BR-02'] },
  ] },
  item: { title: 'New item', submit: 'Add item', done: 'Item added', fields: [
    { key: 'name', label: 'Item name', placeholder: 'e.g. Framing timber 90×45' },
    { key: 'sku', label: 'SKU', placeholder: 'TMB-90x45' },
    { key: 'cat', label: 'Category', type: 'select', options: ['Timber', 'Fixings', 'Paint', 'Aggregate', 'Sealants', 'Labour'] },
    { key: 'price', label: 'Sell price', type: 'money', placeholder: '0.00', suffix: '/ ea' },
    { key: 'cost', label: 'Cost price', type: 'money', placeholder: '0.00', suffix: '/ ea' },
    { key: 'stock', label: 'Opening stock', type: 'number', placeholder: '0' },
  ] },
  expense: { title: 'New expense', submit: 'Save expense', done: 'Expense saved', fields: [
    { key: 'photo', label: 'Receipt', type: 'photo', placeholder: 'Snap or upload receipt' },
    { key: 'vendor', label: 'Vendor', placeholder: 'e.g. Bunnings Warehouse' },
    { key: 'cat', label: 'Category', type: 'select', options: ['Materials', 'Fuel', 'Phone', 'Freight', 'Tools', 'Other'] },
    { key: 'amt', label: 'Amount (incl. GST)', type: 'money', placeholder: '0.00' },
    { key: 'job', label: 'Assign to job', type: 'select', optional: true, options: ['None', 'JOB-318', 'JOB-315'] },
  ] },
  po: { title: 'New purchase order', submit: 'Create PO', done: 'PO created', fields: [
    { key: 'sup', label: 'Supplier', type: 'select', options: ['PlaceMakers', 'Mico Plumbing', 'Bunnings Trade', 'Carters', 'Resene'] },
    { key: 'ref', label: 'Reference', optional: true, placeholder: 'Internal reference' },
    { key: 'expected', label: 'Expected delivery', type: 'date', value: '6 Jun 2025' },
    { key: 'notes', label: 'Notes', type: 'textarea', optional: true, placeholder: 'Delivery instructions…' },
  ] },
  project: { title: 'New project', submit: 'Create project', done: 'Project created', fields: [
    { key: 'name', label: 'Project name', placeholder: 'e.g. Coastal Apartments fitout' },
    { key: 'client', label: 'Client', type: 'picker', value: 'Coastal Fitouts' },
    { key: 'budget', label: 'Budget', type: 'money', placeholder: '0.00' },
    { key: 'start', label: 'Start date', type: 'date', value: '4 Jun 2025' },
    { key: 'due', label: 'Due date', type: 'date', value: '29 Aug 2025' },
  ] },
  staff: { title: 'Invite team member', submit: 'Send invite', done: 'Invite sent', fields: [
    { key: 'first', label: 'First name', placeholder: 'First name' },
    { key: 'last', label: 'Last name', placeholder: 'Last name' },
    { key: 'email', label: 'Work email', placeholder: 'name@business.co.nz' },
    { key: 'role', label: 'Role', type: 'select', options: ['Technician', 'Apprentice', 'Front desk', 'Manager', 'Owner'] },
    { key: 'type', label: 'Employment', type: 'seg', options: ['Employee', 'Contractor'], value: 'Employee' },
  ] },
  compliance: { title: 'Upload document', submit: 'Upload', done: 'Document uploaded', fields: [
    { key: 'file', label: 'File', type: 'photo', icon: 'upload', placeholder: 'Choose a file or photo' },
    { key: 'name', label: 'Document name', placeholder: 'e.g. Site safety plan' },
    { key: 'type', label: 'Type', type: 'select', options: ['SWMS', 'Insurance', 'Licence', 'Certificate', 'Other'] },
    { key: 'expiry', label: 'Expiry date', type: 'date', optional: true, value: 'No expiry' },
  ] },
  recurring: { title: 'New recurring invoice', submit: 'Create schedule', done: 'Schedule created', fields: [
    { key: 'cust', label: 'Customer', type: 'picker', value: 'Coastal Fitouts' },
    { key: 'amt', label: 'Amount', type: 'money', placeholder: '0.00' },
    { key: 'freq', label: 'Frequency', type: 'seg', options: ['Weekly', 'Monthly', 'Quarterly'], value: 'Monthly' },
    { key: 'next', label: 'First invoice', type: 'date', value: '1 Jul 2025' },
  ] },
  claim: { title: 'New claim', submit: 'Create claim', done: 'Claim created', fields: [
    { key: 'cust', label: 'Customer', type: 'picker', value: 'Aroha Whitiora' },
    { key: 'type', label: 'Type', type: 'seg', options: ['Insurance', 'Warranty'], value: 'Insurance' },
    { key: 'amt', label: 'Claim amount', type: 'money', placeholder: '0.00' },
    { key: 'insurer', label: 'Insurer', type: 'select', options: ['AA Insurance', 'State', 'Tower', 'Manufacturer', 'Other'] },
  ] },
  construction: { title: 'New claim / variation', submit: 'Create', done: 'Created', fields: [
    { key: 'kind', label: 'Type', type: 'seg', options: ['Progress claim', 'Variation'], value: 'Progress claim' },
    { key: 'proj', label: 'Project', type: 'select', options: ['Coastal Apartments', 'Te Awa cafe'] },
    { key: 'desc', label: 'Description', placeholder: 'e.g. Additional GPO circuits' },
    { key: 'amt', label: 'Amount', type: 'money', placeholder: '0.00' },
  ] },
  asset: { title: 'Add asset', submit: 'Add asset', done: 'Asset added', fields: [
    { key: 'name', label: 'Asset name', placeholder: 'e.g. Hilti TE 70 rotary hammer' },
    { key: 'tag', label: 'Asset tag', placeholder: 'AST-000' },
    { key: 'value', label: 'Value', type: 'money', placeholder: '0.00' },
    { key: 'loc', label: 'Location', type: 'select', options: ['Workshop', 'Depot', 'Van — Tom R.', 'On site'] },
  ] },
  ppsr: { title: 'Register security', submit: 'Register', done: 'Security registered', fields: [
    { key: 'debtor', label: 'Debtor', type: 'picker', value: 'Coastal Fitouts' },
    { key: 'coll', label: 'Collateral', placeholder: 'e.g. Cabinetry & fixtures' },
    { key: 'expiry', label: 'Expiry', type: 'date', value: 'Jun 2029' },
  ] },
  leave: { title: 'Request leave', submit: 'Submit request', done: 'Request submitted', fields: [
    { key: 'staff', label: 'Staff member', type: 'select', options: ['Tom Rua', 'Mia Kemp', 'Sefa Lautele'] },
    { key: 'type', label: 'Type', type: 'seg', options: ['Annual', 'Sick', 'Other'], value: 'Annual' },
    { key: 'from', label: 'From', type: 'date', value: '14 Jul 2025' },
    { key: 'to', label: 'To', type: 'date', value: '18 Jul 2025' },
    { key: 'reason', label: 'Reason', type: 'textarea', optional: true, placeholder: 'Optional note…' },
  ] },
  service: { title: 'Log service', submit: 'Log service', done: 'Service logged', fields: [
    { key: 'type', label: 'Service type', type: 'select', options: ['WOF inspection', 'Full service', 'Oil & filter', 'Brakes', 'Other'] },
    { key: 'odo', label: 'Odometer', type: 'number', placeholder: '0', suffix: 'km' },
    { key: 'date', label: 'Date', type: 'date', value: '4 Jun 2025' },
    { key: 'notes', label: 'Notes', type: 'textarea', optional: true, placeholder: 'Work performed…' },
  ] },
  message: { title: 'New message', submit: 'Send', done: 'Message sent', fields: [
    { key: 'to', label: 'To', type: 'picker', value: 'Daniel Hayes' },
    { key: 'body', label: 'Message', type: 'textarea', placeholder: 'Type your message…' },
  ] },
};

function CreateFab({ icon = 'plus', label, round, form }) {
  const [open, setOpen] = React.useState(false);
  const cfg = CREATE_FORMS[form] || { title: label, fields: [] };
  return (
    <React.Fragment>
      <button className={`fab${round ? ' round' : ''}`} onClick={() => setOpen(true)}>
        <IX name={icon} />{!round && label ? ` ${label}` : null}
      </button>
      <FormSheet open={open} onClose={() => setOpen(false)} title={cfg.title} fields={cfg.fields} submit={cfg.submit || 'Save'} done={cfg.done || 'Saved'} />
    </React.Fragment>
  );
}

/* ───────── filter sheet + button ───────── */
function FilterBtn({ groups = [{ label: 'Status', options: ['All', 'Paid', 'Sent', 'Overdue', 'Draft'] }, { label: 'Sort by', options: ['Newest', 'Oldest', 'Amount ↑', 'Amount ↓'] }] }) {
  const [open, setOpen] = React.useState(false);
  const [sel, setSel] = React.useState(() => Object.fromEntries(groups.map(g => [g.label, g.options[0]])));
  return (
    <React.Fragment>
      <button className="nav-btn" onClick={() => setOpen(true)} aria-label="Filter"><IX name="filter" /></button>
      <Portal>
      <div className={`sheet-scrim${open ? ' open' : ''}`} onClick={() => setOpen(false)}></div>
      <div className={`sheet${open ? ' open' : ''}`}>
        <div className="grab"></div>
        <div className="sheet-head"><h3>Filter & sort</h3><button className="nav-btn" onClick={() => setOpen(false)}><IX name="x" /></button></div>
        <div className="sheet-body">
          {groups.map(g => (
            <div className="field" key={g.label}>
              <label>{g.label}</label>
              <div className="chips" style={{ overflow: 'visible', flexWrap: 'wrap' }}>
                {g.options.map(o => <button key={o} className={`chip${sel[g.label] === o ? ' on' : ''}`} onClick={() => setSel(s => ({ ...s, [g.label]: o }))}>{o}</button>)}
              </div>
            </div>
          ))}
          <div className="row" style={{ gap: 10, marginTop: 4 }}>
            <button className="btn btn-ghost" style={{ flex: 1 }} onClick={() => { setSel(Object.fromEntries(groups.map(g => [g.label, g.options[0]]))); }}>Reset</button>
            <button className="btn btn-primary" style={{ flex: 1.6 }} onClick={() => { setOpen(false); toast('Filters applied'); }}><IX name="check" /> Apply</button>
          </div>
          <div style={{ height: 8 }}></div>
        </div>
      </div>
      </Portal>
    </React.Fragment>
  );
}

/* ───────── global search overlay ───────── */
function SearchOverlay({ nav, open, onClose }) {
  const [q, setQ] = React.useState('');
  const ql = q.trim().toLowerCase();
  const ref = React.useRef(null);
  React.useEffect(() => { if (open && ref.current) setTimeout(() => ref.current.focus(), 80); }, [open]);
  const results = [];
  if (ql) {
    DX.customers.filter(c => c.name.toLowerCase().includes(ql)).slice(0, 4).forEach(c => results.push({ icon: 'customers', t: c.name, s: 'Customer', go: () => nav.push('customerDetail', { id: c.id }) }));
    DX.invoices.filter(i => i.id.toLowerCase().includes(ql) || i.customer.toLowerCase().includes(ql)).slice(0, 4).forEach(i => results.push({ icon: 'invoice', t: i.id, s: `${i.customer} · ${mx(i.amount)}`, go: () => nav.push('invoiceDetail', { id: i.id }) }));
    DX.jobs.filter(j => j.id.toLowerCase().includes(ql) || j.title.toLowerCase().includes(ql)).slice(0, 3).forEach(j => results.push({ icon: 'job', t: j.title, s: j.id, go: () => nav.push('jobDetail', { id: j.id }) }));
    [['Bookings', 'bookings'], ['Inventory', 'inventory'], ['Payroll', 'payroll'], ['Reports', 'reports'], ['Settings', 'settings'], ['Expenses', 'expenses'], ['Vehicles', 'vehicles'], ['Claims', 'claims']]
      .filter(([n]) => n.toLowerCase().includes(ql)).slice(0, 4).forEach(([n, go]) => results.push({ icon: 'box', t: n, s: 'Open module', go: () => nav.push(go) }));
  }
  if (!open) return null;
  return (
    <Portal>
    <div className="search-overlay">
      <div className="search-bar-row">
        <div className="searchbar grow"><IX name="search" /><input ref={ref} placeholder="Search customers, invoices, jobs…" value={q} onChange={e => setQ(e.target.value)} /></div>
        <button className="nav-btn txt" onClick={onClose}>Cancel</button>
      </div>
      <div className="search-results">
        {!ql && <div className="search-hint"><IX name="search" style={{ fontSize: 26, opacity: .4 }} /><p>Search across customers, invoices, jobs and every module.</p></div>}
        {ql && !results.length && <div className="search-hint"><IX name="search" style={{ fontSize: 26, opacity: .4 }} /><p>No matches for “{q}”.</p></div>}
        {!!results.length && <div className="list">{results.map((r, i) => (
          <div className="li" key={i} onClick={() => { onClose(); r.go(); }}>
            <span className="ico blue" style={{ width: 36, height: 36 }}><IX name={r.icon} style={{ fontSize: 16 }} /></span>
            <div className="body"><div className="t">{r.t}</div><div className="s">{r.s}</div></div>
            <IX name="chev" className="chev" />
          </div>
        ))}</div>}
      </div>
    </div>
    </Portal>
  );
}

function SearchBtn({ nav }) {
  const [open, setOpen] = React.useState(false);
  return (
    <React.Fragment>
      <button className="nav-btn" onClick={() => setOpen(true)} aria-label="Search"><IX name="search" /></button>
      <SearchOverlay nav={nav} open={open} onClose={() => setOpen(false)} />
    </React.Fragment>
  );
}

/* ───────── loading / empty / error states ───────── */
function Skeleton({ rows = 5 }) {
  return (
    <div className="list">
      {Array.from({ length: rows }).map((_, i) => (
        <div className="li" key={i}>
          <span className="sk sk-av"></span>
          <div className="body"><span className="sk sk-line" style={{ width: '62%' }}></span><span className="sk sk-line sm" style={{ width: '40%' }}></span></div>
          <span className="sk sk-line sm" style={{ width: 44 }}></span>
        </div>
      ))}
    </div>
  );
}
function EmptyState({ icon = 'box', title = 'Nothing here yet', sub, action, onAction }) {
  return (
    <div className="state">
      <span className="state-ico"><IX name={icon} /></span>
      <h3>{title}</h3>{sub && <p>{sub}</p>}
      {action && <button className="btn btn-primary" style={{ width: 'auto', marginTop: 16, padding: '0 20px' }} onClick={onAction}><IX name="plus" /> {action}</button>}
    </div>
  );
}
function ErrorState({ title = 'Something went wrong', sub = 'We couldn’t load this. Check your connection and try again.', onRetry }) {
  return (
    <div className="state">
      <span className="state-ico err"><IX name="alert" /></span>
      <h3>{title}</h3><p>{sub}</p>
      <button className="btn btn-ghost" style={{ width: 'auto', marginTop: 16, padding: '0 20px' }} onClick={onRetry}><IX name="refresh" /> Try again</button>
    </div>
  );
}

Object.assign(window, { toast, FormSheet, CreateFab, FilterBtn, SearchOverlay, SearchBtn, Skeleton, EmptyState, ErrorState, CREATE_FORMS });

/* portal helper — lifts navbar-embedded overlays up to the app root so
   position:absolute covers the whole screen, not just the navbar. */
function Portal({ children }) {
  const [el] = React.useState(() => document.createElement('div'));
  React.useEffect(() => {
    const host = document.querySelector('.app-root') || document.body;
    host.appendChild(el);
    return () => { try { host.removeChild(el); } catch (e) {} };
  }, [el]);
  return ReactDOM.createPortal(children, el);
}
window.Portal = Portal;
