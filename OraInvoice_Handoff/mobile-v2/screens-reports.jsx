// screens-reports.jsx — parametrized Report detail sub-pages.
const { Ico: IR, money: mr, StatusBadge: SBr, Navbar: NBr, IconBtn: IBr } = window;

function BarMini({ data, accent = 'var(--accent)' }) {
  const max = Math.max(...data.map(d => d.v), 1);
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 132, padding: '4px 2px' }}>
      {data.map((d, i) => (
        <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 7 }}>
          <div style={{ width: '100%', height: `${Math.round((d.v / max) * 104)}px`, background: i === data.length - 1 ? accent : 'color-mix(in srgb, ' + accent + ' 26%, transparent)', borderRadius: '6px 6px 3px 3px', transition: 'height .3s' }}></div>
          <span className="mono" style={{ fontSize: 10.5, color: 'var(--muted-2)' }}>{d.l}</span>
        </div>
      ))}
    </div>
  );
}
function AreaMini({ pts, accent = 'var(--accent)' }) {
  const max = Math.max(...pts, 1), min = Math.min(...pts, 0), W = 320, H = 120;
  const xs = pts.map((p, i) => (i / (pts.length - 1)) * W);
  const ys = pts.map(p => H - ((p - min) / (max - min || 1)) * (H - 12) - 6);
  const line = xs.map((x, i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${ys[i].toFixed(1)}`).join(' ');
  const area = `${line} L${W} ${H} L0 ${H} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 120, display: 'block' }}>
      <defs><linearGradient id="rg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={accent} stopOpacity="0.22" /><stop offset="1" stopColor={accent} stopOpacity="0" /></linearGradient></defs>
      <path d={area} fill="url(#rg)" />
      <path d={line} fill="none" stroke={accent} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={xs[xs.length - 1]} cy={ys[ys.length - 1]} r="4" fill={accent} stroke="var(--card)" strokeWidth="2.5" />
    </svg>
  );
}

const REPORTS = {
  pl: { title: 'Profit & Loss', kpis: [['Revenue', '$58,420', 'up', '↑ 12%'], ['Expenses', '$40,000', 'down', '↑ 4%'], ['Net profit', '$18,420', 'up', '↑ 11%']], chart: { type: 'bar', data: [{ l: 'Feb', v: 12 }, { l: 'Mar', v: 15 }, { l: 'Apr', v: 14 }, { l: 'May', v: 17 }, { l: 'Jun', v: 18.4 }] }, table: { head: ['Account', 'Amount'], rows: [['Sales income', '$54,200'], ['Other income', '$4,220'], ['Materials', '−$21,400'], ['Wages', '−$14,100'], ['Overheads', '−$4,500'], ['Net profit', '$18,420']] } },
  balance: { title: 'Balance Sheet', kpis: [['Assets', '$214,800', 'up', ''], ['Liabilities', '$88,300', 'down', ''], ['Equity', '$126,500', 'up', '']], chart: { type: 'bar', data: [{ l: 'Cash', v: 42 }, { l: 'Recv', v: 31 }, { l: 'Stock', v: 18 }, { l: 'Fixed', v: 64 }, { l: 'Other', v: 12 }] }, table: { head: ['Line', 'Balance'], rows: [['Bank accounts', '$42,100'], ['Accounts receivable', '$31,200'], ['Inventory', '$18,400'], ['Fixed assets', '$123,100'], ['Accounts payable', '−$22,300'], ['GST payable', '−$4,210']] } },
  cashflow: { title: 'Cash Flow', kpis: [['Money in', '$61,200', 'up', ''], ['Money out', '$48,900', 'down', ''], ['Net', '$12,300', 'up', '↑ 6%']], chart: { type: 'area', pts: [8, 11, 9, 13, 12, 15, 12.3] }, table: { head: ['Activity', 'Net'], rows: [['Operating', '$15,400'], ['Investing', '−$4,200'], ['Financing', '$1,100'], ['Net movement', '$12,300']] } },
  revenue: { title: 'Revenue summary', kpis: [['This month', '$54,200', 'up', '↑ 9%'], ['Avg invoice', '$1,420', 'up', ''], ['Invoices', '38', 'up', '']], chart: { type: 'area', pts: [38, 41, 39, 46, 44, 50, 54.2] }, table: { head: ['Customer', 'Revenue'], rows: [['Coastal Fitouts', '$18,400'], ['Mórné Property Group', '$12,900'], ['Hayes Contracting', '$9,200'], ['Te Awa Cafe', '$6,800'], ['Others', '$6,900']] } },
  topservices: { title: 'Top services', kpis: [['Top earner', 'Labour', '', ''], ['Services', '12', '', ''], ['Avg margin', '46%', 'up', '']], chart: { type: 'bar', data: [{ l: 'Lab', v: 24 }, { l: 'Mat', v: 18 }, { l: 'WOF', v: 9 }, { l: 'Diag', v: 6 }, { l: 'Call', v: 4 }] }, table: { head: ['Service', 'Revenue'], rows: [['Standard labour', '$24,100'], ['Materials supply', '$18,300'], ['WOF inspection', '$9,400'], ['Diagnostics', '$6,200'], ['Callout fee', '$4,000']] } },
  aged: { title: 'Aged receivables', kpis: [['Outstanding', '$23,810', 'down', ''], ['Overdue', '$6,450', 'down', ''], ['Avg days', '21', '', '']], chart: { type: 'bar', data: [{ l: 'Cur', v: 14 }, { l: '1-30', v: 6 }, { l: '31-60', v: 3 }, { l: '61-90', v: 1 }, { l: '90+', v: 0.8 }] }, table: { head: ['Customer', 'Overdue'], rows: [['Coastal Fitouts', '$6,450'], ['Aroha Whitiora', '$4,200'], ['Te Awa Cafe', '$1,890'], ['Greenline', '$1,100']] } },
  gstreturn: { title: 'GST return', kpis: [['GST on sales', '$7,620', '', ''], ['GST on purchases', '$3,410', '', ''], ['Net GST', '$4,210', 'down', '']], chart: { type: 'bar', data: [{ l: 'Dec', v: 3.8 }, { l: 'Feb', v: 4.1 }, { l: 'Apr', v: 3.9 }, { l: 'Jun', v: 4.21 }] }, table: { head: ['GST101 box', 'Value'], rows: [['Box 5 — Total sales', '$58,420'], ['Box 8 — GST on sales', '$7,620'], ['Box 11 — GST on purchases', '$3,410'], ['Box 13 — Net GST', '$4,210']] } },
  taxposition: { title: 'Tax position', kpis: [['Provisional', '$9,800', '', ''], ['Paid YTD', '$6,400', 'up', ''], ['Remaining', '$3,400', 'down', '']], chart: { type: 'area', pts: [2, 4, 6.4, 6.4, 8, 9.8] }, table: { head: ['Instalment', 'Amount'], rows: [['28 Aug 2024', '$3,200 · paid'], ['15 Jan 2025', '$3,200 · paid'], ['7 May 2025', '$3,400 · due']] } },
};

function ReportDetailScreen({ nav, params }) {
  const r = REPORTS[params.id] || REPORTS.pl;
  const [range, setRange] = React.useState('30D');
  return (
    <div className="scr">
      <NBr title={r.title} onBack={nav.pop} backLabel="Reports" actions={<IBr name="download" label="Export" onClick={() => window.toast('Report exported')} />} />
      <div className="screen"><div className="pad scroll-pad stack">
        <div className="seg">{['7D', '30D', 'QTR', 'YR'].map(s => <button key={s} className={range === s ? 'on' : ''} onClick={() => setRange(s)}>{s}</button>)}</div>
        <div className="kpi-grid" style={{ gridTemplateColumns: r.kpis.length === 3 ? '1fr 1fr 1fr' : '1fr 1fr' }}>
          {r.kpis.map(([l, v, dir, delta], i) => (
            <div className="kpi" key={i} style={{ padding: '13px 12px' }}>
              <div className="klabel" style={{ fontSize: 10.5 }}>{l}</div>
              <div className="kval" style={{ fontSize: 16, marginTop: 5 }}>{v}</div>
              {delta && <div className={`kdelta ${dir}`} style={{ fontSize: 10.5 }}>{delta}</div>}
            </div>
          ))}
        </div>
        <div className="card card-pad">
          <div className="card-head" style={{ padding: 0, marginBottom: 10 }}><h2>Trend</h2><span className="muted mono" style={{ fontSize: 11 }}>{range}</span></div>
          {r.chart.type === 'bar' ? <BarMini data={r.chart.data} /> : <AreaMini pts={r.chart.pts} />}
        </div>
        <div className="card">
          <div className="card-head"><h2>Breakdown</h2></div>
          <div className="card-pad" style={{ paddingTop: 4 }}>
            {r.table.rows.map((row, i) => (
              <div className="meta-row" key={i} style={{ borderBottom: i < r.table.rows.length - 1 ? '1px solid var(--border)' : 'none' }}>
                <span className="k" style={{ color: i === r.table.rows.length - 1 ? 'var(--text)' : 'var(--muted)', fontWeight: i === r.table.rows.length - 1 ? 700 : 400 }}>{row[0]}</span>
                <span className="v mono">{row[1]}</span>
              </div>
            ))}
          </div>
        </div>
        <button className="btn btn-ghost" onClick={() => window.toast('Report exported')}><IR name="download" /> Export {r.title}</button>
      </div></div>
    </div>
  );
}

window.ReportDetailScreen = ReportDetailScreen;
window.REPORTS = REPORTS;
