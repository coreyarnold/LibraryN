from app.models import ScanLog


# ---------------------------------------------------------------------------
# POST /api/scan-log
# ---------------------------------------------------------------------------

def test_scan_log_requires_auth(client):
    r = client.post('/api/scan-log', json={'isbn': '9780743273565', 'lookup_status': 'not_found'})
    assert r.status_code == 302


def test_scan_log_creates_record(logged_in_client, app):
    r = logged_in_client.post('/api/scan-log', json={
        'isbn': '9780743273565',
        'lookup_status': 'found_external',
        'add_status': 'added',
        'book_id': None,
        'book_title': 'The Great Gatsby',
    })
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        log = ScanLog.query.order_by(ScanLog.scanned_at.desc()).first()
        assert log is not None
        assert log.isbn == '9780743273565'
        assert log.lookup_status == 'found_external'
        assert log.add_status == 'added'
        assert log.book_title == 'The Great Gatsby'


def test_scan_log_records_user(logged_in_client, app):
    logged_in_client.post('/api/scan-log', json={
        'isbn': '1234567890',
        'lookup_status': 'not_found',
    })
    with app.app_context():
        log = ScanLog.query.order_by(ScanLog.scanned_at.desc()).first()
        assert log.user_display_name == 'Admin'
        assert log.user_id is not None


def test_scan_log_records_error_detail(logged_in_client, app):
    logged_in_client.post('/api/scan-log', json={
        'isbn': '123',
        'lookup_status': 'invalid',
        'error_detail': 'Invalid ISBN format. Must be 10 or 13 digits.',
    })
    with app.app_context():
        log = ScanLog.query.order_by(ScanLog.scanned_at.desc()).first()
        assert log.lookup_status == 'invalid'
        assert 'Invalid ISBN' in log.error_detail


def test_scan_log_null_add_status_when_lookup_failed(logged_in_client, app):
    logged_in_client.post('/api/scan-log', json={
        'isbn': '9780743273565',
        'lookup_status': 'not_found',
        'add_status': '',   # empty string should be stored as NULL
    })
    with app.app_context():
        log = ScanLog.query.order_by(ScanLog.scanned_at.desc()).first()
        assert log.add_status is None


# ---------------------------------------------------------------------------
# GET /audit  (admin-only page)
# ---------------------------------------------------------------------------

def test_audit_page_requires_admin(app):
    from app.extensions import db, bcrypt
    from app.models import User
    with app.app_context():
        u = User(
            username='nonadmin',
            display_name='Regular',
            password_hash=bcrypt.generate_password_hash('pass').decode(),
            color='#aaa',
        )
        db.session.add(u)
        db.session.commit()

    c = app.test_client()
    c.post('/login', data={'username': 'nonadmin', 'password': 'pass'})
    r = c.get('/audit')
    assert r.status_code == 403


def test_audit_page_renders(logged_in_client):
    r = logged_in_client.get('/audit')
    assert r.status_code == 200
    assert b'Scan Audit' in r.data


def test_audit_page_requires_auth(client):
    r = client.get('/audit')
    assert r.status_code == 302
    assert 'login' in r.headers['Location']


def test_audit_page_shows_log_entries(logged_in_client):
    logged_in_client.post('/api/scan-log', json={
        'isbn': '9780743273565',
        'lookup_status': 'found_external',
        'add_status': 'added',
        'book_title': 'The Great Gatsby',
    })

    r = logged_in_client.get('/audit')
    assert r.status_code == 200
    assert b'9780743273565' in r.data
    assert b'Great Gatsby' in r.data


def test_audit_page_stat_counts(logged_in_client):
    logged_in_client.post('/api/scan-log', json={'isbn': '1111111111', 'lookup_status': 'not_found'})
    logged_in_client.post('/api/scan-log', json={'isbn': '2222222222', 'lookup_status': 'found_external', 'add_status': 'added', 'book_title': 'A'})
    logged_in_client.post('/api/scan-log', json={'isbn': '3333333333', 'lookup_status': 'invalid', 'error_detail': 'bad'})

    r = logged_in_client.get('/audit')
    assert r.status_code == 200
    # Page renders with stats — just verify no 500 and key terms present
    assert b'Total Scans' in r.data
    assert b'Added to Library' in r.data
    assert b'Not Found' in r.data
    assert b'Errors' in r.data


def test_audit_page_filter_by_status_added(logged_in_client):
    logged_in_client.post('/api/scan-log', json={'isbn': '1111111111', 'lookup_status': 'not_found'})
    logged_in_client.post('/api/scan-log', json={'isbn': '2222222222', 'lookup_status': 'found_external', 'add_status': 'added', 'book_title': 'B'})

    r = logged_in_client.get('/audit?status=added')
    assert r.status_code == 200
    assert b'2222222222' in r.data
    assert b'1111111111' not in r.data


def test_audit_page_filter_by_status_not_found(logged_in_client):
    logged_in_client.post('/api/scan-log', json={'isbn': '9990000001', 'lookup_status': 'not_found'})
    logged_in_client.post('/api/scan-log', json={'isbn': '9990000002', 'lookup_status': 'found_external', 'add_status': 'added', 'book_title': 'C'})

    r = logged_in_client.get('/audit?status=not_found')
    assert r.status_code == 200
    assert b'9990000001' in r.data
    assert b'9990000002' not in r.data


def test_audit_page_filter_by_status_error(logged_in_client):
    logged_in_client.post('/api/scan-log', json={'isbn': '8880000001', 'lookup_status': 'invalid', 'error_detail': 'bad isbn'})
    logged_in_client.post('/api/scan-log', json={'isbn': '8880000002', 'lookup_status': 'found_external', 'add_status': 'added', 'book_title': 'D'})

    r = logged_in_client.get('/audit?status=error')
    assert r.status_code == 200
    assert b'8880000001' in r.data
    assert b'8880000002' not in r.data
