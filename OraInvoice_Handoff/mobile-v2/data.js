// data.js — mock data for the OraInvoice mobile prototype (NZ trades / invoicing).
window.DATA = (function () {
  const avatarColor = (s) => {
    const colors = ['#2F62F0', '#6D5AE6', '#1F8A5B', '#B5740F', '#C8412F', '#0E8C9E'];
    let h = 0; for (let i = 0; i < s.length; i++) h = s.charCodeAt(i) + ((h << 5) - h);
    return colors[Math.abs(h) % colors.length];
  };
  const initials = (s) => s.split(' ').filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase();

  const customers = [
    { id: 'c1', name: 'Hayes Contracting Ltd', contact: 'Daniel Hayes', phone: '021 448 920', email: 'accounts@hayescontracting.co.nz', receivables: 4820.50, type: 'Business', since: 'Mar 2021', jobs: 14 },
    { id: 'c2', name: 'Mórné Property Group', contact: 'Sophie Tran', phone: '027 330 118', email: 'sophie@morne.co.nz', receivables: 0, type: 'Business', since: 'Jun 2022', jobs: 8 },
    { id: 'c3', name: 'Aroha Whitiora', contact: 'Aroha Whitiora', phone: '022 901 553', email: 'aroha.w@gmail.com', receivables: 312.00, type: 'Individual', since: 'Jan 2023', jobs: 3 },
    { id: 'c4', name: 'Coastal Fitouts', contact: 'Marcus Bell', phone: '021 776 040', email: 'marcus@coastalfitouts.nz', receivables: 9650.00, type: 'Business', since: 'Sep 2020', jobs: 22 },
    { id: 'c5', name: 'Te Awa Cafe', contact: 'Niko Patel', phone: '027 558 112', email: 'hello@teawacafe.co.nz', receivables: 0, type: 'Business', since: 'Nov 2023', jobs: 5 },
    { id: 'c6', name: 'Greenline Landscaping', contact: 'Ruth Connolly', phone: '021 204 887', email: 'ruth@greenline.nz', receivables: 1180.75, type: 'Business', since: 'Feb 2024', jobs: 6 },
  ];

  const invoices = [
    { id: 'INV-2041', customer: 'Hayes Contracting Ltd', amount: 2480.00, status: 'overdue', date: '12 May', due: '26 May', days: 9, items: [{ desc: 'Site labour — 16 hrs', qty: 16, rate: 95, amt: 1520 }, { desc: 'Materials — framing timber', qty: 1, rate: 640, amt: 640 }, { desc: 'Disposal fee', qty: 1, rate: 60, amt: 60 }] },
    { id: 'INV-2040', customer: 'Coastal Fitouts', amount: 6450.00, status: 'sent', date: '28 May', due: '11 Jun', days: 0, items: [{ desc: 'Cabinetry install', qty: 1, rate: 4200, amt: 4200 }, { desc: 'Benchtop — stone', qty: 1, rate: 1410, amt: 1410 }] },
    { id: 'INV-2039', customer: 'Te Awa Cafe', amount: 890.00, status: 'paid', date: '24 May', due: '07 Jun', days: 0, items: [{ desc: 'Espresso machine service', qty: 1, rate: 320, amt: 320 }, { desc: 'Plumbing — water line', qty: 1, rate: 454, amt: 454 }] },
    { id: 'INV-2038', customer: 'Aroha Whitiora', amount: 312.00, status: 'overdue', date: '03 May', due: '17 May', days: 18, items: [{ desc: 'Callout + diagnostic', qty: 1, rate: 271.30, amt: 271.30 }] },
    { id: 'INV-2037', customer: 'Greenline Landscaping', amount: 1180.75, status: 'sent', date: '27 May', due: '10 Jun', days: 0, items: [{ desc: 'Retaining wall — stage 1', qty: 1, rate: 1026.74, amt: 1026.74 }] },
    { id: 'INV-2036', customer: 'Mórné Property Group', amount: 3300.00, status: 'paid', date: '20 May', due: '03 Jun', days: 0, items: [{ desc: 'Maintenance retainer — May', qty: 1, rate: 2869.57, amt: 2869.57 }] },
    { id: 'INV-2035', customer: 'Hayes Contracting Ltd', amount: 540.00, status: 'draft', date: '29 May', due: '12 Jun', days: 0, items: [{ desc: 'Variation — extra outlet', qty: 1, rate: 469.57, amt: 469.57 }] },
  ];

  const jobs = [
    { id: 'JOB-318', title: 'Kitchen refit — Unit 4', customer: 'Coastal Fitouts', status: 'inprogress', assignee: 'Tom R.', due: 'Today', vehicle: null, progress: 60, tasks: '6 of 10 tasks' },
    { id: 'JOB-317', title: 'Brake & WOF — Hilux', customer: 'Hayes Contracting Ltd', status: 'inprogress', assignee: 'Mia K.', due: 'Tomorrow', vehicle: 'KLN294', progress: 30, tasks: '3 of 9 tasks' },
    { id: 'JOB-316', title: 'Deck rebuild', customer: 'Aroha Whitiora', status: 'pending', assignee: 'Unassigned', due: '6 Jun', vehicle: null, progress: 0, tasks: '0 of 7 tasks' },
    { id: 'JOB-315', title: 'Retaining wall — stage 2', customer: 'Greenline Landscaping', status: 'completed', assignee: 'Tom R.', due: 'Done', vehicle: null, progress: 100, tasks: '8 of 8 tasks' },
    { id: 'JOB-314', title: 'Cafe fitout snagging', customer: 'Te Awa Cafe', status: 'pending', assignee: 'Mia K.', due: '7 Jun', vehicle: null, progress: 0, tasks: '0 of 5 tasks' },
  ];

  const quotes = [
    { id: 'QTE-189', customer: 'Mórné Property Group', amount: 14200.00, status: 'sent', date: '26 May', expires: '9 Jun' },
    { id: 'QTE-188', customer: 'Coastal Fitouts', amount: 8650.00, status: 'accepted', date: '22 May', expires: '5 Jun' },
    { id: 'QTE-187', customer: 'Aroha Whitiora', amount: 3120.00, status: 'draft', date: '29 May', expires: '12 Jun' },
    { id: 'QTE-186', customer: 'Greenline Landscaping', amount: 5400.00, status: 'overdue', date: '8 May', expires: '22 May' },
  ];

  const activity = [
    { on: true, t: 'Payment received', s: 'Mórné Property Group · INV-2036', tm: '2h ago', amt: '+$3,300.00', cls: 'green' },
    { on: false, t: 'Invoice sent', s: 'Coastal Fitouts · INV-2040', tm: '5h ago', amt: '$6,450.00', cls: 'blue' },
    { on: false, t: 'Quote accepted', s: 'Coastal Fitouts · QTE-188', tm: 'Yesterday', amt: '$8,650.00', cls: 'green' },
    { on: false, t: 'Job completed', s: 'Greenline · JOB-315', tm: 'Yesterday', amt: '', cls: 'purple' },
  ];

  // module grid in More — [icon, label, screen route]
  const modules = [
    { icon: 'quote', label: 'Quotes', go: 'quotes' }, { icon: 'bookings', label: 'Bookings', go: 'bookings' },
    { icon: 'box', label: 'Inventory', go: 'inventory' }, { icon: 'car', label: 'Vehicles', go: 'vehicles' },
    { icon: 'receipt', label: 'Expenses', go: 'expenses' }, { icon: 'clock', label: 'Time', go: 'clock' },
    { icon: 'bank', label: 'Banking', go: 'banking' }, { icon: 'chart', label: 'Reports', go: 'reports' },
    { icon: 'building', label: 'Projects', go: 'projects' }, { icon: 'shield', label: 'Compliance', go: 'compliance' },
    { icon: 'card', label: 'POS', go: 'pos' }, { icon: 'user', label: 'Staff', go: 'staff' },
    { icon: 'box', label: 'Items', go: 'items' }, { icon: 'invoice', label: 'Recurring', go: 'recurring' },
    { icon: 'shield', label: 'Claims', go: 'claims' }, { icon: 'building', label: 'Construction', go: 'construction' },
    { icon: 'box', label: 'Assets', go: 'assets' }, { icon: 'shield', label: 'PPSR', go: 'ppsr' },
    { icon: 'dollar', label: 'Payroll', go: 'payroll' }, { icon: 'calendar', label: 'Leave', go: 'leave' },
    { icon: 'calendar', label: 'Roster', go: 'roster' }, { icon: 'sms', label: 'Messages', go: 'sms' },
    { icon: 'card', label: 'Payments', go: 'payments' }, { icon: 'receipt', label: 'GST', go: 'gst' },
    { icon: 'trend', label: 'Loyalty', go: 'loyalty' }, { icon: 'box', label: 'Purchase', go: 'purchaseOrders' },
  ];

  // ── id-keyed datasets for detail screens ──
  const vehicles = [
    { id: 'v1', rego: 'KLN294', mk: 'Toyota Hilux SR5', year: 2019, cust: 'Hayes Contracting Ltd', odo: '84,210 km', wof: 'Due 12 Jun', wofcls: 'warn', service: 'Due in 1,790 km', vin: 'JTNBE40K803218840', fuel: 'Diesel' },
    { id: 'v2', rego: 'BXR771', mk: 'Ford Ranger Wildtrak', year: 2021, cust: 'Coastal Fitouts', odo: '41,005 km', wof: 'Valid to Nov', wofcls: 'active', service: 'Due in 4,995 km', vin: '6FPAAAJG6MGB12345', fuel: 'Diesel' },
    { id: 'v3', rego: 'AGT102', mk: 'Mazda CX-5 GSX', year: 2018, cust: 'Aroha Whitiora', odo: '112,540 km', wof: 'Overdue 3d', wofcls: 'overdue', service: 'Overdue', vin: 'JM0KF4WLA00123456', fuel: 'Petrol' },
    { id: 'v4', rego: 'DPL558', mk: 'Isuzu D-Max LS', year: 2020, cust: 'Greenline Landscaping', odo: '62,880 km', wof: 'Valid to Aug', wofcls: 'active', service: 'Due in 2,120 km', vin: 'MPATFS85JKT001234', fuel: 'Diesel' },
  ];

  const items = [
    { id: 'i1', sku: 'TMB-90x45', name: 'Framing timber 90×45 H1.2', stock: 142, unit: 'lm', price: 4.20, cost: 2.85, low: false, cat: 'Timber', supplier: 'PlaceMakers' },
    { id: 'i2', sku: 'SCR-65', name: 'Decking screws 65mm (500)', stock: 8, unit: 'box', price: 28.50, cost: 18.10, low: true, cat: 'Fixings', supplier: 'Bunnings Trade' },
    { id: 'i3', sku: 'PNT-WHT', name: 'Resene Lumbersider white 10L', stock: 23, unit: 'ea', price: 119.00, cost: 78.00, low: false, cat: 'Paint', supplier: 'Resene' },
    { id: 'i4', sku: 'CON-20', name: 'Concrete mix 20kg', stock: 4, unit: 'bag', price: 12.90, cost: 7.40, low: true, cat: 'Aggregate', supplier: 'Carters' },
    { id: 'i5', sku: 'SIL-CLR', name: 'Silicone sealant clear', stock: 61, unit: 'ea', price: 9.80, cost: 4.95, low: false, cat: 'Sealants', supplier: 'Mico Plumbing' },
  ];

  const expenses = [
    { id: 'e1', v: 'Bunnings Warehouse', cat: 'Materials', amt: 284.50, gst: 37.11, date: '3 Jun', status: 'pending', method: 'Company card ••4821', job: 'JOB-318' },
    { id: 'e2', v: 'Z Energy', cat: 'Fuel', amt: 110.20, gst: 14.37, date: '3 Jun', status: 'paid', method: 'Fuel card', job: null },
    { id: 'e3', v: 'PlaceMakers', cat: 'Materials', amt: 642.00, gst: 83.74, date: '1 Jun', status: 'paid', method: 'Account', job: 'JOB-315' },
    { id: 'e4', v: 'Spark Mobile', cat: 'Phone', amt: 89.00, gst: 11.61, date: '1 Jun', status: 'paid', method: 'Direct debit', job: null },
    { id: 'e5', v: 'NZ Couriers', cat: 'Freight', amt: 38.40, gst: 5.01, date: '29 May', status: 'pending', method: 'Company card ••4821', job: null },
  ];

  const purchaseOrders = [
    { id: 'PO-0231', sup: 'PlaceMakers', amt: 2840.00, status: 'sent', date: '3 Jun', expected: '6 Jun', lines: [{ d: 'H3.2 framing 140×45', q: 80, u: 'lm', r: 6.40 }, { d: 'Galv bracket 90mm', q: 200, u: 'ea', r: 1.85 }, { d: 'Bugle screws 100mm', q: 12, u: 'box', r: 32.10 }] },
    { id: 'PO-0230', sup: 'Mico Plumbing', amt: 612.40, status: 'completed', date: '30 May', expected: '2 Jun', lines: [{ d: 'PEX pipe 20mm', q: 50, u: 'm', r: 4.10 }] },
    { id: 'PO-0229', sup: 'Bunnings Trade', amt: 388.90, status: 'draft', date: '29 May', expected: '—', lines: [{ d: 'Resene paint 10L', q: 3, u: 'ea', r: 119.00 }] },
    { id: 'PO-0228', sup: 'Carters', amt: 5210.00, status: 'pending', date: '27 May', expected: '5 Jun', lines: [{ d: 'Plasterboard 13mm', q: 60, u: 'sht', r: 28.50 }] },
  ];

  const projects = [
    { id: 'pr1', name: 'Coastal Apartments fitout', client: 'Coastal Fitouts', prog: 64, budget: 142000, spent: 91000, status: 'inprogress', start: '14 Apr', due: '29 Aug', team: ['Tom Rua', 'Mia Kemp', 'Sefa Lautele'] },
    { id: 'pr2', name: 'Te Awa cafe build', client: 'Te Awa Cafe', prog: 28, budget: 86000, spent: 24000, status: 'inprogress', start: '20 May', due: '12 Sep', team: ['Tom Rua', 'Mia Kemp'] },
    { id: 'pr3', name: 'Hayes depot extension', client: 'Hayes Contracting Ltd', prog: 100, budget: 54000, spent: 52800, status: 'completed', start: '2 Feb', due: '30 Apr', team: ['Tom Rua'] },
  ];

  const staff = [
    { id: 's1', name: 'Tom Rua', role: 'Senior technician', status: 'Clocked in', cls: 'active', empId: 'EMP-004', phone: '021 556 200', email: 'tom@hayes.co.nz', rate: 42, start: 'Jan 2020', skills: ['Carpentry', 'WOF', 'Site lead'] },
    { id: 's2', name: 'Mia Kemp', role: 'Technician', status: 'Clocked in', cls: 'active', empId: 'EMP-011', phone: '027 118 905', email: 'mia@hayes.co.nz', rate: 36, start: 'Aug 2021', skills: ['Electrical', 'Diagnostics'] },
    { id: 's3', name: 'Sefa Lautele', role: 'Apprentice', status: 'On break', cls: 'pending', empId: 'EMP-018', phone: '022 740 331', email: 'sefa@hayes.co.nz', rate: 24, start: 'Feb 2024', skills: ['General labour'] },
    { id: 's4', name: 'Ruby Nott', role: 'Front desk', status: 'Off today', cls: 'neutral', empId: 'EMP-007', phone: '021 909 442', email: 'ruby@hayes.co.nz', rate: 30, start: 'May 2022', skills: ['Admin', 'Scheduling'] },
    { id: 's5', name: 'Jordan Hayes', role: 'Owner', status: 'Admin', cls: 'info', empId: 'EMP-001', phone: '021 448 920', email: 'jordan@hayes.co.nz', rate: 0, start: 'Mar 2018', skills: ['Estimating', 'Management'] },
  ];

  const bookings = [
    { id: 'b1', t: '08:00', d: '45 min', cust: 'Hayes Contracting Ltd', svc: 'WOF inspection', status: 'completed', who: 'Mia Kemp', vehicle: 'KLN294', notes: 'Customer waiting on-site.' },
    { id: 'b2', t: '09:30', d: '2 hrs', cust: 'Coastal Fitouts', svc: 'On-site measure', status: 'inprogress', who: 'Tom Rua', vehicle: null, notes: 'Bring laser measure + samples.' },
    { id: 'b3', t: '11:00', d: '1 hr', cust: 'Aroha Whitiora', svc: 'Diagnostic', status: 'sent', who: 'Mia Kemp', vehicle: 'AGT102', notes: 'Intermittent fault, hard to reproduce.' },
    { id: 'b4', t: '13:30', d: '3 hrs', cust: 'Te Awa Cafe', svc: 'Espresso service', status: 'sent', who: 'Tom Rua', vehicle: null, notes: '' },
    { id: 'b5', t: '15:00', d: '30 min', cust: 'Greenline Landscaping', svc: 'Site walkthrough', status: 'pending', who: 'Unassigned', vehicle: null, notes: 'Quote follow-up.' },
  ];

  const recurring = [
    { id: 'r1', customer: 'Mórné Property Group', amount: 2869.57, every: 'Monthly', next: '1 Jul', status: 'active' },
    { id: 'r2', customer: 'Coastal Fitouts', amount: 450.00, every: 'Weekly', next: '9 Jun', status: 'active' },
    { id: 'r3', customer: 'Te Awa Cafe', amount: 180.00, every: 'Monthly', next: '15 Jun', status: 'pending' },
  ];

  const claims = [
    { id: 'CLM-204', cust: 'Aroha Whitiora', type: 'Insurance', amt: 4200.00, status: 'inprogress', date: '28 May', insurer: 'AA Insurance' },
    { id: 'CLM-203', cust: 'Hayes Contracting Ltd', type: 'Warranty', amt: 860.00, status: 'sent', date: '24 May', insurer: 'Manufacturer' },
    { id: 'CLM-202', cust: 'Coastal Fitouts', type: 'Insurance', amt: 12500.00, status: 'completed', date: '12 May', insurer: 'State' },
  ];

  const assets = [
    { id: 'a1', name: 'Hilti TE 70 rotary hammer', tag: 'AST-014', value: 1890, status: 'active', loc: 'Van — Tom R.' },
    { id: 'a2', name: 'Makita compound saw', tag: 'AST-022', value: 740, status: 'active', loc: 'Workshop' },
    { id: 'a3', name: 'Scaffold tower 6m', tag: 'AST-031', value: 2400, status: 'pending', loc: 'Coastal site' },
    { id: 'a4', name: 'Generator 5kVA', tag: 'AST-009', value: 1250, status: 'neutral', loc: 'Depot (idle)' },
  ];

  const payslips = [
    { id: 'p1', name: 'Tom Rua', period: '26 May – 1 Jun', gross: 1680.00, net: 1284.40, status: 'paid' },
    { id: 'p2', name: 'Mia Kemp', period: '26 May – 1 Jun', gross: 1440.00, net: 1118.60, status: 'paid' },
    { id: 'p3', name: 'Sefa Lautele', period: '26 May – 1 Jun', gross: 960.00, net: 802.10, status: 'pending' },
  ];

  const payments = [
    { id: 'pay1', customer: 'Mórné Property Group', inv: 'INV-2036', amt: 3300.00, method: 'Bank transfer', date: '3 Jun', status: 'completed' },
    { id: 'pay2', customer: 'Te Awa Cafe', inv: 'INV-2039', amt: 890.00, method: 'Card', date: '1 Jun', status: 'completed' },
    { id: 'pay3', customer: 'Coastal Fitouts', inv: 'INV-2040', amt: 6450.00, method: 'Bank transfer', date: '—', status: 'pending' },
  ];

  return {
    customers, invoices, jobs, quotes, activity, modules, avatarColor, initials,
    vehicles, items, expenses, purchaseOrders, projects, staff, bookings,
    recurring, claims, assets, payslips, payments,
  };
})();
