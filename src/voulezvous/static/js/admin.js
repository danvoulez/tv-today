const API = '';

// --- Navigation ---
document.querySelectorAll('.nav-item[data-page]').forEach(item => {
  item.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    item.classList.add('active');
    document.querySelectorAll('main > section').forEach(s => s.style.display = 'none');
    document.getElementById('page-' + item.dataset.page).style.display = '';
    if (item.dataset.page === 'assets') loadAssets();
    if (item.dataset.page === 'discovery') loadDiscovery();
    if (item.dataset.page === 'plans') loadPlans();
    if (item.dataset.page === 'dashboard') loadDashboard();
  });
});

// --- Toast ---
function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = 'toast toast-' + type;
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// --- Modal ---
function showModal(id) { document.getElementById(id).classList.add('show'); }
function closeModal(id) { document.getElementById(id).classList.remove('show'); }
function showAddAsset() { showModal('addAssetModal'); }
function showGeneratePlan() {
  const today = new Date().toISOString().split('T')[0];
  document.getElementById('planDate').value = today;
  showModal('genPlanModal');
}

// --- Helpers ---
function badge(text, color) {
  return `<span class="badge badge-${color}">${text}</span>`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function rightsBadge(status) {
  if (status === 'approved_for_stream') return badge('approved', 'green');
  if (status === 'blocked') return badge('blocked', 'red');
  return badge('pending', 'yellow');
}

function statusBadge(status) {
  const colors = {
    registered: 'grey', approved: 'green', blocked: 'red',
    downloaded: 'blue', prepared: 'pink', deleted: 'grey',
    draft: 'yellow', preparing: 'blue', ready: 'green',
    streaming: 'pink', completed: 'green', failed: 'red',
    queued: 'grey', skipped: 'yellow',
    found: 'blue', inspected: 'yellow', accepted: 'green', rejected: 'red',
    authorized_direct: 'green', authorized_official: 'green', metadata_only: 'yellow',
    unavailable: 'red', none: 'grey', blocked: 'red',
    pending_review: 'yellow', approved_for_stream: 'green',
  };
  return badge(status, colors[status] || 'grey');
}

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

// --- Dashboard ---
async function loadDashboard() {
  try {
    const [assets, streamStatus] = await Promise.all([
      api('GET', '/assets?limit=1000'),
      api('GET', '/stream/status'),
    ]);
    const videos = assets.filter(a => a.kind === 'video');
    const music = assets.filter(a => a.kind === 'music');
    const bumpers = assets.filter(a => a.kind === 'bumper');
    const approved = assets.filter(a => a.rights_status === 'approved_for_stream');
    const pending = assets.filter(a => a.rights_status === 'pending_review');

    document.getElementById('dashStats').innerHTML = `
      <div class="stat-card"><div class="stat-label">Total Assets</div><div class="stat-value">${assets.length}</div></div>
      <div class="stat-card"><div class="stat-label">Videos</div><div class="stat-value accent">${videos.length}</div></div>
      <div class="stat-card"><div class="stat-label">Music Sets</div><div class="stat-value">${music.length}</div></div>
      <div class="stat-card"><div class="stat-label">Bumpers</div><div class="stat-value">${bumpers.length}</div></div>
      <div class="stat-card"><div class="stat-label">Approved</div><div class="stat-value green">${approved.length}</div></div>
      <div class="stat-card"><div class="stat-label">Pending Review</div><div class="stat-value yellow">${pending.length}</div></div>
    `;

    document.getElementById('streamStatus').innerHTML = streamStatus.running
      ? '<span class="badge badge-pink">LIVE</span> Stream is running'
      : '<span class="badge badge-grey">OFF</span> Stream is stopped';

    const recent = assets.slice(0, 5);
    document.getElementById('recentAssetsTable').innerHTML = recent.length
      ? assetTable(recent, true)
      : '<div class="empty-state"><p>No assets yet — add some!</p></div>';
  } catch (e) {
    toast('Failed to load dashboard: ' + e.message, 'error');
  }
}

// --- Assets ---
async function loadAssets() {
  try {
    let params = [];
    const kind = document.getElementById('filterKind').value;
    const rights = document.getElementById('filterRights').value;
    if (kind) params.push('kind=' + kind);
    if (rights) params.push('rights_status=' + rights);
    const qs = params.length ? '?' + params.join('&') : '';
    const assets = await api('GET', '/assets' + qs);
    document.getElementById('assetsTable').innerHTML = assets.length
      ? assetTable(assets, false)
      : '<div class="empty-state"><p>No assets match your filters</p></div>';
  } catch (e) {
    toast('Failed to load assets: ' + e.message, 'error');
  }
}

function assetTable(assets, compact) {
  let html = '<table><thead><tr>';
  html += '<th>Title</th><th>Kind</th><th>Rights</th><th>Status</th>';
  if (!compact) html += '<th>Duration</th><th>Streamed</th>';
  html += '<th>Actions</th></tr></thead><tbody>';
  for (const a of assets) {
    html += '<tr>';
    html += `<td><strong>${a.title}</strong></td>`;
    html += `<td>${badge(a.kind, a.kind === 'video' ? 'blue' : a.kind === 'music' ? 'pink' : 'yellow')}</td>`;
    html += `<td>${rightsBadge(a.rights_status)}</td>`;
    html += `<td>${statusBadge(a.status)}</td>`;
    if (!compact) {
      html += `<td>${a.duration_sec ? Math.round(a.duration_sec / 60) + 'm' : '—'}</td>`;
      html += `<td>${a.times_streamed}×</td>`;
    }
    html += '<td>';
    if (a.rights_status === 'pending_review') {
      html += `<button class="btn btn-primary btn-sm" onclick="approveAsset('${a.id}')">Approve</button> `;
      html += `<button class="btn btn-danger btn-sm" onclick="blockAsset('${a.id}')">Block</button>`;
    } else if (a.rights_status === 'approved_for_stream') {
      html += `<button class="btn btn-danger btn-sm" onclick="blockAsset('${a.id}')">Block</button>`;
    } else {
      html += `<button class="btn btn-primary btn-sm" onclick="approveAsset('${a.id}')">Approve</button>`;
    }
    html += '</td></tr>';
  }
  html += '</tbody></table>';
  return html;
}

async function approveAsset(id) {
  try {
    await api('PATCH', '/assets/' + id, { rights_status: 'approved_for_stream' });
    toast('Asset approved');
    loadAssets();
    loadDashboard();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function blockAsset(id) {
  try {
    await api('PATCH', '/assets/' + id, { rights_status: 'blocked' });
    toast('Asset blocked');
    loadAssets();
    loadDashboard();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function createAsset() {
  try {
    const body = {
      kind: document.getElementById('newKind').value,
      title: document.getElementById('newTitle').value,
      source_type: document.getElementById('newSourceType').value,
    };
    const url = document.getElementById('newSourceUrl').value;
    const path = document.getElementById('newLocalPath').value;
    const dur = document.getElementById('newDuration').value;
    const notes = document.getElementById('newNotes').value;
    if (url) body.source_url = url;
    if (path) body.local_source_path = path;
    if (dur) body.duration_sec = parseInt(dur);
    if (notes) body.notes = notes;
    if (!body.title) { toast('Title is required', 'error'); return; }
    await api('POST', '/assets', body);
    toast('Asset created');
    closeModal('addAssetModal');
    document.getElementById('newTitle').value = '';
    document.getElementById('newSourceUrl').value = '';
    document.getElementById('newLocalPath').value = '';
    document.getElementById('newDuration').value = '';
    document.getElementById('newNotes').value = '';
    loadAssets();
    loadDashboard();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// --- Discovery ---
async function loadDiscovery() {
  await Promise.all([
    loadKeywords(),
    loadDomainPolicies(),
    loadDiscoveryRuns(),
    loadCandidates(),
  ]);
}

async function loadKeywords() {
  try {
    const keywords = await api('GET', '/keywords');
    document.getElementById('keywordCount').textContent = keywords.length;
    const active = keywords.filter(k => k.active);
    const inactive = keywords.length - active.length;
    let html = `
      <div class="mini-summary">
        <span>${active.length} active</span>
        <span>${inactive} paused</span>
      </div>
    `;
    if (!keywords.length) {
      html += '<div class="empty-state compact"><p>No keywords yet</p></div>';
    } else {
      html += '<div class="stack-list">';
      for (const k of keywords) {
        html += `
          <div class="stack-item">
            <div>
              <strong>${escapeHtml(k.keyword)}</strong>
              <div class="muted">${escapeHtml(k.category || 'uncategorized')} · weight ${k.weight}</div>
            </div>
            <div class="inline-actions">
              ${badge(k.include ? 'include' : 'exclude', k.include ? 'green' : 'red')}
              ${badge(k.active ? 'active' : 'paused', k.active ? 'blue' : 'grey')}
              <button class="btn btn-secondary btn-sm" onclick="toggleKeyword('${k.id}', ${!k.active})">${k.active ? 'Pause' : 'Enable'}</button>
            </div>
          </div>
        `;
      }
      html += '</div>';
    }
    document.getElementById('keywordsList').innerHTML = html;
  } catch (e) {
    toast('Failed to load keywords: ' + e.message, 'error');
  }
}

async function createKeyword() {
  const keyword = document.getElementById('keywordText').value.trim();
  if (!keyword) { toast('Keyword is required', 'error'); return; }
  const include = document.querySelector('input[name="keywordInclude"]:checked').value === 'true';
  const body = {
    keyword,
    category: document.getElementById('keywordCategory').value.trim() || null,
    weight: parseFloat(document.getElementById('keywordWeight').value || '1'),
    include,
    active: true,
  };
  try {
    await api('POST', '/keywords', body);
    toast(include ? 'Keyword added' : 'Exclude term added');
    document.getElementById('keywordText').value = '';
    document.getElementById('keywordCategory').value = '';
    document.getElementById('keywordWeight').value = '1';
    loadKeywords();
  } catch (e) {
    toast('Keyword error: ' + e.message, 'error');
  }
}

async function toggleKeyword(id, active) {
  try {
    await api('PATCH', '/keywords/' + id, { active });
    toast(active ? 'Keyword enabled' : 'Keyword paused');
    loadKeywords();
  } catch (e) {
    toast('Keyword error: ' + e.message, 'error');
  }
}

async function loadDomainPolicies() {
  try {
    const domains = await api('GET', '/domain-policies');
    document.getElementById('domainCount').textContent = domains.length;
    let html = '';
    if (!domains.length) {
      html = '<div class="empty-state compact"><p>No search domains yet</p></div>';
    } else {
      html = '<div class="stack-list">';
      for (const d of domains) {
        html += `
          <div class="stack-item">
            <div>
              <strong>${escapeHtml(d.domain)}</strong>
              <div class="muted">${escapeHtml(d.search_mode)} · ${d.max_pages_per_run} pages/run</div>
            </div>
            <div class="inline-actions">
              ${badge(d.is_enabled ? 'enabled' : 'off', d.is_enabled ? 'green' : 'grey')}
              <button class="btn btn-secondary btn-sm" onclick="toggleDomain('${d.id}', ${!d.is_enabled})">${d.is_enabled ? 'Disable' : 'Enable'}</button>
            </div>
          </div>
        `;
      }
      html += '</div>';
    }
    document.getElementById('domainsList').innerHTML = html;
  } catch (e) {
    toast('Failed to load domains: ' + e.message, 'error');
  }
}

function presetDomain(domain) {
  document.getElementById('domainName').value = domain;
}

async function createDomainPolicy() {
  const domain = document.getElementById('domainName').value.trim().replace(/^https?:\/\//, '').replace(/\/.*$/, '');
  if (!domain) { toast('Domain is required', 'error'); return; }
  const body = {
    domain,
    is_enabled: document.getElementById('domainEnabled').checked,
    search_mode: document.getElementById('domainMode').value,
    retrieval_modes: ['official_download', 'direct_url'],
    requires_playback_verification: false,
    max_pages_per_run: parseInt(document.getElementById('domainPages').value || '5'),
    notes: domain === 'archive.org' ? 'Public domain and downloadable media search' : 'Operator-approved discovery domain',
  };
  try {
    await api('POST', '/domain-policies', body);
    toast('Domain added');
    document.getElementById('domainName').value = '';
    loadDomainPolicies();
  } catch (e) {
    toast('Domain error: ' + e.message, 'error');
  }
}

async function toggleDomain(id, isEnabled) {
  try {
    await api('PATCH', '/domain-policies/' + id, { is_enabled: isEnabled });
    toast(isEnabled ? 'Domain enabled' : 'Domain disabled');
    loadDomainPolicies();
  } catch (e) {
    toast('Domain error: ' + e.message, 'error');
  }
}

async function runDiscovery(simulated) {
  try {
    toast(simulated ? 'Running test discovery...' : 'Running real discovery...');
    const run = await api('POST', '/discovery/run' + (simulated ? '?simulated=true' : ''));
    const found = run.output_summary?.total_found ?? 0;
    const accepted = run.output_summary?.total_accepted ?? 0;
    toast(`Discovery finished: ${found} found, ${accepted} downloadable`);
    await Promise.all([loadDiscoveryRuns(), loadCandidates()]);
  } catch (e) {
    toast('Discovery error: ' + e.message, 'error');
  }
}

async function loadDiscoveryRuns() {
  try {
    const runs = await api('GET', '/discovery/runs');
    if (!runs.length) {
      document.getElementById('discoveryRuns').innerHTML = '<div class="empty-state compact"><p>No discovery runs yet</p></div>';
      return;
    }
    let html = '<table><thead><tr><th>Date</th><th>Status</th><th>Keywords</th><th>Found</th><th>Downloadable</th></tr></thead><tbody>';
    for (const run of runs.slice(0, 8)) {
      const input = run.input_summary || {};
      const output = run.output_summary || {};
      html += `
        <tr>
          <td>${escapeHtml(run.run_date)}</td>
          <td>${statusBadge(run.status)}</td>
          <td>${escapeHtml((input.include_keywords || []).slice(0, 4).join(', '))}</td>
          <td>${output.total_found ?? 0}</td>
          <td>${output.total_accepted ?? 0}</td>
        </tr>
      `;
    }
    html += '</tbody></table>';
    document.getElementById('discoveryRuns').innerHTML = html;
  } catch (e) {
    toast('Failed to load discovery runs: ' + e.message, 'error');
  }
}

async function loadCandidates() {
  try {
    const params = ['limit=100'];
    const retrieval = document.getElementById('candidateRetrievalFilter')?.value;
    const rights = document.getElementById('candidateRightsFilter')?.value;
    if (retrieval) params.push('retrieval_status=' + encodeURIComponent(retrieval));
    if (rights) params.push('rights_status=' + encodeURIComponent(rights));
    const candidates = await api('GET', '/candidates?' + params.join('&'));
    document.getElementById('candidatesTable').innerHTML = candidates.length
      ? candidateTable(candidates)
      : '<div class="empty-state"><p>No candidates yet. Add keywords and run a search.</p></div>';
  } catch (e) {
    toast('Failed to load candidates: ' + e.message, 'error');
  }
}

function candidateTable(candidates) {
  let html = '<table><thead><tr><th>Title</th><th>Retrieval</th><th>Rights</th><th>Discovery</th><th>Duration</th><th>Actions</th></tr></thead><tbody>';
  for (const c of candidates) {
    const url = c.source_url || c.page_url || '';
    html += '<tr>';
    html += `
      <td>
        <strong>${escapeHtml(c.title)}</strong>
        <div class="muted url-text">${escapeHtml(url)}</div>
      </td>
    `;
    html += `<td>${statusBadge(c.retrieval_status)}</td>`;
    html += `<td>${rightsBadge(c.rights_status)}</td>`;
    html += `<td>${statusBadge(c.discovery_status)}</td>`;
    html += `<td>${c.duration_sec ? Math.round(c.duration_sec / 60) + 'm' : '-'}</td>`;
    html += '<td><div class="inline-actions">';
    if (c.rights_status !== 'approved_for_stream') {
      html += `<button class="btn btn-primary btn-sm" onclick="approveCandidate('${c.id}')">Approve</button>`;
    }
    html += `<button class="btn btn-secondary btn-sm" onclick="promoteCandidate('${c.id}')">Promote</button>`;
    html += `<button class="btn btn-danger btn-sm" onclick="blockCandidate('${c.id}')">Block</button>`;
    html += '</div></td></tr>';
  }
  html += '</tbody></table>';
  return html;
}

async function approveCandidate(id) {
  try {
    await approveCandidateRecord(id);
    toast('Candidate approved');
    loadCandidates();
  } catch (e) {
    toast('Candidate error: ' + e.message, 'error');
  }
}

async function approveCandidateRecord(id) {
  return api('PATCH', '/candidates/' + id, {
    rights_status: 'approved_for_stream',
    discovery_status: 'accepted',
  });
}

async function blockCandidate(id) {
  try {
    await api('PATCH', '/candidates/' + id, {
      rights_status: 'blocked',
      discovery_status: 'rejected',
      rejection_reason: 'Blocked by operator',
    });
    toast('Candidate blocked');
    loadCandidates();
  } catch (e) {
    toast('Candidate error: ' + e.message, 'error');
  }
}

async function promoteCandidate(id) {
  try {
    await approveCandidateRecord(id);
    const promoted = await api('POST', '/acq/candidates/' + id + '/promote');
    toast('Promoted to library: ' + promoted.title);
    await Promise.all([loadCandidates(), loadAssets(), loadDashboard()]);
  } catch (e) {
    toast('Promote error: ' + e.message, 'error');
  }
}

// --- Plans ---
async function loadPlans() {
  document.getElementById('plansContent').innerHTML =
    '<div class="empty-state"><p>Loading plans...</p></div>';
  try {
    const assets = await api('GET', '/assets?limit=1');
    // We don't have a list-plans endpoint yet, show generate UI
    document.getElementById('plansContent').innerHTML = `
      <div class="card">
        <div class="card-header">
          <span class="card-title">Plan Management</span>
          <button class="btn btn-primary btn-sm" onclick="showGeneratePlan()">+ Generate Plan</button>
        </div>
        <div id="planDetails">
          <div class="empty-state"><p>Generate a plan to get started, or enter a plan ID below</p></div>
          <div style="margin-top:16px;display:flex;gap:8px">
            <input class="form-control" id="planIdInput" placeholder="Plan ID (UUID)" style="max-width:400px">
            <button class="btn btn-secondary btn-sm" onclick="loadPlanById()">Load</button>
          </div>
        </div>
      </div>
      <div class="card" id="planDetailCard" style="display:none">
        <div class="card-header">
          <span class="card-title" id="planDetailTitle"></span>
          <div id="planActions"></div>
        </div>
        <div id="planInfo"></div>
        <div class="table-wrap" id="planItemsTable" style="margin-top:12px;max-height:400px;overflow-y:auto"></div>
      </div>
    `;
  } catch (e) {
    toast('Failed: ' + e.message, 'error');
  }
}

async function generatePlan() {
  try {
    const body = {
      plan_date: document.getElementById('planDate').value,
      hours: parseInt(document.getElementById('planHours').value),
      mix_music: document.getElementById('planMixMusic').checked,
    };
    if (!body.plan_date) { toast('Date is required', 'error'); return; }
    toast('Generating plan...');
    const plan = await api('POST', '/plans/generate', body);
    toast('Plan generated: ' + plan.items.length + ' items');
    closeModal('genPlanModal');
    showPlanDetail(plan);
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function loadPlanById() {
  const id = document.getElementById('planIdInput').value.trim();
  if (!id) { toast('Enter a plan ID', 'error'); return; }
  try {
    const plan = await api('GET', '/plans/' + id);
    showPlanDetail(plan);
  } catch (e) { toast('Plan not found: ' + e.message, 'error'); }
}

function showPlanDetail(plan) {
  const card = document.getElementById('planDetailCard');
  card.style.display = '';
  document.getElementById('planDetailTitle').textContent =
    'Plan: ' + plan.plan_date + ' — ' + plan.items.length + ' items';

  let actions = '';
  if (plan.status === 'draft') {
    actions = `<button class="btn btn-primary btn-sm" onclick="approvePlan('${plan.id}')">Approve Plan</button>`;
  }
  if (plan.status === 'approved') {
    actions = `<button class="btn btn-primary btn-sm" onclick="runPrep()">Run Prep</button>`;
  }
  document.getElementById('planActions').innerHTML = actions;

  const items = plan.items || [];
  const ready = items.filter(i => i.prep_status === 'ready').length;
  const queued = items.filter(i => i.prep_status === 'queued').length;
  const totalSec = items.reduce((s, i) => s + (i.target_duration_sec || 0), 0);

  document.getElementById('planInfo').innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-label">Status</div><div class="stat-value">${statusBadge(plan.status)}</div></div>
      <div class="stat-card"><div class="stat-label">Items</div><div class="stat-value">${items.length}</div></div>
      <div class="stat-card"><div class="stat-label">Duration</div><div class="stat-value">${(totalSec/3600).toFixed(1)}h</div></div>
      <div class="stat-card"><div class="stat-label">Prep Ready</div><div class="stat-value green">${ready}</div></div>
      <div class="stat-card"><div class="stat-label">Queued</div><div class="stat-value yellow">${queued}</div></div>
    </div>
  `;

  const shown = items.slice(0, 50);
  let html = '<table><thead><tr><th>#</th><th>Prep</th><th>Stream</th><th>Duration</th><th>Mix</th></tr></thead><tbody>';
  for (const it of shown) {
    html += '<tr>';
    html += `<td>${it.sequence_index}</td>`;
    html += `<td>${statusBadge(it.prep_status)}</td>`;
    html += `<td>${statusBadge(it.stream_status)}</td>`;
    html += `<td>${it.target_duration_sec ? it.target_duration_sec + 's' : '—'}</td>`;
    html += `<td>${it.mix_enabled ? '🎵' : '—'}</td>`;
    html += '</tr>';
  }
  if (items.length > 50) {
    html += `<tr><td colspan="5" style="text-align:center;color:var(--text2)">... and ${items.length - 50} more items</td></tr>`;
  }
  html += '</tbody></table>';
  document.getElementById('planItemsTable').innerHTML = html;
}

async function approvePlan(id) {
  try {
    const plan = await api('POST', '/plans/' + id + '/approve');
    toast('Plan approved');
    showPlanDetail(plan);
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function runPrep() {
  try {
    toast('Running prep cycle...');
    const res = await api('POST', '/prep/run-once');
    toast('Prep processed: ' + res.processed + ' items');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// --- Reports ---
async function loadReport() {
  const date = document.getElementById('reportDate').value;
  if (!date) { toast('Pick a date', 'error'); return; }
  try {
    const report = await api('GET', '/reports/' + date);
    renderReport(report);
  } catch (e) {
    document.getElementById('reportContent').innerHTML =
      '<div class="empty-state"><p>No report found for ' + date + '</p></div>';
  }
}

async function generateReport() {
  const date = document.getElementById('reportDate').value;
  if (!date) { toast('Pick a date', 'error'); return; }
  try {
    toast('Generating report...');
    await api('POST', '/reports/' + date + '/generate');
    toast('Report generated');
    loadReport();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

function renderReport(report) {
  const s = report.summary || {};
  let html = '<div class="stats-grid">';
  html += `<div class="stat-card"><div class="stat-label">Planned Hours</div><div class="stat-value">${s.planned_hours || 0}</div></div>`;
  html += `<div class="stat-card"><div class="stat-label">Streamed Hours</div><div class="stat-value accent">${s.streamed_hours || 0}</div></div>`;
  html += `<div class="stat-card"><div class="stat-label">Completed</div><div class="stat-value green">${s.completed_items || 0}</div></div>`;
  html += `<div class="stat-card"><div class="stat-label">Failed</div><div class="stat-value red">${s.failed_items || 0}</div></div>`;
  html += `<div class="stat-card"><div class="stat-label">Fallback Events</div><div class="stat-value yellow">${s.fallback_events || 0}</div></div>`;
  html += `<div class="stat-card"><div class="stat-label">Pending Review</div><div class="stat-value">${s.pending_review_assets || 0}</div></div>`;
  html += '</div>';

  if (s.suggestions && s.suggestions.length) {
    html += '<div class="card" style="margin-top:8px"><div class="card-title" style="margin-bottom:8px">Suggestions</div><ul style="padding-left:20px">';
    for (const sug of s.suggestions) {
      html += `<li style="margin-bottom:4px;color:var(--text2)">${sug}</li>`;
    }
    html += '</ul></div>';
  }

  if (report.markdown_text) {
    html += `<div class="card" style="margin-top:8px"><div class="card-title" style="margin-bottom:8px">Full Report</div><pre style="white-space:pre-wrap;color:var(--text2);font-size:12px">${report.markdown_text}</pre></div>`;
  }

  document.getElementById('reportContent').innerHTML = html;
}

// --- Stream ---
async function streamStart() {
  try {
    await api('POST', '/stream/start');
    toast('Stream start requested');
    loadDashboard();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function streamStop() {
  try {
    await api('POST', '/stream/stop');
    toast('Stream stop requested');
    loadDashboard();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// --- Init ---
loadDashboard();
