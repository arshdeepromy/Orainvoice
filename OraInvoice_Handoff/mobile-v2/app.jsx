// app.jsx — shell, stack router, tab bar, status bar, phone frame, tweaks.
const { useTweaks, TweaksPanel, TweakSection, TweakColor, TweakRadio, TweakToggle } = window;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#2F62F0",
  "density": "regular",
  "tabstyle": "pill",
  "dark": false
}/*EDITMODE-END*/;

// which bottom tab owns each root screen
const TAB_FOR = { home: 'home', invoices: 'invoices', customers: 'customers', jobs: 'jobs', more: 'more' };
const TABS = [
  { id: 'home', label: 'Home', icon: 'home', root: 'home' },
  { id: 'invoices', label: 'Invoices', icon: 'invoice', root: 'invoices' },
  { id: 'customers', label: 'Customers', icon: 'customers', root: 'customers' },
  { id: 'jobs', label: 'Jobs', icon: 'job', root: 'jobs' },
  { id: 'more', label: 'More', icon: 'more', root: 'more', badge: true },
];

function StatusBar() {
  return (
    <div style={{ height: 50, flexShrink: 0, position: 'absolute', top: 0, left: 0, right: 0, zIndex: 12,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 28px', paddingTop: 8,
      background: 'var(--canvas)', color: 'var(--text)', font: '600 15px var(--sans)' }}>
      <span style={{ letterSpacing: '0.01em' }}>9:41</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <svg width="18" height="12" viewBox="0 0 18 12" fill="currentColor"><rect x="0" y="7" width="3" height="5" rx="1"/><rect x="5" y="4" width="3" height="8" rx="1"/><rect x="10" y="1.5" width="3" height="10.5" rx="1"/><rect x="15" y="0" width="3" height="12" rx="1" opacity="0.35"/></svg>
        <svg width="17" height="12" viewBox="0 0 17 12" fill="currentColor"><path d="M8.5 2.5c2.3 0 4.4.9 6 2.4l1.3-1.4A11 11 0 0 0 8.5.5 11 11 0 0 0 1.2 3.5l1.3 1.4A8.5 8.5 0 0 1 8.5 2.5z"/><path d="M8.5 6c1.2 0 2.3.5 3.1 1.3l1.3-1.4A6.5 6.5 0 0 0 8.5 4 6.5 6.5 0 0 0 4.1 5.9l1.3 1.4A4.5 4.5 0 0 1 8.5 6z"/><circle cx="8.5" cy="10" r="1.6"/></svg>
        <svg width="26" height="13" viewBox="0 0 26 13" fill="none"><rect x="0.5" y="0.5" width="22" height="12" rx="3.5" stroke="currentColor" opacity="0.4"/><rect x="2" y="2" width="17" height="9" rx="2" fill="currentColor"/><rect x="24" y="4" width="1.5" height="5" rx="0.75" fill="currentColor" opacity="0.4"/></svg>
      </div>
    </div>
  );
}

function TabBar({ tab, onTab }) {
  return (
    <div className="tabbar">
      {TABS.map(t => (
        <button key={t.id} className={`tab${tab === t.id ? ' on' : ''}`} onClick={() => onTab(t)}>
          <span className="tab-ico"><Ico name={t.icon} />{t.badge && <span className="tdot"></span>}</span>
          <span className="tl">{t.label}</span>
        </button>
      ))}
    </div>
  );
}

const SCREENS = {
  login: (p) => <LoginScreen {...p} />,
  home: (p) => <HomeScreen {...p} />,
  invoices: (p) => <InvoicesScreen {...p} />,
  invoiceDetail: (p) => <InvoiceDetailScreen {...p} />,
  invoiceCreate: (p) => <InvoiceCreateScreen {...p} />,
  customers: (p) => <CustomersScreen {...p} />,
  customerDetail: (p) => <CustomerDetailScreen {...p} />,
  customerCreate: (p) => <CustomerCreateScreen {...p} />,
  jobs: (p) => <JobsScreen {...p} />,
  quotes: (p) => <QuotesScreen {...p} />,
  clock: (p) => <ClockScreen {...p} />,
  more: (p) => <MoreScreen {...p} />,
  // module lists (batch 2)
  bookings: (p) => <BookingsScreen {...p} />,
  schedule: (p) => <ScheduleScreen {...p} />,
  vehicles: (p) => <VehiclesScreen {...p} />,
  inventory: (p) => <InventoryScreen {...p} />,
  expenses: (p) => <ExpensesScreen {...p} />,
  purchaseOrders: (p) => <PurchaseOrdersScreen {...p} />,
  projects: (p) => <ProjectsScreen {...p} />,
  staff: (p) => <StaffScreen {...p} />,
  reports: (p) => <ReportsScreen {...p} />,
  accounting: (p) => <AccountingScreen {...p} />,
  banking: (p) => <BankingScreen {...p} />,
  compliance: (p) => <ComplianceScreen {...p} />,
  pos: (p) => <PosScreen {...p} />,
  notifications: (p) => <NotificationsScreen {...p} />,
  settings: (p) => <SettingsScreen {...p} />,
  // detail screens (batch 3)
  quoteDetail: (p) => <QuoteDetailScreen {...p} />,
  jobDetail: (p) => <JobDetailScreen {...p} />,
  bookingDetail: (p) => <BookingDetailScreen {...p} />,
  vehicleDetail: (p) => <VehicleDetailScreen {...p} />,
  itemDetail: (p) => <ItemDetailScreen {...p} />,
  poDetail: (p) => <PoDetailScreen {...p} />,
  projectDetail: (p) => <ProjectDetailScreen {...p} />,
  expenseDetail: (p) => <ExpenseDetailScreen {...p} />,
  staffDetail: (p) => <StaffDetailScreen {...p} />,
  // new module lists (batch 4)
  items: (p) => <ItemsScreen {...p} />,
  recurring: (p) => <RecurringScreen {...p} />,
  claims: (p) => <ClaimsScreen {...p} />,
  construction: (p) => <ConstructionScreen {...p} />,
  assets: (p) => <AssetsScreen {...p} />,
  ppsr: (p) => <PpsrScreen {...p} />,
  loyalty: (p) => <LoyaltyScreen {...p} />,
  payroll: (p) => <PayrollScreen {...p} />,
  leave: (p) => <LeaveScreen {...p} />,
  roster: (p) => <RosterScreen {...p} />,
  sms: (p) => <SmsScreen {...p} />,
  payments: (p) => <PaymentsScreen {...p} />,
  gst: (p) => <GstScreen {...p} />,
  quoteCreate: (p) => <QuoteCreateScreen {...p} />,
  // customer-facing, auth, directory (batch 5)
  portal: (p) => <PortalScreen {...p} />,
  publicBooking: (p) => <PublicBookingScreen {...p} />,
  paymentPage: (p) => <PaymentPageScreen {...p} />,
  signup: (p) => <SignupScreen {...p} />,
  mfa: (p) => <MfaScreen {...p} />,
  reset: (p) => <ResetScreen {...p} />,
  setupWizard: (p) => <SetupWizardScreen {...p} />,
  directory: (p) => <DirectoryScreen {...p} />,
  // sub-pages & states (batch 6)
  reportDetail: (p) => <ReportDetailScreen {...p} />,
  settingsDetail: (p) => <SettingsDetailScreen {...p} />,
  states: (p) => <StatesScreen {...p} />,
};

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [stack, setStack] = React.useState([{ name: 'login', params: {} }]);
  const [tab, setTab] = React.useState('home');
  const [leaving, setLeaving] = React.useState(null);
  const [anim, setAnim] = React.useState('fade');

  const nav = React.useMemo(() => ({
    push(name, params = {}) { setAnim('push'); setStack(s => [...s, { name, params, key: Date.now() }]); },
    pop() {
      setStack(s => {
        if (s.length <= 1) return s;
        setAnim('pop');
        setLeaving(s[s.length - 1]);
        setTimeout(() => setLeaving(null), 300);
        return s.slice(0, -1);
      });
    },
    reset(name) { setAnim('fade'); setLeaving(null); setStack([{ name, params: {}, key: Date.now() }]); if (TAB_FOR[name]) setTab(TAB_FOR[name]); },
    switchTab(id) { const tb = TABS.find(x => x.id === id); if (tb) { setAnim('fade'); setLeaving(null); setStack([{ name: tb.root, params: {}, key: Date.now() }]); setTab(id); } },
  }), []);

  const top = stack[stack.length - 1];
  const showTab = stack.length === 1 && top.name !== 'login';
  const extra = { dark: t.dark, onToggleDark: () => setTweak('dark', !t.dark) };

  const onTab = (tb) => {
    if (tab === tb.id && stack.length === 1) return;
    nav.switchTab(tb.id);
  };

  return (
    <div className="device-wrap">
      <div className="device">
        <div className="screen-area"
          data-theme={t.dark ? 'dark' : 'light'}
          data-density={t.density}
          data-tabstyle={t.tabstyle}
          style={{ '--accent': t.accent, '--safe-bot': '20px' }}>
          <StatusBar />
          <div className="app-root">
            <div className="layers">
              <div key={top.key || top.name} className={`layer anim-${anim}`}>
                {SCREENS[top.name]({ nav, params: top.params, ...extra })}
              </div>
              {leaving && (
                <div className="layer anim-leave" style={{ zIndex: 9 }}>
                  {SCREENS[leaving.name]({ nav, params: leaving.params, ...extra })}
                </div>
              )}
            </div>
            {showTab && <TabBar tab={tab} onTab={onTab} />}
          </div>
          <div className="home-indicator"></div>
        </div>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Brand" />
        <TweakColor label="Accent" value={t.accent}
          options={['#2F62F0', '#1F8A5B', '#6D5AE6', '#0E8C9E', '#C8412F', '#B5740F']}
          onChange={(v) => setTweak('accent', v)} />
        <TweakToggle label="Dark mode" value={t.dark} onChange={(v) => setTweak('dark', v)} />
        <TweakSection label="Layout" />
        <TweakRadio label="Card density" value={t.density} options={['compact', 'regular', 'comfy']}
          onChange={(v) => setTweak('density', v)} />
        <TweakRadio label="Tab bar style" value={t.tabstyle} options={['pill', 'bar', 'minimal']}
          onChange={(v) => setTweak('tabstyle', v)} />
      </TweaksPanel>
    </div>
  );
}

// scale device to fit viewport
function fitDevice() {
  const wrap = document.querySelector('.device');
  if (!wrap) return;
  const W = 408, H = 862, m = 24;
  const s = Math.min((window.innerWidth - m) / W, (window.innerHeight - m) / H, 1);
  wrap.style.transform = `scale(${s})`;
}
window.addEventListener('resize', fitDevice);

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
setTimeout(fitDevice, 60);
