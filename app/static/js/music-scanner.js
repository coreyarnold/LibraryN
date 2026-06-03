'use strict';

const barcodeInput  = document.getElementById('barcode-input');
const lookupBtn     = document.getElementById('lookup-btn');
const resultDiv     = document.getElementById('scan-result');
const locationInput = document.getElementById('session-location');
const conditionSelect = document.getElementById('session-condition');
const manualModal   = new bootstrap.Modal(document.getElementById('manualModal'));

locationInput.value = sessionStorage.getItem('musicScanLocation') || '';
const savedCondition = sessionStorage.getItem('musicScanCondition');
if (savedCondition) conditionSelect.value = savedCondition;

locationInput.addEventListener('input',  () => sessionStorage.setItem('musicScanLocation', locationInput.value));
conditionSelect.addEventListener('change', () => sessionStorage.setItem('musicScanCondition', conditionSelect.value));

let selectedUserId = currentUserId;
document.querySelectorAll('.user-select-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.user-select-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedUserId = parseInt(btn.dataset.userId);
  });
});

barcodeInput.focus();
document.addEventListener('click', e => {
  if (!e.target.closest('button, a, input, select, textarea, .modal'))
    barcodeInput.focus();
});

barcodeInput.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); triggerScan(); } });
lookupBtn.addEventListener('click', triggerScan);

function triggerScan() {
  const barcode = barcodeInput.value.trim().replace(/[^0-9]/g, '');
  if (!barcode) return;
  barcodeInput.value = '';
  scanAndAdd(barcode);
}

async function scanAndAdd(barcode) {
  showLoading();

  let releaseData;
  try {
    const res  = await fetch(`/api/music/lookup/${barcode}`);
    const data = await res.json();
    if (!res.ok) {
      const lstatus = res.status === 400 ? 'invalid'
                    : res.status === 429 ? 'rate_limited'
                    : 'not_found';
      logScan({ barcode, lookup_status: lstatus, error_detail: data.error });
      if (res.status === 429) { enqueueRetry('music', barcode); showRateLimited(); }
      else                    { showError(data.error || 'Release not found.', barcode); }
      barcodeInput.focus();
      return;
    }
    releaseData = data;
  } catch {
    logScan({ barcode, lookup_status: 'error', error_detail: 'network_error' });
    showError('Network error — check your connection.', barcode);
    barcodeInput.focus();
    return;
  }

  const lookupStatus = releaseData.in_library ? 'found_local' : 'found_external';

  if ((releaseData.owners || []).some(o => o.id === selectedUserId)) {
    logScan({ barcode, lookup_status: lookupStatus, add_status: 'already_owned',
              music_id: releaseData.id, title: releaseData.title });
    showAlreadyOwned(releaseData);
    barcodeInput.focus();
    return;
  }

  try {
    const res  = await fetch('/api/music', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        barcode:     releaseData.barcode,
        title:       releaseData.title,
        artist:      releaseData.artist      || '',
        label:       releaseData.label       || '',
        year:        releaseData.year        || '',
        format:      releaseData.format      || '',
        track_count: releaseData.track_count || null,
        genre:       releaseData.genre       || '',
        cover_url:   releaseData.cover_url   || '',
        mbid:        releaseData.mbid        || '',
        user_id:     selectedUserId,
        condition:   conditionSelect.value,
        location:    locationInput.value.trim(),
      }),
    });
    const data = await res.json();

    if (data.success) {
      logScan({ barcode, lookup_status: lookupStatus, add_status: 'added',
                music_id: data.music_id, title: releaseData.title });
      showSuccess(releaseData, data.music_id);
    } else if (res.status === 409) {
      logScan({ barcode, lookup_status: lookupStatus, add_status: 'already_owned',
                music_id: releaseData.id, title: releaseData.title });
      showAlreadyOwned(releaseData);
    } else {
      logScan({ barcode, lookup_status: lookupStatus, add_status: 'error',
                title: releaseData.title, error_detail: data.error });
      showError(data.error || 'Failed to add release.', barcode);
    }
  } catch {
    logScan({ barcode, lookup_status: lookupStatus, add_status: 'error',
              title: releaseData.title, error_detail: 'network_error' });
    showError('Network error — check your connection.', barcode);
  }

  barcodeInput.focus();
}

function logScan(payload) {
  fetch('/api/music-scan-log', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {});
}

function enqueueRetry(mediaType, identifier) {
  fetch('/api/retry-queue', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      media_type: mediaType, identifier,
      for_user_id: selectedUserId,
      condition:   conditionSelect.value,
      location:    locationInput.value.trim(),
    }),
  }).catch(() => {});
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

function thumb(release) {
  return release.cover_url
    ? `<img src="${escHtml(release.cover_url)}" alt="" style="width:48px;height:48px;object-fit:cover;border-radius:4px;flex-shrink:0">`
    : `<div style="width:48px;height:48px;background:#e9ecef;border-radius:4px;flex-shrink:0;display:flex;align-items:center;justify-content:center"><i class="bi bi-music-note text-muted"></i></div>`;
}

function showSuccess(release, musicId) {
  resultDiv.innerHTML = `
    <div class="card shadow-sm mb-3 border-start border-success border-3">
      <div class="card-body py-2 px-3">
        <div class="d-flex align-items-center gap-3">
          ${thumb(release)}
          <div class="flex-grow-1 min-w-0">
            <div class="d-flex align-items-center gap-2 mb-1">
              <i class="bi bi-check-circle-fill text-success"></i>
              <span class="fw-semibold text-success small">Added</span>
            </div>
            <div class="fw-bold text-truncate">${escHtml(release.title)}</div>
            ${release.artist ? `<div class="text-muted small text-truncate">${escHtml(release.artist)}</div>` : ''}
          </div>
          <a href="/music/${musicId}" class="btn btn-sm btn-outline-secondary flex-shrink-0">View</a>
        </div>
      </div>
    </div>`;
}

function showAlreadyOwned(release) {
  resultDiv.innerHTML = `
    <div class="card shadow-sm mb-3 border-start border-warning border-3">
      <div class="card-body py-2 px-3">
        <div class="d-flex align-items-center gap-3">
          ${thumb(release)}
          <div class="flex-grow-1 min-w-0">
            <div class="d-flex align-items-center gap-2 mb-1">
              <i class="bi bi-bookmark-check-fill text-warning"></i>
              <span class="fw-semibold text-warning small">Already in library</span>
            </div>
            <div class="fw-bold text-truncate">${escHtml(release.title)}</div>
            ${release.artist ? `<div class="text-muted small text-truncate">${escHtml(release.artist)}</div>` : ''}
          </div>
        </div>
      </div>
    </div>`;
}

function showError(message, barcode) {
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
    document.getElementById('manual-barcode').value   = barcode || '';
    document.getElementById('manual-location').value  = locationInput.value.trim();
    document.getElementById('manual-condition').value = conditionSelect.value;
    manualModal.show();
    setTimeout(() => document.getElementById('manual-title').focus(), 300);
  });
}

function showRateLimited() {
  resultDiv.innerHTML = `
    <div class="card shadow-sm mb-3 border-start border-warning border-3">
      <div class="card-body py-2 px-3">
        <div class="d-flex align-items-center gap-2 mb-1">
          <i class="bi bi-hourglass-split text-warning flex-shrink-0"></i>
          <span class="fw-semibold text-warning small">Rate limited — queued for retry</span>
        </div>
        <p class="text-muted small mb-0">Will retry in 45 s, then 90 s, then 180 s. Check the Audit log for results.</p>
      </div>
    </div>`;
}

// --- Manual entry ---

document.getElementById('manual-submit').addEventListener('click', async () => {
  const barcode = document.getElementById('manual-barcode').value.trim();
  const title   = document.getElementById('manual-title').value.trim();
  if (!barcode || !title) { alert('Barcode and title are required.'); return; }

  const btn = document.getElementById('manual-submit');
  btn.disabled = true;
  try {
    const res = await fetch('/api/music', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        barcode, title,
        artist:    document.getElementById('manual-artist').value.trim(),
        label:     document.getElementById('manual-label').value.trim(),
        year:      document.getElementById('manual-year').value.trim(),
        format:    document.getElementById('manual-format').value,
        condition: document.getElementById('manual-condition').value,
        location:  document.getElementById('manual-location').value.trim(),
        user_id:   selectedUserId,
      }),
    });
    const data = await res.json();
    if (data.success) {
      manualModal.hide();
      showSuccess({ title, artist: document.getElementById('manual-artist').value.trim(), cover_url: '' }, data.music_id);
    } else { alert(data.error || 'Failed to add release.'); }
  } catch { alert('Network error.'); }
  finally { btn.disabled = false; }
});

function escHtml(str) {
  return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
