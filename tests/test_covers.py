"""Tests for cover image download and local storage."""
import io
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


def _make_jpeg(width=200, height=300):
    buf = io.BytesIO()
    Image.new('RGB', (width, height), color=(100, 149, 237)).save(buf, 'JPEG')
    return buf.getvalue()


def _mock_response(status=200, content=None):
    resp = MagicMock()
    resp.status_code = status
    resp.content = content or _make_jpeg()
    return resp


# ---------------------------------------------------------------------------
# fetch_and_store
# ---------------------------------------------------------------------------

def test_fetch_and_store_downloads_and_saves(app):
    with tempfile.TemporaryDirectory() as d:
        app.config['COVERS_DIR'] = d
        with app.app_context():
            from app.covers import fetch_and_store
            with patch('app.covers.requests.get', return_value=_mock_response()):
                result = fetch_and_store('https://example.com/cover.jpg', 'test-isbn')

        assert result == '/covers/test-isbn.jpg'
        assert os.path.exists(os.path.join(d, 'test-isbn.jpg'))


def test_fetch_and_store_resizes_large_image(app):
    """Images wider than MAX_SIZE should be shrunk."""
    big_jpeg = _make_jpeg(width=1200, height=1800)
    with tempfile.TemporaryDirectory() as d:
        app.config['COVERS_DIR'] = d
        with app.app_context():
            from app.covers import fetch_and_store, MAX_SIZE
            with patch('app.covers.requests.get',
                       return_value=_mock_response(content=big_jpeg)):
                fetch_and_store('https://example.com/big.jpg', 'big-cover')

        img = Image.open(os.path.join(d, 'big-cover.jpg'))
        assert img.width <= MAX_SIZE[0]
        assert img.height <= MAX_SIZE[1]


def test_fetch_and_store_non200_returns_none(app):
    with tempfile.TemporaryDirectory() as d:
        app.config['COVERS_DIR'] = d
        with app.app_context():
            from app.covers import fetch_and_store
            with patch('app.covers.requests.get', return_value=_mock_response(status=404)):
                result = fetch_and_store('https://example.com/missing.jpg', 'x')
        assert result is None


def test_fetch_and_store_empty_url_returns_none(app):
    with app.app_context():
        from app.covers import fetch_and_store
        assert fetch_and_store('', 'x') is None
        assert fetch_and_store(None, 'x') is None


def test_fetch_and_store_timeout_returns_none(app):
    import requests as req
    with tempfile.TemporaryDirectory() as d:
        app.config['COVERS_DIR'] = d
        with app.app_context():
            from app.covers import fetch_and_store
            with patch('app.covers.requests.get', side_effect=req.Timeout):
                result = fetch_and_store('https://example.com/slow.jpg', 'x')
        assert result is None


def test_fetch_and_store_unexpected_error_returns_none(app):
    with tempfile.TemporaryDirectory() as d:
        app.config['COVERS_DIR'] = d
        with app.app_context():
            from app.covers import fetch_and_store
            with patch('app.covers.requests.get', side_effect=ValueError('bad')):
                result = fetch_and_store('https://example.com/bad.jpg', 'x')
        assert result is None


def test_fetch_and_store_creates_covers_dir(app):
    """COVERS_DIR should be created if it doesn't exist yet."""
    with tempfile.TemporaryDirectory() as base:
        new_dir = os.path.join(base, 'covers', 'nested')
        app.config['COVERS_DIR'] = new_dir
        with app.app_context():
            from app.covers import fetch_and_store
            with patch('app.covers.requests.get', return_value=_mock_response()):
                fetch_and_store('https://example.com/c.jpg', 'c')
        assert os.path.isdir(new_dir)


def test_covers_route_serves_file(app):
    """GET /covers/<filename> should serve the stored image."""
    with tempfile.TemporaryDirectory() as d:
        app.config['COVERS_DIR'] = d
        # Write a real JPEG into the covers dir
        Image.new('RGB', (50, 75)).save(os.path.join(d, 'testbook.jpg'), 'JPEG')

        client = app.test_client()
        client.post('/login', data={'username': 'admin', 'password': 'changeme'})
        r = client.get('/covers/testbook.jpg')
        # Flask serves it with 200 or triggers a redirect — just not 404
        assert r.status_code == 200


def test_covers_route_404_for_missing_file(app):
    with tempfile.TemporaryDirectory() as d:
        app.config['COVERS_DIR'] = d
        client = app.test_client()
        r = client.get('/covers/nonexistent.jpg')
        assert r.status_code == 404
