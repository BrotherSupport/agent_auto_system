// ── Constants ─────────────────────────────────────────────────────────────────

const ALL_TYPES = ['google_form_fill', 'web_scraper', 'hacker_news_digest', 'x_scraper'];

const TYPE_META = {
  google_form_fill:   { chip: 'FORM', cls: 'chip-form' },
  web_scraper:        { chip: 'WEB',  cls: 'chip-web'  },
  hacker_news_digest: { chip: 'HN',   cls: 'chip-hn'   },
  x_scraper:          { chip: 'X',    cls: 'chip-x'    },
};

// ── State ─────────────────────────────────────────────────────────────────────

let activeEventSource = null;
let sseStartTime      = null;
let cachedRuns        = [];
const elapsedTimers   = new Map();  // runId → intervalId
let toastTimer        = null;

// ── DOM refs ──────────────────────────────────────────────────────────────────

const modal           = document.getElementById('modal');
const runForm         = document.getElementById('run-form');
const progressPanel   = document.getElementById('progress-panel');
const progressLog     = document.getElementById('progress-log');
const progressJobName = document.getElementById('progress-job-name');
const progressPulse   = document.getElementById('progress-pulse');
const heroSection     = document.getElementById('hero-section');
const heroRestoreBtn  = document.getElementById('hero-restore');

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

function openModal() { modal.classList.remove('hidden'); }
function closeModalFn() { modal.classList.add('hidden'); }

document.getElementById('new-run-btn').addEventListener('click', openModal);
document.getElementById('hero-run-btn').addEventListener('click', openModal);
document.getElementById('modal-close').addEventListener('click', closeModalFn);
document.getElementById('cancel-btn').addEventListener('click', closeModalFn);
modal.addEventListener('click', (e) => { if (e.target === modal) closeModalFn(); });

// ── Job type card selection (event delegation on grid) ────────────────────────

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

// ── Table event delegation ────────────────────────────────────────────────────
// All row interactions (toggle, tab, rerun, delete, copy) go through one listener.

document.getElementById('history-tbody').addEventListener('click', (e) => {
  const actionEl = e.target.closest('[data-action]');

  if (actionEl) {
    const action = actionEl.dataset.action;
    const runId  = parseInt(actionEl.dataset.runId,  10);
    const jobId  = parseInt(actionEl.dataset.jobId,  10);
    const tab    = actionEl.dataset.tab;

    switch (action) {
      case 'tab':    switchTab(runId, tab);  return;
      case 'rerun':  rerun(jobId);           return;
      case 'delete': deleteRun(runId);       return;
      case 'copy':   copyResult(runId);      return;
    }
    return;
  }

  // Plain row click → toggle detail panel
  const row = e.target.closest('tr.data-row');
  if (row) toggleDetail(parseInt(row.dataset.runId, 10));
});

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
    payload = {
      url,
      question: document.getElementById('scrape-question').value.trim() || 'What is this page about?',
    };
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
  }

  closeModalFn();
  runForm.reset();
  selectJobType('google_form_fill');
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

    const cached  = cachedRuns.find(r => r.job_id === jobId);
    const jobName = cached?.job_name ?? `job ${jobId}`;

    showProgress(jobName);
    await loadHistory();
    scrollToRun(run_id);
    startSSE(run_id);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// ── Delete run ────────────────────────────────────────────────────────────────

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
    await loadHistory();
    showToast('Run deleted', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

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
  const ok    = status === 'success';
  const color = ok ? 'var(--green)' : 'var(--red)';
  progressJobName.innerHTML =
    `<span style="color:${color}">${ok ? '✓ Completed' : '✗ Failed'} in ${durationSecs}s</span>`;
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

async function loadHistory() {
  try {
    const resp = await fetch('/api/runs?limit=50');
    if (!resp.ok) return;
    renderHistory(await resp.json());
  } catch (_) {}
}

function renderHistory(runs) {
  cachedRuns = runs;
  const tbody = document.getElementById('history-tbody');

  if (!runs.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No runs yet. Click "New Run" to get started.</td></tr>';
    return;
  }

  tbody.innerHTML = runs.map((run) => {
    const meta      = TYPE_META[run.job_type] || { chip: run.job_type?.toUpperCase() || '?', cls: 'chip-unknown' };
    const isActive  = run.status === 'running' || run.status === 'pending';
    const duration  = run.finished_at
      ? `${((new Date(run.finished_at) - new Date(run.started_at)) / 1000).toFixed(1)}s`
      : '—';
    const durCell   = isActive
      ? `<span class="elapsed-timer" data-started="${run.started_at}">…</span>`
      : duration;
    const started   = new Date(run.started_at).toLocaleString();

    let resultText = '', resultJson = null;
    if (run.result) {
      try { resultJson = JSON.parse(run.result); resultText = extractResultText(resultJson); }
      catch (_) { resultText = run.result; }
    }

    let logJson = null;
    if (run.log) { try { logJson = JSON.parse(run.log); } catch (_) {} }

    const logTab = logJson
      ? `<button class="detail-tab" data-action="tab" data-tab="log" data-run-id="${run.id}">Log (${logJson.length})</button>`
      : '';
    const logPane = logJson
      ? `<div class="detail-pane" id="pane-log-${run.id}" data-pane="log">
           <ul class="log-list">${logJson.map(e =>
             `<li><span class="log-ts">${escHtml(e.ts)}</span>${escHtml(e.msg)}</li>`
           ).join('')}</ul>
         </div>`
      : '';

    const deleteDis = isActive ? 'disabled title="Cannot delete an active run"' : 'title="Delete run"';

    return `
      <tr class="data-row" data-run-id="${run.id}">
        <td style="color:var(--text-muted)">#${run.id}</td>
        <td>
          <div class="job-cell">
            <span class="job-name-text">${escHtml(run.job_name)}</span>
            <span class="type-chip ${meta.cls}">${meta.chip}</span>
          </div>
        </td>
        <td><span class="badge badge-${run.status}">${run.status}</span></td>
        <td style="color:var(--text-muted);font-size:0.8rem">${started}</td>
        <td style="color:var(--text-muted)">${durCell}</td>
        <td class="result-cell" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.82rem;color:var(--text-muted)">${escHtml(resultText)}</td>
        <td style="padding:0.65rem 0.5rem">
          <div class="row-actions">
            <button class="btn-rerun" data-action="rerun" data-job-id="${run.job_id}" data-run-id="${run.id}" title="Re-run">↺</button>
            <button class="btn-delete" data-action="delete" data-run-id="${run.id}" ${deleteDis}>🗑</button>
          </div>
        </td>
      </tr>
      <tr class="detail-row hidden" id="detail-${run.id}">
        <td colspan="7" style="padding:0">
          <div class="detail-tabs">
            <button class="detail-tab active" data-action="tab" data-tab="result" data-run-id="${run.id}">Result</button>
            ${logTab}
          </div>
          <div class="detail-pane active" id="pane-result-${run.id}" data-pane="result">
            <div class="pane-toolbar">
              <button class="btn-copy" data-action="copy" data-run-id="${run.id}">Copy JSON</button>
            </div>
            <pre>${escHtml(resultJson ? JSON.stringify(resultJson, null, 2) : (run.result || ''))}</pre>
          </div>
          ${logPane}
        </td>
      </tr>`;
  }).join('');

  initElapsedTimers();
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
      clearInterval(id);
      elapsedTimers.delete(runId);
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

// ── Helpers ───────────────────────────────────────────────────────────────────

function extractResultText(r) {
  if (!r) return '';
  return r.answer
    || r.story_of_the_day?.title
    || r.summary
    || r.confirmation_text
    || r.confirmation
    || r.error
    || r.message
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

loadHistory();
setInterval(() => { if (!activeEventSource) loadHistory(); }, 5000);
