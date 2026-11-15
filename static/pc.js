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
  // Download Folders Management
  // -------------------------------------------------------------------------
  async function fetchSharedFolders() {
    try {
      const resp = await fetch('/api/shared-folders');
      if (resp.ok) {
        const data = await resp.json();
        const folders = data.shared_folders || data.folders || [];
        renderFolders(folders);
      }
    } catch (err) {
      console.warn('[PC Hub] Failed to fetch shared folders:', err);
    }
  }

  function renderFolders(folders) {
    const tbody = document.getElementById('pc-folders-tbody');
    const countBadge = document.getElementById('folders-count-badge');
    if (!tbody) return;

    if (countBadge) {
      countBadge.textContent = `${folders.length} Folders`;
    }

    if (folders.length === 0) {
      tbody.innerHTML = `
        <tr class="empty-row">
          <td colspan="4" class="empty-state">No allowed folders configured. Add a folder to enable downloads.</td>
        </tr>`;
      return;
    }

    tbody.innerHTML = folders.map(folder => {
      const name = escapeHtml(folder.name || '');
      const path = escapeHtml(folder.path || '');
      const exists = Boolean(folder.exists);
      const isDefault = Boolean(folder.is_default);
      const subs = Array.isArray(folder.subfolders) ? folder.subfolders : [];

      const subfoldersDropdownHtml = subs.length > 0 ? `
        <details class="subfolders-dropdown">
          <summary class="subfolders-dropdown-toggle" title="Click to view all ${subs.length} subfolders">
            <span>📁 ${subs.length} Subfolder${subs.length > 1 ? 's' : ''}</span>
            <span class="dropdown-caret">▾</span>
          </summary>
          <div class="subfolders-dropdown-menu">
            <div class="subfolders-menu-header">
              <span>Folders inside ${name} (${subs.length})</span>
            </div>
            <div class="subfolders-scroll-list">
              ${subs.map(s => {
                const subPath = `${path}\\${s.replace(/\//g, '\\')}`;
                return `
                  <div class="subfolder-row">
                    <span class="subfolder-name" title="${name} / ${escapeHtml(s)}">📂 ${escapeHtml(s)}</span>
                    <button type="button" class="btn-open-subfolder" data-path="${escapeHtml(subPath)}" title="Open ${escapeHtml(s)} in Explorer">
                      Open
                    </button>
                  </div>
                `;
              }).join('')}
            </div>
          </div>
        </details>
      ` : '';

      return `
        <tr>
          <td class="cell-url">
            <div class="folder-name-row">
              <span class="folder-name-text">${name}</span>
              ${isDefault ? '<span class="default-pill">DEFAULT</span>' : ''}
            </div>
            ${subfoldersDropdownHtml}
          </td>
          <td class="cell-path" title="${path}">${path}</td>
          <td>
            <span class="status-badge ${exists ? 'downloading' : 'queued'}">${exists ? 'ACTIVE' : 'READY'}</span>
          </td>
          <td class="cell-actions">
            <button type="button" class="btn-action-sm btn-open-folder-path" data-path="${path}" title="Open folder in Explorer">
              📂 Open
            </button>
            <button type="button" class="btn-action-sm btn-danger btn-remove-folder" data-name="${name}" title="Remove access to this folder">
              🗑️
            </button>
          </td>
        </tr>`;
    }).join('');
  }

  function toggleAddFolderSection() {
    const section = document.getElementById('add-folder-section');
    const btn = document.getElementById('btn-toggle-add-folder');
    if (!section) return;

    const isHidden = section.classList.contains('hidden');
    if (isHidden) {
      section.classList.remove('hidden');
      if (btn) btn.innerHTML = '<span>✕ Close</span>';
      const nameInput = document.getElementById('pc-folder-name-input');
      if (nameInput) nameInput.focus();
    } else {
      section.classList.add('hidden');
      if (btn) btn.innerHTML = '<span>➕ Allow New Folder</span>';
    }
  }

  async function handleBrowseFolder() {
    const btn = document.getElementById('btn-browse-folder');
    const originalText = btn ? btn.innerHTML : '';
    if (btn) {
      btn.innerHTML = '<span>⏳ Browsing...</span>';
      btn.disabled = true;
    }

    try {
      const resp = await fetch('/api/dialog/pick-folder', { method: 'POST' });
      if (resp.ok) {
        const data = await resp.json();
        if (data.status === 'selected' && data.path) {
          const pathInput = document.getElementById('pc-folder-path-input');
          const nameInput = document.getElementById('pc-folder-name-input');
          if (pathInput) pathInput.value = data.path;
          if (nameInput && !nameInput.value.trim() && data.name) {
            nameInput.value = data.name;
          }
          showToast(`Selected folder: ${data.name || data.path}`);
        }
      } else {
        showToast('Could not open Windows folder browser', false);
      }
    } catch (err) {
      showToast('Error opening folder picker', false);
    } finally {
      if (btn) {
        btn.innerHTML = originalText || '<span>📂 Browse PC...</span>';
        btn.disabled = false;
      }
    }
  }

  async function handleAddFolderSubmit(e) {
    e.preventDefault();
    const nameInput = document.getElementById('pc-folder-name-input');
    const pathInput = document.getElementById('pc-folder-path-input');
    const submitBtn = document.getElementById('btn-submit-folder');

    const name = nameInput ? nameInput.value.trim() : '';
    const path = pathInput ? pathInput.value.trim() : '';

    if (!name || !path) {
      showToast('Please provide both a folder name and path', false);
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span>Adding...</span>';
    }

    try {
      const resp = await fetch('/api/shared-folders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, path }),
      });

      if (resp.ok) {
        showToast(`✓ Allowed folder "${name}" for downloads!`);
        if (nameInput) nameInput.value = '';
        if (pathInput) pathInput.value = '';
        toggleAddFolderSection();
        await fetchSharedFolders();
      } else {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail || 'Failed to add folder', false);
      }
    } catch (err) {
      showToast('Network error adding folder', false);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<span>Allow Access</span>';
      }
    }
  }

  async function handleFolderTableClick(e) {
    // 1. Remove folder
    const removeBtn = e.target.closest('.btn-remove-folder');
    if (removeBtn) {
      const name = removeBtn.getAttribute('data-name');
      if (!name) return;
      if (!confirm(`Are you sure you want to remove access to folder "${name}"? Phone will no longer be able to download to it.`)) {
        return;
      }
      try {
        const resp = await fetch(`/api/shared-folders/${encodeURIComponent(name)}`, {
          method: 'DELETE',
        });
        if (resp.ok) {
          showToast(`✓ Removed folder access: "${name}"`);
          await fetchSharedFolders();
        } else {
          const err = await resp.json().catch(() => ({}));
          showToast(err.detail || 'Could not remove folder', false);
        }
      } catch (err) {
        showToast('Network error removing folder', false);
      }
      return;
    }

    // 2. Open folder path in Explorer
    const openBtn = e.target.closest('.btn-open-folder-path');
    if (openBtn) {
      const path = openBtn.getAttribute('data-path');
      if (!path) return;
      try {
        const resp = await fetch('/api/open-folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path }),
        });
        if (resp.ok) {
          showToast('Folder opened in Windows File Explorer');
        } else {
          showToast('Could not open folder in Explorer', false);
        }
      } catch (_) {
        showToast('Network error opening folder', false);
      }
      return;
    }

    // 3. Open specific subfolder in Explorer
    const openSubBtn = e.target.closest('.btn-open-subfolder');
    if (openSubBtn) {
      const path = openSubBtn.getAttribute('data-path');
      if (!path) return;
      try {
        const resp = await fetch('/api/open-folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path }),
        });
        if (resp.ok) {
          showToast(`✓ Opened in Explorer: ${path}`);
        } else {
          showToast('Could not open subfolder in Explorer', false);
        }
      } catch (_) {
        showToast('Network error opening subfolder', false);
      }
      return;
    }
  }

  // -------------------------------------------------------------------------
  // Settings Modal & Server Lifecycle Controls
  // -------------------------------------------------------------------------
  function openSettingsModal() {
    const modal = document.getElementById('pc-settings-modal');
    if (modal) {
      modal.classList.remove('hidden');
      document.body.style.overflow = 'hidden';
    }
  }

  function closeSettingsModal() {
    const modal = document.getElementById('pc-settings-modal');
    if (modal) {
      modal.classList.add('hidden');
      document.body.style.overflow = '';
    }
  }

  async function handleCopyLanUrl() {
    const url = state.credentials.connectionUrl;
    if (!url) return;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(url);
      } else {
        const ta = document.createElement('textarea');
        ta.value = url;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      showToast('✓ LAN URL copied to clipboard');
    } catch (_) {
      showToast('Could not copy URL to clipboard', false);
    }
  }

  async function handleStopServer() {
    const btn = document.getElementById('btn-stop-server');
    const msg = document.getElementById('server-stopping-message');
    const statusText = document.getElementById('server-status-subtext');

    if (!confirm('Are you sure you want to shut down the AssetDrop server daemon?')) {
      return;
    }

    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span>Stopping...</span>';
    }

    try {
      const resp = await fetch('/api/server/shutdown', {
        method: 'POST',
      });
      if (resp.ok) {
        if (msg) msg.classList.remove('hidden');
        if (statusText) statusText.textContent = 'Server Stopped (Offline)';
        setConnectionStatus(false);
        showToast('✓ Server shutdown initiated');
        if (state.pollingTimer) {
          clearInterval(state.pollingTimer);
        }
      } else {
        showToast('Could not stop server', false);
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<span>🛑 Stop Server</span>';
        }
      }
    } catch (_) {
      // Server may terminate before returning HTTP or during transport
      if (msg) msg.classList.remove('hidden');
      if (statusText) statusText.textContent = 'Server Stopped';
      setConnectionStatus(false);
      showToast('AssetDrop server stopped');
    }
  }

  // -------------------------------------------------------------------------
  // Initialization
  // -------------------------------------------------------------------------
  function init() {
    // Settings Modal Listeners
    const btnOpenSettings = document.getElementById('btn-open-settings');
    if (btnOpenSettings) {
      btnOpenSettings.addEventListener('click', openSettingsModal);
    }

    const btnCloseSettings = document.getElementById('btn-close-settings');
    if (btnCloseSettings) {
      btnCloseSettings.addEventListener('click', closeSettingsModal);
    }

    const settingsBackdrop = document.getElementById('pc-settings-backdrop');
    if (settingsBackdrop) {
      settingsBackdrop.addEventListener('click', closeSettingsModal);
    }

    const btnCopyLan = document.getElementById('btn-copy-lan-url');
    if (btnCopyLan) {
      btnCopyLan.addEventListener('click', handleCopyLanUrl);
    }

    const btnStopServer = document.getElementById('btn-stop-server');
    if (btnStopServer) {
      btnStopServer.addEventListener('click', handleStopServer);
    }

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeSettingsModal();
      }
    });

    // Event Listeners
    const btnCreds = document.getElementById('btn-toggle-credentials');
    if (btnCreds) {
      btnCreds.addEventListener('click', toggleCredentialsVisibility);
    }

    const btnMask = document.getElementById('btn-toggle-password-mask');
    if (btnMask) {
      btnMask.addEventListener('click', togglePasswordMask);
    }

    // Folder Management Listeners
    const btnToggleAdd = document.getElementById('btn-toggle-add-folder');
    if (btnToggleAdd) {
      btnToggleAdd.addEventListener('click', toggleAddFolderSection);
    }

    const btnCancelAdd = document.getElementById('btn-cancel-add-folder');
    if (btnCancelAdd) {
      btnCancelAdd.addEventListener('click', toggleAddFolderSection);
    }

    const btnBrowse = document.getElementById('btn-browse-folder');
    if (btnBrowse) {
      btnBrowse.addEventListener('click', handleBrowseFolder);
    }

    const addFolderForm = document.getElementById('pc-add-folder-form');
    if (addFolderForm) {
      addFolderForm.addEventListener('submit', handleAddFolderSubmit);
    }

    const foldersTbody = document.getElementById('pc-folders-tbody');
    if (foldersTbody) {
      foldersTbody.addEventListener('click', handleFolderTableClick);
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
    fetchSharedFolders();
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
