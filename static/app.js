/**
 * AssetDrop — Client Application Logic (v2.0)
 *
 * Implements:
 * - Sub-50ms instant optimistic queue feedback & emerald toast
 * - Real-time YouTube regex detection & dynamic format toggle
 * - Rapid clipboard paste with plain-HTTP LAN fallback
 * - PC directory browser modal & preset pinning
 * - Adaptive status tray telemetry polling (2s active / 10s idle)
 * - Constant-time PIN authentication & session management
 * - Service Worker registration & PWA standalone install support
 */

'use strict';

// ============================================================================
// 1. Centralized Application State
// ============================================================================
const AppState = {
  // Authentication & Security (Device Pairing & Tokens)
  pinRequired: false,
  accessPin: localStorage.getItem('assetdrop_pin') || null,
  deviceUid: localStorage.getItem('assetdrop_device_uid') || ('Device-' + Math.random().toString(36).substring(2, 8).toUpperCase()),
  deviceToken: localStorage.getItem('assetdrop_token') || null,
  workstationPw: null,
  isAuthenticated: false,

  // Destination Folders & Presets
  presets: {},
  selectedFolderKey: 'B-Roll (General)',
  customPath: null,

  // Input & Media Classification
  url: '',
  platform: 'generic',
  formatType: 'video',

  // PC Directory Browser Modal State
  browser: {
    isOpen: false,
    drives: [],
    activeDrive: '',
    currentPath: '',
    parentPath: null,
    folders: [],
    isLoading: false,
    error: null,
  },

  // Status Tray Telemetry
  tray: {
    isExpanded: false,
    activeCount: 0,
    activeJobs: [],
    completedJobs: [],
    failedJobs: [],
    optimisticJobs: new Map(),
    pollingTimer: null,
    pollingIntervalMs: 2000,
    isPolling: false,
  },
};

// ============================================================================
// 2. Authoritative Platform Detection Regex Matrix
// ============================================================================
const PLATFORM_REGEX = {
  // Matches youtube.com, youtu.be, m.youtube.com, shorts, embed, watch, etc.
  // Rejects phishing domains like youtube.com.evil.com via (\/|\?|$)
  youtube: /^(https?:\/\/)?([a-zA-Z0-9-]+\.)?(youtube\.com|youtu\.be)(\/|\?|$).*/i,
  instagram: /^(https?:\/\/)?([a-zA-Z0-9-]+\.)?(instagram\.com|instagr\.am)(\/|\?|$).*/i,
  tiktok: /^(https?:\/\/)?([a-zA-Z0-9-]+\.)?tiktok\.com(\/|\?|$).*/i,
  pinterest: /^(https?:\/\/)?([a-zA-Z0-9-]+\.)?(pinterest\.(?:com|[a-z]{2,4}(?:\.[a-z]{2})?)|pin\.it)(\/|\?|$).*/i,
  twitter: /^(https?:\/\/)?([a-zA-Z0-9-]+\.)?(twitter\.com|x\.com)(\/|\?|$).*/i,
};

function detectPlatform(urlStr) {
  const clean = (urlStr || '').trim();
  if (!clean) return null;
  if (PLATFORM_REGEX.youtube.test(clean)) return 'youtube';
  if (PLATFORM_REGEX.instagram.test(clean)) return 'instagram';
  if (PLATFORM_REGEX.tiktok.test(clean)) return 'tiktok';
  if (PLATFORM_REGEX.pinterest.test(clean)) return 'pinterest';
  if (PLATFORM_REGEX.twitter.test(clean)) return 'twitter';
  return 'generic';
}

// ============================================================================
// 3. Centralized Authenticated API Fetch Wrapper
// ============================================================================
async function apiFetch(endpoint, options = {}) {
  options.headers = options.headers || {};

  // Inject Device Bearer Token if available (Section 1)
  const activeToken = localStorage.getItem('assetdrop_device_token') || localStorage.getItem('assetdrop_token') || AppState.deviceToken;
  if (activeToken) {
    options.headers['Authorization'] = `Bearer ${activeToken}`;
    options.headers['X-Device-Token'] = activeToken;
  }

  // Inject stored PIN header if available
  if (AppState.accessPin) {
    options.headers['X-Access-PIN'] = AppState.accessPin;
  }

  // Auto-set JSON Content-Type for string bodies
  if (options.body && typeof options.body === 'string' && !options.headers['Content-Type']) {
    options.headers['Content-Type'] = 'application/json';
  }

  let response;
  try {
    response = await fetch(endpoint, options);
  } catch (netErr) {
    console.warn(`[AssetDrop API] Network error on ${endpoint}:`, netErr);
    throw new Error('Could not connect to host server. Check Wi-Fi or Tailscale connection.');
  }

  // Trap 401 Unauthorized globally (Section 2 & 8: invalidate stored token, never show password prompt)
  if (response.status === 401) {
    AppState.isAuthenticated = false;
    AppState.deviceToken = null;
    localStorage.removeItem('assetdrop_device_token');
    localStorage.removeItem('assetdrop_token');
    if (typeof renderCurrentView === 'function') {
      renderCurrentView();
    }
    showToast('Workstation authorization required. Please scan QR code on PC.', 'error', 3500);
    throw new Error('Authentication required (401)');
  }

  // Handle non-2xx responses
  if (!response.ok) {
    const errorJson = await response.json().catch(() => ({}));
    const message = errorJson.detail || `Server error (${response.status})`;
    throw new Error(message);
  }

  return response.json();
}

// ============================================================================
// 4. Toast Notification System (< 50ms Feedback)
// ============================================================================
let toastTimer = null;

function showToast(message, type = 'success', durationMs = 2500) {
  const toast = document.getElementById('toast');
  const toastIcon = document.getElementById('toast-icon');
  const toastMessage = document.getElementById('toast-message');
  if (!toast || !toastMessage) return;

  if (toastTimer) {
    clearTimeout(toastTimer);
    toastTimer = null;
  }

  // Set icon according to notification type
  if (toastIcon) {
    if (type === 'success') {
      toastIcon.textContent = '✓';
    } else if (type === 'error') {
      toastIcon.textContent = '✕';
    } else if (type === 'warning') {
      toastIcon.textContent = '⚠️';
    } else {
      toastIcon.textContent = 'ℹ';
    }
  }

  toastMessage.textContent = message;

  if (type === 'error') {
    toast.classList.add('toast-error');
  } else {
    toast.classList.remove('toast-error');
  }

  toast.classList.add('show');

  toastTimer = setTimeout(() => {
    toast.classList.remove('show');
    toastTimer = null;
  }, durationMs);
}

// ============================================================================
// 5. Dynamic URL Detection & Format Toggle UI
// ============================================================================
function handleUrlInputChange() {
  const urlInput = document.getElementById('url-input');
  const clearBtn = document.getElementById('clear-url-btn');
  const ytFormatContainer = document.getElementById('youtube-format-container');
  const directQualityBadge = document.getElementById('direct-quality-badge');

  if (!urlInput) return;

  const rawUrl = urlInput.value.trim();
  AppState.url = rawUrl;

  // Toggle clear button
  if (clearBtn) {
    clearBtn.classList.toggle('hidden', rawUrl.length === 0);
  }

  if (!rawUrl) {
    if (ytFormatContainer) ytFormatContainer.classList.add('hidden');
    if (directQualityBadge) directQualityBadge.classList.add('hidden');
    AppState.platform = 'generic';
    AppState.formatType = 'video';
    return;
  }

  const detected = detectPlatform(rawUrl);
  AppState.platform = detected || 'generic';

  if (detected === 'youtube') {
    if (ytFormatContainer) ytFormatContainer.classList.remove('hidden');
    if (directQualityBadge) directQualityBadge.classList.add('hidden');
  } else {
    if (ytFormatContainer) ytFormatContainer.classList.add('hidden');
    if (directQualityBadge) directQualityBadge.classList.remove('hidden');
    AppState.formatType = 'video';
  }
}

function setFormat(formatType) {
  AppState.formatType = formatType;
  const videoBtn = document.getElementById('format-video-btn');
  const audioBtn = document.getElementById('format-audio-btn');

  if (videoBtn) {
    const isVideo = formatType === 'video';
    videoBtn.classList.toggle('active', isVideo);
    videoBtn.setAttribute('aria-checked', String(isVideo));
  }
  if (audioBtn) {
    const isAudio = formatType === 'audio';
    audioBtn.classList.toggle('active', isAudio);
    audioBtn.setAttribute('aria-checked', String(isAudio));
  }
}

// ============================================================================
// 6. Rapid Clipboard Paste with Plain-HTTP LAN Fallback
// ============================================================================
async function handleClipboardPaste() {
  const urlInput = document.getElementById('url-input');
  if (!urlInput) return;

  // 1. Modern Asynchronous Clipboard API (HTTPS or localhost)
  if (navigator.clipboard && typeof navigator.clipboard.readText === 'function') {
    try {
      const text = await navigator.clipboard.readText();
      const cleanText = (text || '').trim();
      if (cleanText) {
        urlInput.value = cleanText;
        handleUrlInputChange();
        urlInput.focus();
        showToast('Pasted from clipboard', 'info', 1500);
        return;
      } else {
        showToast('Clipboard is empty or contains no URL', 'warning', 2000);
        return;
      }
    } catch (err) {
      console.warn('[AssetDrop] Async clipboard read error (likely plain HTTP LAN context):', err);
    }
  }

  // 2. Plain-HTTP Fallback Protocol for Local LAN Access (http://192.168.x.x:8000)
  urlInput.focus();
  urlInput.select();

  let legacySuccess = false;
  try {
    legacySuccess = document.execCommand('paste');
  } catch (e) {
    legacySuccess = false;
  }

  if (legacySuccess && urlInput.value.trim()) {
    handleUrlInputChange();
    showToast('Pasted from clipboard', 'info', 1500);
    return;
  }

  showToast('Clipboard blocked over HTTP: Long-press input & tap Paste', 'warning', 3500);
}

// ============================================================================
// 7. Sub-50ms Instant Queue Submission Architecture
// ============================================================================
async function handleQueueSubmit(event) {
  if (event) event.preventDefault();

  const urlInput = document.getElementById('url-input');
  if (!urlInput) return;

  const url = urlInput.value.trim();
  if (!url) {
    urlInput.classList.remove('shake');
    void urlInput.offsetWidth; // Force CSS reflow
    urlInput.classList.add('shake');
    setTimeout(() => urlInput.classList.remove('shake'), 400);
    showToast('Please paste or enter a media URL', 'warning', 2500);
    urlInput.focus();
    return;
  }

  // Synchronous State Preparation (< 5ms)
  const tempId = 'opt_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7);
  const folderKey = AppState.customPath ? null : AppState.selectedFolderKey;
  const customPath = AppState.customPath;
  const targetDir = customPath || AppState.presets[folderKey] || folderKey || 'D:/Assets/BRoll';
  const formatType = AppState.platform === 'youtube' ? AppState.formatType : 'video';
  const platform = AppState.platform;

  const optimisticJob = {
    id: tempId,
    temp_id: tempId,
    url: url,
    platform: platform,
    format_type: formatType,
    target_dir: targetDir,
    status: 'queued',
    filename: null,
    progress: 0.0,
    speed: null,
    eta: null,
    error: null,
    created_at: Date.now() / 1000,
    isOptimistic: true,
  };

  AppState.tray.optimisticJobs.set(tempId, optimisticJob);

  // Synchronously clear input and reset dynamic format UI
  urlInput.value = '';
  handleUrlInputChange();

  // Instant Emerald Toast (< 16ms render)
  showToast('Job Queued!', 'success', 2000);

  // Prepend card to active list and update counters
  renderOptimisticJobCard(optimisticJob);
  updateTraySummary();

  // Start active polling immediately
  startStatusPolling(true);

  // Asynchronous Background Queue Dispatch
  try {
    const payload = {
      url: url,
      folder_key: folderKey,
      format_type: formatType,
      custom_path: customPath,
    };

    let data;
    try {
      data = await apiFetch('/api/queue', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    } catch (err) {
      // Fallback route alias support (/download)
      if (err.message && err.message.includes('404')) {
        data = await apiFetch('/download', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      } else {
        throw err;
      }
    }

    // Update optimistic card with server-assigned Job ID
    if (data && data.job_id) {
      const realId = data.job_id;
      optimisticJob.id = realId;
      optimisticJob.status = data.status || 'queued';

      const cardEl = document.getElementById(`job-card-${tempId}`);
      if (cardEl) {
        cardEl.id = `job-card-${realId}`;
        cardEl.dataset.jobId = realId;
      }

      // Schedule immediate status telemetry refresh
      pollTelemetryStatus();
    }
  } catch (err) {
    console.error('[AssetDrop] Ingestion dispatch failed:', err);
    optimisticJob.status = 'failed';
    optimisticJob.error = err.message || 'Dispatch failed';

    // Update DOM card to show error state
    renderOptimisticJobCard(optimisticJob);
    updateTraySummary();
    showToast(err.message || 'Failed to queue download', 'error', 4000);
  }
}

// ============================================================================
// 8. Preset Folders Management
// ============================================================================
async function loadPresets() {
  try {
    let data;
    try {
      data = await apiFetch('/api/presets');
    } catch (e) {
      data = await apiFetch('/folders');
    }

    const presetsMap = data.presets || {};
    AppState.presets = presetsMap;

    renderPresetChips();
  } catch (err) {
    console.warn('[AssetDrop] Could not fetch presets from server:', err);
    // Retain default preset fallback
    AppState.presets = {
      'B-Roll (General)': 'D:/Assets/BRoll',
      'Social Edits': 'D:/Assets/Social',
      'Sound Effects': 'D:/Assets/SFX',
      'Background Music': 'D:/Assets/Music',
    };
    renderPresetChips();
  }
}

function renderPresetChips() {
  const container = document.getElementById('preset-chips-container');
  const browseBtn = document.getElementById('browse-pc-btn');
  const selectedDisplay = document.getElementById('selected-folder-display');
  if (!container) return;

  // Preserve the browse PC button
  const browseBtnHtml = browseBtn ? browseBtn.outerHTML : `
    <button type="button" id="browse-pc-btn" class="preset-chip chip-browse" aria-label="Browse PC Directories">
      <span class="chip-icon">📁</span>
      <span class="chip-text">Browse PC...</span>
    </button>
  `;

  const presetEntries = Object.entries(AppState.presets);
  if (presetEntries.length > 0 && !AppState.presets[AppState.selectedFolderKey] && !AppState.customPath) {
    AppState.selectedFolderKey = presetEntries[0][0];
  }

  let html = '';
  presetEntries.forEach(([key, path]) => {
    const isActive = !AppState.customPath && key === AppState.selectedFolderKey;
    const icon = getPresetIcon(key);
    html += `
      <button
        type="button"
        class="preset-chip ${isActive ? 'active' : ''}"
        role="radio"
        aria-checked="${isActive}"
        data-folder="${escapeHtml(key)}"
      >
        <span class="chip-icon">${icon}</span>
        <span class="chip-text">${escapeHtml(key)}</span>
      </button>
    `;
  });

  html += browseBtnHtml;
  container.innerHTML = html;

  // Re-bind click events
  container.querySelectorAll('.preset-chip[data-folder]').forEach((chip) => {
    chip.addEventListener('click', () => {
      const folderKey = chip.getAttribute('data-folder');
      selectPreset(folderKey);
    });
  });

  const newBrowseBtn = document.getElementById('browse-pc-btn');
  if (newBrowseBtn) {
    newBrowseBtn.addEventListener('click', openDirectoryBrowser);
  }

  if (selectedDisplay) {
    selectedDisplay.textContent = AppState.customPath
      ? pathBasename(AppState.customPath)
      : AppState.selectedFolderKey;
  }
}

function getPresetIcon(label) {
  const lower = (label || '').toLowerCase();
  if (lower.includes('b-roll') || lower.includes('video')) return '🎥';
  if (lower.includes('social') || lower.includes('edit')) return '📱';
  if (lower.includes('sound') || lower.includes('sfx')) return '🔊';
  if (lower.includes('music') || lower.includes('audio')) return '🎵';
  return '📁';
}

function selectPreset(folderKey) {
  AppState.selectedFolderKey = folderKey;
  AppState.customPath = null;

  // Hide custom path banner
  const customBanner = document.getElementById('custom-dir-banner');
  if (customBanner) customBanner.classList.add('hidden');

  const selectedDisplay = document.getElementById('selected-folder-display');
  if (selectedDisplay) selectedDisplay.textContent = folderKey;

  const container = document.getElementById('preset-chips-container');
  if (container) {
    container.querySelectorAll('.preset-chip[data-folder]').forEach((chip) => {
      const match = chip.getAttribute('data-folder') === folderKey;
      chip.classList.toggle('active', match);
      chip.setAttribute('aria-checked', String(match));
    });
  }
}

function resetCustomDirectory() {
  AppState.customPath = null;
  const customBanner = document.getElementById('custom-dir-banner');
  if (customBanner) customBanner.classList.add('hidden');

  const firstPreset = Object.keys(AppState.presets)[0] || 'B-Roll (General)';
  selectPreset(firstPreset);
  showToast('Reset to default preset', 'info', 1500);
}

// ============================================================================
// 9. Sliding Bottom Sheet PC Directory Browser
// ============================================================================
function openDirectoryBrowser() {
  const sheet = document.getElementById('pc-browser-sheet');
  const backdrop = document.getElementById('sheet-backdrop');
  if (!sheet || !backdrop) return;

  AppState.browser.isOpen = true;
  backdrop.classList.add('active');
  sheet.classList.add('open');

  if (AppState.browser.drives.length === 0) {
    loadDrivesAndBrowse();
  } else {
    browseDirectoryPath(AppState.browser.currentPath || AppState.browser.activeDrive);
  }
}

function closeDirectoryBrowser() {
  const sheet = document.getElementById('pc-browser-sheet');
  const backdrop = document.getElementById('sheet-backdrop');
  if (!sheet || !backdrop) return;

  AppState.browser.isOpen = false;
  sheet.classList.remove('open');
  backdrop.classList.remove('active');
}

async function loadDrivesAndBrowse() {
  try {
    const data = await apiFetch('/api/drives');
    const drives = data.drives || ['C:\\'];
    AppState.browser.drives = drives;

    // Pick D:\ if available, else first drive
    const preferredDrive = drives.find((d) => d.toUpperCase().startsWith('D')) || drives[0];
    AppState.browser.activeDrive = preferredDrive;

    renderDrivesList();
    browseDirectoryPath(preferredDrive);
  } catch (err) {
    console.warn('[AssetDrop] Failed to load drives, falling back to C:\\:', err);
    AppState.browser.drives = ['C:\\', 'D:\\'];
    AppState.browser.activeDrive = 'C:\\';
    renderDrivesList();
    browseDirectoryPath('C:\\');
  }
}

function renderDrivesList() {
  const drivesContainer = document.getElementById('sheet-drives-list');
  if (!drivesContainer) return;

  drivesContainer.innerHTML = AppState.browser.drives
    .map((drive) => {
      const isActive = drive.toUpperCase() === (AppState.browser.activeDrive || '').toUpperCase();
      return `
        <button
          type="button"
          class="drive-btn ${isActive ? 'active' : ''}"
          data-drive="${escapeHtml(drive)}"
        >
          ${escapeHtml(drive)}
        </button>
      `;
    })
    .join('');

  drivesContainer.querySelectorAll('.drive-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const drive = btn.getAttribute('data-drive');
      AppState.browser.activeDrive = drive;
      renderDrivesList();
      browseDirectoryPath(drive);
    });
  });
}

async function browseDirectoryPath(targetPath) {
  const spinner = document.getElementById('sheet-loading-spinner');
  const errorMsg = document.getElementById('sheet-error-msg');
  const folderList = document.getElementById('sheet-folder-list');
  const currentPathText = document.getElementById('sheet-current-path-text');
  const upBtn = document.getElementById('sheet-up-btn');

  if (spinner) spinner.classList.remove('hidden');
  if (errorMsg) errorMsg.classList.add('hidden');
  if (folderList) folderList.innerHTML = '';

  try {
    const encoded = encodeURIComponent(targetPath || '');
    const data = await apiFetch(`/api/browse?path=${encoded}`);

    AppState.browser.currentPath = data.current || targetPath;
    AppState.browser.parentPath = data.parent || null;
    AppState.browser.folders = data.folders || data.subdirectories || [];

    // Match drive in active drives list
    const driveMatch = AppState.browser.currentPath.match(/^([a-zA-Z]:\\?)/);
    if (driveMatch) {
      const driveRoot = driveMatch[1].toUpperCase().replace(/\\$/, '') + '\\';
      if (driveRoot !== AppState.browser.activeDrive) {
        AppState.browser.activeDrive = driveRoot;
        renderDrivesList();
      }
    }

    if (currentPathText) {
      currentPathText.textContent = AppState.browser.currentPath;
      currentPathText.title = AppState.browser.currentPath;
    }

    if (upBtn) {
      upBtn.disabled = !AppState.browser.parentPath;
      upBtn.style.opacity = AppState.browser.parentPath ? '1' : '0.4';
      upBtn.style.pointerEvents = AppState.browser.parentPath ? 'auto' : 'none';
    }

    renderSubfolderList();
  } catch (err) {
    console.warn('[AssetDrop] Browse directory error:', err);
    if (errorMsg) {
      errorMsg.textContent = err.message || 'Access Denied: Unable to browse directory.';
      errorMsg.classList.remove('hidden');
    }
  } finally {
    if (spinner) spinner.classList.add('hidden');
  }
}

function renderSubfolderList() {
  const folderList = document.getElementById('sheet-folder-list');
  if (!folderList) return;

  const folders = AppState.browser.folders || [];
  if (folders.length === 0) {
    folderList.innerHTML = `
      <div style="padding: 24px; text-align: center; color: var(--text-dim); font-size: 13.5px;">
        📂 No subdirectories in this folder.<br/>
        <span style="font-size: 12px; color: var(--text-muted);">You can select or pin this folder below.</span>
      </div>
    `;
    return;
  }

  folderList.innerHTML = folders
    .map((name) => `
      <div class="dir-item" role="button" tabindex="0" data-folder-name="${escapeHtml(name)}">
        <div class="dir-item-left">
          <span class="dir-icon">📁</span>
          <span class="dir-name">${escapeHtml(name)}</span>
        </div>
        <span class="dir-arrow">›</span>
      </div>
    `)
    .join('');

  folderList.querySelectorAll('.dir-item').forEach((item) => {
    item.addEventListener('click', () => {
      const folderName = item.getAttribute('data-folder-name');
      const cur = AppState.browser.currentPath;
      const separator = cur.endsWith('\\') || cur.endsWith('/') ? '' : '\\';
      const nextPath = cur + separator + folderName;
      browseDirectoryPath(nextPath);
    });
  });
}

function handleSheetUpClick() {
  if (AppState.browser.parentPath) {
    browseDirectoryPath(AppState.browser.parentPath);
  }
}

function handleSelectFolderFromBrowser() {
  const chosenPath = AppState.browser.currentPath;
  if (!chosenPath) return;

  AppState.customPath = chosenPath;

  const customBanner = document.getElementById('custom-dir-banner');
  const customPathVal = document.getElementById('custom-dir-path');
  const selectedDisplay = document.getElementById('selected-folder-display');

  if (customPathVal) customPathVal.textContent = chosenPath;
  if (customBanner) customBanner.classList.remove('hidden');
  if (selectedDisplay) selectedDisplay.textContent = pathBasename(chosenPath);

  // Uncheck presets
  const container = document.getElementById('preset-chips-container');
  if (container) {
    container.querySelectorAll('.preset-chip[data-folder]').forEach((chip) => {
      chip.classList.remove('active');
      chip.setAttribute('aria-checked', 'false');
    });
  }

  closeDirectoryBrowser();
  showToast(`Folder selected: ${pathBasename(chosenPath)}`, 'success', 2500);
}

// ============================================================================
// 10. Pin Preset Dialog Modal
// ============================================================================
function openPinPresetDialog() {
  const modal = document.getElementById('pin-preset-dialog');
  const backdrop = document.getElementById('pin-modal-backdrop');
  const input = document.getElementById('pin-preset-name-input');
  const errorDiv = document.getElementById('pin-dialog-error');

  if (!modal || !backdrop) return;

  const currentFolder = pathBasename(AppState.browser.currentPath) || 'Custom Project';
  if (input) {
    input.value = currentFolder;
  }
  if (errorDiv) errorDiv.classList.add('hidden');

  backdrop.classList.remove('hidden');
  modal.classList.remove('hidden');
  if (input) setTimeout(() => input.focus(), 50);
}

function closePinPresetDialog() {
  const modal = document.getElementById('pin-preset-dialog');
  const backdrop = document.getElementById('pin-modal-backdrop');
  if (modal) modal.classList.add('hidden');
  if (backdrop) backdrop.classList.add('hidden');
}

async function handleConfirmPinPreset() {
  const input = document.getElementById('pin-preset-name-input');
  const errorDiv = document.getElementById('pin-dialog-error');
  if (!input) return;

  const name = input.value.trim();
  if (!name || name.length > 64) {
    if (errorDiv) {
      errorDiv.textContent = 'Preset name must be between 1 and 64 characters.';
      errorDiv.classList.remove('hidden');
    }
    input.classList.remove('shake');
    void input.offsetWidth;
    input.classList.add('shake');
    return;
  }

  try {
    await apiFetch('/api/presets', {
      method: 'POST',
      body: JSON.stringify({
        name: name,
        path: AppState.browser.currentPath,
      }),
    });

    showToast(`Preset "${name}" pinned!`, 'success', 2500);
    closePinPresetDialog();
    closeDirectoryBrowser();

    // Reload presets and select the newly pinned preset
    await loadPresets();
    selectPreset(name);
  } catch (err) {
    console.error('[AssetDrop] Failed to pin preset:', err);
    if (errorDiv) {
      errorDiv.textContent = err.message || 'Failed to pin preset.';
      errorDiv.classList.remove('hidden');
    }
  }
}

// ============================================================================
// 11. Expandable Status Tray & Telemetry Engine
// ============================================================================
function toggleStatusTray() {
  const tray = document.getElementById('status-tray');
  const header = document.getElementById('status-tray-header');
  if (!tray) return;

  AppState.tray.isExpanded = !AppState.tray.isExpanded;
  tray.classList.toggle('expanded', AppState.tray.isExpanded);
  if (header) {
    header.setAttribute('aria-expanded', String(AppState.tray.isExpanded));
  }

  if (AppState.tray.isExpanded) {
    pollTelemetryStatus();
  }
}

function startStatusPolling(forceImmediate = false) {
  if (AppState.tray.pollingTimer) {
    clearTimeout(AppState.tray.pollingTimer);
    AppState.tray.pollingTimer = null;
  }

  if (forceImmediate) {
    pollTelemetryStatus();
  } else {
    scheduleNextPoll();
  }
}

function stopStatusPolling() {
  if (AppState.tray.pollingTimer) {
    clearTimeout(AppState.tray.pollingTimer);
    AppState.tray.pollingTimer = null;
  }
  AppState.tray.isPolling = false;
}

function scheduleNextPoll() {
  if (AppState.tray.pollingTimer) {
    clearTimeout(AppState.tray.pollingTimer);
  }

  // Active poll: 2s when downloads in flight; Idle poll: 10s when quiescent
  const hasInFlight = AppState.tray.activeCount > 0 || AppState.tray.optimisticJobs.size > 0;
  const interval = hasInFlight ? 2000 : 10000;
  AppState.tray.pollingIntervalMs = interval;

  AppState.tray.pollingTimer = setTimeout(async () => {
    await pollTelemetryStatus();
    scheduleNextPoll();
  }, interval);
}

async function pollTelemetryStatus() {
  if (document.hidden) return; // Save mobile battery and data while in background

  try {
    let data;
    try {
      data = await apiFetch('/api/status');
    } catch (e) {
      data = await apiFetch('/status');
    }

    reconcileTelemetry(data);
  } catch (err) {
    console.warn('[AssetDrop] Status polling error:', err);
  }
}

function reconcileTelemetry(data) {
  const serverActive = data.active || [];
  const serverCompleted = data.completed || data.recent || [];
  const serverFailed = data.failed || data.errors || [];

  // Match and reconcile optimistic pending jobs
  AppState.tray.optimisticJobs.forEach((optJob, tempId) => {
    // Check if matched by server job_id or URL
    const activeMatch = serverActive.find(
      (j) => j.id === optJob.id || (j.url && j.url === optJob.url)
    );
    if (activeMatch) {
      AppState.tray.optimisticJobs.delete(tempId);
      return;
    }

    const doneMatch = serverCompleted.find(
      (j) => j.id === optJob.id || (j.url && j.url === optJob.url)
    );
    if (doneMatch) {
      AppState.tray.optimisticJobs.delete(tempId);
      return;
    }

    const failMatch = serverFailed.find(
      (j) => j.id === optJob.id || (j.url && j.url === optJob.url)
    );
    if (failMatch) {
      AppState.tray.optimisticJobs.delete(tempId);
      return;
    }
  });

  AppState.tray.activeJobs = serverActive;
  AppState.tray.completedJobs = serverCompleted;
  AppState.tray.failedJobs = serverFailed;

  AppState.tray.activeCount = serverActive.length + AppState.tray.optimisticJobs.size;

  updateTraySummary();
  renderTrayJobCards();
}

function updateTraySummary() {
  const dot = document.getElementById('tray-status-dot');
  const title = document.getElementById('tray-summary-title');
  const sub = document.getElementById('tray-summary-sub');
  const badgeActive = document.getElementById('tray-badge-active');
  const badgeCompleted = document.getElementById('tray-badge-completed');
  const badgeError = document.getElementById('tray-badge-error');
  const countActiveLabel = document.getElementById('active-count-label');
  const countRecentLabel = document.getElementById('recent-count-label');
  const countErrorsLabel = document.getElementById('errors-count-label');

  const activeCount = AppState.tray.activeCount;
  const completedCount = AppState.tray.completedJobs.length;
  const failedCount = AppState.tray.failedJobs.length;

  if (dot) {
    if (activeCount > 0) {
      dot.className = 'status-pulse-dot active';
    } else {
      dot.className = 'status-pulse-dot idle';
    }
  }

  if (title) {
    if (activeCount > 0) {
      title.textContent = `${activeCount} Active Transfer${activeCount > 1 ? 's' : ''}`;
    } else {
      title.textContent = 'Queue Idle';
    }
  }

  if (sub) {
    if (activeCount > 0) {
      sub.textContent = 'Ingesting in background stealth';
    } else {
      sub.textContent = 'Ready for media URLs';
    }
  }

  if (badgeActive) {
    badgeActive.textContent = `${activeCount} Active`;
    badgeActive.classList.toggle('hidden', activeCount === 0);
  }

  if (badgeCompleted) {
    badgeCompleted.textContent = `${completedCount} Done`;
    badgeCompleted.classList.toggle('hidden', completedCount === 0);
  }

  if (badgeError) {
    badgeError.textContent = `${failedCount} Errors`;
    badgeError.classList.toggle('hidden', failedCount === 0);
  }

  if (countActiveLabel) countActiveLabel.textContent = String(activeCount);
  if (countRecentLabel) countRecentLabel.textContent = String(completedCount);
  if (countErrorsLabel) countErrorsLabel.textContent = String(failedCount);
}

function renderTrayJobCards() {
  const activeList = document.getElementById('tray-active-list');
  const recentList = document.getElementById('tray-recent-list');
  const errorsList = document.getElementById('tray-errors-list');
  const emptyState = document.getElementById('tray-empty-state');

  const activeJobs = [...AppState.tray.optimisticJobs.values(), ...AppState.tray.activeJobs];
  const completedJobs = AppState.tray.completedJobs;
  const failedJobs = AppState.tray.failedJobs;

  const total = activeJobs.length + completedJobs.length + failedJobs.length;
  if (emptyState) {
    emptyState.classList.toggle('hidden', total > 0);
  }

  // Active Cards
  if (activeList) {
    activeList.innerHTML = activeJobs.map(renderActiveJobCardHtml).join('');
  }

  // Recent Completed Cards
  if (recentList) {
    recentList.innerHTML = completedJobs.map(renderCompletedJobCardHtml).join('');
  }

  // Error Cards
  if (errorsList) {
    errorsList.innerHTML = failedJobs.map(renderFailedJobCardHtml).join('');
  }
}

function renderOptimisticJobCard(job) {
  const activeList = document.getElementById('tray-active-list');
  const emptyState = document.getElementById('tray-empty-state');
  if (emptyState) emptyState.classList.add('hidden');
  if (!activeList) return;

  const existing = document.getElementById(`job-card-${job.id}`);
  const html = renderActiveJobCardHtml(job);

  if (existing) {
    existing.outerHTML = html;
  } else {
    activeList.insertAdjacentHTML('afterbegin', html);
  }
}

function renderActiveJobCardHtml(job) {
  const isVideo = (job.format_type || 'video').toLowerCase() === 'video';
  const pillClass = isVideo ? 'pill-video' : 'pill-audio';
  const isIndeterminate = !job.progress || job.progress <= 0;
  const progressPercent = Math.min(100, Math.max(0, job.progress || 0)).toFixed(1);

  return `
    <div class="tray-card" id="job-card-${job.id}" data-job-id="${job.id}">
      <div class="tray-card-top">
        <span class="tray-item-title" title="${escapeHtml(job.url || '')}">
          ${escapeHtml(job.filename || job.url || 'Queued download...')}
        </span>
        <div class="tray-card-badges">
          <span class="tray-pill ${pillClass}">
            ${escapeHtml((job.format_type || 'video').toUpperCase())}
          </span>
        </div>
      </div>
      <div class="tray-progress-container">
        <div class="tray-progress-fill ${isIndeterminate ? 'indeterminate' : ''}" style="width: ${isIndeterminate ? '40%' : progressPercent + '%'}"></div>
      </div>
      <div class="tray-card-meta">
        <span>📁 ${escapeHtml(pathBasename(job.target_dir || 'BRoll'))}</span>
        <span>${isIndeterminate ? 'Queued / Starting...' : progressPercent + '%'} ${job.speed ? '• ' + escapeHtml(job.speed) : ''}</span>
      </div>
    </div>
  `;
}

function renderCompletedJobCardHtml(job) {
  return `
    <div class="tray-card" id="job-card-${job.id}" data-job-id="${job.id}">
      <div class="tray-card-top">
        <span class="tray-item-title" title="${escapeHtml(job.filename || job.url || '')}">
          ✓ ${escapeHtml(job.filename || job.url || 'Media Downloaded')}
        </span>
        <div class="tray-card-badges">
          <span class="tray-pill" style="color: var(--color-emerald); background: var(--color-emerald-bg);">DONE</span>
        </div>
      </div>
      <div class="tray-card-meta">
        <span>📁 ${escapeHtml(pathBasename(job.target_dir || 'Assets'))}</span>
        <span>${escapeHtml(job.platform || 'source')}</span>
      </div>
    </div>
  `;
}

function renderFailedJobCardHtml(job) {
  return `
    <div class="tray-card error-card" id="job-card-${job.id}" data-job-id="${job.id}">
      <div class="tray-card-top">
        <span class="tray-item-title error-text" title="${escapeHtml(job.url || '')}">
          ✕ ${escapeHtml(job.url || 'Download failed')}
        </span>
        <div class="tray-card-badges">
          <span class="tray-pill" style="color: var(--color-crimson); background: var(--color-crimson-bg);">FAILED</span>
        </div>
      </div>
      ${job.error ? `<div class="error-snippet">${escapeHtml(job.error)}</div>` : ''}
      <div class="tray-card-meta">
        <span>📁 ${escapeHtml(pathBasename(job.target_dir || 'Assets'))}</span>
        <span>${escapeHtml(job.platform || 'media')}</span>
      </div>
    </div>
  `;
}

function clearTrayHistory() {
  AppState.tray.completedJobs = [];
  AppState.tray.failedJobs = [];
  AppState.tray.optimisticJobs.clear();
  renderTrayJobCards();
  updateTraySummary();
  showToast('Tray history cleared', 'info', 1500);
}

// ============================================================================
// 12. Security PIN Authentication
// ============================================================================
async function checkAuthStatus() {
  try {
    const data = await apiFetch('/api/auth/status');
    AppState.pinRequired = !!data.pin_required;

    if (!AppState.pinRequired) {
      AppState.isAuthenticated = true;
      initApplicationData();
      return;
    }

    // PIN is required on this host
    if (AppState.accessPin) {
      // Validate cached PIN against backend
      const verifyResp = await fetch('/api/auth/verify', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Access-PIN': AppState.accessPin,
        },
        body: JSON.stringify({ pin: AppState.accessPin }),
      }).catch(() => null);

      if (verifyResp && verifyResp.ok) {
        const verifyData = await verifyResp.json();
        if (verifyData.valid) {
          AppState.isAuthenticated = true;
          initApplicationData();
          return;
        }
      }

      // If stored PIN was invalid, remove it
      AppState.accessPin = null;
      localStorage.removeItem('assetdrop_pin');
    }

    // Display PIN prompt dialog
    showAuthModal();
  } catch (err) {
    console.warn('[AssetDrop] Auth check error:', err);
    initApplicationData();
  }
}

function showAuthModal(customDesc = null) {
  const modal = document.getElementById('auth-dialog');
  const backdrop = document.getElementById('auth-modal-backdrop');
  const errorDiv = document.getElementById('auth-dialog-error');
  const pinInput = document.getElementById('auth-pin-input');

  if (modal && backdrop) {
    if (errorDiv) {
      if (customDesc) {
        errorDiv.textContent = customDesc;
        errorDiv.classList.remove('hidden');
      } else {
        errorDiv.classList.add('hidden');
      }
    }
    backdrop.classList.remove('hidden');
    modal.classList.remove('hidden');
    if (pinInput) setTimeout(() => pinInput.focus(), 60);
  }
}

function hideAuthModal() {
  const modal = document.getElementById('auth-dialog');
  const backdrop = document.getElementById('auth-modal-backdrop');
  if (modal) modal.classList.add('hidden');
  if (backdrop) backdrop.classList.add('hidden');
}

async function handlePinSubmit() {
  const pinInput = document.getElementById('auth-pin-input');
  const errorDiv = document.getElementById('auth-dialog-error');
  if (!pinInput) return;

  const candidate = pinInput.value.trim();
  if (!candidate) {
    pinInput.classList.remove('shake');
    void pinInput.offsetWidth;
    pinInput.classList.add('shake');
    return;
  }

  try {
    const resp = await fetch('/api/auth/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: candidate }),
    });

    const data = await resp.json().catch(() => ({ valid: false }));
    if (data.valid) {
      AppState.accessPin = candidate;
      localStorage.setItem('assetdrop_pin', candidate);
      AppState.isAuthenticated = true;
      hideAuthModal();
      showToast('Authenticated successfully', 'success', 2000);
      initApplicationData();
    } else {
      if (errorDiv) {
        errorDiv.textContent = 'Invalid PIN. Please try again.';
        errorDiv.classList.remove('hidden');
      }
      pinInput.classList.remove('shake');
      void pinInput.offsetWidth;
      pinInput.classList.add('shake');
      pinInput.value = '';
      pinInput.focus();
    }
  } catch (err) {
    if (errorDiv) {
      errorDiv.textContent = err.message || 'Verification failed';
      errorDiv.classList.remove('hidden');
    }
  }
}

// ============================================================================
// 13. PWA Standalone & Service Worker Lifecycle
// ============================================================================
function initPwaCapabilities() {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker
        .register('/sw.js', { scope: '/' })
        .then((reg) => {
          console.log('[AssetDrop PWA] Service Worker registered with scope:', reg.scope);
        })
        .catch((err) => {
          console.warn('[AssetDrop PWA] Service Worker registration failed:', err);
        });
    });
  }

  // Android Chrome Custom Install Prompt Hook
  let deferredInstallPrompt = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    const installBtn = document.getElementById('btn-pwa-install');
    if (installBtn) {
      installBtn.classList.remove('hidden');
      installBtn.addEventListener('click', async () => {
        if (!deferredInstallPrompt) return;
        deferredInstallPrompt.prompt();
        const choice = await deferredInstallPrompt.userChoice;
        if (choice.outcome === 'accepted') {
          console.log('[AssetDrop PWA] User accepted installation prompt');
        }
        deferredInstallPrompt = null;
        installBtn.classList.add('hidden');
      });
    }
  });
}

// ============================================================================
// 14. Utilities & Helpers
// ============================================================================
function escapeHtml(str) {
  if (typeof str !== 'string') return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function pathBasename(pathStr) {
  if (!pathStr) return '';
  const clean = pathStr.replace(/[\\/]+$/, '');
  const parts = clean.split(/[\\/]/);
  return parts[parts.length - 1] || pathStr;
}

// ============================================================================
// 15. Application Bootstrapping
// ============================================================================
function initApplicationData() {
  loadPresets();
  startStatusPolling(true);
}

function initEventBindings() {
  // 1. URL Input & Platform detection
  const urlInput = document.getElementById('url-input');
  const clearUrlBtn = document.getElementById('clear-url-btn');
  const pasteBtn = document.getElementById('paste-btn');
  const submitBtn = document.getElementById('submit-btn');

  if (urlInput) {
    urlInput.addEventListener('input', handleUrlInputChange);
    urlInput.addEventListener('change', handleUrlInputChange);
    urlInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleQueueSubmit();
      }
    });
  }

  if (clearUrlBtn) {
    clearUrlBtn.addEventListener('click', () => {
      if (urlInput) {
        urlInput.value = '';
        handleUrlInputChange();
        urlInput.focus();
      }
    });
  }

  if (pasteBtn) {
    pasteBtn.addEventListener('click', handleClipboardPaste);
  }

  if (submitBtn) {
    submitBtn.addEventListener('click', handleQueueSubmit);
  }

  // 2. Format Segmented Controls
  const videoBtn = document.getElementById('format-video-btn');
  const audioBtn = document.getElementById('format-audio-btn');
  if (videoBtn) videoBtn.addEventListener('click', () => setFormat('video'));
  if (audioBtn) audioBtn.addEventListener('click', () => setFormat('audio'));

  // 3. Custom directory banner reset
  const resetDirBtn = document.getElementById('reset-custom-dir-btn');
  if (resetDirBtn) {
    resetDirBtn.addEventListener('click', resetCustomDirectory);
  }

  // 4. PC Directory Browser Modal
  const sheetCloseBtn = document.getElementById('sheet-close-btn');
  const sheetBackdrop = document.getElementById('sheet-backdrop');
  const sheetUpBtn = document.getElementById('sheet-up-btn');
  const sheetSelectBtn = document.getElementById('sheet-select-btn');
  const sheetPinBtn = document.getElementById('sheet-pin-btn');

  if (sheetCloseBtn) sheetCloseBtn.addEventListener('click', closeDirectoryBrowser);
  if (sheetBackdrop) sheetBackdrop.addEventListener('click', closeDirectoryBrowser);
  if (sheetUpBtn) sheetUpBtn.addEventListener('click', handleSheetUpClick);
  if (sheetSelectBtn) sheetSelectBtn.addEventListener('click', handleSelectFolderFromBrowser);
  if (sheetPinBtn) sheetPinBtn.addEventListener('click', openPinPresetDialog);

  // 5. Pin Preset Dialog
  const pinDialogCloseBtn = document.getElementById('pin-dialog-close-btn');
  const pinDialogCancelBtn = document.getElementById('pin-dialog-cancel-btn');
  const pinDialogConfirmBtn = document.getElementById('pin-dialog-confirm-btn');
  const pinNameInput = document.getElementById('pin-preset-name-input');

  if (pinDialogCloseBtn) pinDialogCloseBtn.addEventListener('click', closePinPresetDialog);
  if (pinDialogCancelBtn) pinDialogCancelBtn.addEventListener('click', closePinPresetDialog);
  if (pinDialogConfirmBtn) pinDialogConfirmBtn.addEventListener('click', handleConfirmPinPreset);
  if (pinNameInput) {
    pinNameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleConfirmPinPreset();
      }
    });
  }

  // 6. Auth PIN Dialog
  const authSubmitBtn = document.getElementById('auth-pin-submit-btn');
  const authPinInput = document.getElementById('auth-pin-input');
  if (authSubmitBtn) authSubmitBtn.addEventListener('click', handlePinSubmit);
  if (authPinInput) {
    authPinInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handlePinSubmit();
      }
    });
  }

  // 7. Status Tray
  const trayHeader = document.getElementById('status-tray-header');
  const trayRefreshBtn = document.getElementById('tray-refresh-btn');
  const trayClearBtn = document.getElementById('tray-clear-btn');

  if (trayHeader) trayHeader.addEventListener('click', toggleStatusTray);
  if (trayRefreshBtn) {
    trayRefreshBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      pollTelemetryStatus();
      showToast('Telemetry refreshed', 'info', 1000);
    });
  }
  if (trayClearBtn) {
    trayClearBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      clearTrayHistory();
    });
  }

  // ============================================================================
// 15. Terminal-Modern Workstation Hub & Device Pairing Logic
// ============================================================================

function switchTab(tabId) {
  const tabs = ['ingest', 'hub', 'devices'];
  tabs.forEach((t) => {
    const btn = document.getElementById(`tab-${t}`);
    const view = document.getElementById(`view-${t}`);
    if (btn) btn.classList.toggle('active', t === tabId);
    if (view) view.classList.toggle('active', t === tabId);
  });

  if (tabId === 'hub') loadWorkstationHub();
  if (tabId === 'devices') loadPairedDevices();
}

let qrCountdownTimer = null;
let qrExpiresAt = 0;

function startQrCountdown(expiresAt) {
  qrExpiresAt = expiresAt;
  if (qrCountdownTimer) {
    clearInterval(qrCountdownTimer);
    qrCountdownTimer = null;
  }

  const expiryElem = document.getElementById('qr-expiry-text');
  function updateTimer() {
    const remaining = Math.max(0, Math.floor(qrExpiresAt - (Date.now() / 1000)));
    const mins = Math.floor(remaining / 60);
    const secs = remaining % 60;
    if (expiryElem) {
      if (remaining > 0) {
        expiryElem.textContent = `⏳ Valid for ${mins}:${secs < 10 ? '0' : ''}${secs} (Single Use)`;
        expiryElem.style.color = '#10b981';
      } else {
        expiryElem.textContent = '⚠️ Expired — Click Regenerate';
        expiryElem.style.color = '#ef4444';
      }
    }
    if (remaining <= 0 && qrCountdownTimer) {
      clearInterval(qrCountdownTimer);
      qrCountdownTimer = null;
    }
  }

  updateTimer();
  qrCountdownTimer = setInterval(updateTimer, 1000);
}

async function regenerateQRCode() {
  const qrImg = document.getElementById('qr-code-img');
  const qrPlaceholder = document.getElementById('qr-loading');
  if (qrPlaceholder) {
    qrPlaceholder.textContent = 'Generating fresh 1-time QR...';
    qrPlaceholder.classList.remove('hidden');
  }
  if (qrImg) qrImg.classList.add('hidden');

  try {
    const res = await fetch('/api/qrcode/regenerate', { method: 'POST' });
    const data = await res.json();
    if (data.qr_data_url && qrImg) {
      qrImg.src = data.qr_data_url;
      qrImg.classList.remove('hidden');
      if (qrPlaceholder) qrPlaceholder.classList.add('hidden');
    }
    if (data.expires_at) {
      startQrCountdown(data.expires_at);
    }
    showToast('Regenerated fresh 1-time pairing QR', 'success', 2000);
  } catch (err) {
    console.warn('Failed to regenerate QR code:', err);
    showToast('Could not regenerate QR code', 'error');
  }
}

async function loadWorkstationHub() {
  try {
    const [qrData, meta] = await Promise.all([
      fetch('/api/qrcode').then((r) => r.json()).catch(() => ({})),
      fetch('/api/auth/workstation').then((r) => r.json()).catch(() => ({})),
    ]);

    const qrImg = document.getElementById('qr-code-img');
    const qrPlaceholder = document.getElementById('qr-loading');
    if (qrData.qr_data_url && qrImg) {
      qrImg.src = qrData.qr_data_url;
      qrImg.classList.remove('hidden');
      if (qrPlaceholder) qrPlaceholder.classList.add('hidden');
    }
    if (qrData.expires_at) {
      startQrCountdown(qrData.expires_at);
    }

    const hostElem = document.getElementById('telemetry-host');
    const lanUrlElem = document.getElementById('hub-lan-url');
    const wsIdElem = document.getElementById('hub-workstation-id');

    const displayUrl = qrData.url || meta.connection_url || 'http://127.0.0.1:8000';
    if (hostElem) hostElem.textContent = displayUrl.replace('http://', '');
    if (lanUrlElem) lanUrlElem.textContent = displayUrl;
    if (wsIdElem && meta.workstation_id) wsIdElem.textContent = meta.workstation_id;

    const countElem = document.getElementById('devices-badge-count');
    if (countElem && meta.paired_devices_count !== undefined) {
      countElem.textContent = meta.paired_devices_count;
    }
  } catch (err) {
    console.warn('Failed loading workstation hub data:', err);
  }
}

async function loadPairedDevices() {
  const container = document.getElementById('devices-list-container');
  if (!container) return;

  try {
    const devices = await apiFetch('/api/devices');
    const countElem = document.getElementById('devices-badge-count');
    if (countElem) countElem.textContent = devices.length;

    if (!devices || devices.length === 0) {
      container.innerHTML = '<div class="empty-state">No mobile devices currently paired. Use the Workstation QR code or Pair modal.</div>';
      return;
    }

    let html = '';
    devices.forEach((dev) => {
      const pairedDate = dev.paired_at ? new Date(dev.paired_at).toLocaleDateString() : 'Active';
      html += `
        <div class="device-row">
          <div class="device-meta-left">
            <span class="device-name">📱 ${escapeHtml(dev.device_name || dev.device_uid)}</span>
            <span class="device-sub">UID: ${escapeHtml(dev.device_uid)} • Paired: ${pairedDate} ${dev.ip ? '• ' + dev.ip : ''}</span>
          </div>
          <button type="button" class="btn-revoke" onclick="revokeDeviceById('${escapeHtml(dev.device_uid)}')">Revoke</button>
        </div>
      `;
    });
    container.innerHTML = html;
  } catch (err) {
    container.innerHTML = `<div class="empty-state">Pairing required to inspect authorized devices.</div>`;
  }
}

async function revokeDeviceById(uid) {
  if (!confirm(`Revoke authorization token for device '${uid}'?`)) return;
  try {
    await apiFetch(`/api/devices/${encodeURIComponent(uid)}`, { method: 'DELETE' });
    showToast(`Device '${uid}' revoked.`, 'info');
    loadPairedDevices();
  } catch (err) {
    showToast(err.message, 'error');
  }
}
window.revokeDeviceById = revokeDeviceById;

function openPairModal(message = '') {
  const modal = document.getElementById('pair-modal');
  const uidInput = document.getElementById('pair-device-uid');
  if (uidInput && !uidInput.value) {
    uidInput.value = AppState.deviceUid;
  }
  if (modal) modal.classList.remove('hidden');
  if (message) showToast(message, 'info', 2500);
}

function closePairModal() {
  const modal = document.getElementById('pair-modal');
  if (modal) modal.classList.add('hidden');
}

async function executePairing() {
  const uidInput = document.getElementById('pair-device-uid');
  const pwInput = document.getElementById('pair-password');

  const uid = (uidInput?.value || '').trim() || AppState.deviceUid;
  const pw = (pwInput?.value || '').trim();

  if (!pw) {
    showToast('Workstation password required.', 'error');
    if (pwInput) pwInput.focus();
    return;
  }

  try {
    const res = await fetch('/api/auth/pair', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_uid: uid,
        device_name: uid,
        password: pw,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Pairing rejected. Check password.');
    }

    const data = await res.json();
    AppState.deviceToken = data.token;
    AppState.deviceUid = data.device_uid;
    localStorage.setItem('assetdrop_token', data.token);
    localStorage.setItem('assetdrop_device_uid', data.device_uid);

    closePairModal();
    showToast(`✓ Bonded with ${data.workstation_id}!`, 'success', 3000);

    const authText = document.getElementById('telemetry-auth-text');
    if (authText) {
      authText.textContent = 'PAIRED';
      authText.className = 'telemetry-val green';
    }

    const pairBtn = document.getElementById('btn-pair-device');
    if (pairBtn) pairBtn.innerHTML = '<span>✓ Paired</span>';

    // Refresh presets & devices
    loadPresets();
    loadPairedDevices();
  } catch (err) {
    showToast(err.message, 'error', 3000);
  }
}

async function handleOpenAssetsFolder() {
  try {
    await apiFetch('/api/open-folder', { method: 'POST' });
    showToast('Opened D:\\Assets in File Explorer', 'success');
  } catch (err) {
    showToast('Failed to open folder: ' + err.message, 'error');
  }
}

function handleCopyLanUrl() {
  const urlElem = document.getElementById('hub-lan-url');
  const url = urlElem ? urlElem.textContent : `http://${location.host}`;
  navigator.clipboard.writeText(url)
    .then(() => showToast('Copied LAN URL to clipboard!', 'success'))
    .catch(() => showToast(url, 'info', 4000));
}

let passwordRevealed = false;
function handleTogglePasswordReveal() {
  const pwDisplay = document.getElementById('hub-password-display');
  const btn = document.getElementById('btn-toggle-password');
  passwordRevealed = !passwordRevealed;
  if (passwordRevealed) {
    if (pwDisplay) pwDisplay.textContent = 'AssetDrop2026';
    if (btn) btn.textContent = 'Hide';
  } else {
    if (pwDisplay) pwDisplay.textContent = '••••••••';
    if (btn) btn.textContent = 'Reveal';
  }
}

// ============================================================================
// 15. Dual-Mode View Routing & Dynamic State Engine (PC vs Mobile)
// ============================================================================
let activeView = null; // 'desktop' | 'mobile'
let cameraStream = null;
let cameraScanInterval = null;
let mobileFormat = 'video';

function isMobileDevice() {
  return /Android|iPhone|iPad|iPod|Windows Phone|webOS/i.test(navigator.userAgent) || window.innerWidth < 768;
}

function initViewRouting() {
  // Check for override in sessionStorage
  const savedView = sessionStorage.getItem('assetdrop_view_override');
  if (savedView === 'desktop' || savedView === 'mobile') {
    activeView = savedView;
  } else {
    activeView = isMobileDevice() ? 'mobile' : 'desktop';
  }

  // Check URL query parameters for auto-pairing (?token=...)
  const params = new URLSearchParams(window.location.search);
  const pairToken = params.get('token');
  if (pairToken) {
    executePairingWithToken(pairToken);
    // Clean URL
    window.history.replaceState({}, document.title, window.location.pathname);
  }

  // Setup view toggle button
  const toggleBtn = document.getElementById('btn-toggle-view');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      activeView = activeView === 'desktop' ? 'mobile' : 'desktop';
      sessionStorage.setItem('assetdrop_view_override', activeView);
      renderCurrentView();
    });
  }

  renderCurrentView();
}

function renderCurrentView() {
  const viewDesktop = document.getElementById('view-desktop');
  const viewMobile = document.getElementById('view-mobile');
  const viewModeIndicator = document.getElementById('view-mode-indicator');
  const toggleBtnText = document.getElementById('btn-toggle-view-text');

  if (activeView === 'mobile') {
    if (viewDesktop) viewDesktop.classList.add('hidden');
    if (viewMobile) viewMobile.classList.remove('hidden');
    if (viewModeIndicator) viewModeIndicator.textContent = 'Mobile Ingestion';
    if (toggleBtnText) toggleBtnText.textContent = '💻 Switch to PC View';

    renderMobileView();
  } else {
    if (viewDesktop) viewDesktop.classList.remove('hidden');
    if (viewMobile) viewMobile.classList.add('hidden');
    if (viewModeIndicator) viewModeIndicator.textContent = 'PC Hub';
    if (toggleBtnText) toggleBtnText.textContent = '📱 Switch to Mobile View';

    renderDesktopView();
  }
}

// ---------------------------------------------------------------------------
// Mobile View Engine (Unpaired QR Scanner vs Paired Single-Screen Ingest)
// ---------------------------------------------------------------------------
function renderMobileView() {
  const mobileUnpaired = document.getElementById('mobile-view-unpaired');
  const mobileIngest = document.getElementById('mobile-view-ingest');

  const token = localStorage.getItem('assetdrop_device_token');
  if (token) {
    // STATE B: Paired Single Screen
    if (mobileUnpaired) mobileUnpaired.classList.add('hidden');
    if (mobileIngest) mobileIngest.classList.remove('hidden');
    loadMobileSharedFolders();
    stopCameraScan();
  } else {
    // STATE A: Unpaired Screen (QR Scanner, zero password fields)
    if (mobileUnpaired) mobileUnpaired.classList.remove('hidden');
    if (mobileIngest) mobileIngest.classList.add('hidden');
  }
}

async function loadMobileSharedFolders() {
  const select = document.getElementById('mobile-folder-select');
  if (!select) return;

  try {
    const res = await apiFetch('/api/folders');
    const folders = res.folders || [];
    if (folders.length > 0) {
      select.innerHTML = folders.map((f) => {
        const name = typeof f === 'object' ? f.name : f;
        return `<option value="${escapeHtml(name)}">📁 ${escapeHtml(name)}</option>`;
      }).join('');
    }
  } catch (err) {
    console.warn('Could not load mobile shared folders:', err);
  }
}

async function executePairingWithToken(rawToken) {
  if (!rawToken) return;
  let cleanToken = rawToken.trim();
  if (cleanToken.includes('token=')) {
    const m = cleanToken.match(/token=([a-zA-Z0-9_-]+)/);
    if (m) cleanToken = m[1];
  }

  showToast('Authorizing with PC Workstation...', 'info', 2000);
  try {
    const devName = /iPhone|iPad/i.test(navigator.userAgent)
      ? 'Apple iPhone (iOS)'
      : (/Android/i.test(navigator.userAgent) ? 'Android Device' : 'Mobile Client');

    const res = await fetch('/pair', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: cleanToken, device_name: devName }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Pairing token invalid or expired. Please regenerate QR on PC.');
    }

    const data = await res.json();
    if (data.token) {
      localStorage.setItem('assetdrop_device_token', data.token);
      localStorage.setItem('assetdrop_device_id', data.device_id || '');
      showToast('✓ Successfully paired with PC Workstation!', 'success', 3000);
      renderCurrentView();
    }
  } catch (err) {
    showToast(err.message, 'error', 3500);
  }
}

function startCameraScan() {
  const wrapper = document.getElementById('mobile-scanner-wrapper');
  const video = document.getElementById('mobile-qr-video');
  if (!wrapper || !video) return;

  wrapper.classList.remove('hidden');

  navigator.mediaDevices?.getUserMedia({ video: { facingMode: 'environment' } })
    .then((stream) => {
      cameraStream = stream;
      video.srcObject = stream;
      video.setAttribute('playsinline', 'true');
      video.play();

      if ('BarcodeDetector' in window) {
        const detector = new BarcodeDetector({ formats: ['qr_code'] });
        cameraScanInterval = setInterval(async () => {
          try {
            const barcodes = await detector.detect(video);
            if (barcodes && barcodes.length > 0) {
              const rawVal = barcodes[0].rawValue;
              stopCameraScan();
              executePairingWithToken(rawVal);
            }
          } catch (e) {
            // Scanner frame pass
          }
        }, 300);
      } else {
        showToast('Camera live. Scan QR with your phone camera app or upload photo.', 'info', 4000);
      }
    })
    .catch((err) => {
      wrapper.classList.add('hidden');
      showToast('Camera access blocked. Use phone camera app or enter token.', 'error', 3500);
    });
}

function stopCameraScan() {
  if (cameraScanInterval) {
    clearInterval(cameraScanInterval);
    cameraScanInterval = null;
  }
  if (cameraStream) {
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
  }
  const wrapper = document.getElementById('mobile-scanner-wrapper');
  if (wrapper) wrapper.classList.add('hidden');
}

function handleMobileFileScan() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.onchange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if ('BarcodeDetector' in window) {
      try {
        const bmp = await createImageBitmap(file);
        const detector = new BarcodeDetector({ formats: ['qr_code'] });
        const barcodes = await detector.detect(bmp);
        if (barcodes && barcodes.length > 0) {
          executePairingWithToken(barcodes[0].rawValue);
          return;
        }
      } catch (err) {
        console.warn('BarcodeDetector error:', err);
      }
    }
    const entered = prompt('Could not auto-read QR image. Enter the pairing token or URL:');
    if (entered) executePairingWithToken(entered);
  };
  input.click();
}

async function handleMobileDownload() {
  const urlInput = document.getElementById('mobile-url-input');
  const folderSelect = document.getElementById('mobile-folder-select');
  if (!urlInput) return;

  const url = urlInput.value.trim();
  if (!url) {
    showToast('Please paste a media link first.', 'error', 2000);
    urlInput.focus();
    return;
  }

  // Clear input immediately (<50ms feedback)
  urlInput.value = '';

  const selectedFolder = folderSelect ? folderSelect.value : 'B-Roll (General)';
  showToast('✓ Queued! Sending to PC Workstation...', 'success', 2000);

  const statusBadge = document.getElementById('mobile-latest-status-badge');
  const titleDisplay = document.getElementById('mobile-latest-title');
  if (statusBadge) statusBadge.textContent = 'Queued on PC';
  if (titleDisplay) titleDisplay.textContent = url;

  try {
    const payload = {
      url: url,
      format_type: mobileFormat,
      folder_key: selectedFolder,
    };

    const res = await apiFetch('/api/queue', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    if (statusBadge) statusBadge.textContent = 'Ingesting on PC';
    if (res.job_id) {
      showToast(`✓ Ingest running on PC: ${res.platform || 'media'}`, 'success', 3000);
    }
  } catch (err) {
    if (statusBadge) statusBadge.textContent = 'Failed';
    showToast(err.message, 'error', 3500);
  }
}

// ---------------------------------------------------------------------------
// Desktop View Engine (Network Mode, QR Code, Shared Folders, Devices, Feed)
// ---------------------------------------------------------------------------
let desktopFeedTimer = null;

function renderDesktopView() {
  loadNetworkMode();
  loadWorkstationHub();
  loadDesktopSharedFolders();
  loadPairedDevices();
  loadDesktopFeed();

  if (!desktopFeedTimer) {
    desktopFeedTimer = setInterval(loadDesktopFeed, 2500);
  }
}

async function loadNetworkMode() {
  try {
    const res = await fetch('/api/network/mode').then((r) => r.json()).catch(() => ({}));
    const isPublic = res.is_public ?? true;

    const btnPublic = document.getElementById('btn-network-mode-public');
    const btnTrusted = document.getElementById('btn-network-mode-trusted');
    const telemetryAuth = document.getElementById('telemetry-auth-text');

    if (btnPublic) btnPublic.classList.toggle('active', isPublic);
    if (btnTrusted) btnTrusted.classList.toggle('active', !isPublic);
    if (telemetryAuth) {
      telemetryAuth.textContent = isPublic ? 'PUBLIC (STRICT)' : 'TRUSTED (STUDIO)';
      telemetryAuth.className = isPublic ? 'telemetry-val emerald' : 'telemetry-val cyan';
    }
  } catch (err) {
    console.warn('Could not load network mode:', err);
  }
}

async function setNetworkMode(mode) {
  try {
    await fetch('/api/network/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode }),
    });
    showToast(`✓ Network mode updated to: ${mode.toUpperCase()}`, 'success', 2000);
    loadNetworkMode();
    regenerateQRCode();
  } catch (err) {
    showToast('Failed to update network mode: ' + err.message, 'error');
  }
}

async function loadDesktopSharedFolders() {
  const container = document.getElementById('desktop-shared-folders-list');
  if (!container) return;

  try {
    const res = await fetch('/api/shared-folders').then((r) => r.json()).catch(() => ({ shared_folders: [] }));
    const folders = res.shared_folders || [];

    if (folders.length === 0) {
      container.innerHTML = '<div class="empty-state">No shared folders configured. Click "+ Add Shared Folder" to expose a folder to mobile phones.</div>';
      return;
    }

    container.innerHTML = folders.map((f) => `
      <div class="folder-card-row">
        <div class="folder-meta-left">
          <span class="folder-name-title">📁 ${escapeHtml(f.name)}</span>
          <span class="folder-path-sub">${escapeHtml(f.path)}</span>
        </div>
        <div style="display:flex; gap:0.5rem;">
          <button type="button" class="btn-terminal-sm" style="min-height:36px; padding:0 8px;" onclick="openFolderInExplorer('${escapeHtml(f.path)}')">📂 Open</button>
          <button type="button" class="btn-terminal-sm" style="min-height:36px; padding:0 8px; color:#ef4444; border-color:rgba(239,68,68,0.4);" onclick="removeSharedFolder('${escapeHtml(f.name)}')">✕</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = '<div class="empty-state">Could not load shared folders.</div>';
  }
}

async function openFolderInExplorer(folderPath) {
  try {
    await fetch('/api/shared-folders/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: folderPath }),
    });
    showToast(`Opened folder in Explorer`, 'success', 2000);
  } catch (err) {
    showToast('Could not open folder: ' + err.message, 'error');
  }
}
window.openFolderInExplorer = openFolderInExplorer;

async function removeSharedFolder(folderName) {
  if (!confirm(`Stop sharing folder '${folderName}' with mobile devices?`)) return;
  try {
    await fetch(`/api/shared-folders/${encodeURIComponent(folderName)}`, { method: 'DELETE' });
    showToast(`Folder '${folderName}' removed.`, 'info');
    loadDesktopSharedFolders();
  } catch (err) {
    showToast('Failed to remove folder: ' + err.message, 'error');
  }
}
window.removeSharedFolder = removeSharedFolder;

async function handleSaveSharedFolder() {
  const nameInput = document.getElementById('new-folder-name-input');
  const pathInput = document.getElementById('new-folder-path-input');
  const box = document.getElementById('add-folder-box');
  if (!nameInput || !pathInput) return;

  const name = nameInput.value.trim();
  const path = pathInput.value.trim();

  if (!name || !path) {
    showToast('Please enter both folder name and path.', 'error');
    return;
  }

  try {
    const res = await fetch('/api/shared-folders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, path }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Could not add shared folder.');
    }

    nameInput.value = '';
    pathInput.value = '';
    if (box) box.classList.add('hidden');
    showToast(`✓ Shared folder '${name}' added!`, 'success');
    loadDesktopSharedFolders();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function loadDesktopFeed() {
  const tbody = document.getElementById('desktop-feed-tbody');
  if (!tbody) return;

  try {
    const statusData = await fetch('/api/status').then((r) => r.json()).catch(() => ({ transfers: [] }));
    const transfers = statusData.transfers || [];

    if (transfers.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" class="empty-state" style="text-align:center; padding:1.5rem; color:#6b7280;">
            No transfers yet. Paste links from your phone to start downloading.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = transfers.slice(0, 10).map((t) => {
      const statusClass = t.status === 'completed' ? 'completed' : (t.status === 'failed' ? 'failed' : (t.status === 'downloading' ? 'downloading' : 'queued'));
      const title = t.filename || t.url || 'Media Download';
      return `
        <tr style="border-bottom:1px solid rgba(255,255,255,0.05); font-size:13px;">
          <td style="padding:0.75rem; color:#f3f4f6; max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(title)}">${escapeHtml(title)}</td>
          <td style="padding:0.75rem; color:#9ca3af; text-transform:capitalize;">${escapeHtml(t.platform || 'auto')}</td>
          <td style="padding:0.75rem; color:#9ca3af; text-transform:uppercase;">${escapeHtml(t.format_type || 'video')}</td>
          <td style="padding:0.75rem; color:#9ca3af; max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(t.target_dir || 'D:\\Assets')}</td>
          <td style="padding:0.75rem;"><span class="badge-status ${statusClass}">${escapeHtml(t.status)}</span></td>
          <td style="padding:0.75rem;">
            <button type="button" class="btn-terminal-sm" style="min-height:36px; padding:0 8px;" onclick="openFolderInExplorer('${escapeHtml(t.target_dir)}')">📂 Open</button>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    // Feed fetch pass
  }
}

// ---------------------------------------------------------------------------
// Global Bindings & Startup
// ---------------------------------------------------------------------------
function initDualEngineBindings() {
  // Mobile Format Toggles
  const btnFmtVid = document.getElementById('mobile-fmt-video');
  const btnFmtAud = document.getElementById('mobile-fmt-audio');
  if (btnFmtVid) {
    btnFmtVid.addEventListener('click', () => {
      mobileFormat = 'video';
      btnFmtVid.classList.add('active');
      btnFmtAud?.classList.remove('active');
    });
  }
  if (btnFmtAud) {
    btnFmtAud.addEventListener('click', () => {
      mobileFormat = 'audio';
      btnFmtAud.classList.add('active');
      btnFmtVid?.classList.remove('active');
    });
  }

  // Mobile Paste Button
  const btnMobPaste = document.getElementById('mobile-paste-btn');
  const mobUrlInput = document.getElementById('mobile-url-input');
  if (btnMobPaste && mobUrlInput) {
    btnMobPaste.addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          mobUrlInput.value = text;
          showToast('Pasted link from clipboard!', 'success', 1500);
        }
      } catch (e) {
        mobUrlInput.focus();
      }
    });
  }

  // Mobile Download Button
  const btnMobDownload = document.getElementById('mobile-download-btn');
  if (btnMobDownload) {
    btnMobDownload.addEventListener('click', handleMobileDownload);
  }

  // Mobile Unpair
  const btnMobDisconnect = document.getElementById('mobile-btn-disconnect');
  if (btnMobDisconnect) {
    btnMobDisconnect.addEventListener('click', () => {
      localStorage.removeItem('assetdrop_device_token');
      showToast('Unlinked device.', 'info');
      renderCurrentView();
    });
  }

  // Mobile QR Scanner Controls
  const btnCamScan = document.getElementById('mobile-btn-camera-scan');
  const btnCloseScan = document.getElementById('btn-close-scanner');
  const btnFileScan = document.getElementById('mobile-btn-file-scan');
  const btnSubmitManual = document.getElementById('btn-submit-manual-token');
  const inputManual = document.getElementById('mobile-manual-token-input');

  if (btnCamScan) btnCamScan.addEventListener('click', startCameraScan);
  if (btnCloseScan) btnCloseScan.addEventListener('click', stopCameraScan);
  if (btnFileScan) btnFileScan.addEventListener('click', handleMobileFileScan);
  if (btnSubmitManual && inputManual) {
    btnSubmitManual.addEventListener('click', () => {
      const val = inputManual.value.trim();
      if (val) executePairingWithToken(val);
    });
  }

  // Desktop Network Mode Controls
  const btnModePub = document.getElementById('btn-network-mode-public');
  const btnModeTrust = document.getElementById('btn-network-mode-trusted');
  if (btnModePub) btnModePub.addEventListener('click', () => setNetworkMode('public'));
  if (btnModeTrust) btnModeTrust.addEventListener('click', () => setNetworkMode('trusted'));

  // Desktop Shared Folders Controls
  const btnShowAddFld = document.getElementById('btn-show-add-folder');
  const btnCancelAddFld = document.getElementById('btn-cancel-add-folder');
  const btnSaveSharedFld = document.getElementById('btn-save-shared-folder');
  const addFolderBox = document.getElementById('add-folder-box');

  if (btnShowAddFld) btnShowAddFld.addEventListener('click', () => addFolderBox?.classList.toggle('hidden'));
  if (btnCancelAddFld) btnCancelAddFld.addEventListener('click', () => addFolderBox?.classList.add('hidden'));
  if (btnSaveSharedFld) btnSaveSharedFld.addEventListener('click', handleSaveSharedFolder);

  // Desktop Refresh Feed
  const btnRefreshFeed = document.getElementById('btn-refresh-feed');
  if (btnRefreshFeed) btnRefreshFeed.addEventListener('click', loadDesktopFeed);
}

// 8. Mobile tab visibility listener (pause polling while backgrounded)
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    stopStatusPolling();
  } else {
    startStatusPolling(true);
  }
});

// Global initialization on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  initEventBindings();
  initPwaCapabilities();
  checkAuthStatus();
  initDualEngineBindings();
  initViewRouting();
});
