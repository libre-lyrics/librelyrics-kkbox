"""KKBOX lyrics plugin for LibreLyrics.

Provides lyrics from KKBOX using their encrypted API.
Requires account credentials and decryption keys for authentication.

Install: pip install librelyrics-kkbox
"""
from .module import KkboxModule

__all__ = ['KkboxModule']
