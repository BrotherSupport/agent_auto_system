// ── Constants ──────────────────────────────────────────────────────────────────

const ALL_TYPES = ['google_form_fill', 'web_scraper', 'hacker_news_digest', 'x_scraper', 'email_sender'];

const TYPE_META = {
  google_form_fill:   { chip: 'FORM',  cls: 'chip-form'  },
  web_scraper:        { chip: 'WEB',   cls: 'chip-web'   },
  hacker_news_digest: { chip: 'HN',    cls: 'chip-hn'    },
  x_scraper:          { chip: 'X',     cls: 'chip-x'     },
  email_sender:       { chip: 'EMAIL', cls: 'chip-email' },
};

const AUTO_CATALOG = {
  google_form_fill: {
    icon: '📋', name: 'Form Fill',
    desc: 'Automatically fill and submit any Google Form using AI agents that inspect the form structure and match your data to the correct fields.',
    inputs: [
      { name: 'company_name', type: 'str', desc: 'Company name to fill in' },
      { name: 'company_size', type: 'select', desc: 'Size tier of the company' },
      { name: 'ai_problem',   type: 'str', desc: 'AI use-case or problem description' },
    ],
    crew: 'FormFillerCrew', flow: 'FormFillFlow',
    agent: 'Form Agent', tools: ['Google Form Inspector', 'Google Form Submit'],
  },
  web_scraper: {
    icon: '🌐', name: 'Web Scraper',
    desc: 'Fetch any public web page and return a comprehensive structured summary — title, key points, headings, word count, and outbound links. No question needed.',
    inputs: [
      { name: 'url', type: 'str', desc: 'Full URL to scrape' },
    ],
    crew: 'WebScraperCrew', flow: 'WebScraperFlow',
    agent: 'Web Content Analyst', tools: ['Web Scraper'],
  },
  hacker_news_digest: {
    icon: '🔶', name: 'HN Digest',
    desc: 'Fetch the top N Hacker News stories, summarize each in one sentence, pick the story of the day, and identify recurring themes.',
    inputs: [
      { name: 'limit', type: 'int (1–10)', desc: 'Number of top stories to include' },
    ],
    crew: 'HNDigestCrew', flow: 'HNDigestFlow',
    agent: 'HN Analyst', tools: ['HN Top Stories'],
  },
  x_scraper: {
    icon: '✕', name: 'X Scraper',
    desc: 'Scrape recent public posts from any X (Twitter) profile, identify top content, themes, and produce a written summary.',
    inputs: [
      { name: 'username', type: 'str', desc: 'X handle (without the @ symbol)' },
      { name: 'limit',    type: 'int (1–10)', desc: 'Number of recent posts to fetch' },
    ],
    crew: 'XScraperCrew', flow: 'XScraperFlow',
    agent: 'X Analyst', tools: ['X Post Scraper'],
  },
  email_sender: {
    icon: '✉️', name: 'Email Sender',
    desc: 'Send an email to one or more recipients via Gmail SMTP. Supports HTML or plain-text bodies, CC, and multiple comma-separated addresses. No LLM — content is sent exactly as provided.',
    inputs: [
      { name: 'to',      type: 'str', desc: 'Recipient address(es), comma-separated' },
      { name: 'subject', type: 'str', desc: 'Email subject line' },
      { name: 'body',    type: 'str', desc: 'Email body — HTML or plain text' },
      { name: 'cc',      type: 'str (optional)', desc: 'CC addresses, comma-separated' },
    ],
    crew: 'EmailSenderCrew', flow: 'EmailSenderFlow',
    agent: 'Email Sender Agent', tools: ['Gmail Send'],
  },
};

// ── LLM provider → model map ──────────────────────────────────────────────────

const LLM_MODELS = {
  openai:    [['gpt-4o-mini', 'gpt-4o-mini (fast)'], ['gpt-4o', 'gpt-4o (smart)']],
  anthropic: [['claude-haiku-4-5-20251001', 'Haiku (fast)'], ['claude-sonnet-4-6', 'Sonnet (smart)']],
  gemini: [
    ['gemini/gemini-3.5-flash',       'Gemini 3.5 Flash'],
    ['gemini/gemini-3.1-flash-lite',   'Gemini 3.1 Flash-Lite'],
    ['gemini/gemini-3-flash-preview',  'Gemini 3 Flash (preview)'],
    ['gemini/gemini-2.5-flash',        'Gemini 2.5 Flash'],
    ['gemini/gemini-2.0-flash',        'Gemini 2.0 Flash'],
    ['gemini/gemini-2.0-flash-lite',   'Gemini 2.0 Flash-Lite'],
  ],
};

function updateModelOptions() {
  const provider = document.getElementById('llm-provider').value;
  const modelSel = document.getElementById('llm-model');
  const models = LLM_MODELS[provider] || LLM_MODELS.openai;
  modelSel.innerHTML = models.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
}

// ── State ─────────────────────────────────────────────────────────────────────

let activeEventSource  = null;
let sseStartTime       = null;
let cachedRuns         = [];
const elapsedTimers    = new Map();
let toastTimer         = null;
let selectedRunIds     = new Set();
let systemData         = null;
let systemCategory     = 'agents';
let confirmResolve     = null;
let runsOffset         = 0;
const RUNS_PAGE_SIZE   = 50;

// ── DOM refs ──────────────────────────────────────────────────────────────────

const modal           = document.getElementById('modal');
const runForm         = document.getElementById('run-form');
const progressPanel   = document.getElementById('progress-panel');
const progressLog     = document.getElementById('progress-log');
const progressJobName = document.getElementById('progress-job-name');
const progressPulse   = document.getElementById('progress-pulse');
const heroSection     = document.getElementById('hero-section');
const heroRestoreBtn  = document.getElementById('hero-restore');
const confirmModal    = document.getElementById('confirm-modal');

// ── Page routing ──────────────────────────────────────────────────────────────

function navigate(page) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.toggle('active', t.dataset.page === page));
  document.querySelectorAll('.page').forEach(p => {
    p.classList.toggle('active', p.id === `page-${page}`);
  });
  history.replaceState(null, '', `#${page}`);

  if (page === 'system')      loadSystemPage();
  if (page === 'automations') renderAutomationsPage();
  if (page === 'performance') loadPerformancePage();
}

document.getElementById('nav-tabs').addEventListener('click', (e) => {
  const tab = e.target.closest('.nav-tab');
  if (tab) navigate(tab.dataset.page);
});

// Navigate to the page in the hash on load, defaulting to dashboard
const initialPage = (location.hash.slice(1) || 'dashboard');
navigate(['dashboard','system','automations','performance'].includes(initialPage) ? initialPage : 'dashboard');

// ── Hero dismiss / restore ────────────────────────────────────────────────────

if (localStorage.getItem('hero-dismissed')) {
  heroSection.classList.add('hidden');
  heroRestoreBtn.classList.remove('hidden');
}

document.getElementById('hero-dismiss').addEventListener('click', () => {
  heroSection.classList.add('hidden');
  heroRestoreBtn.classList.remove('hidden');
  localStorage.setItem('hero-dismissed', '1');
});

heroRestoreBtn.addEventListener('click', () => {
  heroSection.classList.remove('hidden');
  heroRestoreBtn.classList.add('hidden');
  localStorage.removeItem('hero-dismissed');
  heroSection.scrollIntoView({ behavior: 'smooth' });
});

// ── Modal open/close ──────────────────────────────────────────────────────────

function openModal(preselect) {
  if (preselect) selectJobType(preselect);
  modal.classList.remove('hidden');
}
function closeModalFn() { modal.classList.add('hidden'); }

document.getElementById('new-run-btn').addEventListener('click', () => openModal());
document.getElementById('hero-run-btn').addEventListener('click', () => openModal());
document.getElementById('modal-close').addEventListener('click', closeModalFn);
document.getElementById('cancel-btn').addEventListener('click', closeModalFn);
document.getElementById('llm-provider').addEventListener('change', updateModelOptions);
modal.addEventListener('click', (e) => { if (e.target === modal) closeModalFn(); });

// ── Job type card selection ───────────────────────────────────────────────────

document.getElementById('type-grid').addEventListener('click', (e) => {
  const card = e.target.closest('.type-card');
  if (card) selectJobType(card.dataset.type);
});

function selectJobType(type) {
  document.querySelectorAll('.type-card')
    .forEach(c => c.classList.toggle('active', c.dataset.type === type));
  document.getElementById('job-type').value = type;
  ALL_TYPES.forEach(t =>
    document.getElementById(`fields-${t}`).classList.toggle('hidden', t !== type));
}

// ── Form submit ───────────────────────────────────────────────────────────────

runForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const jobType = document.getElementById('job-type').value;
  let payload, jobName;

  if (jobType === 'google_form_fill') {
    const company = document.getElementById('company-name').value.trim();
    if (!company) { showToast('Company name is required', 'error'); return; }
    payload = {
      company_name: company,
      company_size: document.getElementById('company-size').value,
      ai_problem:   document.getElementById('ai-problem').value.trim(),
    };
    jobName = `Form: ${company}`;
  } else if (jobType === 'web_scraper') {
    const url = document.getElementById('scrape-url').value.trim();
    if (!url) { showToast('URL is required', 'error'); return; }
    payload = { url };
    jobName = `Scrape: ${new URL(url).hostname}`;
  } else if (jobType === 'hacker_news_digest') {
    const limit = parseInt(document.getElementById('hn-limit').value, 10) || 5;
    payload = { limit };
    jobName = `HN Digest (top ${limit})`;
  } else if (jobType === 'x_scraper') {
    const username = document.getElementById('x-username').value.trim().replace(/^@/, '');
    if (!username) { showToast('X username is required', 'error'); return; }
    payload = { username, limit: parseInt(document.getElementById('x-limit').value, 10) || 5 };
    jobName = `X: @${username}`;

  } else if (jobType === 'email_sender') {
    const to = document.getElementById('email-to').value.trim();
    const subject = document.getElementById('email-subject').value.trim();
    const body = document.getElementById('email-body').value.trim();
    if (!to)      { showToast('Recipients are required', 'error'); return; }
    if (!subject) { showToast('Subject is required', 'error'); return; }
    if (!body)    { showToast('Body is required', 'error'); return; }
    const cc = document.getElementById('email-cc').value.trim();
    payload = { to, subject, body, ...(cc ? { cc } : {}) };
    const recipientCount = to.split(',').filter(e => e.trim()).length;
    jobName = `Email: ${subject} → ${recipientCount} recipient${recipientCount !== 1 ? 's' : ''}`;
  }

  // Attach LLM config to payload
  payload.llm_provider = document.getElementById('llm-provider').value;
  payload.llm_model    = document.getElementById('llm-model').value;

  closeModalFn();
  runForm.reset();
  selectJobType('google_form_fill');
  updateModelOptions();
  navigate('dashboard');
  await triggerRun(jobType, jobName, payload);
});

// ── Trigger a new run ─────────────────────────────────────────────────────────

async function triggerRun(jobType, jobName, payload) {
  try {
    const jobResp = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: jobName, job_type: jobType, payload }),
    });
    if (!jobResp.ok) throw new Error('Failed to create job');
    const job = await jobResp.json();

    const runResp = await fetch(`/api/jobs/${job.id}/run`, { method: 'POST' });
    if (!runResp.ok) throw new Error('Failed to trigger run');
    const { run_id } = await runResp.json();

    showProgress(jobName);
    await loadHistory();
    scrollToRun(run_id);
    document.getElementById(`detail-${run_id}`)?.classList.remove('hidden');
    startSSE(run_id);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// ── Re-run ────────────────────────────────────────────────────────────────────

async function rerun(jobId) {
  try {
    const runResp = await fetch(`/api/jobs/${jobId}/run`, { method: 'POST' });
    if (!runResp.ok) throw new Error('Re-run failed');
    const { run_id } = await runResp.json();
    const cached = cachedRuns.find(r => r.job_id === jobId);
    const jobName = cached?.job_name ?? `job ${jobId}`;
    showProgress(jobName);
    await loadHistory();
    scrollToRun(run_id);
    document.getElementById(`detail-${run_id}`)?.classList.remove('hidden');
    startSSE(run_id);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// ── Delete single run ─────────────────────────────────────────────────────────

async function deleteRun(runId) {
  const run = cachedRuns.find(r => r.id === runId);
  if (run?.status === 'pending' || run?.status === 'running') {
    showToast('Cannot delete an active run', 'error');
    return;
  }
  try {
    const resp = await fetch(`/api/runs/${runId}`, { method: 'DELETE' });
    if (resp.status === 409) { showToast('Cannot delete an active run', 'error'); return; }
    if (!resp.ok) throw new Error('Delete failed');
    selectedRunIds.delete(runId);
    updateBulkActionButtons();
    await loadHistory();
    showToast('Run deleted', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// ── Bulk delete ───────────────────────────────────────────────────────────────

document.getElementById('delete-selected-btn').addEventListener('click', async () => {
  if (!selectedRunIds.size) return;
  const ok = await confirmDialog('Delete Selected Runs', `Delete ${selectedRunIds.size} selected run(s)? Active runs will be skipped.`);
  if (!ok) return;
  try {
    const ids = [...selectedRunIds].join(',');
    const resp = await fetch(`/api/runs?ids=${ids}`, { method: 'DELETE' });
    if (!resp.ok) throw new Error('Bulk delete failed');
    const { deleted } = await resp.json();
    selectedRunIds.clear();
    updateBulkActionButtons();
    await loadHistory();
    showToast(`Deleted ${deleted} run(s)`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

document.getElementById('delete-all-btn').addEventListener('click', async () => {
  const completedCount = cachedRuns.filter(r => r.status !== 'pending' && r.status !== 'running').length;
  if (!completedCount) { showToast('No completed runs to delete', 'error'); return; }
  const ok = await confirmDialog('Delete All Runs', `Delete all ${completedCount} completed run(s)? Active runs will be kept.`);
  if (!ok) return;
  try {
    const resp = await fetch('/api/runs?delete_all=true', { method: 'DELETE' });
    if (!resp.ok) throw new Error('Delete all failed');
    const { deleted } = await resp.json();
    selectedRunIds.clear();
    updateBulkActionButtons();
    await loadHistory();
    showToast(`Deleted ${deleted} run(s)`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// ── Confirm dialog ────────────────────────────────────────────────────────────

function confirmDialog(title, msg) {
  return new Promise((resolve) => {
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-msg').textContent = msg;
    confirmModal.classList.remove('hidden');
    confirmResolve = resolve;
  });
}

document.getElementById('confirm-ok').addEventListener('click', () => {
  confirmModal.classList.add('hidden');
  confirmResolve?.(true);
});
document.getElementById('confirm-cancel').addEventListener('click', () => {
  confirmModal.classList.add('hidden');
  confirmResolve?.(false);
});
document.getElementById('confirm-close').addEventListener('click', () => {
  confirmModal.classList.add('hidden');
  confirmResolve?.(false);
});
confirmModal.addEventListener('click', (e) => {
  if (e.target === confirmModal) { confirmModal.classList.add('hidden'); confirmResolve?.(false); }
});

// ── Select all checkbox ───────────────────────────────────────────────────────

document.getElementById('select-all-cb').addEventListener('change', (e) => {
  const checked = e.target.checked;
  cachedRuns.forEach(run => {
    if (run.status !== 'pending' && run.status !== 'running') {
      if (checked) selectedRunIds.add(run.id);
      else selectedRunIds.delete(run.id);
    }
  });
  document.querySelectorAll('.run-cb').forEach(cb => {
    const run = cachedRuns.find(r => r.id === parseInt(cb.dataset.runId, 10));
    if (run && run.status !== 'pending' && run.status !== 'running') cb.checked = checked;
  });
  updateBulkActionButtons();
});

function updateBulkActionButtons() {
  const btn = document.getElementById('delete-selected-btn');
  if (selectedRunIds.size > 0) {
    btn.classList.remove('hidden');
    btn.textContent = `Delete Selected (${selectedRunIds.size})`;
  } else {
    btn.classList.add('hidden');
  }
}

// ── Table event delegation ────────────────────────────────────────────────────

document.getElementById('history-tbody').addEventListener('click', (e) => {
  // Checkbox toggle
  const cb = e.target.closest('.run-cb');
  if (cb) {
    const runId = parseInt(cb.dataset.runId, 10);
    if (cb.checked) selectedRunIds.add(runId);
    else selectedRunIds.delete(runId);
    const row = document.querySelector(`tr.data-row[data-run-id="${runId}"]`);
    row?.classList.toggle('selected', cb.checked);
    updateBulkActionButtons();
    return;
  }

  const actionEl = e.target.closest('[data-action]');
  if (actionEl) {
    const action = actionEl.dataset.action;
    const runId  = parseInt(actionEl.dataset.runId, 10);
    const jobId  = parseInt(actionEl.dataset.jobId, 10);
    const tab    = actionEl.dataset.tab;
    switch (action) {
      case 'tab':    switchTab(runId, tab); return;
      case 'rerun':  rerun(jobId);          return;
      case 'delete': deleteRun(runId);      return;
      case 'copy':   copyResult(runId);     return;
    }
    return;
  }

  // Guard: clicks inside an open detail pane must not toggle the parent row.
  if (e.target.closest('tr.detail-row')) return;
  const row = e.target.closest('tr.data-row');
  if (row) toggleDetail(parseInt(row.dataset.runId, 10));
});

// ── Scroll to & highlight new row ─────────────────────────────────────────────

function scrollToRun(runId) {
  setTimeout(() => {
    const row = document.querySelector(`tr[data-run-id="${runId}"]`);
    if (!row) return;
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.classList.add('row-highlight');
    setTimeout(() => row.classList.remove('row-highlight'), 2000);
  }, 120);
}

// ── Progress panel ────────────────────────────────────────────────────────────

function showProgress(jobName) {
  progressLog.innerHTML = '';
  progressJobName.textContent = jobName;
  progressPulse.style.display = '';
  progressPanel.classList.remove('hidden');
}

function finishProgress(status, durationSecs) {
  progressPulse.style.display = 'none';
  const ok = status === 'success';
  const color = ok ? 'var(--green)' : 'var(--red)';
  progressJobName.innerHTML = `<span style="color:${color}">${ok ? '✓ Completed' : '✗ Failed'} in ${durationSecs}s</span>`;
  setTimeout(hideProgress, 3000);
}

function hideProgress() { progressPanel.classList.add('hidden'); }

function appendProgressEntry(entry) {
  const li = document.createElement('li');
  li.innerHTML = `<span class="log-ts">${escHtml(entry.ts)}</span>${escHtml(entry.msg)}`;
  progressLog.appendChild(li);
  progressLog.scrollTop = progressLog.scrollHeight;
}

// ── Server-Sent Events ────────────────────────────────────────────────────────

function startSSE(runId) {
  if (activeEventSource) activeEventSource.close();
  sseStartTime = Date.now();
  activeEventSource = new EventSource(`/api/runs/${runId}/stream`);

  activeEventSource.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.new_logs) data.new_logs.forEach(appendProgressEntry);
    updateRow(runId, data);

    if (data.status === 'success' || data.status === 'failed') {
      activeEventSource.close();
      activeEventSource = null;
      finishProgress(data.status, ((Date.now() - sseStartTime) / 1000).toFixed(1));
    }
  };

  activeEventSource.onerror = () => {
    activeEventSource.close();
    activeEventSource = null;
    hideProgress();
  };
}

function updateRow(runId, data) {
  const row = document.querySelector(`tr[data-run-id="${runId}"]`);
  if (!row) { loadHistory(); return; }

  const badge = row.querySelector('.badge');
  if (badge) { badge.textContent = data.status; badge.className = `badge badge-${data.status}`; }

  if (data.result) {
    const cell = row.querySelector('.result-cell');
    if (cell) cell.textContent = extractResultText(data.result);
  }

  if (data.status === 'success' || data.status === 'failed') {
    stopElapsedTimer(runId);
    loadHistory();
  }
}

// ── History table ─────────────────────────────────────────────────────────────

async function loadHistory(reset = true) {
  try {
    if (reset) runsOffset = 0;
    const resp = await fetch(`/api/runs?limit=${RUNS_PAGE_SIZE}&offset=${runsOffset}`);
    if (!resp.ok) return;
    const newRuns = await resp.json();
    const allRuns = reset ? newRuns : [...cachedRuns, ...newRuns];
    renderHistory(allRuns, newRuns.length === RUNS_PAGE_SIZE);
  } catch (_) {}
}

function renderHistory(runs, hasMore = false) {
  cachedRuns = runs;
  const tbody = document.getElementById('history-tbody');

  // Snapshot which detail rows are open and which tab is active before wiping the DOM.
  const openState = new Map(); // runId → active pane name ('result' | 'log')
  tbody.querySelectorAll('.detail-row:not(.hidden)').forEach(el => {
    const runId = parseInt(el.id.replace('detail-', ''), 10);
    const active = el.querySelector('.detail-pane.active');
    openState.set(runId, active?.dataset.pane ?? 'result');
  });

  if (!runs.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No runs yet. Click "New Run" to get started.</td></tr>';
    document.getElementById('select-all-cb').checked = false;
    return;
  }

  tbody.innerHTML = runs.map((run) => {
    const meta     = TYPE_META[run.job_type] || { chip: run.job_type?.toUpperCase() || '?', cls: 'chip-unknown' };
    const isActive = run.status === 'running' || run.status === 'pending';
    const duration = run.finished_at
      ? `${((new Date(run.finished_at) - new Date(run.started_at)) / 1000).toFixed(1)}s`
      : '—';
    const durCell  = isActive
      ? `<span class="elapsed-timer" data-started="${run.started_at}">…</span>`
      : duration;
    const started  = new Date(run.started_at).toLocaleString();

    let resultText = '', resultJson = null;
    if (run.result) {
      try { resultJson = JSON.parse(run.result); resultText = extractResultText(resultJson); }
      catch (_) { resultText = run.result; }
    }

    const totalTok = (run.tokens_in || 0) + (run.tokens_out || 0);
    const provider = run.llm_provider || '';
    const llmBadge = provider
      ? `<span class="llm-badge llm-${provider}">${provider === 'anthropic' ? 'claude' : provider}</span>`
      : '';
    const costStr = run.cost_usd > 0
      ? (run.cost_usd < 0.0001 ? '<$0.0001' : '$' + run.cost_usd.toFixed(4))
      : '';
    const costBadge = costStr ? `<span class="cost-badge">${costStr}</span>` : '';
    const retryBadge = run.retry_count > 0 ? `<span class="retry-badge">${run.retry_count}↺</span>` : '';

    let logJson = null;
    if (run.log) { try { logJson = JSON.parse(run.log); } catch (_) {} }

    const logTab = logJson
      ? `<button class="detail-tab" data-action="tab" data-tab="log" data-run-id="${run.id}">Log (${logJson.length})</button>`
      : '';
    const usageTab = totalTok > 0
      ? `<button class="detail-tab" data-action="tab" data-tab="usage" data-run-id="${run.id}">Usage</button>`
      : '';
    const logPane = logJson
      ? `<div class="detail-pane" id="pane-log-${run.id}" data-pane="log">
           <ul class="log-list">${logJson.map(e =>
             `<li><span class="log-ts">${escHtml(e.ts)}</span>${escHtml(e.msg)}</li>`
           ).join('')}</ul>
         </div>`
      : '';
    const usagePane = totalTok > 0
      ? `<div class="detail-pane" id="pane-usage-${run.id}" data-pane="usage">
           <ul class="log-list" style="column-gap:2rem;display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr))">
             <li><span class="log-ts">provider</span>${escHtml(run.llm_provider || '—')}</li>
             <li><span class="log-ts">model</span>${escHtml(run.llm_model || '—')}</li>
             <li><span class="log-ts">tokens in</span>${(run.tokens_in || 0).toLocaleString()}</li>
             <li><span class="log-ts">tokens out</span>${(run.tokens_out || 0).toLocaleString()}</li>
             <li><span class="log-ts">total tokens</span>${totalTok.toLocaleString()}</li>
             <li><span class="log-ts">cost</span>${costStr || '$0.000000'}</li>
             <li><span class="log-ts">retries</span>${run.retry_count || 0}</li>
           </ul>
         </div>`
      : '';

    const deleteDis  = isActive ? 'disabled title="Cannot delete an active run"' : 'title="Delete run"';
    const rerunLabel = run.status === 'failed' ? '↺ Retry' : '↺';
    const rerunCls   = run.status === 'failed' ? 'btn-rerun btn-retry' : 'btn-rerun';
    const cbChecked  = selectedRunIds.has(run.id) ? 'checked' : '';
    const cbDis      = isActive ? 'disabled' : '';
    const rowSel     = selectedRunIds.has(run.id) ? 'selected' : '';

    return `
      <tr class="data-row ${rowSel}" data-run-id="${run.id}">
        <td class="td-check" onclick="event.stopPropagation()">
          <input type="checkbox" class="run-cb" data-run-id="${run.id}" ${cbChecked} ${cbDis} />
        </td>
        <td style="color:var(--text-muted)">#${run.id}</td>
        <td>
          <div class="job-cell">
            <span class="job-name-text">${escHtml(run.job_name)}</span>
            <div style="display:flex;gap:0.3rem;align-items:center;flex-wrap:wrap">
              <span class="type-chip ${meta.cls}">${meta.chip}</span>
              ${llmBadge}${retryBadge}
            </div>
          </div>
        </td>
        <td><span class="badge badge-${run.status}">${run.status}</span></td>
        <td style="color:var(--text-muted);font-size:0.8rem">${started}</td>
        <td style="color:var(--text-muted)">${durCell}</td>
        <td class="result-cell" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.82rem;color:var(--text-muted)">
          ${escHtml(resultText)}
          ${costBadge ? `<div style="margin-top:0.2rem">${costBadge}${totalTok > 0 ? `<span class="cost-badge" style="margin-left:0.35rem">${totalTok.toLocaleString()}tok</span>` : ''}</div>` : ''}
        </td>
        <td style="padding:0.65rem 0.5rem">
          <div class="row-actions">
            <button class="${rerunCls}" data-action="rerun" data-job-id="${run.job_id}" data-run-id="${run.id}" title="Re-run">${rerunLabel}</button>
            <button class="btn-delete" data-action="delete" data-run-id="${run.id}" ${deleteDis}>🗑</button>
          </div>
        </td>
      </tr>
      <tr class="detail-row hidden" id="detail-${run.id}">
        <td colspan="8" style="padding:0">
          <div class="detail-tabs">
            <button class="detail-tab active" data-action="tab" data-tab="result" data-run-id="${run.id}">Result</button>
            ${logTab}
            ${usageTab}
          </div>
          <div class="detail-pane active" id="pane-result-${run.id}" data-pane="result">
            <div class="pane-toolbar">
              <button class="btn-copy" data-action="copy" data-run-id="${run.id}">Copy JSON</button>
            </div>
            <pre>${escHtml(resultJson ? JSON.stringify(resultJson, null, 2) : (run.result || ''))}</pre>
          </div>
          ${logPane}
          ${usagePane}
        </td>
      </tr>`;
  }).join('');

  // Restore previously open detail rows (preserves state across periodic refreshes).
  openState.forEach((tab, runId) => {
    const detailRow = document.getElementById(`detail-${runId}`);
    if (detailRow) {
      detailRow.classList.remove('hidden');
      switchTab(runId, tab);
    }
  });

  document.getElementById('load-more-btn')?.classList.toggle('hidden', !hasMore);
  initElapsedTimers();
  updateBulkActionButtons();
}

function toggleDetail(runId) {
  document.getElementById(`detail-${runId}`)?.classList.toggle('hidden');
}

function switchTab(runId, tab) {
  document.querySelectorAll(`#detail-${runId} .detail-tab`)
    .forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll(`#detail-${runId} .detail-pane`)
    .forEach(p => p.classList.toggle('active', p.dataset.pane === tab));
}

// ── Elapsed timers ────────────────────────────────────────────────────────────

function initElapsedTimers() {
  elapsedTimers.forEach((id, runId) => {
    if (!document.querySelector(`tr[data-run-id="${runId}"] .elapsed-timer`)) {
      clearInterval(id); elapsedTimers.delete(runId);
    }
  });
  document.querySelectorAll('.elapsed-timer').forEach(el => {
    const runId = parseInt(el.closest('tr')?.dataset.runId, 10);
    if (!runId || elapsedTimers.has(runId)) return;
    const startedAt = new Date(el.dataset.started);
    const tick = () => { el.textContent = `${Math.floor((Date.now() - startedAt) / 1000)}s…`; };
    tick();
    elapsedTimers.set(runId, setInterval(tick, 1000));
  });
}

function stopElapsedTimer(runId) {
  const id = elapsedTimers.get(runId);
  if (id !== undefined) { clearInterval(id); elapsedTimers.delete(runId); }
}

// ── Copy result JSON ──────────────────────────────────────────────────────────

async function copyResult(runId) {
  const pre = document.querySelector(`#pane-result-${runId} pre`);
  if (!pre) return;
  try {
    await navigator.clipboard.writeText(pre.textContent);
    showToast('Copied to clipboard', 'success');
  } catch (_) {
    showToast('Copy failed — select manually', 'error');
  }
}

// ── System page ───────────────────────────────────────────────────────────────

async function loadSystemPage() {
  if (systemData) { renderSystemPage(); return; }
  document.getElementById('system-content').innerHTML = '<div class="loading-state">Loading system catalog…</div>';
  try {
    const resp = await fetch('/api/system');
    if (!resp.ok) throw new Error('Failed to load system data');
    systemData = await resp.json();
    renderSystemPage();
  } catch (err) {
    document.getElementById('system-content').innerHTML = `<div class="loading-state" style="color:var(--red)">Error: ${escHtml(err.message)}</div>`;
  }
}

document.getElementById('cat-tabs').addEventListener('click', (e) => {
  const tab = e.target.closest('.cat-tab');
  if (!tab) return;
  document.querySelectorAll('.cat-tab').forEach(t => t.classList.toggle('active', t === tab));
  systemCategory = tab.dataset.cat;
  renderSystemPage();
});

function renderSystemPage() {
  if (!systemData) return;
  const items = systemData[systemCategory] || [];
  const container = document.getElementById('system-content');

  if (!items.length) {
    container.innerHTML = '<div class="loading-state">No items found.</div>';
    return;
  }

  container.innerHTML = `<div class="system-cards">${items.map(item => renderSysCard(item)).join('')}</div>`;

  // Wire up card toggles
  container.querySelectorAll('.sys-card-header').forEach(hdr => {
    hdr.addEventListener('click', () => {
      hdr.closest('.sys-card').classList.toggle('open');
    });
  });

  // Wire up source code toggles
  container.querySelectorAll('.source-toggle').forEach(tog => {
    tog.addEventListener('click', (e) => {
      e.stopPropagation();
      const body = tog.nextElementSibling;
      const isOpen = body.classList.toggle('open');
      tog.querySelector('.source-arrow').textContent = isOpen ? '▲' : '▼';
    });
  });
}

function renderSysCard(item) {
  const cat = systemCategory;

  if (cat === 'agents') {
    return `
    <div class="sys-card">
      <div class="sys-card-header">
        <div class="sys-card-title">
          <span class="sys-card-name">${escHtml(item.name)}</span>
          <span class="sys-card-badge">${escHtml(item.job_type || '')}</span>
        </div>
        <span class="sys-card-toggle">▼</span>
      </div>
      <div class="sys-card-body">
        <div class="sys-card-meta">
          <div class="meta-item"><div class="meta-label">Role</div><div class="meta-value">${escHtml(item.role)}</div></div>
          <div class="meta-item"><div class="meta-label">Goal</div><div class="meta-value">${escHtml(item.goal)}</div></div>
          <div class="meta-item" style="grid-column:1/-1"><div class="meta-label">Backstory</div><div class="meta-value">${escHtml(item.backstory)}</div></div>
          <div class="meta-item">
            <div class="meta-label">Tools</div>
            <div class="meta-tags">${(item.tools||[]).map(t => `<span class="meta-tag">${escHtml(t)}</span>`).join('')}</div>
          </div>
          <div class="meta-item"><div class="meta-label">Crew</div><div class="meta-value mono">${escHtml(item.crew)}</div></div>
          <div class="meta-item"><div class="meta-label">Task</div><div class="meta-value mono">${escHtml(item.task)}</div></div>
        </div>
        ${renderSourceSection(item.source_code, item.source_file)}
      </div>
    </div>`;
  }

  if (cat === 'tools') {
    const inputs = (item.inputs || []).map(inp =>
      `<div class="auto-input-row">
         <span class="auto-input-name">${escHtml(inp.name)}</span>
         <span class="auto-input-type">${escHtml(inp.type)}</span>
         <span class="auto-input-desc">— ${escHtml(inp.description)}</span>
       </div>`
    ).join('');
    return `
    <div class="sys-card">
      <div class="sys-card-header">
        <div class="sys-card-title">
          <span class="sys-card-name">${escHtml(item.name)}</span>
          <span class="sys-card-sub">${escHtml(item.class)}</span>
        </div>
        <span class="sys-card-toggle">▼</span>
      </div>
      <div class="sys-card-body">
        <div class="sys-card-meta">
          <div class="meta-item" style="grid-column:1/-1"><div class="meta-label">Description</div><div class="meta-value">${escHtml(item.description)}</div></div>
          <div class="meta-item">
            <div class="meta-label">Inputs</div>
            <div class="auto-card-inputs">${inputs}</div>
          </div>
          <div class="meta-item">
            <div class="meta-label">Used By</div>
            <div class="meta-tags">${(item.used_by||[]).map(c => `<span class="meta-tag">${escHtml(c)}</span>`).join('')}</div>
          </div>
        </div>
        ${renderSourceSection(item.source_code, item.source_file)}
      </div>
    </div>`;
  }

  if (cat === 'crews') {
    const tasks = (item.tasks || []).map(t => `
      <div class="flow-step">
        <div class="flow-step-line"><div class="flow-step-dot"></div></div>
        <div class="flow-step-content">
          <div class="flow-step-name">${escHtml(t.name)}</div>
          <div class="flow-step-desc">${escHtml(t.description)}</div>
          <div style="margin-top:0.25rem;font-size:0.75rem;color:var(--text-muted)">Expected: <code style="font-family:ui-monospace,monospace;font-size:0.73rem">${escHtml(t.expected_output)}</code></div>
          ${t.config_code ? renderSourceSection(t.config_code, t.config_file || 'tasks.yaml', 'Task Config') : ''}
        </div>
      </div>`).join('');

    return `
    <div class="sys-card">
      <div class="sys-card-header">
        <div class="sys-card-title">
          <span class="sys-card-name">${escHtml(item.name)}</span>
          <span class="sys-card-badge">process: ${escHtml(item.process)}</span>
        </div>
        <span class="sys-card-toggle">▼</span>
      </div>
      <div class="sys-card-body">
        <div class="sys-card-meta">
          <div class="meta-item">
            <div class="meta-label">Agents</div>
            <div class="meta-tags">${(item.agents||[]).map(a => `<span class="meta-tag">${escHtml(a)}</span>`).join('')}</div>
          </div>
          <div class="meta-item"><div class="meta-label">Flow</div><div class="meta-value mono">${escHtml(item.flow)}</div></div>
          <div class="meta-item"><div class="meta-label">Job Type</div><div class="meta-value mono">${escHtml(item.job_type)}</div></div>
        </div>
        <div style="padding:0 1.1rem 0.25rem"><div class="meta-label" style="margin-bottom:0.5rem">Tasks</div></div>
        <div class="flow-steps">${tasks}</div>
        ${renderSourceSection(item.source_code, item.source_file)}
      </div>
    </div>`;
  }

  if (cat === 'workflows') {
    const steps = (item.steps || []).map((step, i) => `
      <div class="flow-step">
        <div class="flow-step-line">
          <div class="flow-step-dot"></div>
          ${i < item.steps.length - 1 ? '<div class="flow-step-connector"></div>' : ''}
        </div>
        <div class="flow-step-content">
          <div class="flow-step-dec">${escHtml(step.decorator)}</div>
          <div class="flow-step-name">${escHtml(step.name)}</div>
          <div class="flow-step-desc">${escHtml(step.description)}</div>
        </div>
      </div>`).join('');

    const stateFields = (item.state_fields || []).map(f =>
      `<div class="auto-input-row">
         <span class="auto-input-name">${escHtml(f.name)}</span>
         <span class="auto-input-type">${escHtml(f.type)}</span>
         <span class="auto-input-desc">= ${escHtml(String(f.default))}</span>
       </div>`
    ).join('');

    return `
    <div class="sys-card">
      <div class="sys-card-header">
        <div class="sys-card-title">
          <span class="sys-card-name">${escHtml(item.name)}</span>
          <span class="sys-card-badge">${escHtml(item.job_type)}</span>
        </div>
        <span class="sys-card-toggle">▼</span>
      </div>
      <div class="sys-card-body">
        <div class="sys-card-meta">
          <div class="meta-item">
            <div class="meta-label">State Fields</div>
            <div class="auto-card-inputs">${stateFields}</div>
          </div>
          <div class="meta-item"><div class="meta-label">Crew</div><div class="meta-value mono">${escHtml(item.crew)}</div></div>
        </div>
        <div style="padding:0 1.1rem 0.25rem"><div class="meta-label" style="margin-bottom:0.5rem">Flow Steps</div></div>
        <div class="flow-steps">${steps}</div>
        ${renderSourceSection(item.source_code, item.source_file)}
      </div>
    </div>`;
  }

  return '';
}

function renderSourceSection(code, filePath, label = 'Source Code') {
  if (!code) return '';
  return `
    <div class="sys-card-source">
      <div class="source-toggle">
        <span>${escHtml(label)}${filePath ? ` <span style="font-weight:400;opacity:0.55;font-family:ui-monospace,monospace;font-size:0.72rem">${escHtml(filePath)}</span>` : ''}</span>
        <span class="source-arrow">▼</span>
      </div>
      <div class="source-body">
        <pre>${highlightCode(code, filePath)}</pre>
      </div>
    </div>`;
}

// ── Automations page ──────────────────────────────────────────────────────────

function renderAutomationsPage() {
  const grid = document.getElementById('auto-grid');
  grid.innerHTML = Object.entries(AUTO_CATALOG).map(([type, meta]) => {
    const inputs = meta.inputs.map(inp =>
      `<div class="auto-input-row">
         <span class="auto-input-name">${escHtml(inp.name)}</span>
         <span class="auto-input-type">${escHtml(inp.type)}</span>
         <span class="auto-input-desc">— ${escHtml(inp.desc)}</span>
       </div>`
    ).join('');

    return `
    <div class="auto-card">
      <div class="auto-card-header">
        <div class="auto-card-icon">${meta.icon}</div>
        <div>
          <div class="auto-card-name">${escHtml(meta.name)}</div>
          <div class="auto-card-type">${escHtml(type)}</div>
        </div>
      </div>
      <div class="auto-card-desc">${escHtml(meta.desc)}</div>
      <div class="auto-card-section">
        <div class="auto-card-section-label">Inputs</div>
        <div class="auto-card-inputs">${inputs}</div>
      </div>
      <div class="auto-card-section">
        <div class="auto-card-section-label">Pipeline</div>
        <div class="auto-card-links">
          <span class="auto-link-chip">Flow: ${escHtml(meta.flow)}</span>
          <span class="auto-link-chip">Crew: ${escHtml(meta.crew)}</span>
          <span class="auto-link-chip">Agent: ${escHtml(meta.agent)}</span>
          ${meta.tools.map(t => `<span class="auto-link-chip" style="background:rgba(59,130,246,0.1);color:var(--blue);border-color:rgba(59,130,246,0.2)">Tool: ${escHtml(t)}</span>`).join('')}
        </div>
      </div>
      <div class="auto-card-footer">
        <button class="btn btn-primary" style="width:100%" data-run-type="${type}">▶ Run ${escHtml(meta.name)}</button>
      </div>
    </div>`;
  }).join('');

  grid.querySelectorAll('[data-run-type]').forEach(btn => {
    btn.addEventListener('click', () => {
      navigate('dashboard');
      setTimeout(() => openModal(btn.dataset.runType), 80);
    });
  });
}

// ── Performance page ──────────────────────────────────────────────────────────

async function loadPerformancePage() {
  document.getElementById('perf-content').innerHTML = '<div class="loading-state">Loading metrics…</div>';
  try {
    const resp = await fetch('/api/stats');
    if (!resp.ok) throw new Error('Failed to load stats');
    renderPerformancePage(await resp.json());
  } catch (err) {
    document.getElementById('perf-content').innerHTML = `<div class="loading-state" style="color:var(--red)">Error: ${escHtml(err.message)}</div>`;
  }
}

function renderPerformancePage(s) {
  const maxTrend = Math.max(...s.trend.map(d => d.total), 1);

  const trendRows = s.trend.map(d => {
    const sw = Math.round((d.success / maxTrend) * 100);
    const fw = Math.round((d.failed  / maxTrend) * 100);
    return `
      <div class="trend-row">
        <div class="trend-label">${escHtml(d.label)}</div>
        <div class="trend-bar-wrap">
          <div class="trend-bar-success" style="width:${sw}%"></div>
          <div class="trend-bar-failed"  style="width:${fw}%"></div>
        </div>
        <div class="trend-count">${d.total}</div>
      </div>`;
  }).join('');

  const typeRows = Object.entries(s.by_type).map(([type, data]) => {
    const total = data.total || 1;
    const sw = Math.round((data.success / total) * 100);
    const fw = Math.round((data.failed  / total) * 100);
    const meta = TYPE_META[type] || { chip: type.toUpperCase(), cls: 'chip-unknown' };
    return `
      <tr>
        <td><span class="type-chip ${meta.cls}">${meta.chip}</span> ${escHtml(type)}</td>
        <td style="text-align:right">${data.total}</td>
        <td style="text-align:right;color:var(--green)">${data.success}</td>
        <td style="text-align:right;color:var(--red)">${data.failed}</td>
        <td>
          <div class="mini-bar-wrap">
            <div class="mini-bar-s" style="width:${sw}%"></div>
            <div class="mini-bar-f" style="width:${fw}%"></div>
          </div>
        </td>
        <td style="color:var(--text-muted)">${data.avg_duration > 0 ? data.avg_duration + 's' : '—'}</td>
      </tr>`;
  }).join('');

  const successRateColor = s.success_rate >= 80 ? 'green' : s.success_rate >= 50 ? '' : 'red';

  const totalCostStr = s.total_cost_usd > 0
    ? (s.total_cost_usd < 0.01 ? s.total_cost_usd.toFixed(5) : s.total_cost_usd.toFixed(3))
    : '0';
  const totalTokStr = s.total_tokens > 0 ? s.total_tokens.toLocaleString() : '0';

  const providerRows = Object.entries(s.by_provider || {}).map(([prov, d]) => {
    const tok = (d.tokens_in + d.tokens_out).toLocaleString();
    const cost = d.cost_usd > 0
      ? (d.cost_usd < 0.01 ? d.cost_usd.toFixed(5) : d.cost_usd.toFixed(3))
      : '0';
    const provLabel = prov === 'anthropic' ? 'claude' : prov;
    const badgeCls  = `llm-${prov}`;
    const models    = (d.models || []).join(', ') || '—';
    return `
      <tr>
        <td><span class="llm-badge ${badgeCls}">${provLabel}</span></td>
        <td style="text-align:right">${d.runs}</td>
        <td style="text-align:right;color:var(--text-muted)">${tok}</td>
        <td style="text-align:right;color:var(--yellow)">$${cost}</td>
        <td style="color:var(--text-muted);font-size:0.78rem;font-family:ui-monospace,monospace">${escHtml(models)}</td>
      </tr>`;
  }).join('');

  document.getElementById('perf-content').innerHTML = `
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Total Runs</div>
        <div class="stat-value blue">${s.total_runs}</div>
        <div class="stat-sub">${s.active} active</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Success Rate</div>
        <div class="stat-value ${successRateColor}">${s.success_rate}%</div>
        <div class="stat-sub">${s.success} succeeded</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Failed</div>
        <div class="stat-value ${s.failed > 0 ? 'red' : ''}">${s.failed}</div>
        <div class="stat-sub">of ${s.total_runs} total</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Avg Duration</div>
        <div class="stat-value">${s.avg_duration_secs > 0 ? s.avg_duration_secs + 's' : '—'}</div>
        <div class="stat-sub">completed runs</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Total Tokens</div>
        <div class="stat-value orange" style="font-size:1.4rem">${totalTokStr}</div>
        <div class="stat-sub">${(s.total_tokens_in||0).toLocaleString()} in · ${(s.total_tokens_out||0).toLocaleString()} out</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Total Cost</div>
        <div class="stat-value yellow" style="font-size:1.4rem">$${totalCostStr}</div>
        <div class="stat-sub">USD (estimated)</div>
      </div>
    </div>

    <div class="perf-section">
      <div class="perf-section-title">Last 7 Days</div>
      <div class="trend-chart">${trendRows}</div>
    </div>

    ${typeRows ? `
    <div class="perf-section">
      <div class="perf-section-title">By Automation Type</div>
      <div class="perf-table-wrap">
        <table class="perf-table">
          <thead>
            <tr>
              <th>Type</th>
              <th style="text-align:right">Total</th>
              <th style="text-align:right">Success</th>
              <th style="text-align:right">Failed</th>
              <th>Rate</th>
              <th>Avg Duration</th>
            </tr>
          </thead>
          <tbody>${typeRows}</tbody>
        </table>
      </div>
    </div>` : ''}

    ${providerRows ? `
    <div class="perf-section">
      <div class="perf-section-title">LLM Resource Usage</div>
      <div class="provider-table-wrap">
        <table class="provider-table">
          <thead>
            <tr>
              <th>Provider</th>
              <th style="text-align:right">Runs</th>
              <th style="text-align:right">Tokens</th>
              <th style="text-align:right">Cost (USD)</th>
              <th>Models Used</th>
            </tr>
          </thead>
          <tbody>${providerRows}</tbody>
        </table>
      </div>
    </div>` : ''}`;
}

// ── Syntax highlighting ────────────────────────────────────────────────────────

const _PY_KW_ITALIC = new Set(['def','class','async','await','lambda']);
const _PY_KW = new Set([
  'False','None','True','and','as','assert','break','continue','del','elif',
  'else','except','finally','for','from','global','if','import','in','is',
  'nonlocal','not','or','pass','raise','return','try','while','with','yield',
]);
const _PY_BI = new Set([
  'abs','all','any','bin','bool','bytes','callable','chr','dict','dir',
  'divmod','enumerate','eval','exec','filter','float','format','frozenset',
  'getattr','globals','hasattr','hash','help','hex','id','input','int',
  'isinstance','issubclass','iter','len','list','locals','map','max','min',
  'next','object','oct','open','ord','pow','print','property','range','repr',
  'reversed','round','set','setattr','slice','sorted','staticmethod','str',
  'sum','super','tuple','type','vars','zip','self','cls',
]);

function highlightCode(raw, filePath) {
  const ext = (filePath || '').split('.').pop().toLowerCase();
  try {
    if (ext === 'py')              return _hlPython(raw);
    if (ext === 'yaml' || ext === 'yml') return _hlYaml(raw);
  } catch (_) {}
  return escHtml(raw);
}

function _hlPython(code) {
  const out = [];
  let i = 0;
  const n = code.length;

  while (i < n) {
    const ch = code[i];

    // Triple-quoted strings (handle """ and ''')
    if ((ch === '"' || ch === "'") && code[i+1] === ch && code[i+2] === ch) {
      const q = ch.repeat(3);
      const end = code.indexOf(q, i + 3);
      const len = end === -1 ? n - i : end - i + 3;
      out.push(`<span class="hl-s">${escHtml(code.slice(i, i + len))}</span>`);
      i += len;
      continue;
    }

    // Single-line strings
    if (ch === '"' || ch === "'") {
      let j = i + 1;
      while (j < n && code[j] !== ch && code[j] !== '\n') {
        if (code[j] === '\\') j++;
        j++;
      }
      if (j < n && code[j] === ch) j++;
      out.push(`<span class="hl-s">${escHtml(code.slice(i, j))}</span>`);
      i = j;
      continue;
    }

    // Comments
    if (ch === '#') {
      const nl = code.indexOf('\n', i);
      const end = nl === -1 ? n : nl;
      out.push(`<span class="hl-c">${escHtml(code.slice(i, end))}</span>`);
      i = end;
      continue;
    }

    // Decorator
    if (ch === '@') {
      const m = code.slice(i).match(/^@[\w.]+/);
      if (m) {
        out.push(`<span class="hl-d">${escHtml(m[0])}</span>`);
        i += m[0].length;
        continue;
      }
    }

    // Word token
    if (/[a-zA-Z_]/.test(ch)) {
      const m = code.slice(i).match(/^\w+/);
      if (m) {
        const w = m[0];
        let span = '';
        if (_PY_KW_ITALIC.has(w)) {
          span = `<span class="hl-ki">${escHtml(w)}</span>`;
        } else if (_PY_KW.has(w)) {
          span = `<span class="hl-k">${escHtml(w)}</span>`;
        } else if (_PY_BI.has(w)) {
          span = `<span class="hl-bi">${escHtml(w)}</span>`;
        } else {
          // Function/class name after def/class keyword
          const pre = code.slice(Math.max(0, i - 12), i);
          if (/\b(?:def|class)\s+$/.test(pre)) {
            span = `<span class="hl-fn">${escHtml(w)}</span>`;
          } else if (i > 0 && code[i - 1] === '.') {
            // Method access
            span = `<span class="hl-fn">${escHtml(w)}</span>`;
          } else {
            span = escHtml(w);
          }
        }
        out.push(span);
        i += w.length;
        continue;
      }
    }

    // Number
    if (/\d/.test(ch) && (i === 0 || !/\w/.test(code[i-1]))) {
      const m = code.slice(i).match(/^\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/);
      if (m) {
        out.push(`<span class="hl-n">${escHtml(m[0])}</span>`);
        i += m[0].length;
        continue;
      }
    }

    out.push(escHtml(ch));
    i++;
  }

  return out.join('');
}

function _hlYaml(code) {
  return code.split('\n').map(line => {
    // Full-line comment
    if (/^\s*#/.test(line)) {
      return `<span class="hl-c">${escHtml(line)}</span>`;
    }
    // key: value  (skip lines that start with - or are pure values)
    const km = line.match(/^(\s*)([\w][\w _-]*)(\s*:\s*)(.*)?$/);
    if (km) {
      const [, ws, key, sep, val = ''] = km;
      let valHtml = '';
      const vt = val.trim();
      if (!vt) {
        // No value — just a key block
        valHtml = '';
      } else if (vt.startsWith('#')) {
        valHtml = `<span class="hl-c">${escHtml(val)}</span>`;
      } else if (vt.startsWith('"') || vt.startsWith("'")) {
        valHtml = `<span class="hl-yv">${escHtml(val)}</span>`;
      } else if (vt === '>' || vt === '|') {
        valHtml = `<span class="hl-k">${escHtml(val)}</span>`;
      } else if (/^(true|false|yes|no|null|~)$/i.test(vt)) {
        valHtml = `<span class="hl-bi">${escHtml(val)}</span>`;
      } else if (/^-?\d/.test(vt)) {
        valHtml = `<span class="hl-n">${escHtml(val)}</span>`;
      } else {
        valHtml = `<span class="hl-yv">${escHtml(val)}</span>`;
      }
      return `${escHtml(ws)}<span class="hl-yk">${escHtml(key)}</span><span style="color:#5c6370">${escHtml(sep)}</span>${valHtml}`;
    }
    // List item marker
    if (/^\s*-\s/.test(line)) {
      const lm = line.match(/^(\s*-\s)(.*)/);
      if (lm) {
        return `<span class="hl-k">${escHtml(lm[1])}</span><span class="hl-yv">${escHtml(lm[2])}</span>`;
      }
    }
    // Continuation / folded block lines (indented plain text)
    if (/^\s+\S/.test(line)) {
      return `<span class="hl-yv">${escHtml(line)}</span>`;
    }
    return escHtml(line);
  }).join('\n');
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function extractResultText(r) {
  if (!r) return '';
  return r.answer
    || r.story_of_the_day?.title
    || r.summary
    || r.confirmation
    || r.confirmation_text
    || r.error
    || r.message
    || (r.title ? `${r.title} (${r.word_count ?? '?'} words)` : '')
    || '';
}

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showToast(msg, type = 'error') {
  const banner = document.getElementById('toast-banner');
  banner.textContent = msg;
  banner.style.background = type === 'success' ? 'var(--green)' : 'var(--red)';
  banner.classList.remove('hidden');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => banner.classList.add('hidden'), type === 'success' ? 2000 : 4000);
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.getElementById('load-more-btn').addEventListener('click', async () => {
  runsOffset += RUNS_PAGE_SIZE;
  await loadHistory(false);
});

loadHistory();
setInterval(() => { if (!activeEventSource) loadHistory(); }, 5000);
