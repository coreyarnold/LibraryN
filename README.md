# Family Library

A self-hosted web app for tracking every book owned by each member of your family. Scan barcodes with a USB scanner, look up book details automatically, and browse the family collection from any device on your network.

## Features

- **Barcode scanning** — plug in a USB scanner and scan books directly into the browser
- **Auto-lookup** — fetches title, author, cover, description, and publisher from Google Books / Open Library (no API key required)
- **Per-member collections** — each family member has their own account and book list
- **Family dashboard** — filter by member or view everyone's books at once
- **Condition & location tracking** — note where each book lives on which shelf
- **Admin panel** — add/edit/remove family members and their books
- **Runs in Docker** — one command to deploy on any home server (Raspberry Pi, NAS, old laptop)

---

## Quick Start (SQLite — recommended)

SQLite requires no extra setup. All data is stored in a Docker volume.

### 1. Clone and configure

```bash
cd LibraryN
cp .env.example .env
```

Edit `.env` and set a strong `SECRET_KEY` and your desired `ADMIN_PASSWORD`.

### 2. Build and run

```bash
docker compose up -d --build
```

The app starts at **http://localhost:5000** (or replace `localhost` with your server's IP to access from other devices).

### 3. Log in

Use the credentials from your `.env` file (`admin` / your password by default). Then go to **Users → Add Family Member** to create accounts for the rest of the family.

---

## MySQL Setup (optional, for larger collections)

If you prefer MySQL:

```bash
docker compose -f docker-compose.mysql.yml up -d --build
```

Set the MySQL variables in `.env` before starting.

---

## Updating

```bash
docker compose down
docker compose up -d --build
```

Your data is stored in a named Docker volume and persists across rebuilds.

---

## Backup

### SQLite
```bash
docker run --rm -v family-library_library-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/library-backup.tar.gz /data
```

### MySQL
```bash
docker exec family-library-db \
  mysqldump -u librarian -plibrary_pass library > backup.sql
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `change-me…` | Flask session key — **must be changed** |
| `ADMIN_USERNAME` | `admin` | First admin username |
| `ADMIN_PASSWORD` | `changeme` | First admin password — **change this** |
| `ADMIN_DISPLAY_NAME` | `Admin` | Display name for the admin account |
| `DB_TYPE` | `sqlite` | Set to `mysql` to use MySQL |
| `MYSQL_HOST` | `db` | MySQL host (Docker service name) |
| `MYSQL_PORT` | `3306` | MySQL port |
| `MYSQL_DATABASE` | `library` | Database name |
| `MYSQL_USER` | `librarian` | MySQL user |
| `MYSQL_PASSWORD` | `library_pass` | MySQL password |

---

## Scanner Setup

See [SCANNER_SETUP.md](SCANNER_SETUP.md) for recommended hardware and configuration instructions.

---

## Architecture

```
LibraryN/
├── Dockerfile
├── docker-compose.yml          # SQLite (default)
├── docker-compose.mysql.yml    # MySQL
├── entrypoint.sh
└── app/
    ├── __init__.py             # Application factory
    ├── config.py               # Configuration
    ├── extensions.py           # Flask extensions
    ├── models.py               # Database models (User, Book, UserBook)
    ├── routes/
    │   ├── auth.py             # Login / logout
    │   ├── books.py            # Dashboard, book list, detail, scan page
    │   ├── api.py              # JSON API (ISBN lookup, add/remove books)
    │   └── users.py            # User management
    ├── templates/
    └── static/
```

**Book lookup flow:**
1. Scanner sends ISBN keystrokes → browser input field captures them
2. `scanner.js` fires a `GET /api/lookup/<isbn>` request
3. Server checks local DB first (instant), then queries Google Books API
4. Result shown in browser with a confirmation form
5. User clicks "Add to Library" → `POST /api/books` saves the record

---

## Accessing from Other Devices

To use the app from phones, tablets, or other computers on your home network:

1. Find your server's local IP: `ip addr` (Linux) or `ipconfig` (Windows)
2. Open `http://<server-ip>:5000` on any device

To use a hostname like `http://library.home` instead of an IP address, add an entry to your router's DNS or each device's `/etc/hosts` file.
