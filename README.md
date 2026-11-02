# 🎧 Lyrics — Terminal Lyrics Player

<p align="center">
  <b>Bring your favorite lyrics to the terminal.</b><br>
  A lightweight, timestamp-based lyrics experience powered by Python and Textual.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/Interface-TUI-purple?style=for-the-badge" alt="TUI">
  <img src="https://img.shields.io/badge/Lyrics-LRC-orange?style=for-the-badge" alt="LRC">
</p>

---

## ✨ Features

- 🖥️ **Terminal UI** — display lyrics in a clean Textual interface.
- ⏱️ **Timestamp synchronization** — highlight lyrics according to their LRC timestamps.
- 🎵 **Optional MP3 playback** — sync with audio through `mpv` and its IPC interface.
- ⏯️ **Playback controls** — pause, resume, and seek.
- 🔧 **Sync adjustment** — nudge lyrics by 0.1 seconds.
- 🌐 **LRCLIB lookup** — automatically search for synchronized lyrics when no local file is found.
- 📂 **Local LRC support** — use your own timestamped lyrics files.

## 📦 Installation

Install Python dependencies:

```bash
pip install textual
```

For MP3 playback, install **mpv** too.

On Debian / Ubuntu / Kali Linux:

```bash
sudo apt update
sudo apt install mpv
```

## 🚀 Usage

### Lyrics only

```bash
python3 play.py "Song Title" --artist "Artist Name"
```

### Lyrics with MP3

```bash
python3 play.py "Song Title" song.mp3 --artist "Artist Name"
```

### Use a specific LRC file

```bash
python3 play.py "Song Title" --artist "Artist Name" --lrc song.lrc
```

### Silent playback / timing mode

```bash
python3 play.py "Song Title" song.mp3 --artist "Artist Name" --silent
```

### example/contoh langsung

```bash
 python3 play.py "Merry Christmas, i miss you" --artist "Alex Crichton"  
```

## ⌨️ Controls

| Key | Action |
|:---:|---|
| `Space` | Pause / resume |
| `←` | Seek backward 5 seconds |
| `→` | Seek forward 5 seconds |
| `+` / `=` | Shift lyrics forward by 0.1 seconds |
| `-` | Shift lyrics backward by 0.1 seconds |
| `Q` | Quit |

## 📄 LRC format

The player reads timestamped lines in standard LRC format:

```text
[00:12.30]Example lyric line
[00:16.75]Another line goes here
```

If a local LRC file is not found, the program attempts to fetch synchronized lyrics from [LRCLIB](https://lrclib.net/). Lyrics availability depends on the provider.

## 🗂️ Lyrics file lookup

The player checks these sources in order:

1. File provided with `--lrc`
2. LRC file matching the audio filename (or generated title/artist filename)
3. LRC file matching the song title
4. LRCLIB search, with downloaded lyrics saved locally

## 🛠️ Built with

- [Python](https://www.python.org/)
- [Textual](https://textual.textualize.io/)
- [Rich](https://rich.readthedocs.io/)
- [mpv](https://mpv.io/) — optional audio playback
- [LRCLIB](https://lrclib.net/) — synchronized lyrics lookup

## 👨‍💻 Credits

- **Developer:** [0xNanzaa25](https://github.com/0xNanzaa25)
- **Dev & contributor:** andraxc2
- **AI assistance:** Claude

---

<p align="center">
  Made for terminal lovers. <br>
  <i>Stay in sync. Keep the music close.</i>
</p>
