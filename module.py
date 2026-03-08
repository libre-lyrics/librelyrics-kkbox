"""KKBOX lyrics module implementation.

Fetches lyrics from the KKBOX API using KC1-encrypted endpoints.
Supports track, album, and playlist URLs.
"""
from __future__ import annotations

import logging
import re
from typing import ClassVar

from librelyrics.exceptions import (ConfigurationError, LyricsNotFound,
                                    ProviderError)
from librelyrics.models import LyricsLine, LyricsResponse
from librelyrics.modules.base import (LyricsModule, LyricsType,
                                      ModuleCapability, ModuleMeta)

from .api import (KkboxClient, extract_album_id, extract_playlist_id,
                  extract_track_id)

logger = logging.getLogger('librelyrics.modules.kkbox')

# Matches any KKBOX track, album, or playlist URL
KKBOX_URL_PATTERN = re.compile(
    r'kkbox\.com/[a-z]{2}/[a-z]{2}/(song|album|playlist)/'
)


class KkboxModule(LyricsModule):
    """KKBOX lyrics provider module.

    Fetches lyrics from KKBOX's encrypted API.
    Supports track, album, and playlist URLs.
    """

    META: ClassVar[ModuleMeta] = ModuleMeta(
        name='KKBOX',
        regex=KKBOX_URL_PATTERN,
        requires_auth=True,
        description='Fetch lyrics from KKBOX',
        lyrics_types=frozenset({LyricsType.PLAIN, LyricsType.SYNCED}),
        capabilities=frozenset({
            ModuleCapability.SINGLE_TRACK,
            ModuleCapability.ALBUM,
            ModuleCapability.PLAYLIST,
        }),
        config_schema={
            'email': 'KKBOX account email',
            'password': 'KKBOX account password',
            'kc1_key': 'KC1 decryption key (32-char hex)',
            'secret_key': 'API secret key (32-char hex)',
            'kkid': 'Device identifier (optional, auto-generated if empty)',
        },
    )
    LIBRELYRICS_API_VERSION: ClassVar[int] = 1

    def __init__(self, url: str, config: dict) -> None:
        super().__init__(url, config)
        self._client: KkboxClient | None = None

    def _ensure_client(self) -> None:
        """Initialize and authenticate the KKBOX client."""
        kc1_key = self.config.get('kc1_key', '')
        secret_key = self.config.get('secret_key', '')
        email = self.config.get('email', '')
        password = self.config.get('password', '')

        if not kc1_key or not secret_key:
            raise ConfigurationError(
                "KKBOX plugin requires 'kc1_key' and 'secret_key' in configuration. "
                "Run 'librelyrics config edit' to set them up."
            )
        if not email or not password:
            raise ConfigurationError(
                "KKBOX plugin requires 'email' and 'password' in configuration. "
                "Run 'librelyrics config edit' to set them up."
            )

        try:
            client = KkboxClient(
                kc1_key=kc1_key,
                secret_key=secret_key,
                kkid=self.config.get('kkid') or None,
            )
            client.login(email, password)
            self._client = client
            logger.debug('Initialized and authenticated KKBOX client')
        except (ValueError, ConnectionError) as exc:
            raise ProviderError(f'KKBOX authentication failed: {exc}') from exc

    @property
    def client(self) -> KkboxClient:
        """Get the authenticated KKBOX client."""
        if self._client is None:
            self._ensure_client()
        return self._client  # type: ignore[return-value]
    
    @staticmethod
    def default_config() -> dict:
        """Return default KKBOX configuration."""
        return {
            'email': '',
            'password': '',
            'kc1_key': '',
            'secret_key': '',
            'kkid': '',
        }

    @staticmethod
    def validate_config(config: dict) -> None:
        """Validate KKBOX configuration."""
        for key in ('email', 'password', 'kc1_key', 'secret_key'):
            if not config.get(key):
                raise ConfigurationError(
                    f"KKBOX plugin requires '{key}'. "
                    "See README for setup instructions."
                )

    def fetch(self) -> LyricsResponse:
        """Fetch lyrics for the configured URL.

        Returns:
            LyricsResponse with lyrics data.

        Raises:
            LyricsNotFound: If lyrics are not available.
        """
        track_id = extract_track_id(self.url)

        if not track_id:
            if extract_album_id(self.url) or extract_playlist_id(self.url):
                raise LyricsNotFound(
                    "Album/playlist URLs should use fetch_album() or fetch_playlist(). "
                    "Single fetch() requires a track (song) URL."
                )
            raise LyricsNotFound(f'Could not extract song ID from URL: {self.url}')

        return self._fetch_track_lyrics(track_id)

    def _fetch_track_lyrics(self, song_id: str, song_meta: dict | None = None) -> LyricsResponse:
        """Fetch lyrics for a single KKBOX song.

        Args:
            song_id: KKBOX song ID.
            song_meta: Optional pre-fetched song metadata.

        Returns:
            LyricsResponse with lyrics data.

        Raises:
            LyricsNotFound: If lyrics are not available.
        """
        # Get track metadata if not provided
        meta: dict
        if song_meta is None:
            try:
                songs = self.client.get_songs([song_id])
                if not songs:
                    raise LyricsNotFound(f'Song not found: {song_id}')
                meta = songs[0]
            except LookupError as exc:
                raise LyricsNotFound(str(exc)) from exc
        else:
            meta = song_meta

        title = meta.get('song_name', 'Unknown')
        artist = meta.get('artist_name', 'Unknown')
        album_name = meta.get('album_name')
        duration_ms = int(meta['duration']) * 1000 if meta.get('duration') else None

        # Fetch lyrics
        lyrics_resp = self.client.get_song_lyrics(song_id)

        if not lyrics_resp or not lyrics_resp.get('data'):
            raise LyricsNotFound(f'No lyrics available for: {title} - {artist}')

        lyrics_data = lyrics_resp['data']
        lyrics_list = lyrics_data.get('lyrics', [])

        lines: list[LyricsLine] = []
        is_synced = False

        for entry in lyrics_list:
            # KKBOX uses 'content' for the lyrics text
            text = entry.get('content', '').strip()
            start_ms: int = int(entry.get('start_time', 0))
            end_ms: int = int(entry.get('end_time', 0))

            # Lines with start_time=0 and empty content are instrumental breaks
            if start_ms == 0 and end_ms == 0 and not text:
                lines.append(LyricsLine(text=''))
                continue

            # start_time is already in milliseconds
            if start_ms > 0 or end_ms > 0:
                is_synced = True
                lines.append(LyricsLine(text=text, start_ms=start_ms, end_ms=end_ms))
            else:
                lines.append(LyricsLine(text=text))

        # Fallback: if lyrics is a plain string rather than a list
        if not lines and isinstance(lyrics_data.get('lyrics'), str):
            raw_text: str = lyrics_data['lyrics']
            for line_text in raw_text.split('\n'):
                lines.append(LyricsLine(text=line_text))

        if not lines:
            raise LyricsNotFound(f'No lyrics content for: {title} - {artist}')

        logger.debug(f'Fetched lyrics for: {title} - {artist}')

        return LyricsResponse(
            title=title,
            artist=artist,
            album=album_name,
            lyrics=lines,
            source=self.META.name,
            synced=is_synced,
            duration_ms=duration_ms,
            metadata={
                'song_id': song_id,
                'album_id': meta.get('album_id', ''),
                'explicit': meta.get('song_is_explicit', False),
                'track_number': meta.get('song_idx'),
            },
        )

    def fetch_album(self) -> list[LyricsResponse]:
        """Fetch lyrics for all tracks in a KKBOX album.

        Returns:
            List of LyricsResponse objects.

        Raises:
            LyricsNotFound: If album is not found.
        """
        album_id = extract_album_id(self.url)
        if not album_id:
            raise LyricsNotFound(f'Could not extract album ID from URL: {self.url}')

        try:
            album_data = self.client.get_album(album_id)
        except LookupError as exc:
            raise LyricsNotFound(str(exc)) from exc

        songs = album_data.get('songs', [])
        if not songs:
            raise LyricsNotFound(f'No tracks found in album: {album_id}')

        results: list[LyricsResponse] = []
        for i, song in enumerate(songs, 1):
            song_id = song.get('encrypted_song_id') or song.get('song_id', '')
            song['song_idx'] = song.get('song_idx', i)
            try:
                response = self._fetch_track_lyrics(str(song_id), song)
                results.append(response)
            except LyricsNotFound:
                logger.warning(f'No lyrics for track {i}: {song.get("song_name", song_id)}')

        return results
    
    def fetch_playlist(self) -> list[LyricsResponse]:
        """Fetch lyrics for all tracks in a KKBOX playlist.

        Returns:
            List of LyricsResponse objects.

        Raises:
            LyricsNotFound: If playlist is not found.
        """
        playlist_id = extract_playlist_id(self.url)
        if not playlist_id:
            raise LyricsNotFound(f'Could not extract playlist ID from URL: {self.url}')

        try:
            playlists = self.client.get_playlists([playlist_id])
        except LookupError as exc:
            raise LyricsNotFound(str(exc)) from exc

        if not playlists:
            raise LyricsNotFound(f'Playlist not found: {playlist_id}')

        playlist = playlists[0]
        songs = playlist.get('songs', [])
        if not songs:
            raise LyricsNotFound(f'No tracks found in playlist: {playlist_id}')

        results: list[LyricsResponse] = []
        for song in songs:
            song_id = song.get('encrypted_song_id')
            try:
                response = self._fetch_track_lyrics(str(song_id), song)
                results.append(response)
            except LyricsNotFound:
                logger.warning(f'No lyrics for: {song.get("song_name", song_id)}')

        return results
