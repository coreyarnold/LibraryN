import logging
import os
import requests
from datetime import datetime
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from ..extensions import db
from ..models import User, MusicRelease, UserMusicRelease, MusicLoan, ScanLog

music_api_bp = Blueprint('music_api', __name__)
log = logging.getLogger(__name__)

DISCOGS_SEARCH_URL = 'https://api.discogs.com/database/search'
_DISCOGS_HEADERS   = {'User-Agent': 'LibraryN/1.0 (family-library)'}


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def _detect_music_format(formats):
    """Return the most descriptive format string from a Discogs format list."""
    upper = [f.upper() for f in formats]
    if 'VINYL' in upper or 'LP' in upper:
        size = next((f for f in formats if f in ('7"', '10"', '12"')), '')
        if 'EP' in upper:
            return f'{size} Vinyl EP'.strip() if size else 'Vinyl EP'
        if 'SINGLE' in upper:
            return f'{size} Single'.strip() if size else 'Vinyl Single'
        return f'{size} Vinyl'.strip() if size else 'LP'
    if 'CD' in upper:
        if 'EP' in upper:     return 'CD EP'
        if 'SINGLE' in upper: return 'CD Single'
        return 'CD'
    if 'CASSETTE' in upper:
        return 'Cassette'
    return formats[0] if formats else ''


_DISCOGS_PLACEHOLDERS = ('spacer', 'no-image', 'placeholder', '/images/default')


def _fetch_discogs_artwork(release_id, token=''):
    """
    Fetch primary cover art from the full Discogs release record.
    Called when the search result has no usable thumbnail.
    Returns a direct image URL or empty string.
    """
    if not release_id:
        return ''
    params = {'token': token} if token else {}
    try:
        r = requests.get(
            f'https://api.discogs.com/releases/{release_id}',
            params=params, headers=_DISCOGS_HEADERS, timeout=5,
        )
        if r.status_code != 200:
            log.debug('Discogs release detail returned %s for id %s', r.status_code, release_id)
            return ''
        images = r.json().get('images') or []
        # Prefer primary image, fall back to first available
        img = next((i for i in images if i.get('type') == 'primary'), None) \
              or (images[0] if images else None)
        return (img.get('uri') or img.get('uri150') or '') if img else ''
    except Exception:
        log.debug('Failed to fetch Discogs artwork for release %s', release_id)
        return ''


def _lookup_discogs(barcode):
    token = os.environ.get('DISCOGS_TOKEN', '')
    params = {'barcode': barcode, 'type': 'release'}
    if token:
        params['token'] = token
    else:
        log.warning('DISCOGS_TOKEN not set — lookups may be rate-limited or fail')

    try:
        r = requests.get(DISCOGS_SEARCH_URL, params=params,
                         headers=_DISCOGS_HEADERS, timeout=8)
        if r.status_code == 429:
            log.warning('Discogs rate limited for barcode %s', barcode)
            return 'rate_limited'
        if r.status_code == 401:
            log.warning('Discogs authentication failed — check DISCOGS_TOKEN')
            return None
        if r.status_code != 200:
            log.warning('Discogs returned %s for barcode %s — body: %.500s',
                        r.status_code, barcode, r.text)
            return None

        results = r.json().get('results') or []
        if not results:
            log.debug('Discogs returned no results for barcode %s', barcode)
            return None

        result = results[0]

        # Title is "Artist - Album" in Discogs search results
        raw_title = result.get('title', '')
        if ' - ' in raw_title:
            artist, title = raw_title.split(' - ', 1)
        else:
            artist, title = '', raw_title

        labels   = result.get('label')   or []
        formats  = result.get('format')  or []
        genres   = result.get('genre')   or []
        styles   = result.get('style')   or []

        # Use search thumbnail; upgrade to full release artwork if it's a placeholder
        cover_url = result.get('cover_image') or result.get('thumb') or ''
        if not cover_url or any(p in cover_url for p in _DISCOGS_PLACEHOLDERS):
            release_id = result.get('id')
            cover_url  = _fetch_discogs_artwork(release_id, token)
            if cover_url:
                log.debug('Fetched artwork from release details for barcode %s', barcode)

        return {
            'barcode':     barcode,
            'title':       title.strip() or 'Unknown Title',
            'artist':      artist.strip(),
            'label':       labels[0] if labels else '',
            'year':        str(result.get('year') or ''),
            'format':      _detect_music_format(formats),
            'track_count': None,   # not in search results; available via resource_url
            'genre':       ', '.join((genres + styles)[:3]),
            'cover_url':   cover_url,
            'mbid':        '',
        }
    except requests.Timeout:
        log.warning('Discogs timed out for barcode %s', barcode)
        return None
    except Exception:
        log.exception('Discogs lookup failed for barcode %s', barcode)
        return None


@music_api_bp.route('/music/lookup/<barcode>')
@login_required
def music_lookup(barcode):
    barcode = barcode.strip().replace('-', '').replace(' ', '')
    if not barcode.isdigit() or len(barcode) not in (8, 12, 13):
        return jsonify({'error': 'Invalid barcode. Must be 8, 12, or 13 digits.'}), 400

    existing = MusicRelease.query.filter_by(barcode=barcode).first()
    if existing:
        owners = [
            {'id': um.user_id, 'name': um.user.display_name, 'color': um.user.color}
            for um in existing.user_music
        ]
        return jsonify({
            'in_library':  True,
            'id':          existing.id,
            'barcode':     existing.barcode,
            'title':       existing.title,
            'artist':      existing.artist,
            'label':       existing.label,
            'year':        existing.year,
            'format':      existing.format,
            'track_count': existing.track_count,
            'genre':       existing.genre,
            'cover_url':   existing.cover_url,
            'owners':      owners,
        })

    data = _lookup_discogs(barcode)
    if data == 'rate_limited':
        return jsonify({'error': 'Discogs rate limit reached — try again in a moment.'}), 429
    if not data:
        return jsonify({'error': 'Release not found. You can add it manually below.'}), 404

    data['in_library'] = False
    return jsonify(data)


# ---------------------------------------------------------------------------
# Add / remove / update
# ---------------------------------------------------------------------------

@music_api_bp.route('/music', methods=['POST'])
@login_required
def add_music():
    data    = request.get_json(force=True)
    barcode = (data.get('barcode') or '').strip()
    title   = (data.get('title')   or '').strip()
    user_id = data.get('user_id') or current_user.id

    if not barcode or not title:
        return jsonify({'error': 'Barcode and title are required.'}), 400
    if not current_user.is_admin and int(user_id) != current_user.id:
        return jsonify({'error': 'Only admins can add items for other users.'}), 403

    target = db.session.get(User, user_id)
    if not target:
        return jsonify({'error': 'User not found.'}), 404

    music = MusicRelease.query.filter_by(barcode=barcode).first()
    if not music:
        music = MusicRelease(
            barcode=barcode, title=title,
            artist=data.get('artist', ''),
            label=data.get('label', ''),
            year=data.get('year', ''),
            format=data.get('format', ''),
            track_count=data.get('track_count') or None,
            genre=data.get('genre', ''),
            cover_url=data.get('cover_url', ''),
            mbid=data.get('mbid', ''),
        )
        db.session.add(music)
        db.session.flush()
        if music.cover_url and not music.cover_url.startswith('/covers/'):
            from ..covers import fetch_and_store
            local = fetch_and_store(music.cover_url, barcode)
            if local:
                music.cover_url = local

    if UserMusicRelease.query.filter_by(user_id=user_id, music_id=music.id).first():
        return jsonify({'error': f'{target.display_name} already owns this release.'}), 409

    um = UserMusicRelease(
        user_id=user_id, music_id=music.id,
        condition=data.get('condition', 'good'),
        notes=data.get('notes', ''),
        location=data.get('location', ''),
    )
    db.session.add(um)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Database error. Release may already exist for this user.'}), 409

    return jsonify({
        'success':      True,
        'music_id':     music.id,
        'user_music_id': um.id,
        'message':      f'"{music.title}" added to {target.display_name}\'s library.',
    })


@music_api_bp.route('/music/<int:user_music_id>', methods=['DELETE'])
@login_required
def remove_music(user_music_id):
    um = db.session.get(UserMusicRelease, user_music_id)
    if not um:
        return jsonify({'error': 'Not found.'}), 404
    if not current_user.is_admin and um.user_id != current_user.id:
        return jsonify({'error': 'Permission denied.'}), 403

    title = um.music.title
    db.session.delete(um)
    if um.music.user_music.count() == 0:
        db.session.delete(um.music)
    db.session.commit()
    return jsonify({'success': True, 'message': f'"{title}" removed.'})


@music_api_bp.route('/music/<int:music_id>', methods=['PATCH'])
@login_required
def update_music(music_id):
    music = db.session.get(MusicRelease, music_id)
    if not music:
        return jsonify({'error': 'Release not found.'}), 404

    data  = request.get_json(force=True)
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Title is required.'}), 400

    music.title       = title
    music.artist      = (data.get('artist')  or '').strip()
    music.label       = (data.get('label')   or '').strip()
    music.year        = (data.get('year')    or '').strip()
    music.genre       = (data.get('genre')   or '').strip()
    music.format      = (data.get('format')  or '').strip()

    raw_tc = data.get('track_count')
    try:
        music.track_count = int(raw_tc) if raw_tc not in (None, '', 0) else None
    except (ValueError, TypeError):
        music.track_count = None

    new_cover = (data.get('cover_url') or '').strip()
    if new_cover and new_cover != music.cover_url and not new_cover.startswith('/covers/'):
        from ..covers import fetch_and_store
        music.cover_url = fetch_and_store(new_cover, music.barcode) or new_cover
    else:
        music.cover_url = new_cover

    db.session.commit()
    return jsonify({'success': True})


@music_api_bp.route('/user-music/<int:user_music_id>', methods=['PATCH'])
@login_required
def update_user_music(user_music_id):
    um = db.session.get(UserMusicRelease, user_music_id)
    if not um:
        return jsonify({'error': 'Not found.'}), 404
    if not current_user.is_admin and um.user_id != current_user.id:
        return jsonify({'error': 'Permission denied.'}), 403

    data      = request.get_json(force=True)
    condition = (data.get('condition') or '').strip()
    if condition in UserMusicRelease.CONDITIONS:
        um.condition = condition
    um.location = (data.get('location') or '').strip()
    um.notes    = (data.get('notes')    or '').strip()
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Loans
# ---------------------------------------------------------------------------

@music_api_bp.route('/music-loans', methods=['POST'])
@login_required
def create_music_loan():
    data          = request.get_json(force=True)
    user_music_id = data.get('user_music_id')
    loaned_to     = (data.get('loaned_to') or '').strip()

    if not loaned_to:
        return jsonify({'error': 'Friend name is required.'}), 400

    um = db.session.get(UserMusicRelease, user_music_id)
    if not um:
        return jsonify({'error': 'Not found.'}), 404
    if not current_user.is_admin and um.user_id != current_user.id:
        return jsonify({'error': 'Permission denied.'}), 403

    if um.active_loan:
        return jsonify({'error': f'Already loaned to {um.active_loan.loaned_to}.'}), 409

    loan = MusicLoan(
        user_music_id=user_music_id,
        loaned_to=loaned_to,
        notes=(data.get('notes') or '').strip(),
    )
    db.session.add(loan)
    db.session.commit()
    return jsonify({'success': True, 'loan_id': loan.id})


@music_api_bp.route('/music-loans/<int:loan_id>/return', methods=['PATCH'])
@login_required
def return_music_loan(loan_id):
    loan = db.session.get(MusicLoan, loan_id)
    if not loan:
        return jsonify({'error': 'Not found.'}), 404

    is_lender   = loan.user_music.user_id == current_user.id
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

@music_api_bp.route('/music-scan-log', methods=['POST'])
@login_required
def create_music_scan_log():
    data = request.get_json(force=True)
    db.session.add(ScanLog(
        media_type=       'music',
        user_id=          current_user.id,
        user_display_name=current_user.display_name,
        isbn=             (data.get('barcode') or '')[:20] or None,
        lookup_status=    (data.get('lookup_status') or '')[:20] or None,
        add_status=       (data.get('add_status') or '')[:20] or None,
        music_id=         data.get('music_id') or None,
        book_title=       (data.get('title') or '')[:500] or None,
        error_detail=     (data.get('error_detail') or '') or None,
    ))
    db.session.commit()
    return jsonify({'success': True})
