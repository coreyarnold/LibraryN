from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, jsonify
from flask_login import login_required, current_user
from ..extensions import db, bcrypt
from ..models import User, USER_COLORS

users_bp = Blueprint('users', __name__)


def _admin_required():
    if not current_user.is_admin:
        abort(403)


@users_bp.route('/')
@login_required
def manage():
    _admin_required()
    users = User.query.order_by(User.display_name).all()
    return render_template('users/manage.html', users=users, colors=USER_COLORS)


@users_bp.route('/create', methods=['POST'])
@login_required
def create():
    _admin_required()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    username = request.form.get('username', '').strip().lower()
    display_name = request.form.get('display_name', '').strip()
    password = request.form.get('password', '')
    color = request.form.get('color', USER_COLORS[0])
    is_admin_flag = request.form.get('is_admin') == 'on'

    def _err(msg):
        if is_ajax:
            return jsonify({'error': msg}), 400
        flash(msg, 'danger')
        return redirect(url_for('users.manage'))

    if not username or not display_name or not password:
        return _err('All fields are required.')
    if User.query.filter_by(username=username).first():
        return _err(f'Username "{username}" is already taken.')

    email = request.form.get('email', '').strip().lower() or None
    user = User(
        username=username,
        display_name=display_name,
        email=email,
        password_hash=bcrypt.generate_password_hash(password).decode('utf-8'),
        color=color,
        is_admin=is_admin_flag,
    )
    db.session.add(user)
    db.session.commit()

    if is_ajax:
        return jsonify({'success': True})
    flash(f'User "{display_name}" created.', 'success')
    return redirect(url_for('users.manage'))


@users_bp.route('/<int:user_id>/edit', methods=['POST'])
@login_required
def edit(user_id):
    _admin_required()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    user = db.session.get(User, user_id)
    if not user:
        if is_ajax:
            return jsonify({'error': 'User not found.'}), 404
        abort(404)

    display_name = request.form.get('display_name', '').strip()
    color = request.form.get('color', user.color)
    is_admin_flag = request.form.get('is_admin') == 'on'
    new_password = request.form.get('password', '').strip()

    if not display_name:
        if is_ajax:
            return jsonify({'error': 'Display name is required.'}), 400
        flash('Display name is required.', 'danger')
        return redirect(url_for('users.manage'))

    user.display_name = display_name
    user.email = request.form.get('email', '').strip().lower() or None
    user.color = color
    user.is_admin = is_admin_flag

    if new_password:
        user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')

    db.session.commit()

    if is_ajax:
        return jsonify({'success': True})
    flash(f'User "{user.display_name}" updated.', 'success')
    return redirect(url_for('users.manage'))


@users_bp.route('/<int:user_id>/delete', methods=['POST'])
@login_required
def delete(user_id):
    _admin_required()
    if user_id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('users.manage'))

    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    name = user.display_name
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{name}" deleted.', 'success')
    return redirect(url_for('users.manage'))


@users_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '').strip()

        if display_name:
            current_user.display_name = display_name

        current_user.email = request.form.get('email', '').strip().lower() or None
        current_user.goodreads_user_id = request.form.get('goodreads_user_id', '').strip() or None

        if new_password:
            if not bcrypt.check_password_hash(current_user.password_hash, current_password):
                flash('Current password is incorrect.', 'danger')
                return redirect(url_for('users.profile'))
            current_user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')

        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('users.profile'))

    return render_template('users/profile.html')
