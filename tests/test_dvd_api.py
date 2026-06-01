from unittest.mock import patch, MagicMock

from app.extensions import db, bcrypt
from app.models import User, DVD, UserDVD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upcitemdb_mock(title='Fast Five', brand='Universal', description='An action film'):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        'items': [{'title': title, 'brand': brand, 'description': description, 'images': []}]
    }
    return resp


def _add_dvd(client, upc='025192310638', title='Fast Five', **extra):
    return client.post('/api/dvds', json={'upc': upc, 'title': title, **extra})


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


# ---------------------------------------------------------------------------
# UPC lookup
# ---------------------------------------------------------------------------

def test_dvd_lookup_requires_auth(client):
    r = client.get('/api/dvd/lookup/025192310638')
    assert r.status_code == 302
    assert 'login' in r.headers['Location']


def test_dvd_lookup_invalid_upc_letters(logged_in_client):
    r = logged_in_client.get('/api/dvd/lookup/notaupc')
    assert r.status_code == 400
    assert 'error' in r.get_json()


def test_dvd_lookup_invalid_upc_wrong_length(logged_in_client):
    r = logged_in_client.get('/api/dvd/lookup/123')
    assert r.status_code == 400


def test_dvd_lookup_returns_local_dvd(logged_in_client, app):
    with app.app_context():
        user = User.query.first()
        dvd = DVD(upc='025192310638', title='Fast Five', director='Justin Lin')
        db.session.add(dvd)
        db.session.flush()
        db.session.add(UserDVD(user_id=user.id, dvd_id=dvd.id))
        db.session.commit()

    r = logged_in_client.get('/api/dvd/lookup/025192310638')
    data = r.get_json()
    assert r.status_code == 200
    assert data['in_library'] is True
    assert data['title'] == 'Fast Five'
    assert len(data['owners']) == 1


def test_dvd_lookup_calls_external_api(logged_in_client):
    with patch('app.routes.dvd_api.requests.get', return_value=_upcitemdb_mock()):
        r = logged_in_client.get('/api/dvd/lookup/025192310638')
    assert r.status_code == 200
    data = r.get_json()
    assert data['title'] == 'Fast Five'
    assert data['in_library'] is False


def test_dvd_lookup_returns_404_when_not_found(logged_in_client):
    not_found = MagicMock()
    not_found.status_code = 200
    not_found.json.return_value = {'items': []}
    with patch('app.routes.dvd_api.requests.get', return_value=not_found):
        r = logged_in_client.get('/api/dvd/lookup/025192310638')
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Add DVD
# ---------------------------------------------------------------------------

def test_add_dvd_creates_records(logged_in_client, app):
    r = _add_dvd(logged_in_client, director='Justin Lin', format='Blu-ray')
    assert r.status_code == 200
    data = r.get_json()
    assert data['success'] is True

    with app.app_context():
        dvd = DVD.query.filter_by(upc='025192310638').first()
        assert dvd is not None
        assert dvd.director == 'Justin Lin'
        assert UserDVD.query.filter_by(dvd_id=dvd.id).count() == 1


def test_add_dvd_requires_upc_and_title(logged_in_client):
    r = logged_in_client.post('/api/dvds', json={'upc': '025192310638'})
    assert r.status_code == 400

    r = logged_in_client.post('/api/dvds', json={'title': 'No UPC'})
    assert r.status_code == 400


def test_add_dvd_duplicate_returns_409(logged_in_client):
    _add_dvd(logged_in_client)
    r = _add_dvd(logged_in_client)
    assert r.status_code == 409


def test_add_dvd_reuses_existing_dvd_record(logged_in_client, app):
    """Two users owning the same UPC share one DVD row."""
    _create_user(app)
    with app.app_context():
        u2_id = User.query.filter_by(username='user2').first().id

    _add_dvd(logged_in_client)

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = _add_dvd(c2, user_id=u2_id)
    assert r.status_code == 200

    with app.app_context():
        assert DVD.query.filter_by(upc='025192310638').count() == 1
        assert UserDVD.query.count() == 2


def test_add_dvd_requires_auth(client):
    r = client.post('/api/dvds', json={'upc': '025192310638', 'title': 'Test'})
    assert r.status_code == 302


def test_non_admin_cannot_add_dvd_for_other_user(app):
    _create_user(app)
    with app.app_context():
        admin_id = User.query.filter_by(username='admin').first().id

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.post('/api/dvds', json={'upc': '025192310638', 'title': 'Test', 'user_id': admin_id})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Remove DVD
# ---------------------------------------------------------------------------

def test_remove_dvd_deletes_user_dvd(logged_in_client, app):
    r = _add_dvd(logged_in_client)
    user_dvd_id = r.get_json()['user_dvd_id']

    r = logged_in_client.delete(f'/api/dvds/{user_dvd_id}')
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        assert db.session.get(UserDVD, user_dvd_id) is None


def test_remove_last_owner_cascades_to_dvd(logged_in_client, app):
    r = _add_dvd(logged_in_client)
    data = r.get_json()
    user_dvd_id = data['user_dvd_id']
    dvd_id = data['dvd_id']

    logged_in_client.delete(f'/api/dvds/{user_dvd_id}')

    with app.app_context():
        assert db.session.get(DVD, dvd_id) is None


def test_remove_dvd_not_found(logged_in_client):
    r = logged_in_client.delete('/api/dvds/99999')
    assert r.status_code == 404


def test_remove_dvd_other_user_forbidden(app):
    _create_user(app)
    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    r = _add_dvd(admin_client)
    user_dvd_id = r.get_json()['user_dvd_id']

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.delete(f'/api/dvds/{user_dvd_id}')
    assert r.status_code == 403


def test_remove_dvd_requires_auth(client):
    r = client.delete('/api/dvds/1')
    assert r.status_code == 302


# ---------------------------------------------------------------------------
# Update DVD metadata
# ---------------------------------------------------------------------------

def test_update_dvd_metadata(logged_in_client, app):
    r = _add_dvd(logged_in_client)
    dvd_id = r.get_json()['dvd_id']

    r = logged_in_client.patch(f'/api/dvds/{dvd_id}', json={
        'title': 'Fast Five Extended',
        'director': 'Justin Lin',
        'studio': 'Universal',
        'year': '2011',
        'runtime': 130,
        'rating': 'PG-13',
        'format': 'Blu-ray',
        'genre': 'Action',
    })
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        dvd = db.session.get(DVD, dvd_id)
        assert dvd.title == 'Fast Five Extended'
        assert dvd.runtime == 130
        assert dvd.rating == 'PG-13'


def test_update_dvd_requires_title(logged_in_client):
    r = _add_dvd(logged_in_client)
    dvd_id = r.get_json()['dvd_id']
    r = logged_in_client.patch(f'/api/dvds/{dvd_id}', json={'title': ''})
    assert r.status_code == 400


def test_update_dvd_not_found(logged_in_client):
    r = logged_in_client.patch('/api/dvds/99999', json={'title': 'X'})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Update per-copy details
# ---------------------------------------------------------------------------

def test_update_user_dvd_fields(logged_in_client, app):
    r = _add_dvd(logged_in_client)
    ud_id = r.get_json()['user_dvd_id']

    r = logged_in_client.patch(f'/api/user-dvds/{ud_id}', json={
        'condition': 'like_new',
        'location': 'Living Room Cabinet',
        'notes': 'Case is scratched',
    })
    assert r.status_code == 200

    with app.app_context():
        ud = db.session.get(UserDVD, ud_id)
        assert ud.condition == 'like_new'
        assert ud.location == 'Living Room Cabinet'
        assert ud.notes == 'Case is scratched'


def test_update_user_dvd_ignores_invalid_condition(logged_in_client, app):
    r = _add_dvd(logged_in_client, upc='111222333444')
    ud_id = r.get_json()['user_dvd_id']
    logged_in_client.patch(f'/api/user-dvds/{ud_id}', json={
        'condition': 'not_a_condition', 'location': '', 'notes': ''
    })
    with app.app_context():
        assert db.session.get(UserDVD, ud_id).condition == 'good'


def test_update_user_dvd_not_found(logged_in_client):
    r = logged_in_client.patch('/api/user-dvds/99999', json={'condition': 'good'})
    assert r.status_code == 404


def test_update_user_dvd_other_user_forbidden(app):
    _create_user(app)
    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    ud_id = _add_dvd(admin_client).get_json()['user_dvd_id']

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.patch(f'/api/user-dvds/{ud_id}', json={'condition': 'poor', 'location': '', 'notes': ''})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# DVD loans
# ---------------------------------------------------------------------------

def test_create_dvd_loan(logged_in_client, app):
    ud_id = _add_dvd(logged_in_client).get_json()['user_dvd_id']
    r = logged_in_client.post('/api/dvd-loans', json={'user_dvd_id': ud_id, 'loaned_to': 'Dave'})
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    from app.models import DVDLoan
    with app.app_context():
        loan = DVDLoan.query.filter_by(user_dvd_id=ud_id).first()
        assert loan.loaned_to == 'Dave'
        assert loan.returned_at is None


def test_create_dvd_loan_requires_name(logged_in_client):
    ud_id = _add_dvd(logged_in_client).get_json()['user_dvd_id']
    r = logged_in_client.post('/api/dvd-loans', json={'user_dvd_id': ud_id, 'loaned_to': ''})
    assert r.status_code == 400


def test_create_dvd_loan_stores_notes(logged_in_client, app):
    ud_id = _add_dvd(logged_in_client).get_json()['user_dvd_id']
    logged_in_client.post('/api/dvd-loans', json={
        'user_dvd_id': ud_id, 'loaned_to': 'Dave', 'notes': 'Back by Friday'
    })
    from app.models import DVDLoan
    with app.app_context():
        assert DVDLoan.query.first().notes == 'Back by Friday'


def test_create_dvd_loan_prevents_double_loan(logged_in_client):
    ud_id = _add_dvd(logged_in_client).get_json()['user_dvd_id']
    logged_in_client.post('/api/dvd-loans', json={'user_dvd_id': ud_id, 'loaned_to': 'Dave'})
    r = logged_in_client.post('/api/dvd-loans', json={'user_dvd_id': ud_id, 'loaned_to': 'Mike'})
    assert r.status_code == 409


def test_create_dvd_loan_non_owner_forbidden(app):
    _create_user(app)
    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    ud_id = _add_dvd(admin_client).get_json()['user_dvd_id']

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.post('/api/dvd-loans', json={'user_dvd_id': ud_id, 'loaned_to': 'Dave'})
    assert r.status_code == 403


def test_create_dvd_loan_not_found(logged_in_client):
    r = logged_in_client.post('/api/dvd-loans', json={'user_dvd_id': 99999, 'loaned_to': 'Dave'})
    assert r.status_code == 404


def test_return_dvd_loan(logged_in_client, app):
    ud_id = _add_dvd(logged_in_client).get_json()['user_dvd_id']
    loan_id = logged_in_client.post(
        '/api/dvd-loans', json={'user_dvd_id': ud_id, 'loaned_to': 'Dave'}
    ).get_json()['loan_id']

    r = logged_in_client.patch(f'/api/dvd-loans/{loan_id}/return')
    assert r.status_code == 200

    from app.models import DVDLoan
    with app.app_context():
        assert db.session.get(DVDLoan, loan_id).returned_at is not None


def test_return_dvd_loan_already_returned(logged_in_client):
    ud_id = _add_dvd(logged_in_client, upc='111222333444').get_json()['user_dvd_id']
    loan_id = logged_in_client.post(
        '/api/dvd-loans', json={'user_dvd_id': ud_id, 'loaned_to': 'Dave'}
    ).get_json()['loan_id']
    logged_in_client.patch(f'/api/dvd-loans/{loan_id}/return')
    r = logged_in_client.patch(f'/api/dvd-loans/{loan_id}/return')
    assert r.status_code == 409


def test_return_dvd_loan_not_found(logged_in_client):
    r = logged_in_client.patch('/api/dvd-loans/99999/return')
    assert r.status_code == 404


def test_return_dvd_loan_non_owner_forbidden(app):
    _create_user(app)
    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    ud_id = _add_dvd(admin_client).get_json()['user_dvd_id']
    loan_id = admin_client.post(
        '/api/dvd-loans', json={'user_dvd_id': ud_id, 'loaned_to': 'Dave'}
    ).get_json()['loan_id']

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.patch(f'/api/dvd-loans/{loan_id}/return')
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# DVD scan log
# ---------------------------------------------------------------------------

def test_dvd_scan_log_requires_auth(client):
    r = client.post('/api/dvd-scan-log', json={'upc': '025192310638', 'lookup_status': 'not_found'})
    assert r.status_code == 302


def test_dvd_scan_log_creates_record(logged_in_client, app):
    r = logged_in_client.post('/api/dvd-scan-log', json={
        'upc': '025192310638',
        'lookup_status': 'found_external',
        'add_status': 'added',
        'title': 'Fast Five',
    })
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    from app.models import ScanLog
    with app.app_context():
        log = ScanLog.query.order_by(ScanLog.scanned_at.desc()).first()
        assert log.media_type == 'dvd'
        assert log.isbn == '025192310638'
        assert log.lookup_status == 'found_external'
        assert log.add_status == 'added'
        assert log.book_title == 'Fast Five'
        assert log.user_display_name == 'Admin'
