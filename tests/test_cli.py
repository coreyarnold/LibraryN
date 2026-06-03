"""Tests for Flask CLI commands (backfill-covers, backfill-dvd-metadata)."""
import io
from unittest.mock import MagicMock, patch

from PIL import Image

from app.extensions import db
from app.models import Book, DVD


def _fake_jpeg():
    buf = io.BytesIO()
    Image.new('RGB', (100, 150)).save(buf, 'JPEG')
    return buf.getvalue()


def _cover_resp():
    m = MagicMock()
    m.status_code = 200
    m.content = _fake_jpeg()
    return m


# ---------------------------------------------------------------------------
# backfill-covers
# ---------------------------------------------------------------------------

def test_backfill_covers_nothing_to_do(app):
    """No items in DB → prints 'Nothing to backfill'."""
    runner = app.test_cli_runner()
    result = runner.invoke(args=['backfill-covers'])
    assert result.exit_code == 0
    assert 'Nothing to backfill' in result.output


def test_backfill_covers_downloads_book_cover(app):
    """Book with external cover URL gets it downloaded and stored locally."""
    import tempfile
    with app.app_context():
        from app.models import User, UserBook
        uid = User.query.first().id
        book = Book(isbn='9780743273565', title='Gatsby',
                    cover_url='https://example.com/cover.jpg')
        db.session.add(book)
        db.session.flush()
        db.session.add(UserBook(user_id=uid, book_id=book.id))
        db.session.commit()
        book_id = book.id

    with tempfile.TemporaryDirectory() as covers_dir:
        app.config['COVERS_DIR'] = covers_dir
        with patch('app.covers.requests.get', return_value=_cover_resp()):
            result = app.test_cli_runner().invoke(args=['backfill-covers'])

    assert result.exit_code == 0
    assert '1 stored' in result.output

    with app.app_context():
        assert db.session.get(Book, book_id).cover_url.startswith('/covers/')


def test_backfill_covers_skips_already_local(app):
    """Book whose cover is already /covers/… is skipped."""
    with app.app_context():
        from app.models import User, UserBook
        uid = User.query.first().id
        book = Book(isbn='9780743273565', title='Gatsby',
                    cover_url='/covers/already.jpg')
        db.session.add(book)
        db.session.flush()
        db.session.add(UserBook(user_id=uid, book_id=book.id))
        db.session.commit()

    result = app.test_cli_runner().invoke(args=['backfill-covers'])
    assert 'Nothing to backfill' in result.output


def test_backfill_covers_handles_download_failure(app):
    """Download failures are counted as 'failed', not crashes."""
    import tempfile
    with app.app_context():
        from app.models import User, UserBook
        uid = User.query.first().id
        book = Book(isbn='9780743273565', title='Gatsby',
                    cover_url='https://example.com/bad.jpg')
        db.session.add(book)
        db.session.flush()
        db.session.add(UserBook(user_id=uid, book_id=book.id))
        db.session.commit()

    bad_resp = MagicMock()
    bad_resp.status_code = 404

    with tempfile.TemporaryDirectory() as covers_dir:
        app.config['COVERS_DIR'] = covers_dir
        with patch('app.covers.requests.get', return_value=bad_resp):
            result = app.test_cli_runner().invoke(args=['backfill-covers'])

    assert result.exit_code == 0
    assert '0 stored' in result.output
    assert '1 failed' in result.output


# ---------------------------------------------------------------------------
# backfill-dvd-metadata
# ---------------------------------------------------------------------------

def test_backfill_dvd_metadata_no_token(app):
    """Without OMDB_API_KEY the command exits with instructions."""
    import os
    env = {k: v for k, v in os.environ.items() if k != 'OMDB_API_KEY'}
    with patch.dict('os.environ', env, clear=True):
        result = app.test_cli_runner().invoke(args=['backfill-dvd-metadata'])
    assert 'OMDB_API_KEY' in result.output


def test_backfill_dvd_metadata_nothing_to_do(app):
    """All DVDs have director info → prints 'All DVDs already have director info'."""
    with app.app_context():
        from app.models import User, UserDVD
        uid = User.query.first().id
        dvd = DVD(upc='025192310638', title='Fast Five', director='Justin Lin')
        db.session.add(dvd)
        db.session.flush()
        db.session.add(UserDVD(user_id=uid, dvd_id=dvd.id))
        db.session.commit()

    with patch.dict('os.environ', {'OMDB_API_KEY': 'testkey'}):
        result = app.test_cli_runner().invoke(args=['backfill-dvd-metadata'])
    assert 'All DVDs already have director info' in result.output


def test_backfill_dvd_metadata_enriches_dvd(app):
    """DVD without director gets enriched when OMDb returns data."""
    with app.app_context():
        from app.models import User, UserDVD
        uid = User.query.first().id
        dvd = DVD(upc='025192310638', title='Fast Five')
        db.session.add(dvd)
        db.session.flush()
        db.session.add(UserDVD(user_id=uid, dvd_id=dvd.id))
        db.session.commit()
        dvd_id = dvd.id

    omdb_resp = MagicMock()
    omdb_resp.status_code = 200
    omdb_resp.json.return_value = {
        'Response': 'True',
        'Director': 'Justin Lin', 'Year': '2011', 'Rated': 'PG-13',
        'Genre': 'Action', 'Plot': 'Cars go fast.',
        'Production': 'Universal', 'Runtime': '130 min', 'Poster': 'N/A',
    }

    with patch.dict('os.environ', {'OMDB_API_KEY': 'testkey'}):
        with patch('app.routes.dvd_api.requests.get', return_value=omdb_resp):
            result = app.test_cli_runner().invoke(args=['backfill-dvd-metadata'])

    assert result.exit_code == 0
    assert '1 enriched' in result.output

    with app.app_context():
        dvd = db.session.get(DVD, dvd_id)
        assert dvd.director == 'Justin Lin'
        assert dvd.rating   == 'PG-13'


def test_backfill_dvd_metadata_marks_fail_when_not_found(app):
    """When OMDb can't find a title it's counted as failed."""
    with app.app_context():
        from app.models import User, UserDVD
        uid = User.query.first().id
        dvd = DVD(upc='000000000000', title='Obscure Film')
        db.session.add(dvd)
        db.session.flush()
        db.session.add(UserDVD(user_id=uid, dvd_id=dvd.id))
        db.session.commit()

    not_found = MagicMock()
    not_found.status_code = 200
    not_found.json.return_value = {'Response': 'False', 'Error': 'Movie not found!'}

    with patch.dict('os.environ', {'OMDB_API_KEY': 'testkey'}):
        with patch('app.routes.dvd_api.requests.get', return_value=not_found):
            result = app.test_cli_runner().invoke(args=['backfill-dvd-metadata'])

    assert '0 enriched' in result.output
    assert '1 not found' in result.output
