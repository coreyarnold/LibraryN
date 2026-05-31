import threading
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from ..extensions import db, bcrypt
from ..models import User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('books.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('books.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if user and bcrypt.check_password_hash(user.password_hash, password):
            login_user(user, remember=request.form.get('remember') == 'on')
            if user.goodreads_user_id:
                from ..routes.api import sync_goodreads_for_user
                from flask import current_app
                app = current_app._get_current_object()
                threading.Thread(
                    target=lambda: _run_with_context(app, sync_goodreads_for_user, user),
                    daemon=True,
                ).start()
            next_page = request.args.get('next')
            return redirect(next_page or url_for('books.dashboard'))

        flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


def _run_with_context(app, fn, *args, **kwargs):
    with app.app_context():
        fn(*args, **kwargs)


from ..extensions import login_manager

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
