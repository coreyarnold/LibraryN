from datetime import datetime
from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from sqlalchemy import or_
from ..extensions import db
from ..models import User, DVD, UserDVD, DVDLoan

dvds_bp = Blueprint('dvds', __name__)


@dvds_bp.route('/dvds')
@login_required
def index():
    from flask import request
    search         = request.args.get('q', '').strip()
    filter_user_id = request.args.get('user_id', type=int)
    page           = request.args.get('page', 1, type=int)
    users          = User.query.order_by(User.display_name).all()

    query = (
        db.session.query(UserDVD)
        .join(DVD)
        .join(User)
        .order_by(DVD.title)
    )
    if search:
        query = query.filter(
            or_(
                DVD.title.ilike(f'%{search}%'),
                DVD.director.ilike(f'%{search}%'),
                DVD.upc.ilike(f'%{search}%'),
            )
        )
    if filter_user_id:
        query = query.filter(UserDVD.user_id == filter_user_id)

    pagination = query.paginate(page=page, per_page=25, error_out=False)
    return render_template('dvds/index.html', pagination=pagination,
                           users=users, search=search, filter_user_id=filter_user_id)


@dvds_bp.route('/dvds/<int:dvd_id>')
@login_required
def detail(dvd_id):
    dvd = db.session.get(DVD, dvd_id)
    if not dvd:
        abort(404)
    user_dvds = (
        UserDVD.query
        .filter_by(dvd_id=dvd_id)
        .join(User)
        .order_by(User.display_name)
        .all()
    )
    users = User.query.order_by(User.display_name).all()
    return render_template('dvds/detail.html', dvd=dvd, user_dvds=user_dvds,
                           users=users, now=datetime.utcnow())


@dvds_bp.route('/dvd-scan')
@login_required
def scan():
    users = User.query.order_by(User.display_name).all()
    return render_template('dvds/scan.html', users=users)
