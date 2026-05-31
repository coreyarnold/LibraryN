#!/bin/bash
set -e

if [ "$DB_TYPE" = "mysql" ]; then
  echo "Waiting for MySQL at $MYSQL_HOST:${MYSQL_PORT:-3306}..."
  until python -c "
import pymysql, sys
try:
    pymysql.connect(
        host='${MYSQL_HOST}',
        port=int('${MYSQL_PORT:-3306}'),
        user='${MYSQL_USER}',
        password='${MYSQL_PASSWORD}',
        database='${MYSQL_DATABASE}'
    )
    sys.exit(0)
except Exception as e:
    sys.exit(1)
" 2>/dev/null; do
    echo "  MySQL not ready, retrying..."
    sleep 2
  done
  echo "MySQL is ready."
fi

# Initialize DB and seed admin once before workers start
python -c "
import sys
sys.path.insert(0, '/srv')
from app import create_app
app = create_app()
print('Initialization complete.')
"

exec gunicorn \
  --bind 0.0.0.0:5000 \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  "app:create_app()"
