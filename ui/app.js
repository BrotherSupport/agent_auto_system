const modal = document.getElementById('modal');
const runForm = document.getElementById('run-form');
const liveIndicator = document.getElementById('live-indicator');

let activeEventSource = null;

// ── Modal open/close ──────────────────────────────────────────────────────────

function openModal() { modal.classList.remove('hidden'); }
function closeModalFn() { modal.classList.add('hidden'); }

document.getElementById('new-run-btn').addEventListener('click', openModal);
document.getElementById('hero-run-btn').addEventListener('click', openModal);
document.getElementById('modal-close').addEventListener('click', closeModalFn);
document.getElementById('cancel-btn').addEventListener('click', closeModalFn);
modal.addEventListener('click', (e) => { if (e.target === modal) closeModalFn(); });

// ── Form submit ───────────────────────────────────────────────────────────────

runForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    company_name: document.getElementById('company-name').value.trim(),
    company_size: document.getElementById('company-size').value,
    ai_problem: document.getElementById('ai-problem').value.trim(),
  };
  closeModalFn();
  runForm.reset();
  await triggerRun(payload);
});

// ── Trigger a new run ─────────────────────────────────────────────────────────

async function triggerRun(payload) {
  try {
    const jobResp = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: `Form: ${payload.company_name}`,
        job_type: 'google_form_fill',
        payload,
      }),
    });
    if (!jobResp.ok) throw new Error('Failed to create job');
    const job = await jobResp.json();

    const runResp = await fetch(`/api/jobs/${job.id}/run`, { method: 'POST' });
    if (!runResp.ok) throw new Error('Failed to trigger run');
    const { run_id } = await runResp.json();

    await loadHistory();
    startSSE(run_id);
  } catch (err) {
    showError(err.message);
  }
}

// ── Server-Sent Events ────────────────────────────────────────────────────────

function startSSE(runId) {
  if (activeEventSource) activeEventSource.close();

  liveIndicator.classList.remove('hidden');
  activeEventSource = new EventSource(`/api/runs/${runId}/stream`);

  activeEventSource.onmessage = (e) => {
    const data = JSON.parse(e.data);
    updateRow(runId, data);
    if (data.status === 'success' || data.status === 'failed') {
      activeEventSource.close();
      activeEventSource = null;
      liveIndicator.classList.add('hidden');
    }
  };

  activeEventSource.onerror = () => {
    activeEventSource.close();
    activeEventSource = null;
    liveIndicator.classList.add('hidden');
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
    if (resultCell) resultCell.textContent = data.result.confirmation_text || data.result.error || '';

    const detail = document.getElementById(`detail-${runId}`);
    if (detail) {
      detail.querySelector('pre').textContent = JSON.stringify(data.result, null, 2);
    }
  }

  // Update duration once finished
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
        resultText = resultJson.confirmation_text || resultJson.error || resultJson.message || '';
      } catch (_) {
        resultText = run.result;
      }
    }
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
        <td colspan="6"><pre>${resultJson ? JSON.stringify(resultJson, null, 2) : (run.result || '')}</pre></td>
      </tr>`;
  }).join('');
}

function toggleDetail(runId) {
  const detail = document.getElementById(`detail-${runId}`);
  if (detail) detail.classList.toggle('hidden');
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
