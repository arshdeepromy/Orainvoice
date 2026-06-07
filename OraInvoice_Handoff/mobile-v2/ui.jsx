// ui.jsx — shared presentational helpers for the mobile prototype.
// Loaded after icons.jsx. Exposes helpers on window.

const money = (n, dp = 2) =>
  new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD', minimumFractionDigits: dp, maximumFractionDigits: dp }).format(n ?? 0);

const STATUS_LABEL = {
  paid: 'Paid', sent: 'Sent', overdue: 'Overdue', draft: 'Draft',
  inprogress: 'In progress', pending: 'Pending', completed: 'Completed', accepted: 'Accepted',
};

function StatusBadge({ status }) {
  return (
    <span className={`badge ${status}`}>
      <span className="bd"></span>{STATUS_LABEL[status] || status}
    </span>
  );
}

function Avatar({ name, square }) {
  const c = window.DATA.avatarColor(name);
  if (square) {
    return <div className="av" style={{ background: `color-mix(in srgb, ${c} 16%, transparent)`, color: c }}>{window.DATA.initials(name)}</div>;
  }
  return <div className="acircle" style={{ background: c }}>{window.DATA.initials(name)}</div>;
}

// Top app bar. big = large title block; otherwise compact bar with arrow-back + left title.
function Navbar({ title, sub, onBack, backLabel, actions, big }) {
  return (
    <div className={`navbar${big ? ' lg' : ''}`}>
      <div className="nav-row">
        {onBack && (
          <button className="nav-btn" onClick={onBack} aria-label="Back"><Ico name="back" /></button>
        )}
        {!big && <div className="nav-title lead" style={onBack ? { paddingLeft: 2 } : null}>{title}</div>}
        <div className="nav-actions">{actions}</div>
      </div>
      {big && (
        <div className="nav-big">
          <h1>{title}</h1>
          {sub && <div className="sub">{sub}</div>}
        </div>
      )}
    </div>
  );
}

function IconBtn({ name, onClick, badge, label }) {
  return (
    <button className="nav-btn" onClick={onClick} aria-label={label} style={{ position: 'relative' }}>
      <Ico name={name} />
      {badge && <span style={{ position: 'absolute', top: 7, right: 8, width: 8, height: 8, borderRadius: '50%', background: 'var(--danger)', border: '2px solid var(--card)' }}></span>}
    </button>
  );
}

window.money = money;
window.StatusBadge = StatusBadge;
window.Avatar = Avatar;
window.Navbar = Navbar;
window.IconBtn = IconBtn;
window.STATUS_LABEL = STATUS_LABEL;
