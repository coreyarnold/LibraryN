import os
from flask import Flask
from .config import Config
from .extensions import db, login_manager, bcrypt


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'warning'

    from .routes.auth import auth_bp
    from .routes.books import books_bp
    from .routes.api import api_bp
    from .routes.users import users_bp
    from .routes.dvds import dvds_bp
    from .routes.dvd_api import dvd_api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(books_bp)
    app.register_blueprint(dvds_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(dvd_api_bp, url_prefix='/api')
    app.register_blueprint(users_bp, url_prefix='/users')

    app.config['COVERS_DIR'] = os.environ.get(
        'COVERS_DIR', os.path.join(app.instance_path, 'covers')
    )

    with app.app_context():
        db.create_all()
        _migrate()
        _seed_admin()

    return app


def _migrate():
    """Add columns that don't exist yet (no-op on fresh installs)."""
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(db.engine)
    existing_tables = inspector.get_table_names()

    user_cols = {col['name'] for col in inspector.get_columns('users')}
    ub_cols   = {col['name'] for col in inspector.get_columns('user_books')}
    sl_cols   = ({col['name'] for col in inspector.get_columns('scan_logs')}
                 if 'scan_logs' in existing_tables else set())

    with db.engine.connect() as conn:
        if 'email' not in user_cols:
            conn.execute(db.text('ALTER TABLE users ADD COLUMN email VARCHAR(254)'))
        if 'goodreads_user_id' not in user_cols:
            conn.execute(db.text('ALTER TABLE users ADD COLUMN goodreads_user_id VARCHAR(50)'))
        if 'reading_status' not in ub_cols:
            conn.execute(db.text('ALTER TABLE user_books ADD COLUMN reading_status VARCHAR(20)'))
        if 'goodreads_rating' not in ub_cols:
            conn.execute(db.text('ALTER TABLE user_books ADD COLUMN goodreads_rating INTEGER'))
        # DVD-era additions to scan_logs
        if sl_cols and 'media_type' not in sl_cols:
            conn.execute(db.text("ALTER TABLE scan_logs ADD COLUMN media_type VARCHAR(10) DEFAULT 'book'"))
        if sl_cols and 'dvd_id' not in sl_cols:
            conn.execute(db.text('ALTER TABLE scan_logs ADD COLUMN dvd_id INTEGER'))
        conn.commit()


def _seed_admin():
    from .models import User
    from .config import Config

    if User.query.count() == 0:
        admin = User(
            username=Config.ADMIN_USERNAME,
            display_name=Config.ADMIN_DISPLAY_NAME,
            password_hash=bcrypt.generate_password_hash(Config.ADMIN_PASSWORD).decode('utf-8'),
            is_admin=True,
            color='#6c5ce7',
        )
        db.session.add(admin)
        db.session.commit()
