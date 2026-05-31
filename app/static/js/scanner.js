'use strict';

const isbnInput   = document.getElementById('isbn-input');
const lookupBtn   = document.getElementById('lookup-btn');
const resultDiv   = document.getElementById('scan-result');
const addForDiv   = document.getElementById('add-for-user');
const manualModal = new bootstrap.Modal(document.getElementById('manualModal'));

let selectedUserId = currentUserId;
let pendingBookData = null;

// Keep the input focused so scanner keystrokes land here
isbnInput.focus();
document.addEventListener('click', e => {
  if (!e.target.closest('button, a, input, select, textarea, .modal'))
    isbnInput.focus();
});

// Trigger lookup on Enter (scanner sends Enter after the barcode)
isbnInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); triggerLookup(); }
});
lookupBtn.addEventListener('click', triggerLookup);

// User selector
document.querySelectorAll('.user-select-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.user-select-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedUserId = parseInt(btn.dataset.userId);
    updateConfirmButton();
  });
});

function updateConfirmButton() {
  const btn = document.getElementById('confirm-add');
  if (!btn || !pendingBookData) return;
  const alreadyOwns = (pendingBookData.owners || []).some(o => o.id === selectedUserId);
  btn.disabled = alreadyOwns;
  btn.title = alreadyOwns ? 'This user already owns this book' : '';
  btn.innerHTML = alreadyOwns
    ? 'Already Owned'
    : '<i class="bi bi-plus-circle me-1"></i>Add to Library';
}

function triggerLookup() {
  const isbn = isbnInput.value.trim().replace(/[^0-9X]/gi, '');
  if (!isbn) return;
  isbnInput.value = '';
  lookupISBN(isbn);
}

async function lookupISBN(isbn) {
  showLoading();
  try {
    const res  = await fetch(`/api/lookup/${isbn}`);
    const data = await res.json();
    if (!res.ok) {
      showError(data.error || 'Book not found.', isbn);
    } else {
      pendingBookData = data;
      showResult(data);
    }
  } catch {
    showError('Network error — check your connection.', isbn);
  }
  isbnInput.focus();
}

function showLoading() {
  resultDiv.innerHTML = `
    <div class="card scan-result-card shadow-sm mb-3 p-3">
      <div class="d-flex align-items-center gap-3 text-muted">
        <div class="spinner-border spinner-border-sm"></div>
        <span>Looking up book…</span>
      </div>
    </div>`;
  addForDiv.classList.add('d-none');
}

function showResult(book) {
  const ownersHtml = (book.owners || []).map(o =>
    `<span class="badge rounded-pill text-white" style="background:${o.color}">${o.name}</span>`
  ).join(' ');

  const alreadyOwns = (book.owners || []).some(o => o.id === selectedUserId);

  resultDiv.innerHTML = `
    <div class="card scan-result-card shadow-sm mb-3">
      <div class="card-body">
        <div class="d-flex gap-3">
          ${book.cover_url
            ? `<img src="${book.cover_url}" alt="" style="width:70px;height:105px;object-fit:cover;border-radius:6px;flex-shrink:0">`
            : `<div style="width:70px;height:105px;background:#e9ecef;border-radius:6px;flex-shrink:0;display:flex;align-items:center;justify-content:center"><i class="bi bi-book text-muted fs-4"></i></div>`}
          <div class="flex-grow-1">
            <h5 class="fw-bold mb-1">${escHtml(book.title)}</h5>
            ${book.author ? `<p class="text-muted mb-1">${escHtml(book.author)}</p>` : ''}
            <div class="text-muted small mb-2">
              ${book.publisher ? escHtml(book.publisher) + ' · ' : ''}
              ${book.published_year || ''} ${book.page_count ? '· ' + book.page_count + ' pages' : ''}
            </div>
            ${book.in_library
              ? `<div class="mb-2">Already in library: ${ownersHtml}</div>`
              : '<span class="badge bg-success mb-2">New to Library</span>'}
          </div>
        </div>

        <hr class="my-3" />

        <div class="row g-2 mb-3">
          <div class="col-sm-5">
            <label class="form-label small fw-semibold">Condition</label>
            <select class="form-select form-select-sm" id="result-condition">
              <option value="new" selected>New</option>
              <option value="like_new">Like New</option>
              <option value="very_good">Very Good</option>
              <option value="good">Good</option>
              <option value="acceptable">Acceptable</option>
              <option value="poor">Poor</option>
            </select>
          </div>
          <div class="col-sm-7">
            <label class="form-label small fw-semibold">Location <span class="text-muted fw-normal">(optional)</span></label>
            <input type="text" class="form-control form-control-sm" id="result-location"
                   placeholder="e.g. Living Room Shelf A" />
          </div>
        </div>

        <div class="d-flex gap-2">
          <button class="btn btn-primary" id="confirm-add" ${alreadyOwns ? 'disabled title="This user already owns this book"' : ''}>
            <i class="bi bi-plus-circle me-1"></i>${alreadyOwns ? 'Already Owned' : 'Add to Library'}
          </button>
          <button class="btn btn-outline-secondary" onclick="resultDiv.innerHTML='';addForDiv.classList.add(\'d-none\')">
            Dismiss
          </button>
        </div>
      </div>
    </div>`;

  addForDiv.classList.remove('d-none');

  document.getElementById('confirm-add').addEventListener('click', () => addBook(book));
}

function showError(message, isbn) {
  resultDiv.innerHTML = `
    <div class="card scan-result-card shadow-sm mb-3 border-start-danger" style="border-left-color:#dc3545!important">
      <div class="card-body">
        <div class="d-flex align-items-start gap-2 text-danger mb-3">
          <i class="bi bi-exclamation-circle-fill mt-1"></i>
          <span>${escHtml(message)}</span>
        </div>
        <button class="btn btn-sm btn-outline-secondary" id="open-manual">
          <i class="bi bi-pencil me-1"></i>Add Manually
        </button>
      </div>
    </div>`;

  document.getElementById('open-manual').addEventListener('click', () => {
    document.getElementById('manual-isbn').value = isbn || '';
    manualModal.show();
    setTimeout(() => document.getElementById('manual-title').focus(), 300);
  });

  addForDiv.classList.add('d-none');
}

async function addBook(bookData) {
  const btn = document.getElementById('confirm-add');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Adding…';

  const payload = {
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
    condition:      document.getElementById('result-condition').value,
    location:       document.getElementById('result-location').value,
  };

  try {
    const res  = await fetch('/api/books', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (data.success) {
      showSuccess(data.message, data.book_id);
    } else {
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-plus-circle me-1"></i>Add to Library';
      alert(data.error || 'Failed to add book.');
    }
  } catch {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-plus-circle me-1"></i>Add to Library';
    alert('Network error.');
  }
}

function showSuccess(message, bookId) {
  resultDiv.innerHTML = `
    <div class="alert alert-success d-flex align-items-center gap-2 mb-3 scan-result-card">
      <i class="bi bi-check-circle-fill fs-5"></i>
      <div class="flex-grow-1">${escHtml(message)}</div>
      <a href="/books/${bookId}" class="btn btn-sm btn-outline-success">View</a>
    </div>`;
  addForDiv.classList.add('d-none');
}

// Manual entry submit
document.getElementById('manual-submit').addEventListener('click', async () => {
  const isbn  = document.getElementById('manual-isbn').value.trim();
  const title = document.getElementById('manual-title').value.trim();
  if (!isbn || !title) { alert('ISBN and title are required.'); return; }

  const payload = {
    isbn,
    title,
    author:         document.getElementById('manual-author').value.trim(),
    publisher:      document.getElementById('manual-publisher').value.trim(),
    published_year: document.getElementById('manual-year').value.trim(),
    condition:      document.getElementById('manual-condition').value,
    location:       document.getElementById('manual-location').value.trim(),
    user_id:        selectedUserId,
  };

  const btn = document.getElementById('manual-submit');
  btn.disabled = true;

  try {
    const res  = await fetch('/api/books', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (data.success) {
      manualModal.hide();
      showSuccess(data.message, data.book_id);
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
