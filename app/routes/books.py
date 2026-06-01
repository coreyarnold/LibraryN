from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import or_
from ..extensions import db
from ..models import User, Book, UserBook, Loan, ScanLog, DVDLoan, UserDVD, DVD

books_bp = Blueprint('books', __name__)


@books_bp.route('/dashboard')
@login_required
def dashboard():
    users = User.query.order_by(User.display_name).all()
    filter_user_id = request.args.get('user_id', type=int)

    book_q = db.session.query(UserBook).join(Book).join(User).order_by(UserBook.added_at.desc())
    dvd_q  = db.session.query(UserDVD).join(DVD).join(User).order_by(UserDVD.added_at.desc())

    if filter_user_id:
        book_q = book_q.filter(UserBook.user_id == filter_user_id)
        dvd_q  = dvd_q.filter(UserDVD.user_id  == filter_user_id)

    # Merge and sort most-recent-first, cap at 60
    items = sorted(
        [('book', ub) for ub in book_q.all()] +
        [('dvd',  ud) for ud in dvd_q.all()],
        key=lambda x: x[1].added_at,
        reverse=True,
    )[:60]

    total_copies  = UserBook.query.count() + UserDVD.query.count()
    unique_titles = Book.query.count()     + DVD.query.count()

    return render_template(
        'dashboard.html',
        users=users,
        items=items,
        filter_user_id=filter_user_id,
        total_copies=total_copies,
        unique_titles=unique_titles,
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
    return render_template('books/detail.html', book=book, user_books=user_books, now=datetime.utcnow())


@books_bp.route('/scan')
@login_required
def scan():
    users = User.query.order_by(User.display_name).all()
    return render_template('books/scan.html', users=users)


@books_bp.route('/loans')
@login_required
def loans():
    book_q = (
        db.session.query(Loan)
        .join(UserBook).join(Book).join(User)
        .filter(Loan.returned_at.is_(None))
        .order_by(Loan.loaned_at)
    )
    dvd_q = (
        db.session.query(DVDLoan)
        .join(UserDVD).join(DVD).join(User)
        .filter(DVDLoan.returned_at.is_(None))
        .order_by(DVDLoan.loaned_at)
    )
    if not current_user.is_admin:
        book_q = book_q.filter(UserBook.user_id == current_user.id)
        dvd_q  = dvd_q.filter(UserDVD.user_id  == current_user.id)
    return render_template('books/loans.html',
                           book_loans=book_q.all(),
                           dvd_loans=dvd_q.all(),
                           now=datetime.utcnow())


@books_bp.route('/audit')
@login_required
def audit():
    if not current_user.is_admin:
        abort(403)

    page        = request.args.get('page', 1, type=int)
    user_filter = request.args.get('user_id', type=int)
    status_filter = request.args.get('status', '')

    query = ScanLog.query.order_by(ScanLog.scanned_at.desc())
    if user_filter:
        query = query.filter(ScanLog.user_id == user_filter)
    if status_filter == 'added':
        query = query.filter(ScanLog.add_status == 'added')
    elif status_filter == 'already_owned':
        query = query.filter(ScanLog.add_status == 'already_owned')
    elif status_filter == 'not_found':
        query = query.filter(ScanLog.lookup_status == 'not_found')
    elif status_filter == 'error':
        query = query.filter(
            db.or_(ScanLog.lookup_status.in_(['invalid', 'error']),
                   ScanLog.add_status == 'error')
        )

    pagination = query.paginate(page=page, per_page=50, error_out=False)
    users = User.query.order_by(User.display_name).all()

    total      = ScanLog.query.count()
    added      = ScanLog.query.filter_by(add_status='added').count()
    not_found  = ScanLog.query.filter_by(lookup_status='not_found').count()
    errors     = ScanLog.query.filter(
        db.or_(ScanLog.lookup_status.in_(['invalid', 'error']),
               ScanLog.add_status == 'error')
    ).count()

    return render_template(
        'books/audit.html',
        pagination=pagination,
        users=users,
        user_filter=user_filter,
        status_filter=status_filter,
        stats={'total': total, 'added': added, 'not_found': not_found, 'errors': errors},
    )


@books_bp.route('/import')
@login_required
def import_books():
    users = User.query.order_by(User.display_name).all()
    return render_template('books/import.html', users=users)
