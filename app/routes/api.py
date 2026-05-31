import requests
import xml.etree.ElementTree as ET
from io import BytesIO
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from ..extensions import db
from ..models import User, Book, UserBook

api_bp = Blueprint('api', __name__)

GOOGLE_BOOKS_URL = 'https://www.googleapis.com/books/v1/volumes'
OPEN_LIBRARY_URL = 'https://openlibrary.org/isbn/{isbn}.json'
OPEN_LIBRARY_COVERS = 'https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg'


def _lookup_google_books(isbn):
    try:
        r = requests.get(GOOGLE_BOOKS_URL, params={'q': f'isbn:{isbn}'}, timeout=5)
        r.raise_for_status()
        data = r.json()
        if data.get('totalItems', 0) == 0:
            return None
        info = data['items'][0]['volumeInfo']
        return {
            'isbn': isbn,
            'title': info.get('title', 'Unknown Title'),
            'author': ', '.join(info.get('authors', [])),
            'publisher': info.get('publisher', ''),
            'published_year': (info.get('publishedDate', '') or '')[:4],
            'description': info.get('description', ''),
            'cover_url': (info.get('imageLinks', {}).get('thumbnail', '') or '').replace('http://', 'https://'),
            'page_count': info.get('pageCount'),
            'genre': ', '.join(info.get('categories', [])),
            'language': info.get('language', ''),
        }
    except Exception:
        return None


def _lookup_open_library(isbn):
    try:
        r = requests.get(OPEN_LIBRARY_URL.format(isbn=isbn), timeout=5)
        if r.status_code != 200:
            return None
        data = r.json()
        authors = []
        for a in data.get('authors', []):
            key = a.get('key', '')
            if key:
                ar = requests.get(f'https://openlibrary.org{key}.json', timeout=3)
                if ar.status_code == 200:
                    authors.append(ar.json().get('name', ''))
        return {
            'isbn': isbn,
            'title': data.get('title', 'Unknown Title'),
            'author': ', '.join(authors),
            'publisher': ', '.join(data.get('publishers', [])),
            'published_year': str(data.get('publish_date', ''))[:4],
            'description': '',
            'cover_url': OPEN_LIBRARY_COVERS.format(isbn=isbn),
            'page_count': data.get('number_of_pages'),
            'genre': '',
            'language': '',
        }
    except Exception:
        return None


@api_bp.route('/lookup/<isbn>')
@login_required
def lookup(isbn):
    isbn = isbn.strip().replace('-', '').replace(' ', '')
    if not isbn.isdigit() or len(isbn) not in (10, 13):
        return jsonify({'error': 'Invalid ISBN format. Must be 10 or 13 digits.'}), 400

    existing = Book.query.filter_by(isbn=isbn).first()
    if existing:
        owners = [
            {'id': ub.user_id, 'name': ub.user.display_name, 'color': ub.user.color}
            for ub in existing.user_books
        ]
        return jsonify({
            'in_library': True,
            'id': existing.id,
            'isbn': existing.isbn,
            'title': existing.title,
            'author': existing.author,
            'publisher': existing.publisher,
            'published_year': existing.published_year,
            'cover_url': existing.cover_url,
            'page_count': existing.page_count,
            'genre': existing.genre,
            'owners': owners,
        })

    book_data = _lookup_google_books(isbn) or _lookup_open_library(isbn)
    if not book_data:
        return jsonify({'error': 'Book not found. You can add it manually below.'}), 404

    book_data['in_library'] = False
    return jsonify(book_data)


@api_bp.route('/books', methods=['POST'])
@login_required
def add_book():
    data = request.get_json(force=True)
    isbn = (data.get('isbn') or '').strip()
    title = (data.get('title') or '').strip()
    user_id = data.get('user_id') or current_user.id

    if not isbn or not title:
        return jsonify({'error': 'ISBN and title are required.'}), 400

    if not current_user.is_admin and int(user_id) != current_user.id:
        return jsonify({'error': 'Only admins can add books for other users.'}), 403

    target_user = db.session.get(User, user_id)
    if not target_user:
        return jsonify({'error': 'User not found.'}), 404

    book = Book.query.filter_by(isbn=isbn).first()
    if not book:
        book = Book(
            isbn=isbn,
            title=title,
            author=data.get('author', ''),
            publisher=data.get('publisher', ''),
            published_year=data.get('published_year', ''),
            description=data.get('description', ''),
            cover_url=data.get('cover_url', ''),
            page_count=data.get('page_count'),
            genre=data.get('genre', ''),
            language=data.get('language', ''),
        )
        db.session.add(book)
        db.session.flush()

    existing_ub = UserBook.query.filter_by(user_id=user_id, book_id=book.id).first()
    if existing_ub:
        return jsonify({'error': f'{target_user.display_name} already owns this book.'}), 409

    user_book = UserBook(
        user_id=user_id,
        book_id=book.id,
        condition=data.get('condition', 'good'),
        notes=data.get('notes', ''),
        location=data.get('location', ''),
    )
    db.session.add(user_book)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Database error. Book may already exist for this user.'}), 409

    return jsonify({
        'success': True,
        'book_id': book.id,
        'user_book_id': user_book.id,
        'message': f'"{book.title}" added to {target_user.display_name}\'s library.',
    })


@api_bp.route('/books/<int:book_id>', methods=['PATCH'])
@login_required
def update_book(book_id):
    book = db.session.get(Book, book_id)
    if not book:
        return jsonify({'error': 'Book not found.'}), 404

    data = request.get_json(force=True)

    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Title is required.'}), 400

    book.title = title
    book.author = (data.get('author') or '').strip()
    book.publisher = (data.get('publisher') or '').strip()
    book.published_year = (data.get('published_year') or '').strip()
    book.description = (data.get('description') or '').strip()
    book.cover_url = (data.get('cover_url') or '').strip()
    book.genre = (data.get('genre') or '').strip()
    book.language = (data.get('language') or '').strip()

    raw_pages = data.get('page_count')
    try:
        book.page_count = int(raw_pages) if raw_pages not in (None, '', 0) else None
    except (ValueError, TypeError):
        book.page_count = None

    db.session.commit()
    return jsonify({'success': True})


@api_bp.route('/user-books/<int:user_book_id>', methods=['PATCH'])
@login_required
def update_user_book(user_book_id):
    user_book = db.session.get(UserBook, user_book_id)
    if not user_book:
        return jsonify({'error': 'Not found.'}), 404
    if not current_user.is_admin and user_book.user_id != current_user.id:
        return jsonify({'error': 'Permission denied.'}), 403

    data = request.get_json(force=True)

    condition = (data.get('condition') or '').strip()
    if condition in UserBook.CONDITIONS:
        user_book.condition = condition

    user_book.location = (data.get('location') or '').strip()
    user_book.notes = (data.get('notes') or '').strip()

    db.session.commit()
    return jsonify({'success': True})


@api_bp.route('/books/<int:user_book_id>', methods=['DELETE'])
@login_required
def remove_book(user_book_id):
    user_book = db.session.get(UserBook, user_book_id)
    if not user_book:
        return jsonify({'error': 'Not found.'}), 404

    if not current_user.is_admin and user_book.user_id != current_user.id:
        return jsonify({'error': 'Permission denied.'}), 403

    book_title = user_book.book.title
    db.session.delete(user_book)

    if user_book.book.user_books.count() == 0:
        db.session.delete(user_book.book)

    db.session.commit()
    return jsonify({'success': True, 'message': f'"{book_title}" removed.'})


def _parse_goodreads_shelf(user_id, shelf):
    """Fetch one Goodreads RSS shelf. Returns a dict of isbn -> (status, rating) or raises."""
    url = f'https://www.goodreads.com/review/list_rss/{user_id}?shelf={shelf}&per_page=200'
    r = requests.get(url, timeout=15, headers={'User-Agent': 'LibraryN/1.0'})
    if r.status_code == 404:
        raise ValueError('Goodreads user not found. Check your user ID and make sure your profile is public.')
    if r.status_code != 200:
        raise ValueError(f'Goodreads returned HTTP {r.status_code}. Try again later.')

    root = ET.parse(BytesIO(r.content)).getroot()
    results = {}
    for item in root.findall('.//item'):
        raw13 = (item.findtext('isbn13') or '').strip()
        raw10 = (item.findtext('isbn') or '').strip()
        rating_str = (item.findtext('user_rating') or '').strip()
        rating = int(rating_str) if rating_str.isdigit() and rating_str != '0' else None

        for raw in (raw13, raw10):
            isbn = raw.replace('-', '').replace(' ', '')
            if isbn and not all(c == '0' for c in isbn):
                results[isbn] = (shelf, rating)
    return results


def sync_goodreads_for_user(user):
    """Sync Goodreads reading status for a user. Safe to call from any thread."""
    if not user.goodreads_user_id:
        return

    isbn_map = {}
    for shelf in ('read', 'currently-reading', 'to-read'):
        try:
            isbn_map.update(_parse_goodreads_shelf(user.goodreads_user_id, shelf))
        except Exception:
            return  # network or parse failure — leave existing statuses alone

    for ub in user.user_books.all():
        match = isbn_map.get(ub.book.isbn)
        if match:
            status, rating = match
            if status != ub.reading_status or (rating and rating != ub.goodreads_rating):
                ub.reading_status = status
                if rating:
                    ub.goodreads_rating = rating

    db.session.commit()


@api_bp.route('/goodreads/sync', methods=['POST'])
@login_required
def goodreads_sync():
    uid = current_user.goodreads_user_id
    if not uid:
        return jsonify({'error': 'Enter your Goodreads user ID on your profile first.'}), 400

    isbn_map = {}
    for shelf in ('read', 'currently-reading', 'to-read'):
        try:
            isbn_map.update(_parse_goodreads_shelf(uid, shelf))
        except ValueError as e:
            return jsonify({'error': str(e)}), 502
        except ET.ParseError:
            return jsonify({'error': 'Could not parse Goodreads feed. Try again.'}), 502
        except requests.RequestException:
            return jsonify({'error': 'Network error reaching Goodreads. Try again.'}), 502

    updated = 0
    for ub in current_user.user_books.all():
        match = isbn_map.get(ub.book.isbn)
        if match:
            status, rating = match
            if status != ub.reading_status or (rating and rating != ub.goodreads_rating):
                ub.reading_status = status
                if rating:
                    ub.goodreads_rating = rating
                updated += 1

    db.session.commit()
    total = len(isbn_map)
    return jsonify({
        'success': True,
        'updated': updated,
        'message': f'Found {total} books on Goodreads, updated {updated} in your library.',
    })
