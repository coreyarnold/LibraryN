import os
import tempfile
import pytest

from app.config import Config
from app import create_app


ADMIN_USER = 'admin'
ADMIN_PASS = 'changeme'


@pytest.fixture()
def app():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(db_fd)

    orig_uri = Config.SQLALCHEMY_DATABASE_URI
    Config.SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'

    flask_app = create_app()
    flask_app.config['TESTING'] = True

    yield flask_app

    from app.extensions import db
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()

    Config.SQLALCHEMY_DATABASE_URI = orig_uri
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def logged_in_client(client):
    client.post('/login', data={'username': ADMIN_USER, 'password': ADMIN_PASS})
    return client
