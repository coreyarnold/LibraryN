import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'changeme')
    ADMIN_DISPLAY_NAME = os.environ.get('ADMIN_DISPLAY_NAME', 'Admin')

_db_type = os.environ.get('DB_TYPE', 'sqlite')
if _db_type == 'mysql':
    _user = os.environ.get('MYSQL_USER', 'librarian')
    _password = os.environ.get('MYSQL_PASSWORD', 'password')
    _host = os.environ.get('MYSQL_HOST', 'db')
    _port = os.environ.get('MYSQL_PORT', '3306')
    _database = os.environ.get('MYSQL_DATABASE', 'library')
    Config.SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{_user}:{_password}@{_host}:{_port}/{_database}"
    )
else:
    Config.SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', 'sqlite:////data/library.db'
    )
