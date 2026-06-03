"""
Tests for the scan retry queue: the enqueue endpoint and the background
worker that processes due items.
"""
import io
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.extensions import db
from app.models import Book, DVD, ScanLog, ScanRetryQueue, UserBook, UserDVD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BOOK_ISBN = '9780743273565'
_DVD_UPC   = '025192310638'

def _book_data(**kw):
    return {
        'title': 'The Great Gatsby', 'author': 'F. Scott Fitzgerald',
        'publisher': '', 'published_year': '', 'description': '',
        'cover_url': '', 'page_count': None, 'genre': '', 'language': '',
        **kw,
    }

def _dvd_data(**kw):
    return {
        'title': 'Fast Five', 'director': 'Justin Lin', 'studio': 'Universal',
        'year': '2011', 'runtime': 130, 'rating': 'PG-13',
        'genre': 'Action', 'description': '', 'cover_url': '', 'format': 'Blu-ray',
        **kw,
    }

def _enqueue(app, media_type='book', identifier=_BOOK_ISBN,
             attempt=0, overdue=True, for_user_id=None):
    """Insert a queue item directly into the DB and return its id."""
    with app.app_context():
        from app.models import User
        uid = for_user_id or User.query.first().id
        delta = timedelta(seconds=-1) if overdue else timedelta(hours=1)
        item = ScanRetryQueue(
            media_type=media_type,
            identifier=identifier,
            for_user_id=uid,
            requested_by_id=uid,
            requested_by_display_name='Admin',
            condition='good',
            location='Shelf A',
            attempt=attempt,
            next_retry_at=datetime.utcnow() + delta,
        )
        db.session.add(item)
        db.session.commit()
        return item.id


# ---------------------------------------------------------------------------
# POST /api/retry-queue
# ---------------------------------------------------------------------------

def test_enqueue_requires_auth(client):
    r = client.post('/api/retry-queue',
                    json={'media_type': 'book', 'identifier': _BOOK_ISBN})
    assert r.status_code == 302


def test_enqueue_creates_entry(logged_in_client, app):
    r = logged_in_client.post('/api/retry-queue',
                              json={'media_type': 'book', 'identifier': _BOOK_ISBN})
    assert r.status_code == 200
    data = r.get_json()
    assert data['success'] is True
    assert data['retry_in'] == ScanRetryQueue.DELAYS[0]
    assert 'queue_id' in data

    with app.app_context():
        item = db.session.get(ScanRetryQueue, data["queue_id"])
        assert item.identifier == _BOOK_ISBN
        assert item.media_type == 'book'
        assert item.attempt == 0
        assert item.completed_at is None
        assert item.next_retry_at > datetime.utcnow()


def test_enqueue_stores_condition_and_location(logged_in_client, app):
    logged_in_client.post('/api/retry-queue', json={
        'media_type': 'dvd', 'identifier': _DVD_UPC,
        'condition': 'like_new', 'location': 'Living Room',
    })
    with app.app_context():
        item = ScanRetryQueue.query.first()
        assert item.condition == 'like_new'
        assert item.location == 'Living Room'


def test_enqueue_requires_identifier(logged_in_client):
    r = logged_in_client.post('/api/retry-queue', json={'media_type': 'book'})
    assert r.status_code == 400


def test_enqueue_schedules_45s_ahead(logged_in_client, app):
    before = datetime.utcnow()
    logged_in_client.post('/api/retry-queue',
                          json={'media_type': 'book', 'identifier': _BOOK_ISBN})
    with app.app_context():
        item = ScanRetryQueue.query.first()
        assert item.next_retry_at >= before + timedelta(seconds=44)


# ---------------------------------------------------------------------------
# _tick — items that should not be processed
# ---------------------------------------------------------------------------

def test_tick_skips_future_items(app):
    _enqueue(app, overdue=False)
    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books') as mock:
        _tick(app)
    mock.assert_not_called()
    with app.app_context():
        assert ScanRetryQueue.query.first().attempt == 0


def test_tick_skips_completed_items(app):
    item_id = _enqueue(app)
    with app.app_context():
        item = db.session.get(ScanRetryQueue, item_id)
        item.completed_at = datetime.utcnow()
        item.succeeded = False
        db.session.commit()

    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books') as mock:
        _tick(app)
    mock.assert_not_called()


# ---------------------------------------------------------------------------
# Book retry — success path
# ---------------------------------------------------------------------------

def test_book_success_adds_to_library(app):
    item_id = _enqueue(app)
    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books', return_value=_book_data()):
        _tick(app)

    with app.app_context():
        item = db.session.get(ScanRetryQueue, item_id)
        assert item.succeeded is True
        assert item.completed_at is not None
        assert Book.query.filter_by(isbn=_BOOK_ISBN).count() == 1
        assert UserBook.query.count() == 1


def test_book_success_writes_scan_log(app):
    _enqueue(app)
    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books', return_value=_book_data()):
        _tick(app)

    with app.app_context():
        log = ScanLog.query.order_by(ScanLog.scanned_at.desc()).first()
        assert log.lookup_status == 'found_external'
        assert log.add_status == 'added'
        assert log.isbn == _BOOK_ISBN


def test_book_success_respects_condition_and_location(app):
    _enqueue(app)
    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books', return_value=_book_data()):
        _tick(app)

    with app.app_context():
        ub = UserBook.query.first()
        assert ub.condition == 'good'
        assert ub.location == 'Shelf A'


def test_book_already_in_library_marks_succeeded(app):
    """If a concurrent add beat the retry, it should complete gracefully."""
    item_id = _enqueue(app)
    # Pre-seed the book so the retry finds it already there
    with app.app_context():
        from app.models import User
        uid = User.query.first().id
        book = Book(isbn=_BOOK_ISBN, title='Pre-existing')
        db.session.add(book)
        db.session.flush()
        db.session.add(UserBook(user_id=uid, book_id=book.id))
        db.session.commit()

    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books', return_value=_book_data()):
        _tick(app)

    with app.app_context():
        item = db.session.get(ScanRetryQueue, item_id)
        assert item.succeeded is True
        assert UserBook.query.count() == 1  # no duplicate


# ---------------------------------------------------------------------------
# DVD retry — success path
# ---------------------------------------------------------------------------

def test_dvd_success_adds_to_library(app):
    item_id = _enqueue(app, media_type='dvd', identifier=_DVD_UPC)
    from app.retry_worker import _tick
    with patch('app.routes.dvd_api._lookup_upcitemdb', return_value=_dvd_data()), \
         patch('app.routes.dvd_api._lookup_omdb', return_value=None):
        _tick(app)

    with app.app_context():
        item = db.session.get(ScanRetryQueue, item_id)
        assert item.succeeded is True
        assert DVD.query.filter_by(upc=_DVD_UPC).count() == 1
        assert UserDVD.query.count() == 1


def test_dvd_success_writes_scan_log(app):
    _enqueue(app, media_type='dvd', identifier=_DVD_UPC)
    from app.retry_worker import _tick
    with patch('app.routes.dvd_api._lookup_upcitemdb', return_value=_dvd_data()), \
         patch('app.routes.dvd_api._lookup_omdb', return_value=None):
        _tick(app)

    with app.app_context():
        log = ScanLog.query.order_by(ScanLog.scanned_at.desc()).first()
        assert log.media_type == 'dvd'
        assert log.add_status == 'added'


# ---------------------------------------------------------------------------
# Retry scheduling — rate-limited failures
# ---------------------------------------------------------------------------

def test_first_failure_schedules_second_attempt(app):
    """Attempt 1 fails → schedule attempt 2 in 90 s (DELAYS[1])."""
    item_id = _enqueue(app)
    before = datetime.utcnow()
    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books', return_value='rate_limited'), \
         patch('app.routes.api._lookup_open_library', return_value='rate_limited'):
        _tick(app)

    with app.app_context():
        item = db.session.get(ScanRetryQueue, item_id)
        assert item.attempt == 1
        assert item.completed_at is None
        assert item.next_retry_at >= before + timedelta(seconds=ScanRetryQueue.DELAYS[1] - 2)


def test_second_failure_schedules_third_attempt(app):
    """Attempt 2 fails → schedule attempt 3 in 180 s (DELAYS[2])."""
    item_id = _enqueue(app, attempt=1)
    before = datetime.utcnow()
    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books', return_value='rate_limited'), \
         patch('app.routes.api._lookup_open_library', return_value='rate_limited'):
        _tick(app)

    with app.app_context():
        item = db.session.get(ScanRetryQueue, item_id)
        assert item.attempt == 2
        assert item.next_retry_at >= before + timedelta(seconds=ScanRetryQueue.DELAYS[2] - 2)


def test_third_failure_marks_permanently_failed(app):
    """Attempt 3 fails → item is done, succeeded=False."""
    item_id = _enqueue(app, attempt=2)
    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books', return_value='rate_limited'), \
         patch('app.routes.api._lookup_open_library', return_value='rate_limited'):
        _tick(app)

    with app.app_context():
        item = db.session.get(ScanRetryQueue, item_id)
        assert item.attempt == 3
        assert item.succeeded is False
        assert item.completed_at is not None


def test_permanent_failure_writes_scan_log(app):
    _enqueue(app, attempt=2)
    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books', return_value='rate_limited'), \
         patch('app.routes.api._lookup_open_library', return_value='rate_limited'):
        _tick(app)

    with app.app_context():
        log = ScanLog.query.order_by(ScanLog.scanned_at.desc()).first()
        assert log.lookup_status == 'rate_limited'
        assert 'Permanently failed' in (log.error_detail or '')


def test_not_found_on_final_attempt_marks_failed(app):
    """If the API returns None (not 429) on the last attempt, also permanently fails."""
    item_id = _enqueue(app, attempt=2)
    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books', return_value=None), \
         patch('app.routes.api._lookup_open_library', return_value=None):
        _tick(app)

    with app.app_context():
        item = db.session.get(ScanRetryQueue, item_id)
        assert item.succeeded is False


# ---------------------------------------------------------------------------
# Missing user
# ---------------------------------------------------------------------------

def test_missing_target_user_marks_failed(app):
    """If the for_user is deleted before the retry runs, fail gracefully."""
    with app.app_context():
        from app.extensions import bcrypt
        from app.models import User
        ghost = User(username='ghost', display_name='Ghost',
                     password_hash=bcrypt.generate_password_hash('x').decode(),
                     color='#aaa')
        db.session.add(ghost)
        db.session.commit()
        ghost_id = ghost.id

    item_id = _enqueue(app, for_user_id=ghost_id)

    # Delete the user after enqueueing
    with app.app_context():
        from app.models import User
        db.session.delete(db.session.get(User, ghost_id))
        db.session.commit()

    from app.retry_worker import _tick
    with patch('app.routes.api._lookup_google_books', return_value=_book_data()):
        _tick(app)  # should not raise

    with app.app_context():
        item = db.session.get(ScanRetryQueue, item_id)
        assert item.succeeded is False
