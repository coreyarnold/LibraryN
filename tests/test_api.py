from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _google_books_mock(title='Test Book', authors=('Test Author',)):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        'totalItems': 1,
        'items': [{'volumeInfo': {
            'title': title,
            'authors': list(authors),
            'imageLinks': {'thumbnail': 'https://example.com/cover.jpg'},
        }}],
    }
    return resp


def _add_book(client, isbn='9780743273565', title='The Great Gatsby', **extra):
    payload = {'isbn': isbn, 'title': title, **extra}
    return client.post('/api/books', json=payload)


# ---------------------------------------------------------------------------
# ISBN lookup
# ---------------------------------------------------------------------------

def test_lookup_requires_auth(client):
    r = client.get('/api/lookup/9780743273565')
    assert r.status_code == 302
    assert 'login' in r.headers['Location']


def test_lookup_invalid_isbn_letters(logged_in_client):
    r = logged_in_client.get('/api/lookup/notanisbn')
    assert r.status_code == 400
    assert 'error' in r.get_json()


def test_lookup_invalid_isbn_wrong_length(logged_in_client):
    r = logged_in_client.get('/api/lookup/12345')
    assert r.status_code == 400


def test_lookup_returns_local_book(logged_in_client, app):
    from app.extensions import db
    from app.models import Book, User, UserBook
    with app.app_context():
        user = User.query.first()
        book = Book(isbn='9780743273565', title='The Great Gatsby', author='F. Scott Fitzgerald')
        db.session.add(book)
        db.session.flush()
        db.session.add(UserBook(user_id=user.id, book_id=book.id))
        db.session.commit()

    r = logged_in_client.get('/api/lookup/9780743273565')
    data = r.get_json()
    assert r.status_code == 200
    assert data['in_library'] is True
    assert data['title'] == 'The Great Gatsby'
    assert len(data['owners']) == 1


def test_lookup_fetches_external_when_not_in_db(logged_in_client):
    with patch('app.routes.api.requests.get', return_value=_google_books_mock()):
        r = logged_in_client.get('/api/lookup/9780743273565')
    assert r.status_code == 200
    data = r.get_json()
    assert data['title'] == 'Test Book'
    assert data['in_library'] is False


def test_lookup_returns_404_when_external_fails(logged_in_client):
    not_found = MagicMock()
    not_found.raise_for_status.return_value = None
    not_found.json.return_value = {'totalItems': 0}

    open_lib_404 = MagicMock()
    open_lib_404.status_code = 404

    with patch('app.routes.api.requests.get', side_effect=[not_found, open_lib_404]):
        r = logged_in_client.get('/api/lookup/9780743273565')
    assert r.status_code == 404


def test_lookup_google_books_429_returns_429(logged_in_client):
    """Google Books rate limit propagates as 429 to the client."""
    import requests as req
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.raise_for_status.side_effect = req.HTTPError(response=rate_limited)

    with patch('app.routes.api.requests.get', return_value=rate_limited):
        r = logged_in_client.get('/api/lookup/9780743273565')
    assert r.status_code == 429
    assert 'rate limit' in r.get_json()['error'].lower()


def test_lookup_open_library_429_returns_429(logged_in_client):
    """Open Library rate limit (after Google Books miss) propagates as 429."""
    no_results = MagicMock()
    no_results.raise_for_status.return_value = None
    no_results.json.return_value = {'totalItems': 0}

    rate_limited = MagicMock()
    rate_limited.status_code = 429

    with patch('app.routes.api.requests.get', side_effect=[no_results, rate_limited]):
        r = logged_in_client.get('/api/lookup/9780743273565')
    assert r.status_code == 429


def test_lookup_google_books_non429_http_error(logged_in_client):
    """Non-429 HTTP errors from Google Books fall through to Open Library."""
    import requests as req
    server_error = MagicMock()
    server_error.status_code = 503
    server_error.raise_for_status.side_effect = req.HTTPError(response=server_error)

    ol_404 = MagicMock()
    ol_404.status_code = 404

    with patch('app.routes.api.requests.get', side_effect=[server_error, ol_404]):
        r = logged_in_client.get('/api/lookup/9780743273565')
    assert r.status_code == 404  # both sources failed


def test_lookup_google_books_timeout_falls_back(logged_in_client):
    """Timeout on Google Books falls back to Open Library."""
    import requests as req
    ol_404 = MagicMock()
    ol_404.status_code = 404

    with patch('app.routes.api.requests.get', side_effect=[req.Timeout, ol_404]):
        r = logged_in_client.get('/api/lookup/9780743273565')
    assert r.status_code == 404


def test_lookup_open_library_success(logged_in_client):
    """Open Library fallback returns book data when Google Books finds nothing."""
    no_results = MagicMock()
    no_results.raise_for_status.return_value = None
    no_results.json.return_value = {'totalItems': 0}

    ol_book = MagicMock()
    ol_book.status_code = 200
    ol_book.json.return_value = {
        'title': 'Open Library Book',
        'publishers': ['OL Press'],
        'publish_date': '2001',
        'number_of_pages': 200,
        'authors': [],
    }

    with patch('app.routes.api.requests.get', side_effect=[no_results, ol_book]):
        r = logged_in_client.get('/api/lookup/9780743273565')
    assert r.status_code == 200
    assert r.get_json()['title'] == 'Open Library Book'


def test_lookup_open_library_resolves_author(logged_in_client):
    """Open Library author key is followed to resolve the author name."""
    no_results = MagicMock()
    no_results.raise_for_status.return_value = None
    no_results.json.return_value = {'totalItems': 0}

    ol_book = MagicMock()
    ol_book.status_code = 200
    ol_book.json.return_value = {
        'title': 'A Book With Author',
        'publishers': [], 'publish_date': '', 'number_of_pages': None,
        'authors': [{'key': '/authors/OL1A'}],
    }

    author_resp = MagicMock()
    author_resp.status_code = 200
    author_resp.json.return_value = {'name': 'Jane Smith'}

    with patch('app.routes.api.requests.get',
               side_effect=[no_results, ol_book, author_resp]):
        r = logged_in_client.get('/api/lookup/9780743273565')
    assert r.status_code == 200
    assert r.get_json()['author'] == 'Jane Smith'


def test_lookup_open_library_author_fetch_non200_skipped(logged_in_client):
    """A non-200 author fetch is silently skipped rather than crashing."""
    no_results = MagicMock()
    no_results.raise_for_status.return_value = None
    no_results.json.return_value = {'totalItems': 0}

    ol_book = MagicMock()
    ol_book.status_code = 200
    ol_book.json.return_value = {
        'title': 'A Book', 'publishers': [], 'publish_date': '',
        'number_of_pages': None, 'authors': [{'key': '/authors/OL1A'}],
    }

    author_resp = MagicMock()
    author_resp.status_code = 404

    with patch('app.routes.api.requests.get',
               side_effect=[no_results, ol_book, author_resp]):
        r = logged_in_client.get('/api/lookup/9780743273565')
    assert r.status_code == 200
    assert r.get_json()['author'] == ''  # gracefully empty


def test_lookup_open_library_timeout_returns_404(logged_in_client):
    """Open Library timeout returns 404 cleanly."""
    import requests as req
    no_results = MagicMock()
    no_results.raise_for_status.return_value = None
    no_results.json.return_value = {'totalItems': 0}

    with patch('app.routes.api.requests.get', side_effect=[no_results, req.Timeout]):
        r = logged_in_client.get('/api/lookup/9780743273565')
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Add book
# ---------------------------------------------------------------------------

def test_add_book_creates_records(logged_in_client, app):
    r = _add_book(logged_in_client, author='F. Scott Fitzgerald')
    assert r.status_code == 200
    data = r.get_json()
    assert data['success'] is True

    from app.models import Book, UserBook
    with app.app_context():
        book = Book.query.filter_by(isbn='9780743273565').first()
        assert book is not None
        assert UserBook.query.filter_by(book_id=book.id).count() == 1


def test_add_book_requires_isbn_and_title(logged_in_client):
    r = logged_in_client.post('/api/books', json={'isbn': '9780743273565'})
    assert r.status_code == 400

    r = logged_in_client.post('/api/books', json={'title': 'No ISBN'})
    assert r.status_code == 400


def test_add_book_duplicate_returns_409(logged_in_client):
    _add_book(logged_in_client)
    r = _add_book(logged_in_client)
    assert r.status_code == 409


def test_add_book_reuses_existing_book_record(logged_in_client, app):
    """Two different users owning the same ISBN share one Book row."""
    from app.extensions import db, bcrypt
    from app.models import User, UserBook
    with app.app_context():
        user2 = User(
            username='user2',
            display_name='User Two',
            password_hash=bcrypt.generate_password_hash('pass123').decode(),
            color='#aabbcc',
        )
        db.session.add(user2)
        db.session.commit()
        user2_id = user2.id

    _add_book(logged_in_client)

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = _add_book(c2, user_id=user2_id)
    assert r.status_code == 200

    from app.models import Book
    with app.app_context():
        assert Book.query.filter_by(isbn='9780743273565').count() == 1
        assert UserBook.query.count() == 2


def test_non_admin_cannot_add_book_for_other_user(app):
    from app.extensions import db, bcrypt
    from app.models import User
    with app.app_context():
        user2 = User(
            username='user2',
            display_name='User Two',
            password_hash=bcrypt.generate_password_hash('pass123').decode(),
            color='#aabbcc',
        )
        db.session.add(user2)
        db.session.commit()
        admin_id = User.query.filter_by(username='admin').first().id

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.post('/api/books', json={
        'isbn': '9780743273565',
        'title': 'Test',
        'user_id': admin_id,
    })
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Remove book
# ---------------------------------------------------------------------------

def test_remove_book_deletes_user_book(logged_in_client, app):
    r = _add_book(logged_in_client)
    user_book_id = r.get_json()['user_book_id']

    r = logged_in_client.delete(f'/api/books/{user_book_id}')
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    from app.extensions import db
    from app.models import UserBook
    with app.app_context():
        assert db.session.get(UserBook, user_book_id) is None


def test_remove_last_owner_cascades_to_book(logged_in_client, app):
    r = _add_book(logged_in_client)
    data = r.get_json()
    user_book_id = data['user_book_id']
    book_id = data['book_id']

    logged_in_client.delete(f'/api/books/{user_book_id}')

    from app.extensions import db
    from app.models import Book
    with app.app_context():
        assert db.session.get(Book, book_id) is None


def test_remove_book_not_found_returns_404(logged_in_client):
    r = logged_in_client.delete('/api/books/99999')
    assert r.status_code == 404


def test_remove_book_other_user_forbidden(app):
    from app.extensions import db, bcrypt
    from app.models import User
    with app.app_context():
        user2 = User(
            username='user2',
            display_name='User Two',
            password_hash=bcrypt.generate_password_hash('pass123').decode(),
            color='#aabbcc',
        )
        db.session.add(user2)
        db.session.commit()

    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    r = _add_book(admin_client)
    user_book_id = r.get_json()['user_book_id']

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.delete(f'/api/books/{user_book_id}')
    assert r.status_code == 403
