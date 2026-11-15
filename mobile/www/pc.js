/**
 * AssetDrop PC Workstation Dashboard Logic (static/pc.js)
 * Minimal PC Host Interface:
 * - Active Download Queue (queued, downloading, ingesting)
 * - Downloaded Files History (filename, save location, completion time, open folder action)
 * - Mobile Connection Credentials Control (5-digit UID & password reveal)
 */

'use strict';

(function () {
  // Runtime State
  const state = {
    credentials: {
      uid: '',
      password: '',
      connectionUrl: '',
      isRevealed: false,
      isPasswordMasked: true,
    },
    pollingIntervalMs: 2500,
    pollingTimer: null,
    isOnline: true,
  };

  // Helper: Escape HTML to prevent XSS
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Helper: Format completion time
  function formatCompletionTime(completedAt) {
    if (!completedAt) return '—';
    try {
      const ts = typeof completedAt === 'number'
        ? (completedAt < 1e11 ? completedAt * 1000 : completedAt)
        : Date.parse(completedAt);
      if (isNaN(ts)) return String(completedAt);
      const d = new Date(ts);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
        ' ' + d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    } catch (e) {
      return String(completedAt);
    }
  }

  // Toast Notification
  function showToast(message, isSuccess = true) {
    const toast = document.getElementById('pc-toast');
    const msgEl = document.getElementById('pc-toast-message');
    const iconEl = document.getElementById('pc-toast-icon');
    if (!toast || !msgEl) return;

    msgEl.textContent = message;
    if (iconEl) {
      iconEl.textContent = isSuccess ? '✓' : '✕';
      iconEl.style.color = isSuccess ? '#10b981' : '#ef4444';
    }
    toast.classList.remove('hidden');

    clearTimeout(toast._timeout);
    toast._timeout = setTimeout(() => {
      toast.classList.add('hidden');
    }, 3000);
  }

  // Update Connection Status Pill
  function setConnectionStatus(online) {
    state.isOnline = online;
    const pill = document.getElementById('connection-indicator');
    const text = document.getElementById('connection-status-text');
    if (!pill || !text) return;

    if (online) {
      pill.className = 'status-pill online';
      text.textContent = 'Online';
    } else {
      pill.className = 'status-pill offline';
      text.textContent = 'Offline';
    }
  }

  // -------------------------------------------------------------------------
  // Credentials Management
  // -------------------------------------------------------------------------
  async function fetchCredentials() {
    try {
      // Primary: /api/workstation/credentials | Fallback: /api/workstation/settings
      let resp = await fetch('/api/workstation/credentials');
      if (!resp.ok) {
        resp = await fetch('/api/workstation/settings');
      }
      if (resp.ok) {
        const data = await resp.json();
        state.credentials.uid = data.uid || '';
        state.credentials.password = data.password || '';
        state.credentials.connectionUrl = data.connection_url || `http://${data.local_ip || '127.0.0.1'}:${data.port || 8000}`;
        renderCredentialsUI();
      }
    } catch (err) {
      console.warn('[PC Hub] Failed to fetch workstation credentials:', err);
    }
  }

  function renderCredentialsUI() {
    const uidEl = document.getElementById('pc-uid-display');
    const pwEl = document.getElementById('pc-password-display');
    const urlEl = document.getElementById('pc-connection-url');

    if (uidEl) {
      uidEl.textContent = state.credentials.uid || '-----';
    }
    if (pwEl) {
      if (state.credentials.isPasswordMasked) {
        pwEl.textContent = '••••••••';
      } else {
        pwEl.textContent = state.credentials.password || '—';
      }
    }
    if (urlEl) {
      urlEl.textContent = state.credentials.connectionUrl || '—';
    }
  }

  function toggleCredentialsVisibility() {
    state.credentials.isRevealed = !state.credentials.isRevealed;
    const details = document.getElementById('credentials-details');
    const btn = document.getElementById('btn-toggle-credentials');

    if (details) {
      if (state.credentials.isRevealed) {
        details.classList.remove('hidden');
        if (btn) {
          btn.innerHTML = '<span>Hide Credentials</span>';
          btn.setAttribute('aria-expanded', 'true');
        }
      } else {
        details.classList.add('hidden');
        if (btn) {
          btn.innerHTML = '<span>Show Credentials</span>';
          btn.setAttribute('aria-expanded', 'false');
        }
      }
    }
  }

  function togglePasswordMask() {
    state.credentials.isPasswordMasked = !state.credentials.isPasswordMasked;
    const btn = document.getElementById('btn-toggle-password-mask');
    if (btn) {
      btn.innerHTML = state.credentials.isPasswordMasked ? '<span>Reveal</span>' : '<span>Mask</span>';
    }
    renderCredentialsUI();
  }

  // -------------------------------------------------------------------------
  // Telemetry Polling: Queue & History Tables
  // -------------------------------------------------------------------------
  async function pollTransfers() {
    try {
      let resp = await fetch('/api/transfers');
      if (!resp.ok) {
        resp = await fetch('/api/status');
      }
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const data = await resp.json();
      setConnectionStatus(true);
      renderQueue(data.active || []);
      renderHistory(data.completed || data.recent || []);
    } catch (err) {
      console.warn('[PC Hub] Telemetry polling error:', err);
      setConnectionStatus(false);
    }
  }

  function renderQueue(activeJobs) {
    const tbody = document.getElementById('pc-queue-tbody');
    const countBadge = document.getElementById('queue-count-badge');
    if (!tbody) return;

    if (countBadge) {
      countBadge.textContent = `${activeJobs.length} Active`;
    }

    if (activeJobs.length === 0) {
      tbody.innerHTML = `
        <tr class="empty-row">
          <td colspan="4" class="empty-state">No active downloads in queue.</td>
        </tr>`;
      return;
    }

    tbody.innerHTML = activeJobs.map(job => {
      const urlText = escapeHtml(job.url || job.title || 'Unknown');
      const formatLabel = escapeHtml(job.format_label || (job.format_type === 'audio' ? 'MP3' : 'MP4'));
      const targetDir = escapeHtml(job.target_dir || job.target_folder || 'Default');
      const statusText = escapeHtml(job.status || 'queued').toUpperCase();

      let badgeClass = 'queued';
      if (job.status === 'downloading' || job.status === 'ingesting') {
        badgeClass = 'downloading';
      }

      return `
        <tr>
          <td class="cell-url" title="${urlText}">${urlText}</td>
          <td><span class="format-pill">${formatLabel}</span></td>
          <td class="cell-path" title="${targetDir}">${targetDir}</td>
          <td><span class="status-badge ${badgeClass}">${statusText}</span></td>
        </tr>`;
    }).join('');
  }

  function renderHistory(completedJobs) {
    const tbody = document.getElementById('pc-history-tbody');
    const countBadge = document.getElementById('history-count-badge');
    if (!tbody) return;

    if (countBadge) {
      countBadge.textContent = `${completedJobs.length} Completed`;
    }

    if (completedJobs.length === 0) {
      tbody.innerHTML = `
        <tr class="empty-row">
          <td colspan="4" class="empty-state">No completed downloads yet.</td>
        </tr>`;
      return;
    }

    tbody.innerHTML = completedJobs.map(job => {
      const fileName = escapeHtml(job.filename || job.title || 'Completed Download');
      const saveLoc = escapeHtml(job.target_dir || '—');
      const compTime = formatCompletionTime(job.completed_at);
      const jobId = escapeHtml(job.id || job.job_id || '');

      return `
        <tr>
          <td class="cell-url" title="${fileName}">${fileName}</td>
          <td class="cell-path" title="${saveLoc}">${saveLoc}</td>
          <td class="cell-time">${compTime}</td>
          <td>
            <button type="button" class="btn-open-folder" data-job-id="${jobId}" aria-label="Open folder for ${fileName}">
              Open in Folder
            </button>
          </td>
        </tr>`;
    }).join('');
  }

  // -------------------------------------------------------------------------
  // Open in Folder Action
  // -------------------------------------------------------------------------
  async function handleOpenInFolder(e) {
    const btn = e.target.closest('.btn-open-folder');
    if (!btn) return;

    const jobId = btn.getAttribute('data-job-id');
    if (!jobId) return;

    const originalText = btn.textContent;
    btn.textContent = 'Opening...';
    btn.disabled = true;

    try {
      const resp = await fetch(`/api/transfers/${encodeURIComponent(jobId)}/open`, {
        method: 'POST',
      });
      if (resp.ok) {
        btn.textContent = '✓ Opened';
        btn.classList.add('success');
        showToast('Folder opened in Windows File Explorer', true);
        setTimeout(() => {
          btn.textContent = originalText;
          btn.classList.remove('success');
          btn.disabled = false;
        }, 2000);
      } else {
        const err = await resp.json().catch(() => ({}));
        btn.textContent = 'Failed';
        showToast(err.detail || 'Could not open folder', false);
        setTimeout(() => {
          btn.textContent = originalText;
          btn.disabled = false;
        }, 2000);
      }
    } catch (err) {
      btn.textContent = 'Error';
      showToast('Network error opening folder', false);
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
      }, 2000);
    }
  }

  // -------------------------------------------------------------------------
  // Initialization
  // -------------------------------------------------------------------------
  function init() {
    // Event Listeners
    const btnCreds = document.getElementById('btn-toggle-credentials');
    if (btnCreds) {
      btnCreds.addEventListener('click', toggleCredentialsVisibility);
    }

    const btnMask = document.getElementById('btn-toggle-password-mask');
    if (btnMask) {
      btnMask.addEventListener('click', togglePasswordMask);
    }

    const btnRefQueue = document.getElementById('btn-refresh-queue');
    if (btnRefQueue) {
      btnRefQueue.addEventListener('click', pollTransfers);
    }

    const btnRefHist = document.getElementById('btn-refresh-history');
    if (btnRefHist) {
      btnRefHist.addEventListener('click', pollTransfers);
    }

    const historyTbody = document.getElementById('pc-history-tbody');
    if (historyTbody) {
      historyTbody.addEventListener('click', handleOpenInFolder);
    }

    // Initial Fetch & Polling
    fetchCredentials();
    pollTransfers();

    state.pollingTimer = setInterval(pollTransfers, state.pollingIntervalMs);
  }

  // DOM Ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
