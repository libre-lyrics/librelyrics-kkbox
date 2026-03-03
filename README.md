# librelyrics-kkbox

KKBOX lyrics provider plugin for [LibreLyrics](https://github.com/libre-lyrics/librelyrics).

Fetches plain and synced lyrics from KKBOX's encrypted API.

## Installation

```bash
pip install librelyrics-kkbox
```

Or from source:

```bash
pip install git+https://github.com/libre-lyrics/librelyrics-kkbox.git
```

## Configuration

Run the interactive configuration editor:

```bash
librelyrics config edit
```

You will need the following settings:

| Key          | Description                                      |
|--------------|--------------------------------------------------|
| `email`      | Your KKBOX account email                         |
| `password`   | Your KKBOX account password                      |
| `kc1_key`    | KC1 decryption key (32-character hex string)     |
| `secret_key` | API secret key (32-character hex string)         |
| `kkid`       | Device identifier (optional, auto-generated)     |

### Finding the keys

The `kc1_key` and `secret_key` can be extracted from the KKBOX Android app.
These are static keys embedded in the application binary.

## Usage

### CLI

```bash
# Fetch lyrics for a single track
librelyrics "https://www.kkbox.com/tw/tc/song/abcdef123456"

# Fetch lyrics for an entire album
librelyrics "https://www.kkbox.com/tw/tc/album/abcdef123456"

# Fetch lyrics for a playlist
librelyrics "https://www.kkbox.com/tw/tc/playlist/abcdef123456"
```

### Python API

```python
from librelyrics import LibreLyrics

ll = LibreLyrics(config={
    'kkbox': {
        'email': 'your@email.com',
        'password': 'yourpassword',
        'kc1_key': '0123456789abcdef0123456789abcdef',
        'secret_key': 'fedcba9876543210fedcba9876543210',
    }
})

# Single track
result = ll.fetch("https://www.kkbox.com/tw/tc/song/abcdef123456")
print(result.to_lrc())

# Album (batch)
results = ll.fetch_batch("https://www.kkbox.com/tw/tc/album/abcdef123456")
for r in results:
    print(r.title, "-", r.artist)
    print(r.to_lrc())
```

## Supported URL formats

- `https://www.kkbox.com/{region}/{lang}/song/{id}` — single track
- `https://www.kkbox.com/{region}/{lang}/album/{id}` — full album
- `https://www.kkbox.com/{region}/{lang}/playlist/{id}` — playlist

## Requirements

- Python ≥ 3.10
- LibreLyrics ≥ 1.0.0
- PyCryptodome(x) ≥ 3.15.0
- A valid KKBOX account with an active subscription

## License

GPL-3.0-or-later
