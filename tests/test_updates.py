"""Tests for PATCH /api/books/<id> and PATCH /api/user-books/<id>."""
from app.extensions import db, bcrypt
from app.models import User, Book, UserBook


def _add_book(client, isbn='9780743273565', title='The Great Gatsby'):
    return client.post('/api/books', json={'isbn': isbn, 'title': title})


# ---------------------------------------------------------------------------
# PATCH /api/books/<id>  — edit shared book metadata
# ---------------------------------------------------------------------------

def test_update_book_metadata(logged_in_client, app):
    r = _add_book(logged_in_client)
    book_id = r.get_json()['book_id']

    r = logged_in_client.patch(f'/api/books/{book_id}', json={
        'title': 'Updated Title',
        'author': 'New Author',
        'publisher': 'New Publisher',
        'published_year': '1999',
        'description': 'New description',
        'cover_url': 'https://example.com/cover.jpg',
        'genre': 'Fiction',
        'language': 'en',
        'page_count': 350,
    })
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        book = db.session.get(Book, book_id)
        assert book.title == 'Updated Title'
        assert book.author == 'New Author'
        assert book.page_count == 350


def test_update_book_requires_title(logged_in_client):
    r = _add_book(logged_in_client)
    book_id = r.get_json()['book_id']

    r = logged_in_client.patch(f'/api/books/{book_id}', json={'title': ''})
    assert r.status_code == 400


def test_update_book_not_found(logged_in_client):
    r = logged_in_client.patch('/api/books/99999', json={'title': 'X'})
    assert r.status_code == 404


def test_update_book_requires_auth(client):
    r = client.patch('/api/books/1', json={'title': 'X'})
    assert r.status_code == 302


def test_update_book_clears_page_count_when_empty(logged_in_client, app):
    r = _add_book(logged_in_client, isbn='9780061965487', title='Other Book')
    book_id = r.get_json()['book_id']

    logged_in_client.patch(f'/api/books/{book_id}', json={'title': 'Other Book', 'page_count': 200})
    logged_in_client.patch(f'/api/books/{book_id}', json={'title': 'Other Book', 'page_count': ''})

    with app.app_context():
        assert db.session.get(Book, book_id).page_count is None


# ---------------------------------------------------------------------------
# PATCH /api/user-books/<id>  — edit per-copy details
# ---------------------------------------------------------------------------

def test_update_user_book_fields(logged_in_client, app):
    r = _add_book(logged_in_client)
    ub_id = r.get_json()['user_book_id']

    r = logged_in_client.patch(f'/api/user-books/{ub_id}', json={
        'condition': 'like_new',
        'location': 'Bedroom Shelf A',
        'notes': 'Signed copy',
    })
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        ub = db.session.get(UserBook, ub_id)
        assert ub.condition == 'like_new'
        assert ub.location == 'Bedroom Shelf A'
        assert ub.notes == 'Signed copy'


def test_update_user_book_ignores_invalid_condition(logged_in_client, app):
    r = _add_book(logged_in_client, isbn='9780062315007', title='Another Book')
    ub_id = r.get_json()['user_book_id']

    logged_in_client.patch(f'/api/user-books/{ub_id}', json={
        'condition': 'not_a_real_condition',
        'location': '',
        'notes': '',
    })

    with app.app_context():
        # Condition should remain the default 'good' since invalid value is ignored
        assert db.session.get(UserBook, ub_id).condition == 'good'


def test_update_user_book_not_found(logged_in_client):
    r = logged_in_client.patch('/api/user-books/99999', json={'condition': 'good'})
    assert r.status_code == 404


def test_update_user_book_requires_auth(client):
    r = client.patch('/api/user-books/1', json={'condition': 'good'})
    assert r.status_code == 302


def test_update_user_book_non_owner_forbidden(app):
    with app.app_context():
        u2 = User(
            username='user2',
            display_name='User Two',
            password_hash=bcrypt.generate_password_hash('pass').decode(),
            color='#aaa',
        )
        db.session.add(u2)
        db.session.commit()

    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    r = _add_book(admin_client)
    ub_id = r.get_json()['user_book_id']

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass'})
    r = c2.patch(f'/api/user-books/{ub_id}', json={'condition': 'poor', 'location': '', 'notes': ''})
    assert r.status_code == 403
