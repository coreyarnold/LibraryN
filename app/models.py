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

    @property
    def book_count(self):
        return self.user_books.count()

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


class Loan(db.Model):
    __tablename__ = 'loans'

    id = db.Column(db.Integer, primary_key=True)
    user_book_id = db.Column(db.Integer, db.ForeignKey('user_books.id', ondelete='CASCADE'), nullable=False)
    loaned_to = db.Column(db.String(100), nullable=False)
    loaned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    returned_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)

    user_book = db.relationship('UserBook', back_populates='loans')
