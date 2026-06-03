"""
Download, resize, and store cover images locally so the app never depends
on third-party image hosts staying up or keeping URLs stable.

Images are stored in COVERS_DIR (set via env var; defaults to instance/covers).
They are served by the /covers/<filename> route in books.py.
"""
import io
import logging
import os

import requests
from PIL import Image

log = logging.getLogger(__name__)

MAX_SIZE = (400, 600)   # max width × height, aspect ratio preserved
JPEG_QUALITY = 85


def _covers_dir():
    from flask import current_app
    return current_app.config['COVERS_DIR']


def fetch_and_store(url, identifier):
    """
    Download the image at url, resize it to fit within MAX_SIZE, and save it
    as <identifier>.jpg in COVERS_DIR.

    Returns '/covers/<identifier>.jpg' on success, or None on failure so the
    caller can fall back to the original external URL.
    """
    if not url:
        return None

    covers_dir = _covers_dir()
    os.makedirs(covers_dir, exist_ok=True)

    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'LibraryN/1.0'})
        if r.status_code != 200:
            log.warning('Cover download returned HTTP %s for %s (url=%s)',
                        r.status_code, identifier, url)
            return None

        img = Image.open(io.BytesIO(r.content)).convert('RGB')
        original_size = img.size
        img.thumbnail(MAX_SIZE, Image.LANCZOS)

        filename = f'{identifier}.jpg'
        img.save(os.path.join(covers_dir, filename), 'JPEG',
                 quality=JPEG_QUALITY, optimize=True)
        log.debug('Stored cover %s: %s → %s', identifier, original_size, img.size)
        return f'/covers/{filename}'

    except requests.Timeout:
        log.warning('Cover download timed out for %s (url=%s)', identifier, url)
    except Exception:
        log.exception('Failed to download/store cover for %s (url=%s)', identifier, url)
    return None
