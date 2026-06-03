"""
Background worker that retries scans which were rate-limited (429).

Items are stored in scan_retry_queue with exponential backoff:
  attempt 1  →  45 s  after initial failure
  attempt 2  →  90 s  after attempt 1
  attempt 3  → 180 s  after attempt 2
After three failures the item is marked permanently failed.
"""
import logging
import threading
import time
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

_POLL_INTERVAL = 10  # seconds between DB checks


def start(app):
    """Start the retry worker as a background daemon thread."""
    if app.config.get('TESTING'):
        return

    def _loop():
        while True:
            time.sleep(_POLL_INTERVAL)
            try:
                _tick(app)
            except Exception:
                log.exception('Retry worker unexpected error')

    t = threading.Thread(target=_loop, name='scan-retry-worker', daemon=True)
    t.start()
    log.info('Scan retry worker started (poll every %ds)', _POLL_INTERVAL)


def _tick(app):
    with app.app_context():
        from .extensions import db
        from .models import ScanRetryQueue

        now = datetime.utcnow()
        due = (ScanRetryQueue.query
               .filter(ScanRetryQueue.completed_at.is_(None),
                       ScanRetryQueue.next_retry_at <= now)
               .all())

        for item in due:
            try:
                _process(item)
            except Exception:
                log.exception('Error processing retry queue item %d', item.id)

        if due:
            db.session.commit()


def _process(item):
    from datetime import datetime, timedelta
    from .extensions import db
    from .models import ScanRetryQueue

    item.attempt += 1
    log.info('Retry attempt %d/%d — %s %s (queue id %d)',
             item.attempt, ScanRetryQueue.MAX_ATTEMPTS,
             item.media_type, item.identifier, item.id)

    data = _lookup(item)

    if data is None or data == 'rate_limited':
        _on_failure(item, data)
    else:
        _on_success(item, data)


def _lookup(item):
    if item.media_type == 'book':
        from .routes.api import _lookup_google_books, _lookup_open_library
        result = _lookup_google_books(item.identifier)
        if result is None:
            result = _lookup_open_library(item.identifier)
        return result
    elif item.media_type == 'dvd':
        from .routes.dvd_api import _lookup_upcitemdb, _lookup_omdb
        result = _lookup_upcitemdb(item.identifier)
        if result and result != 'rate_limited':
            omdb = _lookup_omdb(result['title'])
            if omdb:
                for k, v in omdb.items():
                    if v:
                        result[k] = v
        return result
    else:  # music
        from .routes.music_api import _lookup_discogs
        return _lookup_discogs(item.identifier)


def _on_failure(item, data):
    from datetime import datetime, timedelta
    from .models import ScanRetryQueue

    still_limited = (data == 'rate_limited')
    if item.attempt >= ScanRetryQueue.MAX_ATTEMPTS:
        item.completed_at = datetime.utcnow()
        item.succeeded = False
        item.result_message = ('Rate limited — lookup failed after all retries'
                               if still_limited else 'Not found after all retries')
        log.warning('Retry queue item %d permanently failed after %d attempts',
                    item.id, item.attempt)
        _write_scan_log(item,
                        lookup_status='rate_limited' if still_limited else 'not_found',
                        add_status=None,
                        error_detail='Permanently failed after retries')
    else:
        delay = ScanRetryQueue.DELAYS[item.attempt]
        item.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
        log.info('Rescheduling item %d for %ds (attempt %d → %d)',
                 item.id, delay, item.attempt, item.attempt + 1)


def _on_success(item, data):
    from datetime import datetime
    from sqlalchemy.exc import IntegrityError
    from .extensions import db
    from .models import Book, DVD, UserBook, UserDVD, User
    from .covers import fetch_and_store

    target = db.session.get(User, item.for_user_id)
    if not target:
        item.completed_at = datetime.utcnow()
        item.succeeded = False
        item.result_message = 'Target user no longer exists'
        return

    try:
        if item.media_type == 'book':
            book = Book.query.filter_by(isbn=item.identifier).first()
            if not book:
                book = Book(
                    isbn=item.identifier,
                    title=data.get('title', ''),
                    author=data.get('author', ''),
                    publisher=data.get('publisher', ''),
                    published_year=data.get('published_year', ''),
                    description=data.get('description', ''),
                    cover_url=data.get('cover_url', ''),
                    page_count=data.get('page_count'),
                    genre=data.get('genre', ''),
                    language=data.get('language', ''),
                )
                db.session.add(book)
                db.session.flush()
                if book.cover_url and not book.cover_url.startswith('/covers/'):
                    local = fetch_and_store(book.cover_url, item.identifier)
                    if local:
                        book.cover_url = local

            if not UserBook.query.filter_by(user_id=item.for_user_id, book_id=book.id).first():
                db.session.add(UserBook(
                    user_id=item.for_user_id, book_id=book.id,
                    condition=item.condition or 'good', location=item.location or '',
                ))
                db.session.flush()

            item.completed_at = datetime.utcnow()
            item.succeeded = True
            item.result_message = f'"{book.title}" added after {item.attempt} retry attempt(s)'
            _write_scan_log(item, 'found_external', 'added', None,
                            book_id=book.id, title=book.title)
            log.info('Retry succeeded: "%s" added for %s after %d attempt(s)',
                     book.title, target.display_name, item.attempt)

        elif item.media_type == 'dvd':
            dvd = DVD.query.filter_by(upc=item.identifier).first()
            if not dvd:
                dvd = DVD(
                    upc=item.identifier,
                    title=data.get('title', ''),
                    director=data.get('director', ''),
                    studio=data.get('studio', ''),
                    year=data.get('year', ''),
                    runtime=data.get('runtime'),
                    rating=data.get('rating', ''),
                    genre=data.get('genre', ''),
                    description=data.get('description', ''),
                    cover_url=data.get('cover_url', ''),
                    format=data.get('format', 'DVD'),
                )
                db.session.add(dvd)
                db.session.flush()
                if dvd.cover_url and not dvd.cover_url.startswith('/covers/'):
                    local = fetch_and_store(dvd.cover_url, item.identifier)
                    if local:
                        dvd.cover_url = local

            if not UserDVD.query.filter_by(user_id=item.for_user_id, dvd_id=dvd.id).first():
                db.session.add(UserDVD(
                    user_id=item.for_user_id, dvd_id=dvd.id,
                    condition=item.condition or 'good', location=item.location or '',
                ))
                db.session.flush()

            item.completed_at = datetime.utcnow()
            item.succeeded = True
            item.result_message = f'"{dvd.title}" added after {item.attempt} retry attempt(s)'
            _write_scan_log(item, 'found_external', 'added', None,
                            dvd_id=dvd.id, title=dvd.title)
            log.info('Retry succeeded: "%s" added for %s after %d attempt(s)',
                     dvd.title, target.display_name, item.attempt)

        else:  # music
            from .models import MusicRelease, UserMusicRelease
            music = MusicRelease.query.filter_by(barcode=item.identifier).first()
            if not music:
                music = MusicRelease(
                    barcode=item.identifier,
                    title=data.get('title', ''),
                    artist=data.get('artist', ''),
                    label=data.get('label', ''),
                    year=data.get('year', ''),
                    format=data.get('format', ''),
                    track_count=data.get('track_count'),
                    genre=data.get('genre', ''),
                    cover_url=data.get('cover_url', ''),
                    mbid=data.get('mbid', ''),
                )
                db.session.add(music)
                db.session.flush()
                if music.cover_url and not music.cover_url.startswith('/covers/'):
                    local = fetch_and_store(music.cover_url, item.identifier)
                    if local:
                        music.cover_url = local

            if not UserMusicRelease.query.filter_by(
                    user_id=item.for_user_id, music_id=music.id).first():
                db.session.add(UserMusicRelease(
                    user_id=item.for_user_id, music_id=music.id,
                    condition=item.condition or 'good', location=item.location or '',
                ))
                db.session.flush()

            item.completed_at = datetime.utcnow()
            item.succeeded = True
            item.result_message = f'"{music.title}" added after {item.attempt} retry attempt(s)'
            _write_scan_log(item, 'found_external', 'added', None,
                            music_id=music.id, title=music.title)
            log.info('Retry succeeded: "%s" added for %s after %d attempt(s)',
                     music.title, target.display_name, item.attempt)

    except IntegrityError:
        from .extensions import db as _db
        _db.session.rollback()
        item.completed_at = datetime.utcnow()
        item.succeeded = True
        item.result_message = 'Already in library (added concurrently)'


def _write_scan_log(item, lookup_status, add_status, error_detail,
                    book_id=None, dvd_id=None, music_id=None, title=None):
    from .extensions import db
    from .models import ScanLog

    db.session.add(ScanLog(
        media_type=item.media_type,
        user_id=item.requested_by_id,
        user_display_name=item.requested_by_display_name,
        isbn=item.identifier,
        lookup_status=lookup_status,
        add_status=add_status,
        book_id=book_id,
        dvd_id=dvd_id,
        music_id=music_id,
        book_title=title,
        error_detail=error_detail,
    ))
