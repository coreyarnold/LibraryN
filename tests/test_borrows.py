"""
Tests for the borrow tracking feature.

Key regression covered: GET /loans was returning no borrowed items because
filter_by(returned_at=None) generates SQL `= NULL` instead of `IS NULL`.
These tests ensure borrowed items always appear on the correct user's loans page.
"""
from app.extensions import db, bcrypt
from app.models import User, Borrow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_user(app, username='user2', password='pass123'):
    with app.app_context():
        u = User(
            username=username,
            display_name=username.title(),
            password_hash=bcrypt.generate_password_hash(password).decode(),
            color='#00b894',
        )
        db.session.add(u)
        db.session.commit()
        return u.id


def _login(app, username, password='pass123'):
    c = app.test_client()
    c.post('/login', data={'username': username, 'password': password})
    return c


def _log_borrow(client, title='Dune', borrowed_from='Sarah', notes=''):
    return client.post('/api/borrows', json={
        'title': title,
        'borrowed_from': borrowed_from,
        'notes': notes,
    })


# ---------------------------------------------------------------------------
# POST /api/borrows
# ---------------------------------------------------------------------------

def test_create_borrow_succeeds(logged_in_client, app):
    r = _log_borrow(logged_in_client)
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        borrow = Borrow.query.first()
        assert borrow is not None
        assert borrow.title == 'Dune'
        assert borrow.borrowed_from == 'Sarah'
        assert borrow.returned_at is None


def test_create_borrow_stores_notes(logged_in_client, app):
    _log_borrow(logged_in_client, notes='Return by July')
    with app.app_context():
        assert Borrow.query.first().notes == 'Return by July'


def test_create_borrow_requires_title(logged_in_client):
    r = logged_in_client.post('/api/borrows', json={'borrowed_from': 'Sarah'})
    assert r.status_code == 400


def test_create_borrow_requires_borrowed_from(logged_in_client):
    r = logged_in_client.post('/api/borrows', json={'title': 'Dune'})
    assert r.status_code == 400


def test_create_borrow_requires_auth(client):
    r = client.post('/api/borrows', json={'title': 'Dune', 'borrowed_from': 'Sarah'})
    assert r.status_code == 302
    assert 'login' in r.headers['Location']


def test_create_borrow_is_scoped_to_current_user(logged_in_client, app):
    _log_borrow(logged_in_client)
    with app.app_context():
        admin_id = User.query.filter_by(username='admin').first().id
        borrow = Borrow.query.first()
        assert borrow.user_id == admin_id


# ---------------------------------------------------------------------------
# PATCH /api/borrows/<id>/return
# ---------------------------------------------------------------------------

def test_return_borrow(logged_in_client, app):
    borrow_id = _log_borrow(logged_in_client).get_json()['borrow_id']

    r = logged_in_client.patch(f'/api/borrows/{borrow_id}/return')
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        assert db.session.get(Borrow, borrow_id).returned_at is not None


def test_return_borrow_already_returned(logged_in_client):
    borrow_id = _log_borrow(logged_in_client).get_json()['borrow_id']
    logged_in_client.patch(f'/api/borrows/{borrow_id}/return')
    r = logged_in_client.patch(f'/api/borrows/{borrow_id}/return')
    assert r.status_code == 409


def test_return_borrow_not_found(logged_in_client):
    r = logged_in_client.patch('/api/borrows/99999/return')
    assert r.status_code == 404


def test_return_borrow_requires_auth(client):
    r = client.patch('/api/borrows/1/return')
    assert r.status_code == 302


def test_return_borrow_other_user_forbidden(app):
    _create_user(app)

    admin_client = _login(app, 'admin', 'changeme')
    borrow_id = _log_borrow(admin_client).get_json()['borrow_id']

    c2 = _login(app, 'user2')
    r = c2.patch(f'/api/borrows/{borrow_id}/return')
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /loans — the critical page display tests
# ---------------------------------------------------------------------------

def test_loans_page_shows_borrowed_item(logged_in_client):
    """Regression: borrowed items must appear on the loans page (IS NULL fix)."""
    _log_borrow(logged_in_client, title='Dune', borrowed_from='Sarah')

    r = logged_in_client.get('/loans')
    assert r.status_code == 200
    assert b'Dune' in r.data
    assert b'Sarah' in r.data


def test_loans_page_shows_multiple_borrowed_items(logged_in_client):
    _log_borrow(logged_in_client, title='Dune', borrowed_from='Sarah')
    _log_borrow(logged_in_client, title='1984', borrowed_from='Mike')

    r = logged_in_client.get('/loans')
    assert b'Dune' in r.data
    assert b'1984' in r.data
    assert b'Sarah' in r.data
    assert b'Mike' in r.data


def test_loans_page_shows_borrowed_from_family_member(app):
    """Logging a borrow from another system user should appear on loans page."""
    _create_user(app, username='sarah')

    c = _login(app, 'admin', 'changeme')
    _log_borrow(c, title='The Road', borrowed_from='Sarah')

    r = c.get('/loans')
    assert r.status_code == 200
    assert b'The Road' in r.data
    assert b'Sarah' in r.data


def test_returned_borrow_not_on_loans_page(logged_in_client):
    borrow_id = _log_borrow(logged_in_client, title='Dune').get_json()['borrow_id']
    logged_in_client.patch(f'/api/borrows/{borrow_id}/return')

    r = logged_in_client.get('/loans')
    assert b'Dune' not in r.data


def test_loans_page_only_shows_own_borrows(app):
    """A user should not see another user's borrowed items."""
    _create_user(app)

    admin_client = _login(app, 'admin', 'changeme')
    _log_borrow(admin_client, title='Admin Borrowed Book', borrowed_from='Friend')

    c2 = _login(app, 'user2')
    _log_borrow(c2, title='User2 Borrowed Book', borrowed_from='Other Friend')

    # Admin sees only their own borrow
    r_admin = admin_client.get('/loans')
    assert b'Admin Borrowed Book' in r_admin.data
    assert b'User2 Borrowed Book' not in r_admin.data

    # User2 sees only their own borrow
    r_user2 = c2.get('/loans')
    assert b'User2 Borrowed Book' in r_user2.data
    assert b'Admin Borrowed Book' not in r_user2.data


def test_loans_page_requires_auth(client):
    r = client.get('/loans')
    assert r.status_code == 302
    assert 'login' in r.headers['Location']


def test_loans_page_shows_borrowed_section_header(logged_in_client):
    r = logged_in_client.get('/loans')
    assert r.status_code == 200
    assert b'Borrowed' in r.data


# ---------------------------------------------------------------------------
# Inbound loans — items loaned TO the current user by family members
# ---------------------------------------------------------------------------

def test_inbound_book_loan_appears_on_borrowers_loans_page(app):
    """
    When User A loans a book to User B via 'Loan Out', User B must see
    it in their Borrowed section on the loans page.
    This was the root cause: Loan records were never surfaced for the borrower.
    """
    _create_user(app, username='sarah')

    # Admin adds a book and loans it to Sarah
    admin_client = _login(app, 'admin', 'changeme')
    r = admin_client.post('/api/books', json={'isbn': '9780743273565', 'title': 'The Great Gatsby'})
    ub_id = r.get_json()['user_book_id']
    admin_client.post('/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'})

    # Sarah logs in and visits loans page
    sarah_client = _login(app, 'sarah')
    r = sarah_client.get('/loans')
    assert r.status_code == 200
    assert b'The Great Gatsby' in r.data


def test_inbound_dvd_loan_appears_on_borrowers_loans_page(app):
    """Same as above but for DVDs."""
    _create_user(app, username='sarah')

    admin_client = _login(app, 'admin', 'changeme')
    r = admin_client.post('/api/dvds', json={'upc': '025192310638', 'title': 'Fast Five'})
    ud_id = r.get_json()['user_dvd_id']
    admin_client.post('/api/dvd-loans', json={'user_dvd_id': ud_id, 'loaned_to': 'Sarah'})

    sarah_client = _login(app, 'sarah')
    r = sarah_client.get('/loans')
    assert r.status_code == 200
    assert b'Fast Five' in r.data


def test_inbound_loan_not_visible_to_unrelated_user(app):
    """A loan to Sarah must not appear on Mike's loans page."""
    _create_user(app, username='sarah')
    _create_user(app, username='mike', password='pass123')

    admin_client = _login(app, 'admin', 'changeme')
    r = admin_client.post('/api/books', json={'isbn': '9780743273565', 'title': 'The Great Gatsby'})
    ub_id = r.get_json()['user_book_id']
    admin_client.post('/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'})

    mike_client = _login(app, 'mike')
    r = mike_client.get('/loans')
    assert b'The Great Gatsby' not in r.data


def test_returned_inbound_loan_not_on_borrowers_page(app):
    """Once returned, the inbound loan disappears from the borrower's page."""
    _create_user(app, username='sarah')

    admin_client = _login(app, 'admin', 'changeme')
    r = admin_client.post('/api/books', json={'isbn': '9780743273565', 'title': 'The Great Gatsby'})
    ub_id = r.get_json()['user_book_id']
    loan_id = admin_client.post(
        '/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']

    # Sarah marks it returned from her own account
    sarah_client = _login(app, 'sarah')
    r = sarah_client.patch(f'/api/loans/{loan_id}/return')
    assert r.status_code == 200

    r = sarah_client.get('/loans')
    assert b'The Great Gatsby' not in r.data


def test_borrower_can_mark_loan_returned(app):
    """The named borrower (not just the lender) can mark a loan as returned."""
    _create_user(app, username='sarah')

    admin_client = _login(app, 'admin', 'changeme')
    r = admin_client.post('/api/books', json={'isbn': '9780743273565', 'title': 'The Great Gatsby'})
    ub_id = r.get_json()['user_book_id']
    loan_id = admin_client.post(
        '/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']

    sarah_client = _login(app, 'sarah')
    r = sarah_client.patch(f'/api/loans/{loan_id}/return')
    assert r.status_code == 200
    assert r.get_json()['success'] is True


def test_borrower_return_is_idempotent_safe(app):
    """
    Regression: the Returned button on inbound loans was using class 'borrow-row'
    while the JS handler searched for '.loan-row', returning null and throwing a
    TypeError in the success branch — caught as 'Network error.' — while the server
    had already recorded the return (200).  The user clicking again then got 409.

    Verify the server-side behaviour is correct: the first return succeeds (200)
    and the second is rejected (409), not the other way around.
    """
    _create_user(app, username='sarah')

    admin_client = _login(app, 'admin', 'changeme')
    r = admin_client.post('/api/books', json={'isbn': '9780743273565', 'title': 'The Great Gatsby'})
    ub_id = r.get_json()['user_book_id']
    loan_id = admin_client.post(
        '/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']

    sarah_client = _login(app, 'sarah')

    # First return must succeed
    r1 = sarah_client.patch(f'/api/loans/{loan_id}/return')
    assert r1.status_code == 200, f'First return should be 200, got {r1.status_code}'

    # Second return must be 409, not silently succeed or 403
    r2 = sarah_client.patch(f'/api/loans/{loan_id}/return')
    assert r2.status_code == 409


def test_unrelated_user_cannot_mark_loan_returned(app):
    """A user who is neither lender nor borrower cannot mark a loan returned."""
    _create_user(app, username='sarah')
    _create_user(app, username='mike', password='pass123')

    admin_client = _login(app, 'admin', 'changeme')
    r = admin_client.post('/api/books', json={'isbn': '9780743273565', 'title': 'The Great Gatsby'})
    ub_id = r.get_json()['user_book_id']
    loan_id = admin_client.post(
        '/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']

    mike_client = _login(app, 'mike')
    r = mike_client.patch(f'/api/loans/{loan_id}/return')
    assert r.status_code == 403
