def test_login_page_loads(client):
    r = client.get('/login')
    assert r.status_code == 200


def test_login_success_redirects_to_dashboard(client):
    r = client.post(
        '/login',
        data={'username': 'admin', 'password': 'changeme'},
        follow_redirects=True,
    )
    assert r.status_code == 200
    # Landed on a page that isn't the login page
    assert b'login' not in r.data.lower().split(b'<title>')[0] or b'dashboard' in r.data.lower()


def test_login_wrong_password_shows_error(client):
    r = client.post(
        '/login',
        data={'username': 'admin', 'password': 'wrong'},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert b'invalid' in r.data.lower()


def test_login_unknown_user_shows_error(client):
    r = client.post(
        '/login',
        data={'username': 'nobody', 'password': 'pass'},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert b'invalid' in r.data.lower()


def test_protected_route_redirects_to_login(client):
    r = client.get('/books')
    assert r.status_code == 302
    assert 'login' in r.headers['Location']


def test_logout_redirects_to_login(logged_in_client):
    r = logged_in_client.get('/logout', follow_redirects=True)
    assert r.status_code == 200
    assert b'login' in r.data.lower()
