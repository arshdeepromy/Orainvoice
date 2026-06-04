/* ============================================================
   OraInvoice — Admin sub-navigation injector
   Renders the platform-admin tab row into every admin page.
   Usage: <div id="admin-nav" data-active="orgs"></div>
          <script src="admin-nav.js"></script>
   ============================================================ */
(function () {
  const TABS = [
    { id:'overview',   t:'Overview',        href:'AdminConsole.html' },
    { id:'orgs',       t:'Organisations',   href:'AdminOrganisations.html' },
    { id:'users',      t:'Users',           href:'AdminUserManagement.html' },
    { id:'analytics',  t:'Analytics',       href:'AdminAnalytics.html' },
    { id:'plans',      t:'Plans & billing', href:'AdminSubscriptionPlans.html' },
    { id:'flags',      t:'Feature flags',   href:'AdminFeatureFlags.html' },
    { id:'trades',     t:'Trade families',  href:'AdminTradeFamilies.html' },
    { id:'email',      t:'Email',           href:'AdminEmailProviders.html' },
    { id:'sms',        t:'SMS',             href:'AdminSmsProviders.html' },
    { id:'delivery',   t:'Email health',    href:'AdminEmailDeliveryHealth.html' },
    { id:'notif',      t:'Notifications',   href:'AdminNotificationManager.html' },
    { id:'integrations', t:'Integrations',  href:'AdminIntegrations.html' },
    { id:'xero',       t:'Xero',            href:'AdminXeroCredentials.html' },
    { id:'calendar',   t:'Calendar sync',   href:'AdminCalendarSync.html' },
    { id:'branding',   t:'Branding',        href:'AdminBranding.html' },
    { id:'pageeditor', t:'Page editor',     href:'PageEditorList.html' },
    { id:'security',   t:'Security',        href:'AdminSecurity.html' },
    { id:'branches',   t:'Branch overview', href:'AdminBranchOverview.html' },
    { id:'errors',     t:'Error log',       href:'AdminErrorLog.html' },
    { id:'audit',      t:'Audit log',       href:'AdminAuditLog.html' },
    { id:'ha',         t:'HA & replication',href:'AdminHAReplication.html' },
    { id:'migration',  t:'Migration',       href:'AdminMigration.html' },
    { id:'reports',    t:'Admin reports',   href:'AdminReports.html' },
    { id:'settings',   t:'Settings',        href:'AdminSettings.html' },
    { id:'profile',    t:'My profile',      href:'AdminProfile.html' },
  ];
  document.querySelectorAll('#admin-nav').forEach(host => {
    const active = host.getAttribute('data-active') || '';
    host.className = 'admin-tabs';
    host.innerHTML = TABS.map(x => `<a class="${x.id===active?'on':''}" href="${x.href}">${x.t}</a>`).join('');
  });
})();
