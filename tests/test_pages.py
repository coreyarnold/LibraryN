"""
Render tests for HTML routes. These verify pages return 200, require auth
where expected, and contain key content — without duplicating the API-level
assertions in other test files.
"""
from app.extensions import db, bcrypt
from app.models import User, Book, UserBook


# ---------------------------------------------------------------------------
# Book pages
# ---------------------------------------------------------------------------

def test_dashboard_renders(logged_in_client):
    r = logged_in_client.get('/dashboard')
    assert r.status_code == 200
    assert b'Dashboard' in r.data or b'library' in r.data.lower()


def test_dashboard_requires_auth(client):
    r = client.get('/dashboard')
    assert r.status_code == 302
    assert 'login' in r.headers['Location']


def test_books_index_renders(logged_in_client):
    r = logged_in_client.get('/books')
    assert r.status_code == 200
    assert b'All Books' in r.data


def test_books_index_requires_auth(client):
    r = client.get('/books')
    assert r.status_code == 302


def test_books_index_search(logged_in_client):
    logged_in_client.post('/api/books', json={'isbn': '9780743273565', 'title': 'The Great Gatsby', 'author': 'Fitzgerald'})
    r = logged_in_client.get('/books?q=Gatsby')
    assert r.status_code == 200
    assert b'Great Gatsby' in r.data


def test_books_index_filter_by_user(logged_in_client, app):
    with app.app_context():
        user_id = User.query.filter_by(username='admin').first().id
    r = logged_in_client.get(f'/books?user_id={user_id}')
    assert r.status_code == 200


def test_books_detail_renders(logged_in_client, app):
    logged_in_client.post('/api/books', json={'isbn': '9780743273565', 'title': 'The Great Gatsby'})
    with app.app_context():
        book_id = Book.query.filter_by(isbn='9780743273565').first().id

    r = logged_in_client.get(f'/books/{book_id}')
    assert r.status_code == 200
    assert b'Great Gatsby' in r.data


def test_books_detail_requires_auth(logged_in_client, app):
    logged_in_client.post('/api/books', json={'isbn': '9780743273565', 'title': 'Gatsby'})
    with app.app_context():
        book_id = Book.query.filter_by(isbn='9780743273565').first().id

    anon = app.test_client()  # fresh unauthenticated client
    r = anon.get(f'/books/{book_id}')
    assert r.status_code == 302


def test_books_detail_404_for_missing(logged_in_client):
    r = logged_in_client.get('/books/99999')
    assert r.status_code == 404


def test_import_page_renders(logged_in_client):
    r = logged_in_client.get('/import')
    assert r.status_code == 200


def test_import_page_requires_auth(client):
    r = client.get('/import')
    assert r.status_code == 302


# ---------------------------------------------------------------------------
# User management pages (admin only)
# ---------------------------------------------------------------------------

def test_users_manage_renders(logged_in_client):
    r = logged_in_client.get('/users/')
    assert r.status_code == 200


def test_users_manage_requires_admin(app):
    with app.app_context():
        u = User(
            username='regular',
            display_name='Regular User',
            password_hash=bcrypt.generate_password_hash('pass').decode(),
            color='#aaa',
        )
        db.session.add(u)
        db.session.commit()

    c = app.test_client()
    c.post('/login', data={'username': 'regular', 'password': 'pass'})
    r = c.get('/users/')
    assert r.status_code == 403


def test_users_create(logged_in_client, app):
    r = logged_in_client.post(
        '/users/create',
        data={'username': 'newuser', 'display_name': 'New User', 'password': 'pass123', 'color': '#6c5ce7'},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        assert User.query.filter_by(username='newuser').first() is not None


def test_users_create_rejects_duplicate_username(logged_in_client):
    logged_in_client.post(
        '/users/create',
        data={'username': 'dupeuser', 'display_name': 'A', 'password': 'pass', 'color': '#000'},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    r = logged_in_client.post(
        '/users/create',
        data={'username': 'dupeuser', 'display_name': 'B', 'password': 'pass', 'color': '#000'},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert r.status_code == 400
    assert 'error' in r.get_json()


def test_users_create_requires_all_fields(logged_in_client):
    r = logged_in_client.post(
        '/users/create',
        data={'username': '', 'display_name': '', 'password': ''},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert r.status_code == 400


def test_users_edit(logged_in_client, app):
    with app.app_context():
        u = User(username='toedit', display_name='Old Name',
                 password_hash=bcrypt.generate_password_hash('pass').decode(), color='#aaa')
        db.session.add(u)
        db.session.commit()
        uid = u.id

    r = logged_in_client.post(
        f'/users/{uid}/edit',
        data={'display_name': 'New Name', 'color': '#00b894'},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        assert db.session.get(User, uid).display_name == 'New Name'


def test_users_edit_requires_display_name(logged_in_client, app):
    with app.app_context():
        u = User(username='nodisplay', display_name='Has Name',
                 password_hash=bcrypt.generate_password_hash('pass').decode(), color='#aaa')
        db.session.add(u)
        db.session.commit()
        uid = u.id

    r = logged_in_client.post(
        f'/users/{uid}/edit',
        data={'display_name': '', 'color': '#aaa'},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert r.status_code == 400


def test_users_delete(logged_in_client, app):
    with app.app_context():
        u = User(username='todelete', display_name='Gone',
                 password_hash=bcrypt.generate_password_hash('pass').decode(), color='#aaa')
        db.session.add(u)
        db.session.commit()
        uid = u.id

    r = logged_in_client.post(f'/users/{uid}/delete')
    assert r.status_code == 302

    with app.app_context():
        assert db.session.get(User, uid) is None


def test_users_cannot_delete_self(logged_in_client, app):
    with app.app_context():
        admin_id = User.query.filter_by(username='admin').first().id

    r = logged_in_client.post(f'/users/{admin_id}/delete', follow_redirects=True)
    assert r.status_code == 200
    assert b'cannot delete' in r.data.lower()

    with app.app_context():
        assert db.session.get(User, admin_id) is not None


# ---------------------------------------------------------------------------
# Profile page
# ---------------------------------------------------------------------------

def test_profile_renders(logged_in_client):
    r = logged_in_client.get('/users/profile')
    assert r.status_code == 200


def test_profile_requires_auth(client):
    r = client.get('/users/profile')
    assert r.status_code == 302


def test_profile_update_display_name(logged_in_client, app):
    r = logged_in_client.post('/users/profile', data={
        'display_name': 'Admin Renamed',
        'email': '',
        'goodreads_user_id': '',
        'current_password': '',
        'new_password': '',
    }, follow_redirects=True)
    assert r.status_code == 200

    with app.app_context():
        assert User.query.filter_by(username='admin').first().display_name == 'Admin Renamed'


def test_profile_wrong_current_password_rejected(logged_in_client):
    r = logged_in_client.post('/users/profile', data={
        'display_name': 'Admin',
        'email': '',
        'goodreads_user_id': '',
        'current_password': 'wrongpassword',
        'new_password': 'newpass123',
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b'incorrect' in r.data.lower()
