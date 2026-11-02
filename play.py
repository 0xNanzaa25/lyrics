#!/usr/bin/env python3
"""
play.py (versi Textual)

Install:
    pip install textual        (dan kalau pakai mp3: sudo apt install mpv)

Pakai:
    python3 play.py "judul" --artist "artis"                 # lirik saja, tanpa mp3
    python3 play.py "judul" namafile.mp3 --artist "artis"    # dengan mp3 via mpv
    python3 play.py "About You" about_you.mp3 --artist "The 1975" --silent

Lirik dicari berurutan:
    1. --lrc file.lrc
    2. <namafile>.lrc (atau <judul>_<artis>.lrc kalau tanpa mp3)
    3. <judul>.lrc di folder yang sama
    4. diunduh dari lrclib.net (disimpan otomatis)

Tanpa mp3: lirik jalan pakai jam internal dari detik 0, mulai lagunya sendiri
di tempat lain bersamaan. Kalau meleset, geser pakai +/-.
Dengan mp3: posisi lirik dibaca langsung dari mpv (IPC), tetap pas saat pause/seek.

Tombol: spasi=pause  <-/->=seek 5 dtk  +/-=geser sinkron 0.1 dtk  q=keluar

ex :  python3 play.py "Merry Christmas, i miss you" --artist "Alex Crichton"    
"""
import argparse
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from bisect import bisect_right

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, ProgressBar, Static

TS = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
OFFSET_TAG = re.compile(r"\[offset:\s*(-?\d+)\]", re.I)


# ---------- lirik ----------

def parse_lrc(path):
    """Baca file .lrc -> list[(detik, teks)] terurut."""
    lines, offset = [], 0.0
    with open(path, encoding="utf-8-sig") as f:
        for raw in f:
            raw = raw.rstrip("\n")
            m = OFFSET_TAG.search(raw)
            if m:
                offset = int(m.group(1)) / 1000.0
                continue
            stamps = TS.findall(raw)
            if not stamps:
                continue
            text = TS.sub("", raw).strip()
            for mm, ss in stamps:
                lines.append((int(mm) * 60 + float(ss) + offset, text))
    lines.sort(key=lambda x: x[0])
    return lines


def _http_json(url, tries=3):
    """GET json, UA mirip browser + retry (503 sering sementara)."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except Exception as e:
            last = e
            if i < tries - 1:
                print(f"  gagal ({e}), coba lagi {i + 1}/{tries - 1} ...")
                time.sleep(2)
    raise last


def fetch_lrclib(title, artist):
    base = "https://lrclib.net/api/search?"
    urls = []
    if artist:
        urls.append(base + urllib.parse.urlencode(
            {"track_name": title, "artist_name": artist}))
    urls.append(base + urllib.parse.urlencode({"q": f"{title} {artist}".strip()}))
    if artist:
        urls.append(base + urllib.parse.urlencode({"q": title}))
    err, ok = None, False
    for u in urls:
        try:
            data = _http_json(u)
        except Exception as e:
            err = e
            continue
        ok = True
        for item in data:
            if item.get("syncedLyrics"):
                return item["syncedLyrics"]
    if not ok and err:
        raise err
    return None


def find_lrc(args):
    if args.mp3:
        base = os.path.splitext(args.mp3)[0]
        folder = os.path.dirname(os.path.abspath(args.mp3))
    else:
        base = re.sub(r"[^\w\-]+", "_", f"{args.title} {args.artist}".strip()).strip("_").lower()
        folder = os.getcwd()
    if args.lrc and not os.path.isfile(args.lrc):
        print(f"Peringatan: file --lrc '{args.lrc}' tidak ada, lanjut cari/unduh lirik.")
    candidates = [args.lrc] if args.lrc else []
    candidates += [base + ".lrc", os.path.join(folder, args.title + ".lrc")]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    print("Lirik lokal tidak ketemu, coba unduh dari lrclib.net ...")
    try:
        text = fetch_lrclib(args.title, args.artist)
    except Exception as e:
        sys.exit(f"Gagal unduh lirik: {e}\nBuat file {base}.lrc sendiri atau pakai --lrc.")
    if not text:
        sys.exit(f"Lirik bertimestamp tidak ditemukan. Buat file {base}.lrc sendiri atau pakai --lrc.")
    out = base + ".lrc"
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Lirik disimpan ke {out}")
    return out


# ---------- mpv via IPC ----------

class MPV:
    def __init__(self, path, extra=None):
        self.lock = threading.Lock()
        self.started = time.time()
        self.sock_path = os.path.join(tempfile.gettempdir(), f"mpv-lyric-{os.getpid()}.sock")
        self.log_path = os.path.join(tempfile.gettempdir(), f"mpv-lyric-{os.getpid()}.log")
        self.log = open(self.log_path, "w")
        self.proc = subprocess.Popen(
            ["mpv", "--no-video", "--msg-level=all=error",
             f"--input-ipc-server={self.sock_path}", *(extra or []), path],
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
        )
        self.sock, self.buf, self.rid = None, b"", 0
        for _ in range(60):
            if self.proc.poll() is not None:
                break
            if os.path.exists(self.sock_path):
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.connect(self.sock_path)
                    s.settimeout(0.2)
                    self.sock = s
                    break
                except OSError:
                    pass
            time.sleep(0.1)

    def cmd(self, *args):
        if not self.sock:
            return None
        with self.lock:
            self.rid += 1
            rid = self.rid
            try:
                self.sock.sendall(json.dumps(
                    {"command": list(args), "request_id": rid}).encode() + b"\n")
            except OSError:
                return None
            deadline = time.time() + 0.4
            while time.time() < deadline:
                while b"\n" in self.buf:
                    line, self.buf = self.buf.split(b"\n", 1)
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("request_id") == rid:
                        return msg
                try:
                    chunk = self.sock.recv(4096)
                    if not chunk:
                        return None
                    self.buf += chunk
                except socket.timeout:
                    pass
                except OSError:
                    return None
        return None

    def get(self, prop):
        r = self.cmd("get_property", prop)
        if r and r.get("error") == "success":
            return r.get("data")
        return None

    def alive(self):
        return self.proc.poll() is None

    def log_tail(self, n=8):
        try:
            self.log.flush()
            with open(self.log_path, errors="replace") as f:
                return "".join(f.readlines()[-n:]).strip()
        except OSError:
            return ""

    def close(self):
        if self.alive():
            self.proc.terminate()
        for p in (self.sock_path, self.log_path):
            try:
                os.remove(p)
            except OSError:
                pass


class Clock:
    """Pengganti mpv kalau tanpa mp3: jam internal, lirik jalan real-time."""

    def __init__(self, length):
        self.lock = threading.Lock()
        self.started = 0
        self.sock = True
        self.length = length
        self._pos = 0.0
        self._t0 = time.time()
        self._paused = False

    def _now(self):
        if self._paused:
            return self._pos
        return min(self._pos + time.time() - self._t0, self.length)

    def get(self, prop):
        with self.lock:
            if prop == "time-pos":
                return self._now()
            if prop == "duration":
                return self.length
            if prop == "pause":
                return self._paused
        return None

    def cmd(self, *args):
        with self.lock:
            now = self._now()
            if args[0] == "cycle" and args[1] == "pause":
                self._pos, self._t0 = now, time.time()
                self._paused = not self._paused
            elif args[0] == "seek":
                self._pos = max(0.0, min(now + float(args[1]), self.length))
                self._t0 = time.time()
        return {"error": "success"}

    def alive(self):
        return self._paused or self._now() < self.length

    def log_tail(self, n=8):
        return ""

    def close(self):
        pass


# ---------- Textual app ----------

def fmt(t):
    t = max(0, t)
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


class PlayerApp(App):
    CSS = """
    Screen { align: center middle; background: $surface; }
    #card {
        width: 90%; max-width: 90; height: auto;
        border: round #c084fc; padding: 1 3;
    }
    #title  { text-align: center; text-style: bold; color: #c084fc; width: 100%; }
    #artist { text-align: center; color: $text-muted; width: 100%; }
    #lyrics { height: 13; width: 100%; content-align: center middle; text-align: center; margin: 1 0; }
    #time   { width: 100%; text-align: center; color: #fbbf24; }
    #bar    { width: 100%; }
    #bar Bar { width: 1fr; }
    Bar > .bar--bar      { color: #6d28d9; }
    Bar > .bar--complete { color: #22d3ee; }
    #status { width: 100%; text-align: center; color: $text-muted; }
    """

    BINDINGS = [
        Binding("space", "toggle_pause", "Pause/Play"),
        Binding("left", "seek(-5)", "-5s"),
        Binding("right", "seek(5)", "+5s"),
        Binding("plus,equals_sign", "sync(0.1)", "Sync +"),
        Binding("minus", "sync(-0.1)", "Sync -"),
        Binding("q", "quit", "Keluar"),
    ]

    def __init__(self, title, artist, lyrics, mpv):
        super().__init__()
        self.song_title = title
        self.artist = artist
        self.lyrics = lyrics
        self.times = [t for t, _ in lyrics]
        self.mpv = mpv
        self.pos = 0.0
        self.duration = None
        self.paused = False
        self.offset = 0.0
        self._cur = -2
        self._stop = threading.Event()

    def compose(self) -> ComposeResult:
        with Vertical(id="card"):
            yield Static(f"♪  {self.song_title}  ♪", id="title")
            yield Static(self.artist, id="artist")
            yield Static("", id="lyrics")
            yield Static("", id="time")
            yield ProgressBar(total=100, show_eta=False, show_percentage=False, id="bar")
            yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = self.song_title
        threading.Thread(target=self._poll, daemon=True).start()
        self.set_interval(0.05, self._tick)
        self._tick()

    def on_unmount(self) -> None:
        self._stop.set()

    # thread: baca status mpv / clock
    def _poll(self):
        while not self._stop.is_set() and self.mpv.alive():
            p = self.mpv.get("time-pos")
            if p is not None:
                self.pos = float(p)
            if self.duration is None:
                self.duration = self.mpv.get("duration")
            self.paused = bool(self.mpv.get("pause"))
            time.sleep(0.05)
        if not self._stop.is_set():
            try:
                self.call_from_thread(self.exit)
            except Exception:
                pass

    def _lyrics_text(self, cur):
        t = Text(justify="center")
        for rel in range(-4, 5):
            idx = cur + rel
            if rel == 0 and cur == -1:
                t.append("· · ·  siap  · · ·", style="dim")
            elif 0 <= idx < len(self.lyrics):
                line = self.lyrics[idx][1] or "♪"
                if rel == 0:
                    t.append(f"▶  {line}  ◀", style="bold cyan")
                elif abs(rel) == 1:
                    t.append(line, style="white")
                else:
                    t.append(line, style="dim")
            if rel != 4:
                t.append("\n")
        return t

    def _tick(self):
        lp = self.pos + self.offset
        cur = bisect_right(self.times, lp) - 1
        if cur != self._cur:
            self._cur = cur
            self.query_one("#lyrics", Static).update(self._lyrics_text(cur))
        total = self.duration or (self.times[-1] + 6 if self.times else 100)
        self.query_one("#time", Static).update(f"{fmt(lp)}  /  {fmt(total)}")
        self.query_one("#bar", ProgressBar).update(
            total=max(total, 1), progress=min(max(lp, 0), total))
        state = "⏸ PAUSE" if self.paused else "▶ PLAY"
        self.query_one("#status", Static).update(f"{state}   sync {self.offset:+.1f}s")

    # aksi
    def _bg(self, *cmd):
        threading.Thread(target=self.mpv.cmd, args=cmd, daemon=True).start()

    def action_toggle_pause(self) -> None:
        self._bg("cycle", "pause")

    def action_seek(self, secs: float) -> None:
        self._bg("seek", secs, "relative")

    def action_sync(self, delta: float) -> None:
        self.offset += delta
        self._cur = -2


def main():
    ap = argparse.ArgumentParser(description="Lirik sinkron TUI (mp3 opsional)")
    ap.add_argument("title", help="judul lagu")
    ap.add_argument("mp3", nargs="?", default=None,
                    help="file audio (opsional, kalau kosong = lirik saja)")
    ap.add_argument("--artist", default="", help="nama artis (membantu cari lirik)")
    ap.add_argument("--lrc", help="file .lrc manual")
    ap.add_argument("--mpv-args", default="",
                    help='opsi tambahan untuk mpv, tulis dengan "=": --mpv-args="--ao=alsa"')
    ap.add_argument("--ao", help="driver audio mpv: null, alsa, pulse, pipewire")
    ap.add_argument("--silent", action="store_true",
                    help="tanpa suara (mpv --ao=null), lirik tetap jalan real-time")
    args = ap.parse_args()

    lyrics = parse_lrc(find_lrc(args))
    if not lyrics:
        sys.exit("File .lrc kosong / formatnya salah (butuh baris seperti [00:12.30] teks).")

    # mode lirik saja (tanpa mp3)
    if not args.mp3:
        clock = Clock(lyrics[-1][0] + 6)
        PlayerApp(args.title, args.artist, lyrics, clock).run()
        return

    # mode dengan mp3 via mpv
    if not shutil.which("mpv"):
        sys.exit("mpv belum terpasang. Install dulu: sudo apt install mpv")
    if not os.path.isfile(args.mp3):
        sys.exit(f"File tidak ditemukan: {args.mp3}")

    extra = shlex.split(args.mpv_args)
    if args.silent:
        extra.append("--ao=null")
    elif args.ao:
        extra.append(f"--ao={args.ao}")
    mpv = MPV(args.mp3, extra)
    if not mpv.sock:
        tail = mpv.log_tail()
        mpv.close()
        sys.exit("Gagal terhubung ke mpv (IPC).\n" + tail)
    try:
        PlayerApp(args.title, args.artist, lyrics, mpv).run()
    finally:
        died_early = (not mpv.alive()) and (time.time() - mpv.started < 5)
        tail = mpv.log_tail()
        mpv.close()
    if died_early:
        print("mpv berhenti sendiri beberapa detik setelah mulai.")
        print(tail or "(mpv tidak mengeluarkan pesan error)")
        print("Kalau tidak ada perangkat audio, coba tambah --silent (lirik jalan tanpa suara)")
        print("atau pilih driver: --ao=alsa / --ao=pulse / --ao=pipewire")


if __name__ == "__main__":
    main()


#github dev : https://github.com/0xNanzaa25
#dev & kontributor : andraxc2 & claude ai
