/**
 * static/mobile.js — AssetDrop Dedicated Two-Stage Mobile Client Logic.
 *
 * Stage 1: Connection Screen (5-digit UID & startup password authentication).
 * Stage 2: Clean Download Form (Media URL + Paste, MP3/MP4, PC folder dropdown, Download btn).
 * Zero peripheral clutter: No QR scanner, no camera video, no 32-char tokens, no directory sheet.
 */

(function () {
  'use strict';

  // LocalStorage & Cookie Keys
  const TOKEN_STORAGE_KEY = 'assetdrop_auth_token';
  const UID_STORAGE_KEY = 'assetdrop_server_uid';
  const PW_STORAGE_KEY = 'assetdrop_server_password';

  // Cookie Persistence Helpers
  function setCookie(name, value, days = 365) {
    try {
      const expires = new Date(Date.now() + days * 864e5).toUTCString();
      document.cookie = `${encodeURIComponent(name)}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax`;
    } catch (_) {}
  }

  function getCookie(name) {
    try {
      const matches = document.cookie.match(new RegExp('(?:^|; )' + encodeURIComponent(name).replace(/[\-\.\+\*]/g, '\\$&') + '=([^;]*)'));
      return matches ? decodeURIComponent(matches[1]) : null;
    } catch (_) {
      return null;
    }
  }

  function saveAuthCredentials(uid, password, token) {
    try {
      if (token) {
        localStorage.setItem(TOKEN_STORAGE_KEY, token);
        setCookie(TOKEN_STORAGE_KEY, token);
      }
      if (uid) {
        localStorage.setItem(UID_STORAGE_KEY, uid);
        setCookie(UID_STORAGE_KEY, uid);
      }
      if (password) {
        localStorage.setItem(PW_STORAGE_KEY, password);
        setCookie(PW_STORAGE_KEY, password);
      }
    } catch (_) {}
  }

  function getCachedCredentials() {
    let token = null, uid = null, password = null;
    try {
      token = localStorage.getItem(TOKEN_STORAGE_KEY) || getCookie(TOKEN_STORAGE_KEY);
      uid = localStorage.getItem(UID_STORAGE_KEY) || getCookie(UID_STORAGE_KEY);
      password = localStorage.getItem(PW_STORAGE_KEY) || getCookie(PW_STORAGE_KEY);
    } catch (_) {}
    return { token, uid, password };
  }

  // Application State
  const state = {
    token: null,
    serverUid: null,
    selectedFormat: 'video', // 'video' (MP4) | 'audio' (MP3)
    folders: [],
    treeRoot: null,
    currentNavNode: null,
    selectedFolderKey: 'WORK',
    selectedParentRoot: 'WORK',
    sortAsc: true,
    toastTimeout: null,
    modalTimeout: null,
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
    btnSearch: document.getElementById('mobile-btn-search'),
    previewCard: document.getElementById('media-preview-card'),
    previewThumbnailImg: document.getElementById('preview-thumbnail-img'),
    previewPlatformBadge: document.getElementById('preview-platform-badge'),
    previewTitle: document.getElementById('preview-title'),
    previewStatus: document.getElementById('preview-status'),
    formatField: document.getElementById('format-selection-field'),
    fmtVideo: document.getElementById('mobile-fmt-video'),
    fmtAudio: document.getElementById('mobile-fmt-audio'),
    folderSelect: document.getElementById('mobile-folder-select'),
    btnDownload: document.getElementById('mobile-btn-download'),

    // Queued Modal
    queuedModal: document.getElementById('queued-modal'),
    queuedModalBackdrop: document.getElementById('queued-modal-backdrop'),
    btnCloseModal: document.getElementById('btn-close-modal'),
    modalFolderName: document.getElementById('modal-folder-name'),
    modalFormatRow: document.getElementById('modal-format-row'),
    modalFormatVal: document.getElementById('modal-format-val'),

    // Dedicated Folder Picker & Creation Modal Elements (Tasks 2 & 3)
    folderTrigger: document.getElementById('mobile-folder-trigger'),
    triggerFolderName: document.getElementById('trigger-folder-name'),
    triggerFolderSub: document.getElementById('trigger-folder-sub'),
    folderPickerModal: document.getElementById('folder-picker-modal'),
    folderPickerBackdrop: document.getElementById('folder-picker-backdrop'),
    btnCloseFolderPicker: document.getElementById('btn-close-folder-picker'),
    folderSearchInput: document.getElementById('folder-search-input'),
    btnClearFolderSearch: document.getElementById('btn-clear-folder-search'),
    explorerBanner: document.getElementById('explorer-banner'),
    explorerCurrentTitle: document.getElementById('explorer-current-title'),
    explorerBannerBadge: document.getElementById('explorer-banner-badge'),
    btnChooseCurrentFolder: document.getElementById('btn-choose-current-folder'),
    explorerBreadcrumbsBar: document.getElementById('explorer-breadcrumbs-bar'),
    explorerBreadcrumbs: document.getElementById('explorer-breadcrumbs'),
    btnNavUp: document.getElementById('btn-nav-up'),
    btnToggleSort: document.getElementById('btn-toggle-sort'),
    btnSortToggleText: document.getElementById('btn-sort-toggle-text'),
    btnToggleNewFolder: document.getElementById('btn-toggle-new-folder'),
    btnCreateToggleText: document.getElementById('btn-create-toggle-text'),
    folderCreateForm: document.getElementById('folder-create-form'),
    newFolderParentLabel: document.getElementById('new-folder-parent-label'),
    newFolderNameInput: document.getElementById('new-folder-name-input'),
    btnConfirmCreateFolder: document.getElementById('btn-confirm-create-folder'),
    btnCancelCreateFolder: document.getElementById('btn-cancel-create-folder'),
    folderPickerList: document.getElementById('folder-picker-list'),
    folderModalSelectedText: document.getElementById('folder-modal-selected-text'),
    btnConfirmFolderModal: document.getElementById('btn-confirm-folder-modal'),
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
        saveAuthCredentials(uid, password, token);

        updateConnectedStatus(uid);
        setStage('download');
        showToast(`✓ Connected to PC (UID: ${uid})`);

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
      localStorage.removeItem(PW_STORAGE_KEY);
      setCookie(TOKEN_STORAGE_KEY, '', -1);
      setCookie(UID_STORAGE_KEY, '', -1);
      setCookie(PW_STORAGE_KEY, '', -1);
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
  // Hierarchical Folder Tree Construction & Helpers (Task 2)
  // ---------------------------------------------------------------------------
  function buildFolderTree(rawFolders) {
    const root = {
      name: 'All Folders',
      relPath: '',
      presetRoot: '',
      fullKey: '',
      isVirtual: true,
      children: [],
      parent: null,
    };

    if (!Array.isArray(rawFolders) || rawFolders.length === 0) {
      return root;
    }

    rawFolders.forEach((item, idx) => {
      const presetName = typeof item === 'string' ? item : (item.name || item.id || `Folder ${idx + 1}`);
      const subs = (item && Array.isArray(item.subfolders)) ? item.subfolders : [];

      const presetNode = {
        name: presetName,
        relPath: '',
        presetRoot: presetName,
        fullKey: presetName,
        isPreset: true,
        children: [],
        parent: root,
      };
      root.children.push(presetNode);

      const pathToNode = new Map();
      pathToNode.set('', presetNode);

      const sortedSubs = [...subs].sort((a, b) => {
        const segsA = a.split(/[\\/]/).length;
        const segsB = b.split(/[\\/]/).length;
        return segsA - segsB;
      });

      sortedSubs.forEach((sub) => {
        if (!sub || typeof sub !== 'string') return;
        const normalized = sub.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
        if (!normalized) return;

        const parts = normalized.split('/');
        let currentParent = presetNode;
        let runningPath = '';

        for (let i = 0; i < parts.length; i++) {
          const part = parts[i];
          runningPath = runningPath ? `${runningPath}/${part}` : part;
          let node = pathToNode.get(runningPath);
          if (!node) {
            node = {
              name: part,
              relPath: runningPath,
              presetRoot: presetName,
              fullKey: `${presetName} / ${runningPath}`,
              isPreset: false,
              children: [],
              parent: currentParent,
            };
            currentParent.children.push(node);
            pathToNode.set(runningPath, node);
          }
          currentParent = node;
        }
      });
    });

    return root;
  }

  function findNodeByKey(root, key) {
    if (!root || !key) return null;
    const cleanKey = key.trim();
    if (root.fullKey === cleanKey) return root;

    for (const child of root.children) {
      const found = findNodeByKey(child, cleanKey);
      if (found) return found;
    }
    return null;
  }

  function collectAllNodes(node, results = []) {
    if (!node) return results;
    if (!node.isVirtual) {
      results.push(node);
    }
    for (const child of node.children) {
      collectAllNodes(child, results);
    }
    return results;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
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
        state.treeRoot = buildFolderTree(rawFolders);

        // Populate hidden fallback select for contract tests
        elements.folderSelect.innerHTML = '';
        if (rawFolders.length === 0) {
          const opt = document.createElement('option');
          opt.value = 'WORK';
          opt.textContent = '📁 WORK [Default]';
          elements.folderSelect.appendChild(opt);
        } else {
          let hasSelected = false;
          rawFolders.forEach((item, index) => {
            const parentName = typeof item === 'string' ? item : (item.name || item.id || `Folder ${index + 1}`);
            const subs = (item && Array.isArray(item.subfolders)) ? item.subfolders : [];

            if (subs.length > 0) {
              const group = document.createElement('optgroup');
              group.label = `📁 ${parentName} (${subs.length} subfolders)`;

              const mainOpt = document.createElement('option');
              mainOpt.value = parentName;
              mainOpt.textContent = `📁 ${parentName} (Root)`;
              if (!hasSelected) {
                mainOpt.selected = true;
                hasSelected = true;
              }
              group.appendChild(mainOpt);

              subs.forEach((sub) => {
                const subOpt = document.createElement('option');
                const fullValue = `${parentName} / ${sub}`;
                subOpt.value = fullValue;
                subOpt.textContent = `  ↳ 📂 ${parentName} / ${sub}`;
                group.appendChild(subOpt);
              });

              elements.folderSelect.appendChild(group);
            } else {
              const opt = document.createElement('option');
              opt.value = parentName;
              opt.textContent = `📁 ${parentName}`;
              if (!hasSelected) {
                opt.selected = true;
                hasSelected = true;
              }
              elements.folderSelect.appendChild(opt);
            }
          });
        }

        // Determine current explorer navigation node
        if (state.treeRoot.children.length === 1) {
          state.currentNavNode = state.treeRoot.children[0];
        } else if (state.treeRoot.children.length > 1) {
          const found = findNodeByKey(state.treeRoot, state.selectedFolderKey);
          if (found) {
            state.currentNavNode = found.isPreset ? found : (found.parent || state.treeRoot);
          } else {
            state.currentNavNode = state.treeRoot.children[0];
          }
        } else {
          state.currentNavNode = state.treeRoot;
        }

        // Sync selected folder key
        if (!state.selectedFolderKey || !findNodeByKey(state.treeRoot, state.selectedFolderKey)) {
          if (state.currentNavNode && !state.currentNavNode.isVirtual) {
            state.selectedFolderKey = state.currentNavNode.fullKey;
            state.selectedParentRoot = state.currentNavNode.presetRoot;
          } else if (rawFolders.length > 0) {
            const first = rawFolders[0];
            const firstName = typeof first === 'string' ? first : (first.name || 'WORK');
            state.selectedFolderKey = firstName;
            state.selectedParentRoot = firstName;
          }
        }

        updateFolderTriggerUI();
        renderFolderPickerList('');
      } else {
        throw new Error('Failed to load folders');
      }
    } catch (err) {
      elements.folderSelect.innerHTML = `
        <option value="WORK" selected>📁 WORK</option>
      `;
      state.selectedFolderKey = 'WORK';
      state.selectedParentRoot = 'WORK';
      state.treeRoot = buildFolderTree([{ name: 'WORK', subfolders: [] }]);
      state.currentNavNode = state.treeRoot.children[0] || state.treeRoot;
      updateFolderTriggerUI();
      renderFolderPickerList('');
    }
  }

  // ---------------------------------------------------------------------------
  // Folder Selection & Popup Modal (Tasks 2 & 3)
  // ---------------------------------------------------------------------------
  function updateFolderTriggerUI() {
    const triggerTitle = elements.triggerFolderName || document.getElementById('trigger-folder-name');
    const triggerSub = elements.triggerFolderSub || document.getElementById('trigger-folder-sub');
    const modalSelText = elements.folderModalSelectedText || document.getElementById('folder-modal-selected-text');
    const newFolderParent = elements.newFolderParentLabel || document.getElementById('new-folder-parent-label');

    const key = state.selectedFolderKey || 'WORK';
    if (triggerTitle) {
      if (key.includes('/')) {
        const parts = key.split('/');
        triggerTitle.textContent = parts[parts.length - 1].trim();
      } else {
        triggerTitle.textContent = key;
      }
    }
    if (triggerSub) {
      if (key.includes('/')) {
        const segments = key.split(/[\/\\]/).map(s => s.trim()).filter(Boolean);
        triggerSub.textContent = `📂 ${segments.join(' > ')}`;
      } else {
        triggerSub.textContent = 'Root Folder';
      }
    }
    if (modalSelText) {
      modalSelText.textContent = key;
    }
    if (newFolderParent) {
      const activeFolder = state.currentNavNode;
      newFolderParent.textContent = (activeFolder && !activeFolder.isVirtual && activeFolder.fullKey) ? activeFolder.fullKey : key;
    }
    if (elements.folderSelect) {
      elements.folderSelect.value = key;
    }
  }

  function selectFolderKey(folderKey, parentRoot, autoClose = false) {
    state.selectedFolderKey = folderKey;
    state.selectedParentRoot = parentRoot || (folderKey.includes('/') ? folderKey.split('/')[0].trim() : folderKey);
    updateFolderTriggerUI();
    const query = elements.folderSearchInput ? elements.folderSearchInput.value : '';
    renderFolderPickerList(query);

    if (autoClose) {
      closeFolderPickerModal();
    }
  }

  function openFolderPickerModal() {
    if (elements.folderPickerModal) {
      elements.folderPickerModal.classList.remove('hidden');
      document.body.style.overflow = 'hidden';
      if (elements.folderSearchInput) {
        elements.folderSearchInput.value = '';
      }
      if (elements.btnClearFolderSearch) {
        elements.btnClearFolderSearch.classList.add('hidden');
      }
      hideNewFolderForm();
      renderFolderPickerList('');
    }
  }

  function closeFolderPickerModal() {
    if (elements.folderPickerModal) {
      elements.folderPickerModal.classList.add('hidden');
      document.body.style.overflow = '';
      hideNewFolderForm();
    }
  }

  function toggleNewFolderForm() {
    if (!elements.folderCreateForm) return;
    const isHidden = elements.folderCreateForm.classList.contains('hidden');
    if (isHidden) {
      elements.folderCreateForm.classList.remove('hidden');
      if (elements.newFolderNameInput) {
        elements.newFolderNameInput.value = '';
        elements.newFolderNameInput.focus();
      }
      if (elements.btnCreateToggleText) {
        elements.btnCreateToggleText.textContent = 'Cancel';
      }
    } else {
      hideNewFolderForm();
    }
  }

  function hideNewFolderForm() {
    if (elements.folderCreateForm) {
      elements.folderCreateForm.classList.add('hidden');
    }
    if (elements.btnCreateToggleText) {
      elements.btnCreateToggleText.textContent = 'New Folder';
    }
  }

  async function handleCreateNewFolderSubmit() {
    if (!elements.newFolderNameInput) return;
    const name = elements.newFolderNameInput.value.trim();
    if (!name) {
      showToast('Please enter a folder name', true);
      elements.newFolderNameInput.focus();
      return;
    }

    // Task 2: Folder creation must be inside the folder currently open / focused by the user!
    let parent = 'WORK';
    if (state.currentNavNode && !state.currentNavNode.isVirtual) {
      parent = state.currentNavNode.fullKey;
    } else if (state.selectedFolderKey) {
      parent = state.selectedFolderKey;
    }

    const btn = elements.btnConfirmCreateFolder;
    if (btn) {
      btn.disabled = true;
      btn.textContent = '...';
    }

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (state.token) {
        headers['Authorization'] = `Bearer ${state.token}`;
      }

      const resp = await fetch('/api/folders/create', {
        method: 'POST',
        headers,
        body: JSON.stringify({ parent, name }),
      });

      if (resp.ok) {
        const data = await resp.json();
        showToast(`✓ Created folder "${name}"`);
        hideNewFolderForm();

        // Remember the currently viewed folder key
        const currentNavKey = state.currentNavNode ? state.currentNavNode.fullKey : null;

        // Reload folders from server
        await loadSharedFolders();

        // Restore view inside the currently focused folder
        if (currentNavKey && state.treeRoot) {
          const restoredNav = findNodeByKey(state.treeRoot, currentNavKey);
          if (restoredNav) {
            state.currentNavNode = restoredNav;
          }
        }

        // Highlight and select newly created folder
        if (data.folder_key) {
          selectFolderKey(data.folder_key, data.parent_preset || 'WORK', false);
        }
      } else {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail || 'Could not create folder', true);
      }
    } catch (err) {
      showToast('Network error creating folder', true);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Create';
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Hierarchical Folder Explorer & Search Rendering (Task 2)
  // ---------------------------------------------------------------------------
  function renderFolderPickerList(searchQuery = '') {
    const listEl = elements.folderPickerList;
    if (!listEl) return;

    const q = (searchQuery || '').trim().toLowerCase();
    const treeRoot = state.treeRoot || buildFolderTree(state.folders || []);

    // -------------------------------------------------------------------------
    // A. SEARCH MODE (When user types a search query)
    // -------------------------------------------------------------------------
    if (q) {
      if (elements.explorerBanner) elements.explorerBanner.classList.add('hidden');
      if (elements.explorerBreadcrumbsBar) elements.explorerBreadcrumbsBar.classList.add('hidden');

      const allNodes = collectAllNodes(treeRoot);
      const matches = allNodes.filter(node => {
        return node.name.toLowerCase().includes(q) || node.fullKey.toLowerCase().includes(q);
      });

      if (matches.length === 0) {
        listEl.innerHTML = `
          <div class="folder-empty-state">
            No folders match "<strong>${escapeHtml(q)}</strong>".<br/>
            <span style="font-size: 0.78rem; color: var(--color-emerald); margin-top: 0.5rem; display: inline-block;">
              Tip: Clear the search and tap "➕ New Folder" to create it.
            </span>
          </div>
        `;
        return;
      }

      matches.sort((a, b) => {
        const cmp = a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
        return state.sortAsc ? cmp : -cmp;
      });

      let html = '';
      matches.forEach(node => {
        const isSelected = state.selectedFolderKey === node.fullKey;
        const trailParts = [];
        let curr = node;
        while (curr && !curr.isVirtual) {
          trailParts.unshift(curr.name);
          curr = curr.parent;
        }
        const trailText = trailParts.join(' > ');

        html += `
          <div
            class="search-result-card ${isSelected ? 'selected' : ''}"
            role="button"
            tabindex="0"
            data-folder-key="${escapeHtml(node.fullKey)}"
            data-parent-root="${escapeHtml(node.presetRoot)}"
          >
            <div class="search-result-top">
              <div class="search-result-title-group">
                <span class="folder-card-icon">${node.isPreset ? '📁' : '📂'}</span>
                <span class="search-result-name">${escapeHtml(node.name)}</span>
              </div>
              <div class="folder-card-right">
                ${isSelected ? '<span class="active-check-icon">✓</span>' : ''}
                <button
                  type="button"
                  class="btn-open-dir"
                  data-jump-key="${escapeHtml(node.fullKey)}"
                  title="Open this folder in tree view"
                >↗</button>
              </div>
            </div>
            <div class="search-result-trail">${escapeHtml(trailText)}</div>
          </div>
        `;
      });

      listEl.innerHTML = html;

      listEl.querySelectorAll('.search-result-card').forEach(card => {
        card.addEventListener('click', (e) => {
          if (e.target.closest('.btn-open-dir')) return;
          const key = card.getAttribute('data-folder-key');
          const root = card.getAttribute('data-parent-root');
          selectFolderKey(key, root, false);
        });
      });

      listEl.querySelectorAll('[data-jump-key]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const targetKey = btn.getAttribute('data-jump-key');
          const targetNode = findNodeByKey(treeRoot, targetKey);
          if (targetNode) {
            // Jump directly inside this folder so user can view/create within it
            state.currentNavNode = targetNode;
            if (elements.folderSearchInput) elements.folderSearchInput.value = '';
            if (elements.btnClearFolderSearch) elements.btnClearFolderSearch.classList.add('hidden');
            selectFolderKey(targetNode.fullKey, targetNode.presetRoot, false);
            renderFolderPickerList('');
          }
        });
      });
      return;
    }

    // -------------------------------------------------------------------------
    // B. HIERARCHICAL EXPLORER DIRECTORY MODE (Matching user's sketch)
    // -------------------------------------------------------------------------
    if (elements.explorerBanner) elements.explorerBanner.classList.remove('hidden');
    if (elements.explorerBreadcrumbsBar) elements.explorerBreadcrumbsBar.classList.remove('hidden');

    let currNode = state.currentNavNode;
    if (!currNode) {
      currNode = (treeRoot.children.length === 1) ? treeRoot.children[0] : treeRoot;
      state.currentNavNode = currNode;
    }

    // 1. Update Big Folder Banner Title
    if (elements.explorerCurrentTitle) {
      elements.explorerCurrentTitle.textContent = currNode.isVirtual ? 'ALL PRESETS' : currNode.name.toUpperCase();
    }
    if (elements.explorerBannerBadge) {
      elements.explorerBannerBadge.textContent = currNode.isVirtual ? 'ROOT' : (currNode.isPreset ? 'ALLOWED FOLDER' : 'SUBFOLDER');
    }

    // 2. Select Current Folder Button in Banner
    if (elements.btnChooseCurrentFolder) {
      if (currNode.isVirtual) {
        elements.btnChooseCurrentFolder.classList.add('hidden');
      } else {
        elements.btnChooseCurrentFolder.classList.remove('hidden');
        const isCurrentActive = state.selectedFolderKey === currNode.fullKey;
        if (isCurrentActive) {
          elements.btnChooseCurrentFolder.innerHTML = '<span>✓ Active Target</span>';
          elements.btnChooseCurrentFolder.classList.add('btn-choose-active');
        } else {
          elements.btnChooseCurrentFolder.innerHTML = '<span>✓ Select This Folder</span>';
          elements.btnChooseCurrentFolder.classList.remove('btn-choose-active');
        }
      }
    }

    // 3. Update Breadcrumbs (e.g. works > TKP)
    if (elements.explorerBreadcrumbs) {
      const trail = [];
      let temp = currNode;
      while (temp) {
        if (!temp.isVirtual) {
          trail.unshift(temp);
        }
        temp = temp.parent;
      }

      let breadcrumbsHtml = '';
      if (treeRoot.children.length > 1) {
        breadcrumbsHtml += `
          <span class="crumb-item ${currNode.isVirtual ? 'active' : ''}" data-crumb-nav="root">Home</span>
        `;
      }

      trail.forEach((item, index) => {
        const isLast = (index === trail.length - 1);
        if (breadcrumbsHtml) {
          breadcrumbsHtml += `<span class="crumb-sep">&gt;</span>`;
        }
        breadcrumbsHtml += `
          <span
            class="crumb-item ${isLast ? 'active' : ''}"
            data-crumb-nav="${escapeHtml(item.fullKey)}"
          >${escapeHtml(item.name.toLowerCase())}</span>
        `;
      });

      elements.explorerBreadcrumbs.innerHTML = breadcrumbsHtml;

      elements.explorerBreadcrumbs.querySelectorAll('[data-crumb-nav]').forEach(crumb => {
        crumb.addEventListener('click', () => {
          const navTarget = crumb.getAttribute('data-crumb-nav');
          if (navTarget === 'root') {
            state.currentNavNode = treeRoot;
            renderFolderPickerList('');
          } else {
            const found = findNodeByKey(treeRoot, navTarget);
            if (found && found !== state.currentNavNode) {
              state.currentNavNode = found;
              renderFolderPickerList('');
            }
          }
        });
      });
    }

    // 4. Up Navigation Button
    if (elements.btnNavUp) {
      if (currNode.parent && (!currNode.parent.isVirtual || treeRoot.children.length > 1)) {
        elements.btnNavUp.classList.remove('hidden');
      } else {
        elements.btnNavUp.classList.add('hidden');
      }
    }

    // 5. Update New Folder Parent Label (inside inline form)
    if (elements.newFolderParentLabel) {
      elements.newFolderParentLabel.textContent = currNode.isVirtual ? 'Root' : currNode.fullKey;
    }

    // 6. Update Sort Toggle Text
    if (elements.btnSortToggleText) {
      elements.btnSortToggleText.textContent = `Sort: ${state.sortAsc ? 'A-Z' : 'Z-A'}`;
    }

    // 7. List Immediate Child Folders
    let children = [...currNode.children];
    children.sort((a, b) => {
      const cmp = a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
      return state.sortAsc ? cmp : -cmp;
    });

    if (children.length === 0) {
      listEl.innerHTML = `
        <div class="folder-empty-state">
          <div class="empty-state-icon" style="font-size: 2.2rem; margin-bottom: 0.35rem; opacity: 0.7;">📂</div>
          <div class="empty-state-title" style="font-size: 0.98rem; font-weight: 700; color: #ffffff;">
            ${escapeHtml(currNode.name)} is empty
          </div>
          <div class="empty-state-desc" style="font-size: 0.8rem; color: var(--text-dim); margin-top: 0.25rem;">
            No subfolders inside this folder yet.
          </div>
          <button
            type="button"
            class="btn btn-primary btn-sm btn-empty-create"
            id="btn-empty-state-create"
            style="margin-top: 0.85rem; padding: 0.45rem 1rem; font-size: 0.82rem; font-weight: 700; border-radius: 8px;"
          >
            ➕ Create Subfolder Here
          </button>
        </div>
      `;
      const emptyBtn = listEl.querySelector('#btn-empty-state-create');
      if (emptyBtn) {
        emptyBtn.addEventListener('click', toggleNewFolderForm);
      }
      return;
    }

    let html = '';
    children.forEach(child => {
      const isSelected = state.selectedFolderKey === child.fullKey;
      const subCount = child.children.length;

      html += `
        <div
          class="folder-card-item ${isSelected ? 'selected' : ''}"
          role="button"
          tabindex="0"
          data-folder-key="${escapeHtml(child.fullKey)}"
          data-parent-root="${escapeHtml(child.presetRoot)}"
        >
          <div class="folder-card-left">
            <span class="folder-card-icon">${child.isPreset ? '📁' : '📂'}</span>
            <div class="folder-card-info">
              <span class="folder-card-name">${escapeHtml(child.name)}</span>
              <span class="folder-card-sub">${subCount > 0 ? `${subCount} subfolder${subCount > 1 ? 's' : ''}` : 'Empty folder'}</span>
            </div>
          </div>
          <div class="folder-card-right">
            ${isSelected ? '<span class="active-check-icon" title="Active Target">✓</span>' : ''}
            <button
              type="button"
              class="btn-open-dir"
              data-open-folder="${escapeHtml(child.fullKey)}"
              title="Open folder ${escapeHtml(child.name)}"
              aria-label="Open folder ${escapeHtml(child.name)}"
            >
              <span class="btn-open-text">Open</span>
              <span class="btn-open-arrow">›</span>
            </button>
          </div>
        </div>
      `;
    });

    listEl.innerHTML = html;

    listEl.querySelectorAll('.folder-card-item').forEach(card => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('.btn-open-dir')) return;
        const key = card.getAttribute('data-folder-key');
        const root = card.getAttribute('data-parent-root');

        // If this folder is already selected, tapping it again opens/steps into it!
        if (state.selectedFolderKey === key) {
          const targetNode = findNodeByKey(treeRoot, key);
          if (targetNode) {
            state.currentNavNode = targetNode;
            renderFolderPickerList('');
            return;
          }
        }

        selectFolderKey(key, root, false);
      });

      // Double-click/tap to directly open the folder
      card.addEventListener('dblclick', () => {
        const key = card.getAttribute('data-folder-key');
        const targetNode = findNodeByKey(treeRoot, key);
        if (targetNode) {
          state.currentNavNode = targetNode;
          renderFolderPickerList('');
        }
      });
    });

    listEl.querySelectorAll('[data-open-folder]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const targetKey = btn.getAttribute('data-open-folder');
        const targetNode = findNodeByKey(treeRoot, targetKey);
        if (targetNode) {
          state.currentNavNode = targetNode;
          renderFolderPickerList('');
        }
      });
    });
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
  // YouTube Detection & Format Selector Gating
  // ---------------------------------------------------------------------------
  function isYouTubeUrl(url) {
    if (!url) return false;
    return /^(https?:\/\/)?([a-zA-Z0-9-]+\.)?(youtube\.com|youtu\.be)\//i.test(url.trim());
  }

  function extractCleanUrl(text) {
    if (!text) return '';
    const trimmed = text.trim();
    // 1. Look for embedded http/https url (e.g. from mobile share text)
    const match = trimmed.match(/https?:\/\/[^\s"'<>]+/i);
    if (match) return match[0];
    // 2. If user entered without protocol (e.g. youtu.be/... or youtube.com/...)
    if (/^[a-zA-Z0-9-]+\.[a-zA-Z]{2,}\//.test(trimmed)) {
      return 'https://' + trimmed;
    }
    return trimmed;
  }

  function detectClientPlatform(url) {
    if (!url) return 'Media';
    const lower = url.toLowerCase();
    if (lower.includes('youtube.com') || lower.includes('youtu.be')) return 'YouTube';
    if (lower.includes('instagram.com')) return 'Instagram';
    if (lower.includes('tiktok.com')) return 'TikTok';
    if (lower.includes('twitter.com') || lower.includes('x.com')) return 'Twitter';
    if (lower.includes('pinterest.com') || lower.includes('pin.it')) return 'Pinterest';
    if (lower.includes('vimeo.com')) return 'Vimeo';
    if (lower.includes('reddit.com')) return 'Reddit';
    return 'Web Media';
  }

  function getPlatformEmoji(platform) {
    const p = (platform || '').toUpperCase();
    if (p.includes('YOUTUBE')) return '🎬';
    if (p.includes('INSTAGRAM')) return '📸';
    if (p.includes('TIKTOK')) return '🎵';
    if (p.includes('TWITTER') || p.includes('X')) return '🐦';
    if (p.includes('PINTEREST')) return '📌';
    if (p.includes('VIMEO')) return '🎥';
    return '🌐';
  }

  function updateFormatVisibility(url) {
    const isYt = isYouTubeUrl(url);
    if (elements.formatField) {
      if (isYt) {
        elements.formatField.classList.remove('hidden');
      } else {
        elements.formatField.classList.add('hidden');
        setFormat('video');
      }
    }
    return isYt;
  }

  // ---------------------------------------------------------------------------
  // Media Preview & Inspect (Search Button)
  // ---------------------------------------------------------------------------
  function showPreviewCard(data) {
    if (!elements.previewCard) return;

    const platform = (data.platform || detectClientPlatform(data.url) || 'Media').toUpperCase();
    if (elements.previewTitle) {
      elements.previewTitle.textContent = data.title || `${platform} Media`;
    }
    if (elements.previewPlatformBadge) {
      elements.previewPlatformBadge.textContent = platform;
    }

    const fallbackIcon = document.getElementById('preview-fallback-icon');
    const thumbImg = elements.previewThumbnailImg;

    if (data.thumbnail && thumbImg) {
      thumbImg.src = data.thumbnail;
      thumbImg.style.display = 'block';
      if (fallbackIcon) fallbackIcon.classList.add('hidden');
      thumbImg.onerror = () => {
        thumbImg.style.display = 'none';
        if (fallbackIcon) {
          fallbackIcon.textContent = getPlatformEmoji(platform);
          fallbackIcon.classList.remove('hidden');
        }
      };
    } else {
      if (thumbImg) thumbImg.style.display = 'none';
      if (fallbackIcon) {
        fallbackIcon.textContent = getPlatformEmoji(platform);
        fallbackIcon.classList.remove('hidden');
      }
    }

    if (elements.previewStatus) {
      elements.previewStatus.textContent = '✓ Ready to download';
    }
    elements.previewCard.classList.remove('hidden');
  }

  function hidePreviewCard() {
    if (!elements.previewCard) return;
    elements.previewCard.classList.add('hidden');
  }

  async function handleMediaSearch(e) {
    if (e && e.preventDefault) e.preventDefault();

    let rawUrl = elements.urlInput ? elements.urlInput.value.trim() : '';
    if (!rawUrl) {
      showToast('Please enter or paste a link first to search.', true);
      if (elements.urlInput) elements.urlInput.focus();
      return;
    }

    const cleanUrl = extractCleanUrl(rawUrl);
    if (cleanUrl !== rawUrl && elements.urlInput) {
      elements.urlInput.value = cleanUrl;
    }

    const isYt = updateFormatVisibility(cleanUrl);

    // Instant thumbnail display for YouTube while waiting for full metadata (<1ms!)
    const ytMatch = cleanUrl.match(/(?:v=|\/|youtu\.be\/|shorts\/)([a-zA-Z0-9_-]{11})/i);
    if (ytMatch && ytMatch[1]) {
      const vid = ytMatch[1];
      showPreviewCard({
        title: 'YouTube Video',
        thumbnail: `https://img.youtube.com/vi/${vid}/hqdefault.jpg`,
        platform: 'YouTube',
        is_youtube: true,
      });
    } else {
      const platformName = detectClientPlatform(cleanUrl);
      showPreviewCard({
        title: `${platformName.toUpperCase()} Media`,
        thumbnail: '',
        platform: platformName,
        is_youtube: false,
      });
    }

    if (elements.btnSearch) {
      elements.btnSearch.disabled = true;
      elements.btnSearch.classList.add('searching');
      const textSpan = elements.btnSearch.querySelector('#search-btn-text') || elements.btnSearch.querySelector('span:last-child');
      if (textSpan) textSpan.textContent = 'Searching...';
      const iconSpan = elements.btnSearch.querySelector('#search-btn-icon') || elements.btnSearch.querySelector('span:first-child');
      if (iconSpan) iconSpan.textContent = '⏳';
    }

    try {
      const resp = await fetch('/api/media/inspect', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(state.token ? { 'Authorization': `Bearer ${state.token}` } : {}),
        },
        body: JSON.stringify({ url: cleanUrl }),
      });

      if (resp.ok) {
        const data = await resp.json();
        showPreviewCard(data);
        if (data.is_youtube !== undefined) {
          if (elements.formatField) {
            if (data.is_youtube) {
              elements.formatField.classList.remove('hidden');
            } else {
              elements.formatField.classList.add('hidden');
              setFormat('video');
            }
          }
        }
        showToast(`✓ Found: ${data.title}`);
      } else {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail || 'Could not inspect media link', true);
      }
    } catch (err) {
      showToast('Network error inspecting link', true);
    } finally {
      if (elements.btnSearch) {
        elements.btnSearch.disabled = false;
        elements.btnSearch.classList.remove('searching');
        const textSpan = elements.btnSearch.querySelector('#search-btn-text') || elements.btnSearch.querySelector('span:last-child');
        if (textSpan) textSpan.textContent = 'Search';
        const iconSpan = elements.btnSearch.querySelector('#search-btn-icon') || elements.btnSearch.querySelector('span:first-child');
        if (iconSpan) iconSpan.textContent = '🔍';
      }
    }
  }

  // Expose globally for inline onclick
  window.handleMediaSearch = handleMediaSearch;

  // ---------------------------------------------------------------------------
  // Queued Download Pop-up Modal System
  // ---------------------------------------------------------------------------
  function showQueuedModal(folderName, formatType) {
    if (!elements.queuedModal) return;

    if (elements.modalFolderName) {
      elements.modalFolderName.textContent = folderName;
    }
    if (elements.modalFormatVal) {
      elements.modalFormatVal.textContent = formatType === 'audio' ? 'Audio (MP3)' : 'Video (MP4)';
    }

    elements.queuedModal.classList.remove('hidden');

    if (state.modalTimeout) {
      clearTimeout(state.modalTimeout);
    }
    state.modalTimeout = setTimeout(hideQueuedModal, 4500);
  }

  function hideQueuedModal() {
    if (elements.queuedModal) {
      elements.queuedModal.classList.add('hidden');
    }
    if (state.modalTimeout) {
      clearTimeout(state.modalTimeout);
      state.modalTimeout = null;
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
          updateFormatVisibility(text.trim());
          showToast('📋 Link pasted from clipboard!');
          handleMediaSearch();
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

    let rawUrl = elements.urlInput ? elements.urlInput.value.trim() : '';
    if (!rawUrl) {
      showToast('Please enter or paste a media URL.', true);
      if (elements.urlInput) elements.urlInput.focus();
      return;
    }

    rawUrl = extractCleanUrl(rawUrl);

    if (!/^https?:\/\//i.test(rawUrl)) {
      showToast('Please enter a valid HTTP or HTTPS media link.', true);
      if (elements.urlInput) elements.urlInput.focus();
      return;
    }

    const folder = state.selectedFolderKey || (elements.folderSelect ? elements.folderSelect.value : 'B-Roll (General)');
    const format = state.selectedFormat || 'video';
    const token = state.token;

    if (!token) {
      showToast('Authentication session lost. Please reconnect to PC.', true);
      setStage('connection');
      return;
    }

    // Immediately show the "Queued to download" pop-up modal and toast!
    showQueuedModal(folder, format);
    showToast('⚡ Queued! Downloading on PC.');
    hidePreviewCard();
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
  // Session Persistence & Seamless Auto-Login (Task 1)
  // ---------------------------------------------------------------------------
  async function initSession() {
    const cached = getCachedCredentials();
    let savedToken = cached.token;
    let savedUid = cached.uid;
    let savedPw = cached.password;

    // Pre-fill inputs in case connection screen is shown
    if (savedUid && elements.uidInput) elements.uidInput.value = savedUid;
    if (savedPw && elements.passwordInput) elements.passwordInput.value = savedPw;

    // 1. If we have a saved token, check if it is still valid
    if (savedToken) {
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
          return;
        }
      } catch (_) {}
    }

    // 2. If token expired, missing, or server restarted:
    // Perform seamless silent background auto-login with cached credentials!
    if (savedUid && savedPw) {
      try {
        const response = await fetch('/api/auth/login', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          body: JSON.stringify({ uid: savedUid, password: savedPw }),
        });

        if (response.ok) {
          const data = await response.json();
          const newToken = data.session_token;

          state.token = newToken;
          state.serverUid = savedUid;
          saveAuthCredentials(savedUid, savedPw, newToken);

          updateConnectedStatus(savedUid);
          setStage('download');
          await loadSharedFolders(newToken);
          showToast(`✓ Connected to PC (UID: ${savedUid})`);
          return;
        }
      } catch (_) {}
    }

    // 3. Fallback to connection screen if credentials not available or rejected
    setStage('connection');
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

    // Stage 2 Search Button (Click & Touch)
    if (elements.btnSearch) {
      elements.btnSearch.addEventListener('click', (e) => {
        handleMediaSearch(e);
      });
      elements.btnSearch.addEventListener('touchend', (e) => {
        e.preventDefault();
        handleMediaSearch(e);
      });
    }

    // Live URL Input Gating, Enter key to search, and Auto-search on paste
    if (elements.urlInput) {
      elements.urlInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          handleMediaSearch(e);
        }
      });
      elements.urlInput.addEventListener('input', (e) => {
        updateFormatVisibility(e.target.value);
      });
      elements.urlInput.addEventListener('paste', () => {
        setTimeout(() => {
          if (elements.urlInput) {
            updateFormatVisibility(elements.urlInput.value);
            handleMediaSearch();
          }
        }, 80);
      });
    }

    // Folder Picker Modal Trigger & Controls (Tasks 2 & 3)
    if (elements.folderTrigger) {
      elements.folderTrigger.addEventListener('click', openFolderPickerModal);
    }
    if (elements.btnCloseFolderPicker) {
      elements.btnCloseFolderPicker.addEventListener('click', closeFolderPickerModal);
    }
    if (elements.folderPickerBackdrop) {
      elements.folderPickerBackdrop.addEventListener('click', closeFolderPickerModal);
    }
    if (elements.btnConfirmFolderModal) {
      elements.btnConfirmFolderModal.addEventListener('click', closeFolderPickerModal);
    }

    // Choose Current Folder in Explorer Banner
    if (elements.btnChooseCurrentFolder) {
      elements.btnChooseCurrentFolder.addEventListener('click', () => {
        if (state.currentNavNode && !state.currentNavNode.isVirtual) {
          selectFolderKey(state.currentNavNode.fullKey, state.currentNavNode.presetRoot, false);
          showToast(`✓ Selected "${state.currentNavNode.name}" as destination`);
        }
      });
    }

    // Explorer Up Navigation Button
    if (elements.btnNavUp) {
      elements.btnNavUp.addEventListener('click', () => {
        if (state.currentNavNode && state.currentNavNode.parent) {
          state.currentNavNode = state.currentNavNode.parent;
          renderFolderPickerList('');
        }
      });
    }

    // Explorer Sort Button Toggle
    if (elements.btnToggleSort) {
      elements.btnToggleSort.addEventListener('click', () => {
        state.sortAsc = !state.sortAsc;
        const query = elements.folderSearchInput ? elements.folderSearchInput.value : '';
        renderFolderPickerList(query);
      });
    }

    // Folder Search Input
    if (elements.folderSearchInput) {
      elements.folderSearchInput.addEventListener('input', (e) => {
        const val = e.target.value;
        if (elements.btnClearFolderSearch) {
          if (val) {
            elements.btnClearFolderSearch.classList.remove('hidden');
          } else {
            elements.btnClearFolderSearch.classList.add('hidden');
          }
        }
        renderFolderPickerList(val);
      });
    }

    if (elements.btnClearFolderSearch) {
      elements.btnClearFolderSearch.addEventListener('click', () => {
        if (elements.folderSearchInput) {
          elements.folderSearchInput.value = '';
          elements.folderSearchInput.focus();
        }
        elements.btnClearFolderSearch.classList.add('hidden');
        renderFolderPickerList('');
      });
    }

    // Create New Folder Controls (Task 3)
    if (elements.btnToggleNewFolder) {
      elements.btnToggleNewFolder.addEventListener('click', toggleNewFolderForm);
    }
    if (elements.btnConfirmCreateFolder) {
      elements.btnConfirmCreateFolder.addEventListener('click', handleCreateNewFolderSubmit);
    }
    if (elements.btnCancelCreateFolder) {
      elements.btnCancelCreateFolder.addEventListener('click', hideNewFolderForm);
    }
    if (elements.newFolderNameInput) {
      elements.newFolderNameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          handleCreateNewFolderSubmit();
        }
      });
    }

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeFolderPickerModal();
      }
    });

    // Queued Modal Dismiss
    if (elements.btnCloseModal) {
      elements.btnCloseModal.addEventListener('click', hideQueuedModal);
    }
    if (elements.queuedModalBackdrop) {
      elements.queuedModalBackdrop.addEventListener('click', hideQueuedModal);
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
