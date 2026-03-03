"""KKBOX API client for lyrics fetching.

Provides authenticated access to the KKBOX API for fetching
track metadata and lyrics. Uses KC1 (ARC4) encryption for
API response decoding.
"""
from __future__ import annotations

import json
import logging
import re
from random import randrange
from time import time

import requests
from Cryptodome.Cipher import ARC4
from Cryptodome.Hash import MD5

logger = logging.getLogger('librelyrics.modules.kkbox.api')

# URL patterns for KKBOX
TRACK_PATTERN = re.compile(r'kkbox\.com/[a-z]{2}/[a-z]{2}/song/([A-Za-z0-9_-]+)')
ALBUM_PATTERN = re.compile(r'kkbox\.com/[a-z]{2}/[a-z]{2}/album/([A-Za-z0-9_-]+)')
PLAYLIST_PATTERN = re.compile(r'kkbox\.com/[a-z]{2}/[a-z]{2}/playlist/([A-Za-z0-9_-]+)')


def extract_track_id(url: str) -> str | None:
    """Extract track/song ID from a KKBOX URL."""
    if match := TRACK_PATTERN.search(url):
        return match.group(1)
    return None


def extract_album_id(url: str) -> str | None:
    """Extract album ID from a KKBOX URL."""
    if match := ALBUM_PATTERN.search(url):
        return match.group(1)
    return None


def extract_playlist_id(url: str) -> str | None:
    """Extract playlist ID from a KKBOX URL."""
    if match := PLAYLIST_PATTERN.search(url):
        return match.group(1)
    return None


class KkboxClient:
    """Client for the KKBOX API.

    Handles authentication, KC1 decryption, and API calls
    for fetching track metadata and lyrics.
    """

    KEY_PATTERN = re.compile(r'[0-9a-f]{32}')

    def __init__(self, kc1_key: str, secret_key: str, kkid: str | None = None) -> None:
        """Initialize the KKBOX client.

        Args:
            kc1_key: 32-char hex key for KC1 (ARC4) decryption.
            secret_key: 32-char hex key for API request signing.
            kkid: Optional device identifier. Generated if not provided.

        Raises:
            ValueError: If kc1_key or secret_key are invalid.
        """
        if not self.KEY_PATTERN.fullmatch(kc1_key):
            raise ValueError('kc1_key is invalid: must be a 32-character hex string')
        if not self.KEY_PATTERN.fullmatch(secret_key):
            raise ValueError('secret_key is invalid: must be a 32-character hex string')

        self.kc1_key = kc1_key.encode('ascii')
        self.secret_key = secret_key.encode('ascii')
        self.kkid = kkid or '%032X' % randrange(16**32)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'okhttp/3.14.9',
        })

        self.sid: str = ''
        self._base_params = {
            'enc': 'u',
            'ver': '06120082',
            'os': 'android',
            'osver': '13',
            'lang': 'en',
            'ui_lang': 'en',
            'dist': '0021',
            'dist2': '0021',
            'resolution': '411x841',
            'of': 'j',
            'oenc': 'kc1',
        }

    def _kc1_decrypt(self, data: bytes) -> str:
        """Decrypt KC1 (ARC4) encrypted API response."""
        cipher = ARC4.new(self.kc1_key)
        return cipher.decrypt(data).decode('utf-8')

    def _make_secret(self, timestamp: int) -> str:
        """Generate the request signing secret."""
        md5 = MD5.new()
        md5.update(self._base_params['ver'].encode('ascii'))
        md5.update(str(timestamp).encode('ascii'))
        md5.update(self.secret_key)
        return md5.hexdigest()
    
    def _api_call(
        self,
        host: str,
        path: str,
        params: dict | None = None,
        payload: dict | None = None,
    ) -> dict | None:
        """Make an authenticated API call to KKBOX.

        Args:
            host: API host prefix (e.g. 'ds', 'login', 'ticket').
            path: API endpoint path.
            params: Additional query parameters.
            payload: POST body (sent as JSON for 'ticket' host, form data otherwise).

        Returns:
            Decoded JSON response, or None if empty.
        """
        data = None
        if payload is not None:
            data = json.dumps(payload) if host == 'ticket' else payload

        timestamp = int(time())

        merged_params: dict[str, str | int] = dict(self._base_params)
        if params:
            merged_params.update(params)
        merged_params['secret'] = self._make_secret(timestamp)
        merged_params['timestamp'] = timestamp

        url = f'https://api-{host}.kkbox.com.tw/{path}'

        if data is None:
            resp = self.session.get(url, params=merged_params, timeout=15)
        else:
            resp = self.session.post(url, params=merged_params, data=data, timeout=15)

        if not resp.content:
            return None
        return json.loads(self._kc1_decrypt(resp.content))
    
    def login(self, email: str, password: str) -> None:
        """Authenticate with KKBOX using email and password.

        Args:
            email: KKBOX account email.
            password: KKBOX account password.

        Raises:
            ConnectionError: On authentication failure with descriptive message.
        """
        md5 = MD5.new()
        md5.update(password.encode('utf-8'))
        pwd_hash = md5.hexdigest()

        resp = self._api_call('login', 'login.php', payload={
            'uid': email,
            'passwd': pwd_hash,
            'kkid': self.kkid,
            'registration_id': '',
        })

        if resp is None:
            raise ConnectionError('Empty response from KKBOX login')

        status: int = resp.get('status', 0)
        if status not in (2, 3):
            error_map: dict[int, str] = {
                -1: 'Email not found',
                -2: 'Incorrect password',
                -4: 'IP address is in unsupported region, use a VPN',
                1: 'Account expired',
            }
            msg = error_map.get(status, f'Login failed, status code {status}')
            raise ConnectionError(msg)

        self._apply_session(resp)
        logger.debug('KKBOX login successful')

    def _apply_session(self, resp: dict) -> None:
        """Apply session data from a login/check response."""
        self.sid = resp['sid']
        self._base_params['sid'] = self.sid

    def renew_session(self) -> None:
        """Renew the current session."""
        resp = self._api_call('login', 'check.php')
        if resp is None or resp.get('status') not in (2, 3):
            raise ConnectionError('KKBOX session renewal failed')
        self._apply_session(resp)
        logger.debug('KKBOX session renewed')

    def get_songs(self, ids: list[str]) -> list[dict]:
        """Get metadata for one or more songs.

        Args:
            ids: List of KKBOX song IDs.

        Returns:
            List of song metadata dictionaries.

        Raises:
            LookupError: If tracks are not found.
        """
        resp = self._api_call('ds', 'v2/song', payload={
            'ids': ','.join(ids),
            'fields': (
                'artist_role,song_idx,album_photo_info,song_is_explicit,'
                'song_more_url,album_more_url,artist_more_url,genre_name,'
                'is_lyrics,audio_quality'
            ),
        })
        if resp is None or resp.get('status', {}).get('type') != 'OK':
            raise LookupError('Track(s) not found on KKBOX')
        return resp['data']['songs']

    def get_song_lyrics(self, song_id: str) -> dict | None:
        """Fetch lyrics for a single song.

        Args:
            song_id: KKBOX song ID.

        Returns:
            Lyrics response dict, or None if unavailable.
        """
        return self._api_call('ds', f'v1/song/{song_id}/lyrics')

    def get_album(self, album_id: str) -> dict:
        """Get album metadata including track list.

        Args:
            album_id: KKBOX album ID.

        Returns:
            Album metadata dictionary.

        Raises:
            LookupError: If album is not found.
        """
        resp = self._api_call('ds', f'v1/album/{album_id}')
        if resp is None or resp.get('status', {}).get('type') != 'OK':
            raise LookupError('Album not found on KKBOX')
        return resp['data']

    def get_playlists(self, ids: list[str]) -> list[dict]:
        """Get playlist metadata including tracks.

        Args:
            ids: List of KKBOX playlist IDs.

        Returns:
            List of playlist metadata dictionaries.

        Raises:
            LookupError: If playlists are not found.
        """
        resp = self._api_call('ds', 'v1/playlists', params={
            'playlist_ids': ','.join(ids),
        })
        if resp is None or resp.get('status', {}).get('type') != 'OK':
            raise LookupError('Playlist not found on KKBOX')
        return resp['data']['playlists']

    def search(self, query: str, types: list[str] | None = None, limit: int = 10) -> dict | None:
        """Search for songs, albums, or artists.

        Args:
            query: Search query string.
            types: Search field types (defaults to ['song']).
            limit: Maximum number of results.

        Returns:
            Search results dict.
        """
        if types is None:
            types = ['song']
        return self._api_call('ds', 'search_music.php', params={
            'sf': ','.join(types),
            'limit': limit,
            'query': query,
            'search_ranking': 'sc-A',
        })
