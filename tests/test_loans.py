from app.extensions import db, bcrypt
from app.models import User, Book, UserBook, Loan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_book(client, isbn='9780743273565', title='The Great Gatsby', **kw):
    return client.post('/api/books', json={'isbn': isbn, 'title': title, **kw})


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


def _login(app, username, password):
    c = app.test_client()
    c.post('/login', data={'username': username, 'password': password})
    return c


# ---------------------------------------------------------------------------
# Create loan
# ---------------------------------------------------------------------------

def test_create_loan(logged_in_client, app):
    r = _add_book(logged_in_client)
    ub_id = r.get_json()['user_book_id']

    r = logged_in_client.post('/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'})
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        loan = Loan.query.filter_by(user_book_id=ub_id).first()
        assert loan is not None
        assert loan.loaned_to == 'Sarah'
        assert loan.returned_at is None


def test_create_loan_requires_auth(client):
    r = client.post('/api/loans', json={'user_book_id': 1, 'loaned_to': 'Sarah'})
    assert r.status_code == 302


def test_create_loan_requires_name(logged_in_client):
    r = _add_book(logged_in_client, isbn='9780061965487', title='Other Book')
    ub_id = r.get_json()['user_book_id']

    r = logged_in_client.post('/api/loans', json={'user_book_id': ub_id, 'loaned_to': ''})
    assert r.status_code == 400


def test_create_loan_stores_notes(logged_in_client, app):
    r = _add_book(logged_in_client, isbn='9780062315007', title='Book With Notes')
    ub_id = r.get_json()['user_book_id']

    logged_in_client.post('/api/loans', json={
        'user_book_id': ub_id,
        'loaned_to': 'Mike',
        'notes': 'Return by December',
    })

    with app.app_context():
        loan = Loan.query.filter_by(user_book_id=ub_id).first()
        assert loan.notes == 'Return by December'


def test_create_loan_prevents_double_loan(logged_in_client):
    r = _add_book(logged_in_client, isbn='9780062315007', title='Some Book')
    ub_id = r.get_json()['user_book_id']

    logged_in_client.post('/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'})
    r = logged_in_client.post('/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Mike'})
    assert r.status_code == 409
    assert 'Sarah' in r.get_json()['error']


def test_create_loan_non_owner_forbidden(app):
    uid2 = _create_user(app)

    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    r = _add_book(admin_client)
    ub_id = r.get_json()['user_book_id']

    c2 = _login(app, 'user2', 'pass123')
    r = c2.post('/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'})
    assert r.status_code == 403


def test_create_loan_not_found(logged_in_client):
    r = logged_in_client.post('/api/loans', json={'user_book_id': 99999, 'loaned_to': 'Sarah'})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Return loan
# ---------------------------------------------------------------------------

def test_return_loan(logged_in_client, app):
    r = _add_book(logged_in_client)
    ub_id = r.get_json()['user_book_id']
    loan_id = logged_in_client.post(
        '/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']

    r = logged_in_client.patch(f'/api/loans/{loan_id}/return')
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        loan = db.session.get(Loan, loan_id)
        assert loan.returned_at is not None


def test_return_loan_already_returned(logged_in_client, app):
    r = _add_book(logged_in_client, isbn='9780062315007', title='Another Book')
    ub_id = r.get_json()['user_book_id']
    loan_id = logged_in_client.post(
        '/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']

    logged_in_client.patch(f'/api/loans/{loan_id}/return')
    r = logged_in_client.patch(f'/api/loans/{loan_id}/return')
    assert r.status_code == 409


def test_return_loan_not_found(logged_in_client):
    r = logged_in_client.patch('/api/loans/99999/return')
    assert r.status_code == 404


def test_return_loan_requires_auth(client):
    r = client.patch('/api/loans/1/return')
    assert r.status_code == 302


def test_return_loan_non_owner_forbidden(app):
    _create_user(app)

    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    r = _add_book(admin_client)
    ub_id = r.get_json()['user_book_id']
    loan_id = admin_client.post(
        '/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']

    c2 = _login(app, 'user2', 'pass123')
    r = c2.patch(f'/api/loans/{loan_id}/return')
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Loans page
# ---------------------------------------------------------------------------

def test_loans_page_requires_auth(client):
    r = client.get('/loans')
    assert r.status_code == 302
    assert 'login' in r.headers['Location']


def test_loans_page_empty_state(logged_in_client):
    r = logged_in_client.get('/loans')
    assert r.status_code == 200
    assert b'Nothing currently loaned out' in r.data


def test_loans_page_shows_active_loan(logged_in_client):
    r = _add_book(logged_in_client)
    ub_id = r.get_json()['user_book_id']
    logged_in_client.post('/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'})

    r = logged_in_client.get('/loans')
    assert r.status_code == 200
    assert b'Sarah' in r.data
    assert b'Great Gatsby' in r.data


def test_loans_page_hides_returned_loans(logged_in_client):
    r = _add_book(logged_in_client)
    ub_id = r.get_json()['user_book_id']
    loan_id = logged_in_client.post(
        '/api/loans', json={'user_book_id': ub_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']
    logged_in_client.patch(f'/api/loans/{loan_id}/return')

    r = logged_in_client.get('/loans')
    assert b'Sarah' not in r.data
