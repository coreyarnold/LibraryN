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

    @app.cli.command('backfill-dvd-metadata')
    def backfill_dvd_metadata():
        """Fill in missing DVD metadata (director, runtime, rating, etc.) via OMDb."""
        import time
        from .covers import fetch_and_store
        from .models import DVD
        from .routes.dvd_api import _lookup_omdb, _clean_title

        if not os.environ.get('OMDB_API_KEY'):
            print('OMDB_API_KEY is not set.')
            print('Get a free key at https://www.omdbapi.com/apikey.aspx')
            print('Then run:  OMDB_API_KEY=your_key flask backfill-dvd-metadata')
            return

        dvds = DVD.query.filter(
            db.or_(DVD.director.is_(None), DVD.director == '')
        ).all()

        if not dvds:
            print('All DVDs already have director info.')
            return

        width = len(str(len(dvds)))
        print(f'Enriching {len(dvds)} DVD(s) via OMDb…\n')
        ok = fail = 0

        for i, dvd in enumerate(dvds, 1):
            searched = _clean_title(dvd.title)
            meta = _lookup_omdb(dvd.title)
            if meta:
                # Only write fields that are currently blank — never overwrite manual edits
                for field in ('director', 'studio', 'year', 'rating', 'genre', 'description'):
                    if meta.get(field) and not getattr(dvd, field):
                        setattr(dvd, field, meta[field])
                if meta.get('runtime') and not dvd.runtime:
                    dvd.runtime = meta['runtime']
                # Upgrade cover: use OMDb's poster if we don't already have a local copy
                if meta.get('cover_url') and not (dvd.cover_url or '').startswith('/covers/'):
                    local = fetch_and_store(meta['cover_url'], dvd.upc)
                    if local:
                        dvd.cover_url = local
                ok += 1
                status = '✓'
            else:
                fail += 1
                status = '✗'

            # Always show what was actually sent to OMDb; show original if it was cleaned
            if searched != dvd.title:
                title_line = f'"{searched}"  (was: "{dvd.title}")'
            else:
                title_line = f'"{searched}"'
            print(f'  [{i:{width}}/{len(dvds)}] {status}  {title_line}')

            if i % 20 == 0:
                db.session.commit()
            time.sleep(0.2)

        db.session.commit()
        print(f'\nDone: {ok} enriched, {fail} not found on OMDb.')

    @app.cli.command('backfill-covers')
    def backfill_covers():
        """Download and store cover images for all books/DVDs that still point to external URLs."""
        import time
        from .covers import fetch_and_store
        from .models import Book, DVD

        books = Book.query.filter(
            Book.cover_url.isnot(None),
            Book.cover_url != '',
            ~Book.cover_url.like('/covers/%'),
        ).all()

        dvds = DVD.query.filter(
            DVD.cover_url.isnot(None),
            DVD.cover_url != '',
            ~DVD.cover_url.like('/covers/%'),
        ).all()

        items = [('BOOK', b, b.isbn, b.title) for b in books] + \
                [('DVD',  d, d.upc,  d.title) for d in dvds]

        if not items:
            print('Nothing to backfill — all covers are already stored locally.')
            return

        width = len(str(len(items)))
        print(f'Backfilling {len(items)} cover image(s)…\n')
        ok = fail = 0

        for i, (kind, record, identifier, title) in enumerate(items, 1):
            local = fetch_and_store(record.cover_url, identifier)
            if local:
                record.cover_url = local
                ok += 1
                status = '✓'
            else:
                fail += 1
                status = '✗'
            print(f'  [{i:{width}}/{len(items)}] {status} {kind:<4}  {title[:60]}')

            if i % 20 == 0:
                db.session.commit()
            time.sleep(0.15)

        db.session.commit()
        print(f'\nDone: {ok} stored, {fail} failed.')

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
