/**
 * static/mobile.js — AssetDrop Dedicated Two-Stage Mobile Client Logic.
 *
 * Stage 1: Connection Screen (5-digit UID & startup password authentication).
 * Stage 2: Clean Download Form (Media URL + Paste, MP3/MP4, PC folder dropdown, Download btn).
 * Zero peripheral clutter: No QR scanner, no camera video, no 32-char tokens, no directory sheet.
 */

(function () {
  'use strict';

  // LocalStorage Keys
  const TOKEN_STORAGE_KEY = 'assetdrop_auth_token';
  const UID_STORAGE_KEY = 'assetdrop_server_uid';

  // Application State
  const state = {
    token: null,
    serverUid: null,
    selectedFormat: 'video', // 'video' (MP4) | 'audio' (MP3)
    folders: [],
    toastTimeout: null,
  };

  // DOM Elements Cache
  const elements = {
    // Toast
    toast: document.getElementById('toast'),
    toastIcon: document.getElementById('toast-icon'),
    toastMessage: document.getElementById('toast-message'),

    // Stages
    stageConnection: document.getElementById('stage-connection'),
    stageDownload: document.getElementById('stage-download'),

    // Stage 1 Auth
    authForm: document.getElementById('mobile-auth-form'),
    uidInput: document.getElementById('mobile-uid-input'),
    passwordInput: document.getElementById('mobile-password-input'),
    btnConnect: document.getElementById('mobile-btn-connect'),
    authError: document.getElementById('mobile-auth-error'),
    authErrorText: document.getElementById('mobile-auth-error-text'),

    // Stage 2 Header & Status
    connectedText: document.getElementById('mobile-connected-text'),
    btnDisconnect: document.getElementById('mobile-btn-disconnect'),

    // Stage 2 Download Form
    downloadForm: document.getElementById('mobile-download-form'),
    urlInput: document.getElementById('mobile-url-input'),
    btnPaste: document.getElementById('mobile-btn-paste'),
    fmtVideo: document.getElementById('mobile-fmt-video'),
    fmtAudio: document.getElementById('mobile-fmt-audio'),
    folderSelect: document.getElementById('mobile-folder-select'),
    btnDownload: document.getElementById('mobile-btn-download'),
  };

  // ---------------------------------------------------------------------------
  // Toast Notification System (<50ms Optimistic Feedback)
  // ---------------------------------------------------------------------------
  function showToast(message, isError = false) {
    if (!elements.toast) return;

    if (elements.toastIcon) {
      elements.toastIcon.textContent = isError ? '⚠' : '✓';
    }
    if (elements.toastMessage) {
      elements.toastMessage.textContent = message;
    }

    if (isError) {
      elements.toast.classList.add('toast-error');
    } else {
      elements.toast.classList.remove('toast-error');
    }

    elements.toast.classList.remove('hidden');

    if (state.toastTimeout) {
      clearTimeout(state.toastTimeout);
    }
    state.toastTimeout = setTimeout(() => {
      elements.toast.classList.add('hidden');
      state.toastTimeout = null;
    }, 3200);
  }

  // ---------------------------------------------------------------------------
  // Stage Navigation
  // ---------------------------------------------------------------------------
  function setStage(stage) {
    if (stage === 'download') {
      if (elements.stageConnection) elements.stageConnection.classList.add('hidden');
      if (elements.stageDownload) elements.stageDownload.classList.remove('hidden');
    } else {
      if (elements.stageDownload) elements.stageDownload.classList.add('hidden');
      if (elements.stageConnection) elements.stageConnection.classList.remove('hidden');
    }
  }

  function updateConnectedStatus(uid) {
    if (elements.connectedText) {
      elements.connectedText.textContent = uid ? `Connected to PC (UID: ${uid})` : 'Connected to PC';
    }
  }

  // ---------------------------------------------------------------------------
  // Stage 1: Authentication Logic (POST /api/auth/login)
  // ---------------------------------------------------------------------------
  function showAuthError(msg) {
    if (!elements.authError) return;
    if (elements.authErrorText) {
      elements.authErrorText.textContent = msg || 'Invalid UID or password. Please verify credentials on the PC screen.';
    }
    elements.authError.classList.remove('hidden');
  }

  function hideAuthError() {
    if (elements.authError) {
      elements.authError.classList.add('hidden');
    }
  }

  async function handleAuthSubmit(e) {
    e.preventDefault();
    hideAuthError();

    const uid = (elements.uidInput ? elements.uidInput.value : '').trim();
    const password = (elements.passwordInput ? elements.passwordInput.value : '').trim();

    if (!uid || !password) {
      showAuthError('Please enter both the 5-digit Server UID and PC password.');
      return;
    }

    if (!/^[0-9]{5}$/.test(uid)) {
      showAuthError('Server UID must be exactly 5 numeric digits.');
      return;
    }

    // Indicate loading state
    if (elements.btnConnect) {
      elements.btnConnect.disabled = true;
      elements.btnConnect.innerHTML = '<span>⏳ Connecting...</span>';
    }

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({ uid, password }),
      });

      if (response.ok) {
        const data = await response.json();
        const token = data.session_token;

        // Persist session
        state.token = token;
        state.serverUid = uid;
        try {
          localStorage.setItem(TOKEN_STORAGE_KEY, token);
          localStorage.setItem(UID_STORAGE_KEY, uid);
        } catch (_) {}

        updateConnectedStatus(uid);
        setStage('download');
        showToast(`✓ Connected to PC (UID: ${uid})`);

        // Reset auth fields
        if (elements.passwordInput) elements.passwordInput.value = '';

        // Load destination folders for Stage 2
        await loadSharedFolders(token);
      } else if (response.status === 401) {
        showAuthError('Invalid UID or password. Please verify credentials on the PC screen.');
      } else {
        const errJson = await response.json().catch(() => ({}));
        showAuthError(errJson.detail || `Server error (${response.status}). Please check PC connection.`);
      }
    } catch (err) {
      showAuthError('Network error connecting to PC. Verify phone and PC are on the same Wi-Fi network.');
    } finally {
      if (elements.btnConnect) {
        elements.btnConnect.disabled = false;
        elements.btnConnect.innerHTML = '<span>⚡ Connect to PC</span>';
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Disconnect & Session Termination
  // ---------------------------------------------------------------------------
  async function handleDisconnect() {
    const token = state.token;

    // Clear local state immediately
    state.token = null;
    state.serverUid = null;
    try {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      localStorage.removeItem(UID_STORAGE_KEY);
    } catch (_) {}

    setStage('connection');
    showToast('Disconnected from PC.');

    // Fire non-blocking logout revocation to server
    if (token) {
      fetch('/api/auth/logout', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      }).catch(() => {});
    }
  }

  // ---------------------------------------------------------------------------
  // Stage 2: Folder Loading (GET /api/shared-folders)
  // ---------------------------------------------------------------------------
  async function loadSharedFolders(token) {
    if (!elements.folderSelect) return;

    elements.folderSelect.innerHTML = '<option value="" disabled selected>Loading folders...</option>';

    try {
      const authToken = token || state.token;
      const headers = authToken ? { 'Authorization': `Bearer ${authToken}` } : {};

      let response = await fetch('/api/shared-folders', { headers });
      if (response.status === 401) {
        // Session invalid
        handleDisconnect();
        return;
      }
      if (!response.ok) {
        response = await fetch('/api/folders', { headers });
      }

      if (response.ok) {
        const data = await response.json();
        const rawFolders = data.folders || data.shared_folders || [];
        state.folders = rawFolders;

        elements.folderSelect.innerHTML = '';
        if (rawFolders.length === 0) {
          const opt = document.createElement('option');
          opt.value = 'B-Roll (General)';
          opt.textContent = '📁 B-Roll (General) [Default]';
          elements.folderSelect.appendChild(opt);
        } else {
          rawFolders.forEach((item, index) => {
            const opt = document.createElement('option');
            const name = typeof item === 'string' ? item : (item.name || item.id || `Folder ${index + 1}`);
            // Use folder name as value so server resolve_destination_folder matches preset
            opt.value = name;
            opt.textContent = `📁 ${name}`;
            if (index === 0) opt.selected = true;
            elements.folderSelect.appendChild(opt);
          });
        }
      } else {
        throw new Error('Failed to load folders');
      }
    } catch (err) {
      elements.folderSelect.innerHTML = `
        <option value="B-Roll (General)" selected>📁 B-Roll (General)</option>
        <option value="Social Edits">📁 Social Edits</option>
        <option value="Sound Effects">📁 Sound Effects</option>
        <option value="Background Music">📁 Background Music</option>
      `;
    }
  }

  // ---------------------------------------------------------------------------
  // Format Selection (MP3 vs MP4)
  // ---------------------------------------------------------------------------
  function setFormat(format) {
    state.selectedFormat = format;

    if (elements.fmtVideo && elements.fmtAudio) {
      if (format === 'video') {
        elements.fmtVideo.classList.add('active');
        elements.fmtVideo.setAttribute('aria-checked', 'true');
        elements.fmtAudio.classList.remove('active');
        elements.fmtAudio.setAttribute('aria-checked', 'false');
      } else {
        elements.fmtAudio.classList.add('active');
        elements.fmtAudio.setAttribute('aria-checked', 'true');
        elements.fmtVideo.classList.remove('active');
        elements.fmtVideo.setAttribute('aria-checked', 'false');
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Clipboard Paste Helper
  // ---------------------------------------------------------------------------
  async function handlePaste() {
    if (!elements.urlInput) return;

    try {
      if (navigator.clipboard && navigator.clipboard.readText) {
        const text = await navigator.clipboard.readText();
        if (text && text.trim()) {
          elements.urlInput.value = text.trim();
          elements.urlInput.focus();
          showToast('📋 Link pasted from clipboard!');
          return;
        }
      }
      elements.urlInput.focus();
      showToast('Clipboard empty or unavailable. Please paste manually.', true);
    } catch (_) {
      elements.urlInput.focus();
      showToast('Clipboard access denied. Please long-press to paste.', true);
    }
  }

  // ---------------------------------------------------------------------------
  // Stage 2: Download Submission (POST /api/queue)
  // ---------------------------------------------------------------------------
  async function handleDownloadSubmit(e) {
    if (e) e.preventDefault();

    const rawUrl = elements.urlInput ? elements.urlInput.value.trim() : '';
    if (!rawUrl) {
      showToast('Please enter or paste a media URL.', true);
      if (elements.urlInput) elements.urlInput.focus();
      return;
    }

    if (!/^https?:\/\//i.test(rawUrl)) {
      showToast('Please enter a valid HTTP or HTTPS media link.', true);
      if (elements.urlInput) elements.urlInput.focus();
      return;
    }

    const folder = elements.folderSelect ? elements.folderSelect.value : 'B-Roll (General)';
    const format = state.selectedFormat || 'video';
    const token = state.token;

    if (!token) {
      showToast('Authentication session lost. Please reconnect to PC.', true);
      setStage('connection');
      return;
    }

    // SUB-50ms OPTIMISTIC FEEDBACK SLA:
    // Instantly provide visual confirmation before awaiting server response!
    showToast('⚡ Queued! Downloading on PC.');
    if (elements.urlInput) {
      elements.urlInput.value = '';
    }

    try {
      const response = await fetch('/api/queue', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
          'Accept': 'application/json',
        },
        body: JSON.stringify({
          url: rawUrl,
          format_type: format,
          folder_key: folder,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        // Keep confirmation active with server assigned job ID
        showToast(`✓ Job [${data.job_id || 'Queued'}] downloading to ${data.target_folder || folder}`);
      } else if (response.status === 401) {
        showToast('Session expired. Please reconnect to your PC.', true);
        handleDisconnect();
      } else if (response.status === 429) {
        showToast('Rate limit reached (10/min). Please wait a moment.', true);
      } else {
        const errJson = await response.json().catch(() => ({}));
        showToast(errJson.detail || `Server error (${response.status})`, true);
      }
    } catch (err) {
      showToast('Network error submitting download. Check PC connection.', true);
    }
  }

  // ---------------------------------------------------------------------------
  // Session Persistence & Initialization
  // ---------------------------------------------------------------------------
  async function initSession() {
    let savedToken = null;
    let savedUid = null;
    try {
      savedToken = localStorage.getItem(TOKEN_STORAGE_KEY);
      savedUid = localStorage.getItem(UID_STORAGE_KEY);
    } catch (_) {}

    if (!savedToken) {
      setStage('connection');
      return;
    }

    // Validate stored token against protected endpoint
    try {
      const response = await fetch('/api/shared-folders', {
        headers: {
          'Authorization': `Bearer ${savedToken}`,
        },
      });

      if (response.ok) {
        state.token = savedToken;
        state.serverUid = savedUid;
        updateConnectedStatus(savedUid);
        setStage('download');
        await loadSharedFolders(savedToken);
      } else {
        // Token expired or invalid
        state.token = null;
        state.serverUid = null;
        try {
          localStorage.removeItem(TOKEN_STORAGE_KEY);
          localStorage.removeItem(UID_STORAGE_KEY);
        } catch (_) {}
        setStage('connection');
      }
    } catch (_) {
      // In case of temporary offline state, fall back to connection stage
      setStage('connection');
    }
  }

  // ---------------------------------------------------------------------------
  // Event Bindings
  // ---------------------------------------------------------------------------
  function bindEvents() {
    // Stage 1 Auth Form
    if (elements.authForm) {
      elements.authForm.addEventListener('submit', handleAuthSubmit);
    }

    // Stage 2 Disconnect
    if (elements.btnDisconnect) {
      elements.btnDisconnect.addEventListener('click', handleDisconnect);
    }

    // Stage 2 Paste Button
    if (elements.btnPaste) {
      elements.btnPaste.addEventListener('click', handlePaste);
    }

    // Format Selector
    if (elements.fmtVideo) {
      elements.fmtVideo.addEventListener('click', () => setFormat('video'));
    }
    if (elements.fmtAudio) {
      elements.fmtAudio.addEventListener('click', () => setFormat('audio'));
    }

    // Stage 2 Download Form
    if (elements.downloadForm) {
      elements.downloadForm.addEventListener('submit', handleDownloadSubmit);
    }
    if (elements.btnDownload) {
      elements.btnDownload.addEventListener('click', (e) => {
        // Trigger submit
        if (elements.downloadForm) {
          elements.downloadForm.requestSubmit ? elements.downloadForm.requestSubmit() : handleDownloadSubmit(e);
        }
      });
    }

    // Numeric filter for UID input (enforce 5 digits)
    if (elements.uidInput) {
      elements.uidInput.addEventListener('input', (e) => {
        e.target.value = e.target.value.replace(/[^0-9]/g, '').slice(0, 5);
      });
    }
  }

  // DOM Ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      bindEvents();
      initSession();
    });
  } else {
    bindEvents();
    initSession();
  }

})();
