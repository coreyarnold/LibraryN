'use strict';

const isbnInput     = document.getElementById('isbn-input');
const lookupBtn     = document.getElementById('lookup-btn');
const resultDiv     = document.getElementById('scan-result');
const locationInput = document.getElementById('session-location');
const conditionSelect = document.getElementById('session-condition');
const manualModal   = new bootstrap.Modal(document.getElementById('manualModal'));

// Restore session settings — survive tab navigation but reset on hard refresh
locationInput.value = sessionStorage.getItem('scanLocation') || '';
const savedCondition = sessionStorage.getItem('scanCondition');
if (savedCondition) conditionSelect.value = savedCondition;

locationInput.addEventListener('input', () => {
  sessionStorage.setItem('scanLocation', locationInput.value);
});
conditionSelect.addEventListener('change', () => {
  sessionStorage.setItem('scanCondition', conditionSelect.value);
});

// User selector (rendered only for admins)
let selectedUserId = currentUserId;
document.querySelectorAll('.user-select-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.user-select-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedUserId = parseInt(btn.dataset.userId);
  });
});

// Keep ISBN input focused so barcode scanner keystrokes land here
isbnInput.focus();
document.addEventListener('click', e => {
  if (!e.target.closest('button, a, input, select, textarea, .modal'))
    isbnInput.focus();
});

isbnInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); triggerScan(); }
});
lookupBtn.addEventListener('click', triggerScan);

function triggerScan() {
  const isbn = isbnInput.value.trim().replace(/[^0-9X]/gi, '');
  if (!isbn) return;
  isbnInput.value = '';
  scanAndAdd(isbn);
}

async function scanAndAdd(isbn) {
  showLoading();

  // Step 1: look up the ISBN
  let bookData;
  try {
    const res  = await fetch(`/api/lookup/${isbn}`);
    const data = await res.json();
    if (!res.ok) {
      showError(data.error || 'Book not found.', isbn);
      isbnInput.focus();
      return;
    }
    bookData = data;
  } catch {
    showError('Network error — check your connection.', isbn);
    isbnInput.focus();
    return;
  }

  // Step 2: if the selected user already owns it, skip the add call
  if ((bookData.owners || []).some(o => o.id === selectedUserId)) {
    showAlreadyOwned(bookData);
    isbnInput.focus();
    return;
  }

  // Step 3: auto-add with the current session settings
  try {
    const res  = await fetch('/api/books', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        isbn:           bookData.isbn,
        title:          bookData.title,
        author:         bookData.author || '',
        publisher:      bookData.publisher || '',
        published_year: bookData.published_year || '',
        description:    bookData.description || '',
        cover_url:      bookData.cover_url || '',
        page_count:     bookData.page_count || null,
        genre:          bookData.genre || '',
        language:       bookData.language || '',
        user_id:        selectedUserId,
        condition:      conditionSelect.value,
        location:       locationInput.value.trim(),
      }),
    });
    const data = await res.json();

    if (data.success) {
      showSuccess(bookData, data.book_id);
    } else if (res.status === 409) {
      showAlreadyOwned(bookData);
    } else {
      showError(data.error || 'Failed to add book.', isbn);
    }
  } catch {
    showError('Network error — check your connection.', isbn);
  }

  isbnInput.focus();
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

function bookThumb(book) {
  return book.cover_url
    ? `<img src="${escHtml(book.cover_url)}" alt=""
           style="width:48px;height:72px;object-fit:cover;border-radius:4px;flex-shrink:0">`
    : `<div style="width:48px;height:72px;background:#e9ecef;border-radius:4px;flex-shrink:0;
                   display:flex;align-items:center;justify-content:center">
         <i class="bi bi-book text-muted"></i>
       </div>`;
}

function showSuccess(book, bookId) {
  resultDiv.innerHTML = `
    <div class="card shadow-sm mb-3 border-start border-success border-3">
      <div class="card-body py-2 px-3">
        <div class="d-flex align-items-center gap-3">
          ${bookThumb(book)}
          <div class="flex-grow-1 min-w-0">
            <div class="d-flex align-items-center gap-2 mb-1">
              <i class="bi bi-check-circle-fill text-success"></i>
              <span class="fw-semibold text-success small">Added</span>
            </div>
            <div class="fw-bold text-truncate">${escHtml(book.title)}</div>
            ${book.author ? `<div class="text-muted small text-truncate">${escHtml(book.author)}</div>` : ''}
          </div>
          <a href="/books/${bookId}" class="btn btn-sm btn-outline-secondary flex-shrink-0">View</a>
        </div>
      </div>
    </div>`;
}

function showAlreadyOwned(book) {
  resultDiv.innerHTML = `
    <div class="card shadow-sm mb-3 border-start border-warning border-3">
      <div class="card-body py-2 px-3">
        <div class="d-flex align-items-center gap-3">
          ${bookThumb(book)}
          <div class="flex-grow-1 min-w-0">
            <div class="d-flex align-items-center gap-2 mb-1">
              <i class="bi bi-bookmark-check-fill text-warning"></i>
              <span class="fw-semibold text-warning small">Already in library</span>
            </div>
            <div class="fw-bold text-truncate">${escHtml(book.title)}</div>
            ${book.author ? `<div class="text-muted small text-truncate">${escHtml(book.author)}</div>` : ''}
          </div>
        </div>
      </div>
    </div>`;
}

function showError(message, isbn) {
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
    document.getElementById('manual-isbn').value    = isbn || '';
    document.getElementById('manual-location').value = locationInput.value.trim();
    document.getElementById('manual-condition').value = conditionSelect.value;
    manualModal.show();
    setTimeout(() => document.getElementById('manual-title').focus(), 300);
  });
}

// --- Manual entry ---

document.getElementById('manual-submit').addEventListener('click', async () => {
  const isbn  = document.getElementById('manual-isbn').value.trim();
  const title = document.getElementById('manual-title').value.trim();
  if (!isbn || !title) { alert('ISBN and title are required.'); return; }

  const btn = document.getElementById('manual-submit');
  btn.disabled = true;

  try {
    const res  = await fetch('/api/books', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        isbn,
        title,
        author:         document.getElementById('manual-author').value.trim(),
        publisher:      document.getElementById('manual-publisher').value.trim(),
        published_year: document.getElementById('manual-year').value.trim(),
        condition:      document.getElementById('manual-condition').value,
        location:       document.getElementById('manual-location').value.trim(),
        user_id:        selectedUserId,
      }),
    });
    const data = await res.json();

    if (data.success) {
      manualModal.hide();
      showSuccess({
        title,
        author:    document.getElementById('manual-author').value.trim(),
        cover_url: '',
      }, data.book_id);
    } else {
      alert(data.error || 'Failed to add book.');
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
