const modal = document.getElementById('modal');
const runForm = document.getElementById('run-form');
const liveIndicator = document.getElementById('live-indicator');
const progressPanel = document.getElementById('progress-panel');
const progressLog = document.getElementById('progress-log');
const progressJobName = document.getElementById('progress-job-name');

let activeEventSource = null;
const ALL_TYPES = ['google_form_fill', 'web_scraper', 'hacker_news_digest', 'x_scraper'];

// ── Modal open/close ──────────────────────────────────────────────────────────

function openModal() { modal.classList.remove('hidden'); }
function closeModalFn() { modal.classList.add('hidden'); }

document.getElementById('new-run-btn').addEventListener('click', openModal);
document.getElementById('hero-run-btn').addEventListener('click', openModal);
document.getElementById('modal-close').addEventListener('click', closeModalFn);
document.getElementById('cancel-btn').addEventListener('click', closeModalFn);
modal.addEventListener('click', (e) => { if (e.target === modal) closeModalFn(); });

// ── Job type switcher ─────────────────────────────────────────────────────────

function switchJobType(type) {
  ALL_TYPES.forEach((t) => {
    document.getElementById(`fields-${t}`).classList.toggle('hidden', t !== type);
  });
}

// ── Form submit ───────────────────────────────────────────────────────────────

runForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const jobType = document.getElementById('job-type').value;
  let payload, jobName;

  if (jobType === 'google_form_fill') {
    const company = document.getElementById('company-name').value.trim();
    if (!company) { showError('Company name is required'); return; }
    payload = {
      company_name: company,
      company_size: document.getElementById('company-size').value,
      ai_problem: document.getElementById('ai-problem').value.trim(),
    };
    jobName = `Form: ${company}`;
  } else if (jobType === 'web_scraper') {
    const url = document.getElementById('scrape-url').value.trim();
    if (!url) { showError('URL is required'); return; }
    payload = {
      url,
      question: document.getElementById('scrape-question').value.trim() || 'What is this page about?',
    };
    jobName = `Scrape: ${new URL(url).hostname}`;
  } else if (jobType === 'hacker_news_digest') {
    payload = { limit: parseInt(document.getElementById('hn-limit').value, 10) || 5 };
    jobName = `HN Digest (top ${payload.limit})`;
  } else if (jobType === 'x_scraper') {
    const username = document.getElementById('x-username').value.trim().replace(/^@/, '');
    if (!username) { showError('X username is required'); return; }
    payload = {
      username,
      limit: parseInt(document.getElementById('x-limit').value, 10) || 5,
    };
    jobName = `X: @${username}`;
  }

  closeModalFn();
  runForm.reset();
  switchJobType('google_form_fill');
  document.getElementById('job-type').value = 'google_form_fill';
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
    startSSE(run_id);
  } catch (err) {
    showError(err.message);
  }
}

// ── Live progress panel ───────────────────────────────────────────────────────

function showProgress(jobName) {
  progressLog.innerHTML = '';
  progressJobName.textContent = jobName;
  progressPanel.classList.remove('hidden');
}

function hideProgress() {
  progressPanel.classList.add('hidden');
}

function appendProgressEntry(entry) {
  const li = document.createElement('li');
  li.innerHTML = `<span class="log-ts">${entry.ts}</span>${escHtml(entry.msg)}`;
  progressLog.appendChild(li);
  progressLog.scrollTop = progressLog.scrollHeight;
}

// ── Server-Sent Events ────────────────────────────────────────────────────────

function startSSE(runId) {
  if (activeEventSource) activeEventSource.close();

  liveIndicator.classList.remove('hidden');
  activeEventSource = new EventSource(`/api/runs/${runId}/stream`);

  activeEventSource.onmessage = (e) => {
    const data = JSON.parse(e.data);

    if (data.new_logs) {
      data.new_logs.forEach(appendProgressEntry);
    }

    updateRow(runId, data);

    if (data.status === 'success' || data.status === 'failed') {
      activeEventSource.close();
      activeEventSource = null;
      liveIndicator.classList.add('hidden');
      hideProgress();
    }
  };

  activeEventSource.onerror = () => {
    activeEventSource.close();
    activeEventSource = null;
    liveIndicator.classList.add('hidden');
    hideProgress();
  };
}

function updateRow(runId, data) {
  const row = document.querySelector(`tr[data-run-id="${runId}"]`);
  if (!row) { loadHistory(); return; }

  const badge = row.querySelector('.badge');
  if (badge) {
    badge.textContent = data.status;
    badge.className = `badge badge-${data.status}`;
  }

  if (data.result) {
    const resultCell = row.querySelector('.result-cell');
    if (resultCell) resultCell.textContent = extractResultText(data.result);
  }

  if (data.status === 'success' || data.status === 'failed') {
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
  const tbody = document.getElementById('history-tbody');
  if (runs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No runs yet. Click "New Run" to get started.</td></tr>';
    return;
  }

  tbody.innerHTML = runs.map((run) => {
    const duration = run.finished_at
      ? `${((new Date(run.finished_at) - new Date(run.started_at)) / 1000).toFixed(1)}s`
      : '—';
    const started = new Date(run.started_at).toLocaleString();
    let resultText = '';
    let resultJson = null;
    if (run.result) {
      try {
        resultJson = JSON.parse(run.result);
        resultText = extractResultText(resultJson);
      } catch (_) {
        resultText = run.result;
      }
    }

    let logJson = null;
    if (run.log) {
      try { logJson = JSON.parse(run.log); } catch (_) {}
    }

    const logTab = logJson
      ? `<button class="detail-tab" onclick="switchTab(${run.id},'log')">Log (${logJson.length})</button>`
      : '';
    const logPane = logJson
      ? `<div class="detail-pane" id="pane-log-${run.id}">
           <ul class="log-list">${logJson.map(e =>
             `<li><span class="log-ts">${escHtml(e.ts)}</span>${escHtml(e.msg)}</li>`
           ).join('')}</ul>
         </div>`
      : '';

    return `
      <tr class="data-row" data-run-id="${run.id}" onclick="toggleDetail(${run.id})">
        <td style="color:var(--text-muted)">#${run.id}</td>
        <td style="color:var(--text-muted)">job ${run.job_id}</td>
        <td><span class="badge badge-${run.status}">${run.status}</span></td>
        <td style="color:var(--text-muted);font-size:0.8rem">${started}</td>
        <td style="color:var(--text-muted)">${duration}</td>
        <td class="result-cell" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.82rem;color:var(--text-muted)">${resultText}</td>
      </tr>
      <tr class="detail-row hidden" id="detail-${run.id}">
        <td colspan="6" style="padding:0">
          <div class="detail-tabs">
            <button class="detail-tab active" onclick="switchTab(${run.id},'result')">Result</button>
            ${logTab}
          </div>
          <div class="detail-pane active" id="pane-result-${run.id}">
            <pre>${escHtml(resultJson ? JSON.stringify(resultJson, null, 2) : (run.result || ''))}</pre>
          </div>
          ${logPane}
        </td>
      </tr>`;
  }).join('');
}

function toggleDetail(runId) {
  const detail = document.getElementById(`detail-${runId}`);
  if (detail) detail.classList.toggle('hidden');
}

function switchTab(runId, tab) {
  const tabs = document.querySelectorAll(`#detail-${runId} .detail-tab`);
  const panes = document.querySelectorAll(`#detail-${runId} .detail-pane`);
  tabs.forEach(t => t.classList.remove('active'));
  panes.forEach(p => p.classList.remove('active'));
  const activeTab = [...tabs].find(t => t.textContent.toLowerCase().startsWith(tab));
  if (activeTab) activeTab.classList.add('active');
  const activePane = document.getElementById(`pane-${tab}-${runId}`);
  if (activePane) activePane.classList.add('active');
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function extractResultText(r) {
  if (!r) return '';
  return r.answer ||
    (r.story_of_the_day && r.story_of_the_day.title) ||
    (r.summary) ||
    r.confirmation_text ||
    r.confirmation ||
    r.error ||
    r.message ||
    '';
}

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Error banner ──────────────────────────────────────────────────────────────

function showError(msg) {
  const banner = document.getElementById('error-banner');
  banner.textContent = msg;
  banner.classList.remove('hidden');
  setTimeout(() => banner.classList.add('hidden'), 4000);
}

// ── Init ──────────────────────────────────────────────────────────────────────

loadHistory();
setInterval(loadHistory, 5000);
