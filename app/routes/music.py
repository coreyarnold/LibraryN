from datetime import datetime
from flask import Blueprint, render_template, abort, request
from flask_login import login_required, current_user
from sqlalchemy import or_
from ..extensions import db
from ..models import User, MusicRelease, UserMusicRelease, MusicLoan

music_bp = Blueprint('music', __name__)


@music_bp.route('/music')
@login_required
def index():
    search         = request.args.get('q', '').strip()
    filter_user_id = request.args.get('user_id', type=int)
    page           = request.args.get('page', 1, type=int)
    users          = User.query.order_by(User.display_name).all()

    query = (
        db.session.query(UserMusicRelease)
        .join(MusicRelease).join(User)
        .order_by(MusicRelease.title)
    )
    if search:
        query = query.filter(or_(
            MusicRelease.title.ilike(f'%{search}%'),
            MusicRelease.artist.ilike(f'%{search}%'),
            MusicRelease.barcode.ilike(f'%{search}%'),
        ))
    if filter_user_id:
        query = query.filter(UserMusicRelease.user_id == filter_user_id)

    pagination = query.paginate(page=page, per_page=25, error_out=False)
    return render_template('music/index.html', pagination=pagination,
                           users=users, search=search, filter_user_id=filter_user_id)


@music_bp.route('/music/<int:music_id>')
@login_required
def detail(music_id):
    music = db.session.get(MusicRelease, music_id)
    if not music:
        abort(404)
    user_music = (
        UserMusicRelease.query
        .filter_by(music_id=music_id)
        .join(User).order_by(User.display_name)
        .all()
    )
    users = User.query.order_by(User.display_name).all()
    return render_template('music/detail.html', music=music, user_music=user_music,
                           users=users, now=datetime.utcnow())


@music_bp.route('/music-scan')
@login_required
def scan():
    users = User.query.order_by(User.display_name).all()
    return render_template('music/scan.html', users=users)
