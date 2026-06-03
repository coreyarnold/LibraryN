from unittest.mock import MagicMock, patch

from app.extensions import db, bcrypt
from app.models import MusicLoan, MusicRelease, ScanLog, User, UserMusicRelease


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mb_mock(title='Dark Side of the Moon', artist='Pink Floyd'):
    """Minimal MusicBrainz search response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        'releases': [{
            'id': 'test-mbid-123',
            'title': title,
            'date': '1973',
            'artist-credit': [{'artist': {'name': artist}}],
            'label-info':    [{'label': {'name': 'Harvest'}}],
            'media':         [{'format': 'LP', 'track-count': 10}],
        }]
    }
    return resp


def _no_cover():
    resp = MagicMock()
    resp.status_code = 404
    return resp


def _add_music(client, barcode='724356842526', title='Dark Side of the Moon', **kw):
    return client.post('/api/music', json={'barcode': barcode, 'title': title, **kw})


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
# GET /api/music/lookup/<barcode>
# ---------------------------------------------------------------------------

def test_music_lookup_requires_auth(client):
    r = client.get('/api/music/lookup/724356842526')
    assert r.status_code == 302
    assert 'login' in r.headers['Location']


def test_music_lookup_invalid_barcode_letters(logged_in_client):
    r = logged_in_client.get('/api/music/lookup/notabarcode')
    assert r.status_code == 400
    assert 'error' in r.get_json()


def test_music_lookup_invalid_barcode_length(logged_in_client):
    r = logged_in_client.get('/api/music/lookup/123')
    assert r.status_code == 400


def test_music_lookup_returns_local_release(logged_in_client, app):
    with app.app_context():
        user = User.query.first()
        rel = MusicRelease(barcode='724356842526', title='Dark Side of the Moon',
                           artist='Pink Floyd')
        db.session.add(rel)
        db.session.flush()
        db.session.add(UserMusicRelease(user_id=user.id, music_id=rel.id))
        db.session.commit()

    r = logged_in_client.get('/api/music/lookup/724356842526')
    data = r.get_json()
    assert r.status_code == 200
    assert data['in_library'] is True
    assert data['title'] == 'Dark Side of the Moon'
    assert len(data['owners']) == 1


def test_music_lookup_calls_musicbrainz(logged_in_client):
    with patch('app.routes.music_api.requests.get',
               side_effect=[_mb_mock(), _no_cover()]):
        r = logged_in_client.get('/api/music/lookup/724356842526')
    assert r.status_code == 200
    data = r.get_json()
    assert data['title'] == 'Dark Side of the Moon'
    assert data['artist'] == 'Pink Floyd'
    assert data['in_library'] is False


def test_music_lookup_returns_404_when_not_found(logged_in_client):
    no_results = MagicMock()
    no_results.status_code = 200
    no_results.json.return_value = {'releases': []}
    with patch('app.routes.music_api.requests.get', return_value=no_results):
        r = logged_in_client.get('/api/music/lookup/724356842526')
    assert r.status_code == 404


def test_music_lookup_429_returns_429(logged_in_client):
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    with patch('app.routes.music_api.requests.get', return_value=rate_limited):
        r = logged_in_client.get('/api/music/lookup/724356842526')
    assert r.status_code == 429
    assert 'rate limit' in r.get_json()['error'].lower()


# ---------------------------------------------------------------------------
# POST /api/music
# ---------------------------------------------------------------------------

def test_add_music_creates_records(logged_in_client, app):
    r = _add_music(logged_in_client, artist='Pink Floyd', format='LP')
    assert r.status_code == 200
    data = r.get_json()
    assert data['success'] is True

    with app.app_context():
        rel = MusicRelease.query.filter_by(barcode='724356842526').first()
        assert rel is not None
        assert rel.artist == 'Pink Floyd'
        assert UserMusicRelease.query.filter_by(music_id=rel.id).count() == 1


def test_add_music_requires_barcode_and_title(logged_in_client):
    r = logged_in_client.post('/api/music', json={'barcode': '724356842526'})
    assert r.status_code == 400

    r = logged_in_client.post('/api/music', json={'title': 'No Barcode'})
    assert r.status_code == 400


def test_add_music_duplicate_returns_409(logged_in_client):
    _add_music(logged_in_client)
    r = _add_music(logged_in_client)
    assert r.status_code == 409


def test_add_music_reuses_existing_release_record(logged_in_client, app):
    """Two users owning the same barcode share one MusicRelease row."""
    _create_user(app)
    with app.app_context():
        u2_id = User.query.filter_by(username='user2').first().id

    _add_music(logged_in_client)

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = _add_music(c2, user_id=u2_id)
    assert r.status_code == 200

    with app.app_context():
        assert MusicRelease.query.filter_by(barcode='724356842526').count() == 1
        assert UserMusicRelease.query.count() == 2


def test_add_music_requires_auth(client):
    r = client.post('/api/music', json={'barcode': '724356842526', 'title': 'Test'})
    assert r.status_code == 302


def test_non_admin_cannot_add_music_for_other_user(app):
    _create_user(app)
    with app.app_context():
        admin_id = User.query.filter_by(username='admin').first().id

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.post('/api/music', json={
        'barcode': '724356842526', 'title': 'Test', 'user_id': admin_id
    })
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/music/<user_music_id>
# ---------------------------------------------------------------------------

def test_remove_music_deletes_user_record(logged_in_client, app):
    r = _add_music(logged_in_client)
    um_id = r.get_json()['user_music_id']

    r = logged_in_client.delete(f'/api/music/{um_id}')
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        assert db.session.get(UserMusicRelease, um_id) is None


def test_remove_last_owner_cascades_to_release(logged_in_client, app):
    r = _add_music(logged_in_client)
    um_id    = r.get_json()['user_music_id']
    music_id = r.get_json()['music_id']

    logged_in_client.delete(f'/api/music/{um_id}')

    with app.app_context():
        assert db.session.get(MusicRelease, music_id) is None


def test_remove_music_not_found(logged_in_client):
    r = logged_in_client.delete('/api/music/99999')
    assert r.status_code == 404


def test_remove_music_other_user_forbidden(app):
    _create_user(app)
    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    um_id = _add_music(admin_client).get_json()['user_music_id']

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.delete(f'/api/music/{um_id}')
    assert r.status_code == 403


def test_remove_music_requires_auth(client):
    r = client.delete('/api/music/1')
    assert r.status_code == 302


# ---------------------------------------------------------------------------
# PATCH /api/music/<music_id>
# ---------------------------------------------------------------------------

def test_update_music_metadata(logged_in_client, app):
    r = _add_music(logged_in_client)
    music_id = r.get_json()['music_id']

    r = logged_in_client.patch(f'/api/music/{music_id}', json={
        'title':  'The Dark Side of the Moon',
        'artist': 'Pink Floyd',
        'label':  'Harvest',
        'year':   '1973',
        'format': 'LP',
        'track_count': 10,
        'genre':  'Progressive Rock',
    })
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        rel = db.session.get(MusicRelease, music_id)
        assert rel.artist == 'Pink Floyd'
        assert rel.track_count == 10


def test_update_music_requires_title(logged_in_client):
    r = _add_music(logged_in_client)
    music_id = r.get_json()['music_id']
    r = logged_in_client.patch(f'/api/music/{music_id}', json={'title': ''})
    assert r.status_code == 400


def test_update_music_not_found(logged_in_client):
    r = logged_in_client.patch('/api/music/99999', json={'title': 'X'})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/user-music/<user_music_id>
# ---------------------------------------------------------------------------

def test_update_user_music_fields(logged_in_client, app):
    um_id = _add_music(logged_in_client).get_json()['user_music_id']

    r = logged_in_client.patch(f'/api/user-music/{um_id}', json={
        'condition': 'like_new',
        'location':  'Record Cabinet',
        'notes':     'Original pressing',
    })
    assert r.status_code == 200

    with app.app_context():
        um = db.session.get(UserMusicRelease, um_id)
        assert um.condition == 'like_new'
        assert um.location  == 'Record Cabinet'
        assert um.notes     == 'Original pressing'


def test_update_user_music_ignores_invalid_condition(logged_in_client, app):
    um_id = _add_music(logged_in_client, barcode='111222333444').get_json()['user_music_id']
    logged_in_client.patch(f'/api/user-music/{um_id}',
                           json={'condition': 'mint_perfect', 'location': '', 'notes': ''})
    with app.app_context():
        assert db.session.get(UserMusicRelease, um_id).condition == 'good'


def test_update_user_music_not_found(logged_in_client):
    r = logged_in_client.patch('/api/user-music/99999', json={'condition': 'good'})
    assert r.status_code == 404


def test_update_user_music_other_user_forbidden(app):
    _create_user(app)
    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    um_id = _add_music(admin_client).get_json()['user_music_id']

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.patch(f'/api/user-music/{um_id}',
                 json={'condition': 'poor', 'location': '', 'notes': ''})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Music loans
# ---------------------------------------------------------------------------

def test_create_music_loan(logged_in_client, app):
    um_id = _add_music(logged_in_client).get_json()['user_music_id']
    r = logged_in_client.post('/api/music-loans',
                              json={'user_music_id': um_id, 'loaned_to': 'Sarah'})
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        loan = MusicLoan.query.filter_by(user_music_id=um_id).first()
        assert loan.loaned_to == 'Sarah'
        assert loan.returned_at is None


def test_create_music_loan_requires_name(logged_in_client):
    um_id = _add_music(logged_in_client, barcode='111222333444').get_json()['user_music_id']
    r = logged_in_client.post('/api/music-loans',
                              json={'user_music_id': um_id, 'loaned_to': ''})
    assert r.status_code == 400


def test_create_music_loan_stores_notes(logged_in_client, app):
    um_id = _add_music(logged_in_client, barcode='111222333444').get_json()['user_music_id']
    logged_in_client.post('/api/music-loans',
                          json={'user_music_id': um_id, 'loaned_to': 'Mike',
                                'notes': 'Handle with care'})
    with app.app_context():
        assert MusicLoan.query.first().notes == 'Handle with care'


def test_create_music_loan_prevents_double_loan(logged_in_client):
    um_id = _add_music(logged_in_client, barcode='111222333444').get_json()['user_music_id']
    logged_in_client.post('/api/music-loans',
                          json={'user_music_id': um_id, 'loaned_to': 'Sarah'})
    r = logged_in_client.post('/api/music-loans',
                              json={'user_music_id': um_id, 'loaned_to': 'Mike'})
    assert r.status_code == 409


def test_create_music_loan_non_owner_forbidden(app):
    _create_user(app)
    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    um_id = _add_music(admin_client).get_json()['user_music_id']

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.post('/api/music-loans',
                json={'user_music_id': um_id, 'loaned_to': 'Sarah'})
    assert r.status_code == 403


def test_create_music_loan_not_found(logged_in_client):
    r = logged_in_client.post('/api/music-loans',
                              json={'user_music_id': 99999, 'loaned_to': 'Sarah'})
    assert r.status_code == 404


def test_return_music_loan(logged_in_client, app):
    um_id = _add_music(logged_in_client).get_json()['user_music_id']
    loan_id = logged_in_client.post(
        '/api/music-loans', json={'user_music_id': um_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']

    r = logged_in_client.patch(f'/api/music-loans/{loan_id}/return')
    assert r.status_code == 200

    with app.app_context():
        assert db.session.get(MusicLoan, loan_id).returned_at is not None


def test_return_music_loan_already_returned(logged_in_client):
    um_id = _add_music(logged_in_client, barcode='111222333444').get_json()['user_music_id']
    loan_id = logged_in_client.post(
        '/api/music-loans', json={'user_music_id': um_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']
    logged_in_client.patch(f'/api/music-loans/{loan_id}/return')
    r = logged_in_client.patch(f'/api/music-loans/{loan_id}/return')
    assert r.status_code == 409


def test_return_music_loan_not_found(logged_in_client):
    r = logged_in_client.patch('/api/music-loans/99999/return')
    assert r.status_code == 404


def test_borrower_can_return_music_loan(app):
    """The named borrower (a family member) can mark a music loan returned."""
    _create_user(app, username='sarah')

    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    um_id = _add_music(admin_client).get_json()['user_music_id']
    loan_id = admin_client.post(
        '/api/music-loans', json={'user_music_id': um_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']

    sarah = app.test_client()
    sarah.post('/login', data={'username': 'sarah', 'password': 'pass123'})
    r = sarah.patch(f'/api/music-loans/{loan_id}/return')
    assert r.status_code == 200


def test_unrelated_user_cannot_return_music_loan(app):
    _create_user(app)
    admin_client = app.test_client()
    admin_client.post('/login', data={'username': 'admin', 'password': 'changeme'})
    um_id = _add_music(admin_client).get_json()['user_music_id']
    loan_id = admin_client.post(
        '/api/music-loans', json={'user_music_id': um_id, 'loaned_to': 'Sarah'}
    ).get_json()['loan_id']

    c2 = app.test_client()
    c2.post('/login', data={'username': 'user2', 'password': 'pass123'})
    r = c2.patch(f'/api/music-loans/{loan_id}/return')
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Music scan log
# ---------------------------------------------------------------------------

def test_music_scan_log_requires_auth(client):
    r = client.post('/api/music-scan-log',
                    json={'barcode': '724356842526', 'lookup_status': 'not_found'})
    assert r.status_code == 302


def test_music_scan_log_creates_record(logged_in_client, app):
    r = logged_in_client.post('/api/music-scan-log', json={
        'barcode':       '724356842526',
        'lookup_status': 'found_external',
        'add_status':    'added',
        'title':         'Dark Side of the Moon',
    })
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    with app.app_context():
        log = ScanLog.query.order_by(ScanLog.scanned_at.desc()).first()
        assert log.media_type      == 'music'
        assert log.isbn            == '724356842526'
        assert log.lookup_status   == 'found_external'
        assert log.add_status      == 'added'
        assert log.book_title      == 'Dark Side of the Moon'
        assert log.user_display_name == 'Admin'
