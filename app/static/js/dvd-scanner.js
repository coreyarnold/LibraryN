'use strict';

const upcInput      = document.getElementById('upc-input');
const lookupBtn     = document.getElementById('lookup-btn');
const resultDiv     = document.getElementById('scan-result');
const locationInput = document.getElementById('session-location');
const conditionSelect = document.getElementById('session-condition');
const manualModal   = new bootstrap.Modal(document.getElementById('manualModal'));

// Restore session settings
locationInput.value = sessionStorage.getItem('dvdScanLocation') || '';
const savedCondition = sessionStorage.getItem('dvdScanCondition');
if (savedCondition) conditionSelect.value = savedCondition;

locationInput.addEventListener('input', () => {
  sessionStorage.setItem('dvdScanLocation', locationInput.value);
});
conditionSelect.addEventListener('change', () => {
  sessionStorage.setItem('dvdScanCondition', conditionSelect.value);
});

// User selector (admin only)
let selectedUserId = currentUserId;
document.querySelectorAll('.user-select-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.user-select-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedUserId = parseInt(btn.dataset.userId);
  });
});

// Keep UPC input focused
upcInput.focus();
document.addEventListener('click', e => {
  if (!e.target.closest('button, a, input, select, textarea, .modal'))
    upcInput.focus();
});

upcInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); triggerScan(); }
});
lookupBtn.addEventListener('click', triggerScan);

function triggerScan() {
  const upc = upcInput.value.trim().replace(/[^0-9]/g, '');
  if (!upc) return;
  upcInput.value = '';
  scanAndAdd(upc);
}

async function scanAndAdd(upc) {
  showLoading();

  let dvdData;
  try {
    const res  = await fetch(`/api/dvd/lookup/${upc}`);
    const data = await res.json();
    if (!res.ok) {
      const lstatus = res.status === 400 ? 'invalid'
                    : res.status === 429 ? 'rate_limited'
                    : 'not_found';
      logScan({ upc, lookup_status: lstatus, error_detail: data.error });
      if (res.status === 429) {
        enqueueRetry('dvd', upc);
        showRateLimited();
      } else {
        showError(data.error || 'DVD not found.', upc);
      }
      upcInput.focus();
      return;
    }
    dvdData = data;
  } catch {
    logScan({ upc, lookup_status: 'error', error_detail: 'network_error' });
    showError('Network error — check your connection.', upc);
    upcInput.focus();
    return;
  }

  const lookupStatus = dvdData.in_library ? 'found_local' : 'found_external';

  if ((dvdData.owners || []).some(o => o.id === selectedUserId)) {
    logScan({ upc, lookup_status: lookupStatus, add_status: 'already_owned',
              dvd_id: dvdData.id, title: dvdData.title });
    showAlreadyOwned(dvdData);
    upcInput.focus();
    return;
  }

  try {
    const res  = await fetch('/api/dvds', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        upc:         dvdData.upc,
        title:       dvdData.title,
        director:    dvdData.director    || '',
        studio:      dvdData.studio      || '',
        year:        dvdData.year        || '',
        runtime:     dvdData.runtime     || null,
        rating:      dvdData.rating      || '',
        genre:       dvdData.genre       || '',
        description: dvdData.description || '',
        cover_url:   dvdData.cover_url   || '',
        format:      dvdData.format      || 'DVD',
        user_id:     selectedUserId,
        condition:   conditionSelect.value,
        location:    locationInput.value.trim(),
      }),
    });
    const data = await res.json();

    if (data.success) {
      logScan({ upc, lookup_status: lookupStatus, add_status: 'added',
                dvd_id: data.dvd_id, title: dvdData.title });
      showSuccess(dvdData, data.dvd_id);
    } else if (res.status === 409) {
      logScan({ upc, lookup_status: lookupStatus, add_status: 'already_owned',
                dvd_id: dvdData.id, title: dvdData.title });
      showAlreadyOwned(dvdData);
    } else {
      logScan({ upc, lookup_status: lookupStatus, add_status: 'error',
                title: dvdData.title, error_detail: data.error });
      showError(data.error || 'Failed to add DVD.', upc);
    }
  } catch {
    logScan({ upc, lookup_status: lookupStatus, add_status: 'error',
              title: dvdData.title, error_detail: 'network_error' });
    showError('Network error — check your connection.', upc);
  }

  upcInput.focus();
}

function logScan(payload) {
  fetch('/api/dvd-scan-log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {});
}

function enqueueRetry(mediaType, identifier) {
  fetch('/api/retry-queue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      media_type:  mediaType,
      identifier:  identifier,
      for_user_id: selectedUserId,
      condition:   conditionSelect.value,
      location:    locationInput.value.trim(),
    }),
  }).catch(() => {});
}

function showRateLimited() {
  resultDiv.innerHTML = `
    <div class="card shadow-sm mb-3 border-start border-warning border-3">
      <div class="card-body py-2 px-3">
        <div class="d-flex align-items-center gap-2 mb-1">
          <i class="bi bi-hourglass-split text-warning flex-shrink-0"></i>
          <span class="fw-semibold text-warning small">Rate limited — queued for retry</span>
        </div>
        <p class="text-muted small mb-0">
          Will retry automatically in 45 s, then 90 s, then 180 s if needed.
          Check the Audit log for the final result.
        </p>
      </div>
    </div>`;
}

// --- Result display ---

function showLoading() {
  resultDiv.innerHTML = `
    <div class="card shadow-sm mb-3 p-3">
      <div class="d-flex align-items-center gap-3 text-muted">
        <div class="spinner-border spinner-border-sm"></div>
        <span>Looking up and adding…</span>
      </div>
    </div>`;
}

function dvdThumb(dvd) {
  return dvd.cover_url
    ? `<img src="${escHtml(dvd.cover_url)}" alt=""
           style="width:48px;height:72px;object-fit:cover;border-radius:4px;flex-shrink:0">`
    : `<div style="width:48px;height:72px;background:#e9ecef;border-radius:4px;flex-shrink:0;
                   display:flex;align-items:center;justify-content:center">
         <i class="bi bi-collection-play text-muted"></i>
       </div>`;
}

function showSuccess(dvd, dvdId) {
  resultDiv.innerHTML = `
    <div class="card shadow-sm mb-3 border-start border-success border-3">
      <div class="card-body py-2 px-3">
        <div class="d-flex align-items-center gap-3">
          ${dvdThumb(dvd)}
          <div class="flex-grow-1 min-w-0">
            <div class="d-flex align-items-center gap-2 mb-1">
              <i class="bi bi-check-circle-fill text-success"></i>
              <span class="fw-semibold text-success small">Added</span>
            </div>
            <div class="fw-bold text-truncate">${escHtml(dvd.title)}</div>
            ${dvd.director ? `<div class="text-muted small text-truncate">dir. ${escHtml(dvd.director)}</div>` : ''}
          </div>
          <a href="/dvds/${dvdId}" class="btn btn-sm btn-outline-secondary flex-shrink-0">View</a>
        </div>
      </div>
    </div>`;
}

function showAlreadyOwned(dvd) {
  resultDiv.innerHTML = `
    <div class="card shadow-sm mb-3 border-start border-warning border-3">
      <div class="card-body py-2 px-3">
        <div class="d-flex align-items-center gap-3">
          ${dvdThumb(dvd)}
          <div class="flex-grow-1 min-w-0">
            <div class="d-flex align-items-center gap-2 mb-1">
              <i class="bi bi-bookmark-check-fill text-warning"></i>
              <span class="fw-semibold text-warning small">Already in library</span>
            </div>
            <div class="fw-bold text-truncate">${escHtml(dvd.title)}</div>
            ${dvd.director ? `<div class="text-muted small text-truncate">dir. ${escHtml(dvd.director)}</div>` : ''}
          </div>
        </div>
      </div>
    </div>`;
}

function showError(message, upc) {
  resultDiv.innerHTML = `
    <div class="card shadow-sm mb-3 border-start border-danger border-3">
      <div class="card-body py-2 px-3">
        <div class="d-flex align-items-start gap-2 text-danger mb-2">
          <i class="bi bi-exclamation-circle-fill mt-1 flex-shrink-0"></i>
          <span class="small">${escHtml(message)}</span>
        </div>
        <button class="btn btn-sm btn-outline-secondary" id="open-manual">
          <i class="bi bi-pencil me-1"></i>Add Manually
        </button>
      </div>
    </div>`;

  document.getElementById('open-manual').addEventListener('click', () => {
    document.getElementById('manual-upc').value      = upc || '';
    document.getElementById('manual-location').value = locationInput.value.trim();
    document.getElementById('manual-condition').value = conditionSelect.value;
    manualModal.show();
    setTimeout(() => document.getElementById('manual-title').focus(), 300);
  });
}

// --- Manual entry ---

document.getElementById('manual-submit').addEventListener('click', async () => {
  const upc   = document.getElementById('manual-upc').value.trim();
  const title = document.getElementById('manual-title').value.trim();
  if (!upc || !title) { alert('UPC and title are required.'); return; }

  const btn = document.getElementById('manual-submit');
  btn.disabled = true;

  try {
    const res  = await fetch('/api/dvds', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        upc, title,
        director:  document.getElementById('manual-director').value.trim(),
        studio:    document.getElementById('manual-studio').value.trim(),
        year:      document.getElementById('manual-year').value.trim(),
        rating:    document.getElementById('manual-rating').value.trim(),
        format:    document.getElementById('manual-format').value,
        condition: document.getElementById('manual-condition').value,
        location:  document.getElementById('manual-location').value.trim(),
        user_id:   selectedUserId,
      }),
    });
    const data = await res.json();

    if (data.success) {
      manualModal.hide();
      showSuccess({ title, director: document.getElementById('manual-director').value.trim(), cover_url: '' },
                  data.dvd_id);
    } else {
      alert(data.error || 'Failed to add DVD.');
    }
  } catch {
    alert('Network error.');
  } finally {
    btn.disabled = false;
  }
});

function escHtml(str) {
  return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
