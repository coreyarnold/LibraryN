import logging
import os
import re
import requests
from datetime import datetime
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from ..extensions import db
from ..models import User, DVD, UserDVD, DVDLoan, ScanLog

dvd_api_bp = Blueprint('dvd_api', __name__)
log = logging.getLogger(__name__)

UPC_ITEMDB_URL = 'https://api.upcitemdb.com/prod/trial/lookup'
OMDB_URL       = 'https://www.omdbapi.com/'


def _lookup_upcitemdb(upc):
    try:
        r = requests.get(UPC_ITEMDB_URL, params={'upc': upc}, timeout=5)
        if r.status_code == 429:
            log.warning('UPC Item DB rate limited for UPC %s', upc)
            return 'rate_limited'
        if r.status_code != 200:
            log.warning('UPC Item DB returned %s for UPC %s — body: %.500s',
                        r.status_code, upc, r.text)
            return None
        items = r.json().get('items') or []
        if not items:
            log.debug('UPC Item DB returned no items for UPC %s', upc)
            return None
        item = items[0]
        images = item.get('images') or []
        return {
            'upc':         upc,
            'title':       item.get('title', 'Unknown Title'),
            'studio':      item.get('brand', ''),
            'description': item.get('description', ''),
            'cover_url':   images[0] if images else '',
            'format':      _detect_format(item.get('title', ''), item.get('model', '')),
            'director':    '',
            'year':        '',
            'runtime':     None,
            'rating':      '',
            'genre':       '',
        }
    except requests.Timeout:
        log.warning('UPC Item DB timed out for UPC %s', upc)
        return None
    except Exception:
        log.exception('UPC Item DB lookup failed for UPC %s', upc)
        return None


def _clean_title(title):
    """Strip disc/format/year suffixes that UPC Item DB appends to movie titles."""
    cleaned = re.sub(r'\s*\[.*?\]', '', title)   # [2 Discs], [Blu-ray/DVD], [2013], …
    cleaned = re.sub(r'\s*\(.*?\)', '', cleaned)  # (Blu-ray + Digital Copy), (4K), …
    return cleaned.strip().rstrip(',:;-').strip()


def _lookup_omdb(title):
    api_key = os.environ.get('OMDB_API_KEY', '')
    if not api_key or not title:
        return None
    search_title = _clean_title(title)
    if not search_title:
        return None
    try:
        r = requests.get(OMDB_URL,
                         params={'apikey': api_key, 't': search_title, 'type': 'movie'},
                         timeout=5)
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get('Response') != 'True':
            return None
        poster = data.get('Poster', '')
        return {
            'director':    data.get('Director', ''),
            'studio':      data.get('Production', '') or '',
            'year':        (data.get('Year', '') or '')[:4],
            'runtime':     _parse_runtime(data.get('Runtime', '')),
            'rating':      data.get('Rated', '').replace('N/A', ''),
            'genre':       data.get('Genre', ''),
            'description': data.get('Plot', '').replace('N/A', ''),
            'cover_url':   poster if poster != 'N/A' else '',
        }
    except Exception:
        return None


def _detect_format(title, model):
    combined = (title + ' ' + model).upper()
    if '4K' in combined or 'UHD' in combined:
        return '4K'
    if 'BLU' in combined:
        return 'Blu-ray'
    return 'DVD'


def _parse_runtime(s):
    m = re.match(r'(\d+)', s or '')
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

@dvd_api_bp.route('/dvd/lookup/<upc>')
@login_required
def dvd_lookup(upc):
    upc = upc.strip().replace('-', '').replace(' ', '')
    if not upc.isdigit() or len(upc) not in (8, 12, 13):
        return jsonify({'error': 'Invalid barcode. Must be 8, 12, or 13 digits.'}), 400

    existing = DVD.query.filter_by(upc=upc).first()
    if existing:
        owners = [
            {'id': ud.user_id, 'name': ud.user.display_name, 'color': ud.user.color}
            for ud in existing.user_dvds
        ]
        return jsonify({
            'in_library': True,
            'id': existing.id,
            'upc': existing.upc,
            'title': existing.title,
            'director': existing.director,
            'studio': existing.studio,
            'year': existing.year,
            'runtime': existing.runtime,
            'rating': existing.rating,
            'genre': existing.genre,
            'cover_url': existing.cover_url,
            'format': existing.format,
            'owners': owners,
        })

    dvd_data = _lookup_upcitemdb(upc)
    if dvd_data == 'rate_limited':
        return jsonify({'error': 'UPC Item DB rate limit reached — try again in a moment.'}), 429
    if dvd_data:
        omdb = _lookup_omdb(dvd_data['title'])
        if omdb:
            for k, v in omdb.items():
                if v:
                    dvd_data[k] = v

    if not dvd_data:
        return jsonify({'error': 'DVD not found. You can add it manually below.'}), 404

    dvd_data['in_library'] = False
    return jsonify(dvd_data)


# ---------------------------------------------------------------------------
# Add / remove / update
# ---------------------------------------------------------------------------

@dvd_api_bp.route('/dvds', methods=['POST'])
@login_required
def add_dvd():
    data    = request.get_json(force=True)
    upc     = (data.get('upc') or '').strip()
    title   = (data.get('title') or '').strip()
    user_id = data.get('user_id') or current_user.id

    if not upc or not title:
        return jsonify({'error': 'UPC and title are required.'}), 400

    if not current_user.is_admin and int(user_id) != current_user.id:
        return jsonify({'error': 'Only admins can add DVDs for other users.'}), 403

    target = db.session.get(User, user_id)
    if not target:
        return jsonify({'error': 'User not found.'}), 404

    dvd = DVD.query.filter_by(upc=upc).first()
    if not dvd:
        dvd = DVD(
            upc=upc, title=title,
            director=data.get('director', ''),
            studio=data.get('studio', ''),
            year=data.get('year', ''),
            runtime=data.get('runtime') or None,
            rating=data.get('rating', ''),
            genre=data.get('genre', ''),
            description=data.get('description', ''),
            cover_url=data.get('cover_url', ''),
            format=data.get('format', 'DVD'),
        )
        db.session.add(dvd)
        db.session.flush()

        if dvd.cover_url and not dvd.cover_url.startswith('/covers/'):
            from ..covers import fetch_and_store
            local_url = fetch_and_store(dvd.cover_url, upc)
            if local_url:
                dvd.cover_url = local_url

    if UserDVD.query.filter_by(user_id=user_id, dvd_id=dvd.id).first():
        return jsonify({'error': f'{target.display_name} already owns this DVD.'}), 409

    user_dvd = UserDVD(
        user_id=user_id,
        dvd_id=dvd.id,
        condition=data.get('condition', 'good'),
        notes=data.get('notes', ''),
        location=data.get('location', ''),
    )
    db.session.add(user_dvd)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Database error. DVD may already exist for this user.'}), 409

    return jsonify({
        'success':     True,
        'dvd_id':      dvd.id,
        'user_dvd_id': user_dvd.id,
        'message':     f'"{dvd.title}" added to {target.display_name}\'s library.',
    })


@dvd_api_bp.route('/dvds/<int:user_dvd_id>', methods=['DELETE'])
@login_required
def remove_dvd(user_dvd_id):
    user_dvd = db.session.get(UserDVD, user_dvd_id)
    if not user_dvd:
        return jsonify({'error': 'Not found.'}), 404
    if not current_user.is_admin and user_dvd.user_id != current_user.id:
        return jsonify({'error': 'Permission denied.'}), 403

    title = user_dvd.dvd.title
    db.session.delete(user_dvd)
    if user_dvd.dvd.user_dvds.count() == 0:
        db.session.delete(user_dvd.dvd)
    db.session.commit()
    return jsonify({'success': True, 'message': f'"{title}" removed.'})


@dvd_api_bp.route('/dvds/<int:dvd_id>', methods=['PATCH'])
@login_required
def update_dvd(dvd_id):
    dvd = db.session.get(DVD, dvd_id)
    if not dvd:
        return jsonify({'error': 'DVD not found.'}), 404

    data  = request.get_json(force=True)
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Title is required.'}), 400

    dvd.title       = title
    dvd.director    = (data.get('director')    or '').strip()
    dvd.studio      = (data.get('studio')      or '').strip()
    dvd.year        = (data.get('year')        or '').strip()
    dvd.rating      = (data.get('rating')      or '').strip()
    dvd.genre       = (data.get('genre')       or '').strip()
    dvd.description = (data.get('description') or '').strip()
    dvd.format      = (data.get('format')      or 'DVD').strip()

    new_cover = (data.get('cover_url') or '').strip()
    if new_cover and new_cover != dvd.cover_url and not new_cover.startswith('/covers/'):
        from ..covers import fetch_and_store
        dvd.cover_url = fetch_and_store(new_cover, dvd.upc) or new_cover
    else:
        dvd.cover_url = new_cover

    raw_rt = data.get('runtime')
    try:
        dvd.runtime = int(raw_rt) if raw_rt not in (None, '', 0) else None
    except (ValueError, TypeError):
        dvd.runtime = None

    db.session.commit()
    return jsonify({'success': True})


@dvd_api_bp.route('/user-dvds/<int:user_dvd_id>', methods=['PATCH'])
@login_required
def update_user_dvd(user_dvd_id):
    user_dvd = db.session.get(UserDVD, user_dvd_id)
    if not user_dvd:
        return jsonify({'error': 'Not found.'}), 404
    if not current_user.is_admin and user_dvd.user_id != current_user.id:
        return jsonify({'error': 'Permission denied.'}), 403

    data      = request.get_json(force=True)
    condition = (data.get('condition') or '').strip()
    if condition in UserDVD.CONDITIONS:
        user_dvd.condition = condition
    user_dvd.location = (data.get('location') or '').strip()
    user_dvd.notes    = (data.get('notes')    or '').strip()
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Loans
# ---------------------------------------------------------------------------

@dvd_api_bp.route('/dvd-loans', methods=['POST'])
@login_required
def create_dvd_loan():
    data        = request.get_json(force=True)
    user_dvd_id = data.get('user_dvd_id')
    loaned_to   = (data.get('loaned_to') or '').strip()

    if not loaned_to:
        return jsonify({'error': 'Friend name is required.'}), 400

    user_dvd = db.session.get(UserDVD, user_dvd_id)
    if not user_dvd:
        return jsonify({'error': 'Not found.'}), 404
    if not current_user.is_admin and user_dvd.user_id != current_user.id:
        return jsonify({'error': 'Permission denied.'}), 403

    active = user_dvd.active_loan
    if active:
        return jsonify({'error': f'Already loaned to {active.loaned_to}.'}), 409

    loan = DVDLoan(
        user_dvd_id=user_dvd_id,
        loaned_to=loaned_to,
        notes=(data.get('notes') or '').strip(),
    )
    db.session.add(loan)
    db.session.commit()
    return jsonify({'success': True, 'loan_id': loan.id})


@dvd_api_bp.route('/dvd-loans/<int:loan_id>/return', methods=['PATCH'])
@login_required
def return_dvd_loan(loan_id):
    loan = db.session.get(DVDLoan, loan_id)
    if not loan:
        return jsonify({'error': 'Not found.'}), 404
    is_lender   = loan.user_dvd.user_id == current_user.id
    is_borrower = loan.loaned_to == current_user.display_name
    if not current_user.is_admin and not is_lender and not is_borrower:
        return jsonify({'error': 'Permission denied.'}), 403
    if loan.returned_at:
        return jsonify({'error': 'Already returned.'}), 409

    loan.returned_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Scan audit log
# ---------------------------------------------------------------------------

@dvd_api_bp.route('/dvd-scan-log', methods=['POST'])
@login_required
def create_dvd_scan_log():
    data = request.get_json(force=True)
    log  = ScanLog(
        media_type=       'dvd',
        user_id=          current_user.id,
        user_display_name=current_user.display_name,
        isbn=             (data.get('upc') or '')[:20] or None,
        lookup_status=    (data.get('lookup_status') or '')[:20] or None,
        add_status=       (data.get('add_status') or '')[:20] or None,
        dvd_id=           data.get('dvd_id') or None,
        book_title=       (data.get('title') or '')[:500] or None,
        error_detail=     (data.get('error_detail') or '') or None,
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({'success': True})
