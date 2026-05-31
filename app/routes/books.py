from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import or_
from ..extensions import db
from ..models import User, Book, UserBook

books_bp = Blueprint('books', __name__)


@books_bp.route('/dashboard')
@login_required
def dashboard():
    users = User.query.order_by(User.display_name).all()
    filter_user_id = request.args.get('user_id', type=int)

    query = (
        db.session.query(UserBook)
        .join(Book)
        .join(User)
        .order_by(UserBook.added_at.desc())
    )
    if filter_user_id:
        query = query.filter(UserBook.user_id == filter_user_id)

    user_books = query.limit(60).all()
    total_books = UserBook.query.count()
    unique_books = Book.query.count()

    return render_template(
        'dashboard.html',
        users=users,
        user_books=user_books,
        filter_user_id=filter_user_id,
        total_books=total_books,
        unique_books=unique_books,
    )


@books_bp.route('/books')
@login_required
def index():
    search = request.args.get('q', '').strip()
    filter_user_id = request.args.get('user_id', type=int)
    page = request.args.get('page', 1, type=int)
    users = User.query.order_by(User.display_name).all()

    query = (
        db.session.query(UserBook)
        .join(Book)
        .join(User)
        .order_by(Book.title)
    )

    if search:
        query = query.filter(
            or_(
                Book.title.ilike(f'%{search}%'),
                Book.author.ilike(f'%{search}%'),
                Book.isbn.ilike(f'%{search}%'),
            )
        )
    if filter_user_id:
        query = query.filter(UserBook.user_id == filter_user_id)

    pagination = query.paginate(page=page, per_page=25, error_out=False)

    return render_template(
        'books/index.html',
        pagination=pagination,
        users=users,
        search=search,
        filter_user_id=filter_user_id,
    )


@books_bp.route('/books/<int:book_id>')
@login_required
def detail(book_id):
    book = db.session.get(Book, book_id)
    if not book:
        abort(404)
    user_books = (
        UserBook.query
        .filter_by(book_id=book_id)
        .join(User)
        .order_by(User.display_name)
        .all()
    )
    return render_template('books/detail.html', book=book, user_books=user_books)


@books_bp.route('/scan')
@login_required
def scan():
    users = User.query.order_by(User.display_name).all()
    return render_template('books/scan.html', users=users)


@books_bp.route('/import')
@login_required
def import_books():
    users = User.query.order_by(User.display_name).all()
    return render_template('books/import.html', users=users)
