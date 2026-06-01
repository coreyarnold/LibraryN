"""
Playwright end-to-end tests for the scan page.

These tests start a real Flask server as a subprocess so the full
request/response cycle — including the JS that chains lookup → add → logScan
— is exercised exactly as it runs in production.
"""
import os
import sys
import time
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import requests as req

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORT       = 5099
BASE_URL   = f'http://localhost:{PORT}'
ADMIN_PASS = 'browser-test-pass'

# Pre-seeded for user2 only (admin will auto-add via scan)
ISBN_USER2_ONLY = '9780743273565'
# Pre-seeded for admin (to test "already owned" path)
ISBN_ADMIN_OWNED = '9780061965487'


# ---------------------------------------------------------------------------
# Session-scoped server fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def server(tmp_path_factory):
    """
    Start a Flask subprocess with a fresh SQLite DB, seed test data,
    and yield the base URL. Tears down after the session.
    """
    db_path = tmp_path_factory.mktemp('browser') / 'browser.db'
    env = {
        **os.environ,
        'DATABASE_URL': f'sqlite:///{db_path}',
        'SECRET_KEY': 'browser-test-secret-key',
        'ADMIN_USERNAME': 'admin',
        'ADMIN_PASSWORD': ADMIN_PASS,
        'ADMIN_DISPLAY_NAME': 'Admin',
    }
    app_dir = Path(__file__).parent.parent / 'app'
    proc = subprocess.Popen(
        [sys.executable, '-m', 'flask', '--app', '__init__:create_app()', 'run', '--port', str(PORT)],
        cwd=str(app_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait up to 10 s for the server to accept connections
    for _ in range(40):
        try:
            urllib.request.urlopen(f'{BASE_URL}/', timeout=1)
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    else:
        proc.terminate()
        pytest.fail('Browser test server did not start in time.')

    # Seed data via the API
    s = req.Session()
    s.post(f'{BASE_URL}/login', data={'username': 'admin', 'password': ADMIN_PASS})

    # Create user2 so we can seed a book they own (admin hasn't scanned it yet)
    s.post(
        f'{BASE_URL}/users/create',
        data={'username': 'user2', 'display_name': 'User Two',
              'password': 'pass123', 'color': '#00b894'},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    # Book owned only by user2 — admin will auto-add this via scan
    s.post(f'{BASE_URL}/api/books', json={
        'isbn': ISBN_USER2_ONLY,
        'title': 'The Great Gatsby',
        'author': 'F. Scott Fitzgerald',
        'user_id': 2,
    })
    # Book already owned by admin — tests "already owned" path
    s.post(f'{BASE_URL}/api/books', json={
        'isbn': ISBN_ADMIN_OWNED,
        'title': 'To Kill a Mockingbird',
        'author': 'Harper Lee',
        'user_id': 1,
    })

    yield BASE_URL

    proc.terminate()
    proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Shared login fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_page(page, server):
    """Playwright page already authenticated as admin."""
    page.goto(f'{server}/login')
    page.fill('#username', 'admin')
    page.fill('#password', ADMIN_PASS)
    page.click("button[type='submit']")
    page.wait_for_url(f'{server}/dashboard')
    return page


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_scan_location_persists_across_navigation(auth_page, server):
    """Location stored in sessionStorage survives same-tab navigation."""
    page = auth_page
    page.goto(f'{server}/scan')
    page.wait_for_selector('#session-location')

    page.fill('#session-location', 'Bedroom Shelf 3')

    # Navigate away and back within the same tab
    page.goto(f'{server}/books')
    page.goto(f'{server}/scan')
    page.wait_for_selector('#session-location')

    assert page.input_value('#session-location') == 'Bedroom Shelf 3'


def test_scan_auto_add_book_found_in_db(auth_page, server):
    """
    Scanning an ISBN that's in the DB (but not owned by admin) auto-adds
    it immediately with no confirmation step and shows an 'Added' result.
    """
    page = auth_page
    page.goto(f'{server}/scan')
    page.wait_for_selector('#isbn-input')

    page.fill('#isbn-input', ISBN_USER2_ONLY)
    page.press('#isbn-input', 'Enter')

    # Wait for spinner to clear (lookup + add complete)
    page.wait_for_selector('#scan-result .spinner-border', state='detached', timeout=10000)

    result = page.inner_text('#scan-result')
    assert 'Added' in result
    assert 'Great Gatsby' in result


def test_scan_already_owned_shows_correct_state(auth_page, server):
    """Scanning a book admin already owns shows 'Already in library', no add attempted."""
    page = auth_page
    page.goto(f'{server}/scan')
    page.wait_for_selector('#isbn-input')

    page.fill('#isbn-input', ISBN_ADMIN_OWNED)
    page.press('#isbn-input', 'Enter')
    page.wait_for_selector('#scan-result .spinner-border', state='detached', timeout=10000)

    result = page.inner_text('#scan-result')
    assert 'Already in library' in result


def test_scan_invalid_isbn_shows_error(auth_page, server):
    """A barcode that's not a valid ISBN shows an error and 'Add Manually' fallback."""
    page = auth_page
    page.goto(f'{server}/scan')
    page.wait_for_selector('#isbn-input')

    page.fill('#isbn-input', '123')
    page.press('#isbn-input', 'Enter')
    page.wait_for_selector('#scan-result .spinner-border', state='detached', timeout=10000)

    result = page.inner_text('#scan-result')
    assert 'Invalid' in result or 'invalid' in result
    # Manual-entry fallback is present
    assert page.query_selector('#open-manual') is not None


def test_scan_input_refocused_after_scan(auth_page, server):
    """After a scan completes the ISBN input is focused, ready for the next barcode."""
    page = auth_page
    page.goto(f'{server}/scan')
    page.wait_for_selector('#isbn-input')

    page.fill('#isbn-input', '123')
    page.press('#isbn-input', 'Enter')
    page.wait_for_selector('#scan-result .spinner-border', state='detached', timeout=10000)

    focused_id = page.evaluate('document.activeElement?.id')
    assert focused_id == 'isbn-input'


def test_scan_creates_audit_log_entry(auth_page, server):
    """Every scan (including failures) creates a row visible on the audit page."""
    page = auth_page

    page.goto(f'{server}/audit')
    page.wait_for_selector('h1')
    initial_rows = len(page.query_selector_all('tbody tr'))

    # Scan a 10-digit ISBN that won't be in the DB → not_found or similar
    page.goto(f'{server}/scan')
    page.wait_for_selector('#isbn-input')
    page.fill('#isbn-input', '0000000000')
    page.press('#isbn-input', 'Enter')
    page.wait_for_selector('#scan-result .spinner-border', state='detached', timeout=15000)

    # Give the fire-and-forget log POST time to land
    page.wait_for_timeout(800)

    page.goto(f'{server}/audit')
    page.wait_for_selector('h1')
    final_rows = len(page.query_selector_all('tbody tr'))

    assert final_rows > initial_rows
