import hashlib
from datetime import datetime
from flask_login import UserMixin
from .extensions import db

USER_COLORS = [
    '#6c5ce7', '#00b894', '#e17055', '#0984e3',
    '#fd79a8', '#fdcb6e', '#00cec9', '#a29bfe',
]


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254))
    goodreads_user_id = db.Column(db.String(50))
    color = db.Column(db.String(7), default='#6c5ce7')
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_books = db.relationship('UserBook', back_populates='user', lazy='dynamic', cascade='all, delete-orphan')
    user_dvds   = db.relationship('UserDVD',          back_populates='user', lazy='dynamic', cascade='all, delete-orphan')
    user_music  = db.relationship('UserMusicRelease', back_populates='user', lazy='dynamic', cascade='all, delete-orphan')
    borrows     = db.relationship('Borrow',           back_populates='user', order_by='Borrow.borrowed_at', cascade='all, delete-orphan')

    @property
    def book_count(self):
        return self.user_books.count()

    @property
    def dvd_count(self):
        return self.user_dvds.count()

    @property
    def music_count(self):
        return self.user_music.count()

    @property
    def media_count(self):
        return self.user_books.count() + self.user_dvds.count() + self.user_music.count()

    @property
    def gravatar_url(self):
        if not self.email:
            return None
        h = hashlib.md5(self.email.strip().lower().encode()).hexdigest()
        return f'https://www.gravatar.com/avatar/{h}?s=200&d=404'


class Book(db.Model):
    __tablename__ = 'books'

    id = db.Column(db.Integer, primary_key=True)
    isbn = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(500), nullable=False)
    author = db.Column(db.String(500))
    publisher = db.Column(db.String(255))
    published_year = db.Column(db.String(10))
    description = db.Column(db.Text)
    cover_url = db.Column(db.String(1000))
    page_count = db.Column(db.Integer)
    genre = db.Column(db.String(255))
    language = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_books = db.relationship('UserBook', back_populates='book', lazy='dynamic', cascade='all, delete-orphan')


class UserBook(db.Model):
    __tablename__ = 'user_books'
    __table_args__ = (db.UniqueConstraint('user_id', 'book_id', name='uq_user_book'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    condition = db.Column(db.String(20), default='good')
    notes = db.Column(db.Text)
    location = db.Column(db.String(255))
    reading_status = db.Column(db.String(20))
    goodreads_rating = db.Column(db.Integer)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='user_books')
    book = db.relationship('Book', back_populates='user_books')
    loans = db.relationship('Loan', back_populates='user_book',
                            order_by='Loan.loaned_at.desc()',
                            cascade='all, delete-orphan')

    @property
    def active_loan(self):
        return next((l for l in self.loans if l.returned_at is None), None)

    CONDITIONS = ['new', 'like_new', 'very_good', 'good', 'acceptable', 'poor']
    CONDITION_LABELS = {
        'new': 'New',
        'like_new': 'Like New',
        'very_good': 'Very Good',
        'good': 'Good',
        'acceptable': 'Acceptable',
        'poor': 'Poor',
    }
    READING_STATUSES = {
        'read': 'Read',
        'currently-reading': 'Reading',
        'to-read': 'Want to Read',
    }


class DVD(db.Model):
    __tablename__ = 'dvds'

    id = db.Column(db.Integer, primary_key=True)
    upc = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(500), nullable=False)
    director = db.Column(db.String(500))
    studio = db.Column(db.String(255))
    year = db.Column(db.String(10))
    runtime = db.Column(db.Integer)       # minutes
    rating = db.Column(db.String(20))     # G / PG / PG-13 / R / etc.
    genre = db.Column(db.String(255))
    description = db.Column(db.Text)
    cover_url = db.Column(db.String(1000))
    format = db.Column(db.String(20))     # DVD / Blu-ray / 4K
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_dvds = db.relationship('UserDVD', back_populates='dvd', lazy='dynamic', cascade='all, delete-orphan')


class UserDVD(db.Model):
    __tablename__ = 'user_dvds'
    __table_args__ = (db.UniqueConstraint('user_id', 'dvd_id', name='uq_user_dvd'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    dvd_id = db.Column(db.Integer, db.ForeignKey('dvds.id'), nullable=False)
    condition = db.Column(db.String(20), default='good')
    notes = db.Column(db.Text)
    location = db.Column(db.String(255))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='user_dvds')
    dvd = db.relationship('DVD', back_populates='user_dvds')
    loans = db.relationship('DVDLoan', back_populates='user_dvd',
                            order_by='DVDLoan.loaned_at.desc()',
                            cascade='all, delete-orphan')

    @property
    def active_loan(self):
        return next((l for l in self.loans if l.returned_at is None), None)

    CONDITIONS = ['new', 'like_new', 'very_good', 'good', 'acceptable', 'poor']
    CONDITION_LABELS = {
        'new': 'New', 'like_new': 'Like New', 'very_good': 'Very Good',
        'good': 'Good', 'acceptable': 'Acceptable', 'poor': 'Poor',
    }


class DVDLoan(db.Model):
    __tablename__ = 'dvd_loans'

    id = db.Column(db.Integer, primary_key=True)
    user_dvd_id = db.Column(db.Integer, db.ForeignKey('user_dvds.id', ondelete='CASCADE'), nullable=False)
    loaned_to = db.Column(db.String(100), nullable=False)
    loaned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    returned_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)

    user_dvd = db.relationship('UserDVD', back_populates='loans')


class MusicRelease(db.Model):
    __tablename__ = 'music_releases'

    id          = db.Column(db.Integer, primary_key=True)
    barcode     = db.Column(db.String(20), unique=True, nullable=False)
    title       = db.Column(db.String(500), nullable=False)
    artist      = db.Column(db.String(500))
    label       = db.Column(db.String(255))
    year        = db.Column(db.String(10))
    format      = db.Column(db.String(50))    # CD / LP / EP / Single / etc.
    track_count = db.Column(db.Integer)
    genre       = db.Column(db.String(255))
    cover_url   = db.Column(db.String(1000))
    mbid        = db.Column(db.String(36))    # MusicBrainz release ID
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    user_music = db.relationship('UserMusicRelease', back_populates='music',
                                  lazy='dynamic', cascade='all, delete-orphan')


class UserMusicRelease(db.Model):
    __tablename__ = 'user_music'
    __table_args__ = (db.UniqueConstraint('user_id', 'music_id', name='uq_user_music'),)

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    music_id   = db.Column(db.Integer, db.ForeignKey('music_releases.id'), nullable=False)
    condition  = db.Column(db.String(20), default='good')
    notes      = db.Column(db.Text)
    location   = db.Column(db.String(255))
    added_at   = db.Column(db.DateTime, default=datetime.utcnow)

    user  = db.relationship('User', back_populates='user_music')
    music = db.relationship('MusicRelease', back_populates='user_music')
    loans = db.relationship('MusicLoan', back_populates='user_music',
                             order_by='MusicLoan.loaned_at.desc()',
                             cascade='all, delete-orphan')

    @property
    def active_loan(self):
        return next((l for l in self.loans if l.returned_at is None), None)

    CONDITIONS = ['new', 'like_new', 'very_good', 'good', 'acceptable', 'poor']
    CONDITION_LABELS = {
        'new': 'New', 'like_new': 'Like New', 'very_good': 'Very Good',
        'good': 'Good', 'acceptable': 'Acceptable', 'poor': 'Poor',
    }


class MusicLoan(db.Model):
    __tablename__ = 'music_loans'

    id            = db.Column(db.Integer, primary_key=True)
    user_music_id = db.Column(db.Integer, db.ForeignKey('user_music.id', ondelete='CASCADE'), nullable=False)
    loaned_to     = db.Column(db.String(100), nullable=False)
    loaned_at     = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    returned_at   = db.Column(db.DateTime)
    notes         = db.Column(db.Text)

    user_music = db.relationship('UserMusicRelease', back_populates='loans')


class ScanLog(db.Model):
    __tablename__ = 'scan_logs'

    id = db.Column(db.Integer, primary_key=True)
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    # Denormalized so records survive user/book/dvd deletion
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    user_display_name = db.Column(db.String(100))
    media_type = db.Column(db.String(10), default='book')   # 'book' | 'dvd' | 'music'
    isbn = db.Column(db.String(20))                          # UPC/barcode for DVDs & music
    # found_local | found_external | not_found | invalid | error | rate_limited
    lookup_status = db.Column(db.String(20))
    # added | already_owned | error | NULL (lookup failed, no add attempted)
    add_status = db.Column(db.String(20))
    book_id  = db.Column(db.Integer, db.ForeignKey('books.id',          ondelete='SET NULL'))
    dvd_id   = db.Column(db.Integer, db.ForeignKey('dvds.id',           ondelete='SET NULL'))
    music_id = db.Column(db.Integer, db.ForeignKey('music_releases.id', ondelete='SET NULL'))
    book_title = db.Column(db.String(500))                   # title for any media type
    error_detail = db.Column(db.Text)

    user  = db.relationship('User',         foreign_keys=[user_id])
    book  = db.relationship('Book',         foreign_keys=[book_id])
    dvd   = db.relationship('DVD',          foreign_keys=[dvd_id])
    music = db.relationship('MusicRelease', foreign_keys=[music_id])


class ScanRetryQueue(db.Model):
    """Scans that were rate-limited and need to be retried server-side."""
    __tablename__ = 'scan_retry_queue'

    DELAYS = [45, 90, 180]   # seconds before attempt 1, 2, 3
    MAX_ATTEMPTS = 3

    id                       = db.Column(db.Integer, primary_key=True)
    created_at               = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    media_type               = db.Column(db.String(10), nullable=False)   # 'book' | 'dvd'
    identifier               = db.Column(db.String(20), nullable=False)   # ISBN or UPC
    for_user_id              = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    requested_by_id          = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    requested_by_display_name= db.Column(db.String(100))                  # denormalized
    condition                = db.Column(db.String(20), default='good')
    location                 = db.Column(db.String(255), default='')
    attempt                  = db.Column(db.Integer, default=0, nullable=False)
    next_retry_at            = db.Column(db.DateTime, nullable=False, index=True)
    completed_at             = db.Column(db.DateTime)
    succeeded                = db.Column(db.Boolean)
    result_message           = db.Column(db.Text)

    for_user      = db.relationship('User', foreign_keys=[for_user_id])
    requested_by  = db.relationship('User', foreign_keys=[requested_by_id])


class Borrow(db.Model):
    """An item a user has borrowed from someone else (not necessarily in the library)."""
    __tablename__ = 'borrows'

    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title         = db.Column(db.String(500), nullable=False)
    borrowed_from = db.Column(db.String(100), nullable=False)
    borrowed_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    returned_at   = db.Column(db.DateTime)
    notes         = db.Column(db.Text)

    user = db.relationship('User', back_populates='borrows')


class Loan(db.Model):
    __tablename__ = 'loans'

    id = db.Column(db.Integer, primary_key=True)
    user_book_id = db.Column(db.Integer, db.ForeignKey('user_books.id', ondelete='CASCADE'), nullable=False)
    loaned_to = db.Column(db.String(100), nullable=False)
    loaned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    returned_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)

    user_book = db.relationship('UserBook', back_populates='loans')
