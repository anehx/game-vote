#!/usr/bin/env python3
"""
Crew game-vote server — Python standard library only. No pip, no npm.

Serves index.html and a tiny like / super-like API. Ballots are stored in
votes.json (one entry per voter id, so re-voting overwrites cleanly).
Old ranked ballots are migrated to likes on read (see normalize()).

Run:  python3 server.py
Env:  HOST (default 127.0.0.1), PORT (default 8787), VOTES_FILE (default ./votes.json)
"""
import json
import os
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
VOTES_FILE = os.environ.get("VOTES_FILE", os.path.join(HERE, "votes.json"))
INDEX_FILE = os.path.join(HERE, "index.html")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8787"))

# Keep in sync with the GAMES list in index.html.
GAME_IDS = {"conan", "7dtd", "ark", "rust", "vrising", "enshrouded", "icarus", "motortown", "satisfactory", "valheim", "abiotic", "sotf", "soulmask", "bellwright", "palworld", "moria"}
MAX_SUPERS = 3  # each voter gets a small budget of super-likes; likes are unlimited

_lock = threading.Lock()


def load():
    try:
        with open(VOTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(data):
    tmp = VOTES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, VOTES_FILE)  # atomic on POSIX


def clean_ids(ids, cap):
    out = []
    if isinstance(ids, list):
        for p in ids:
            if isinstance(p, str) and p in GAME_IDS and p not in out:
                out.append(p)
            if len(out) >= cap:
                break
    return out


def normalize(v):
    """Present a stored ballot as {name, likes, supers, ts}.

    Legacy ranked ballots (an ordered `picks` list) are migrated on read:
    every pick becomes a plain like. A super-like supersedes a like for the
    same game.
    """
    name = v.get("name", "anon")
    ts = v.get("ts", 0)
    if "likes" in v or "supers" in v:
        supers = [g for g in v.get("supers", []) if g in GAME_IDS]
        likes = [g for g in v.get("likes", []) if g in GAME_IDS and g not in supers]
    else:  # legacy: ordered picks -> likes
        supers = []
        likes = [g for g in v.get("picks", []) if g in GAME_IDS]
    return {"name": name, "likes": likes, "supers": supers, "ts": ts}


def name_key(name):
    """Voter key derived from the display name. Must match the frontend's
    voterKey() (trim + lowercase) so a name maps to one ballot everywhere."""
    return str(name).strip().lower()[:64]


def merge_by_name(data):
    """Consolidate ballots that resolve to the same normalized name into a
    single entry keyed by that name — e.g. the same person swiping from desktop
    and mobile, or leftover ballots from the old per-device id scheme.

    Unions likes/supers across their entries; a super-like beats a like for the
    same game. If the merge exceeds MAX_SUPERS, the overflow demotes to likes
    (nothing is lost). Legacy `picks` ballots migrate via normalize() first.
    Idempotent: re-running on already-merged data returns it unchanged.
    """
    acc = {}  # key -> {name, likes[], supers[], ts}
    for entry in sorted(data.values(), key=lambda v: v.get("ts", 0)):  # oldest first
        n = normalize(entry)
        key = name_key(n["name"])
        if not key:
            continue
        m = acc.setdefault(key, {"name": n["name"], "likes": [], "supers": [], "ts": 0})
        for g in n["likes"]:
            if g not in m["likes"]:
                m["likes"].append(g)
        for g in n["supers"]:
            if g not in m["supers"]:
                m["supers"].append(g)
        if n["ts"] >= m["ts"]:  # most recent display spelling / timestamp wins
            m["ts"], m["name"] = n["ts"], n["name"]
    out = {}
    for key, m in acc.items():
        supers = m["supers"][:MAX_SUPERS]
        demoted = m["supers"][MAX_SUPERS:]            # over budget -> becomes a like
        likes, seen = [], set()
        for g in m["likes"] + demoted:
            if g not in supers and g not in seen:
                seen.add(g)
                likes.append(g)
        out[key] = {"name": m["name"], "likes": likes, "supers": supers, "ts": m["ts"]}
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "votesrv/1.0"

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode("utf-8"))

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > 10_000:
                return None
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return None

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                with open(INDEX_FILE, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(500, b"index.html is missing next to server.py", "text/plain")
            return
        if path == "/api/votes":
            voter = (parse_qs(urlparse(self.path).query).get("voter", [""])[0])[:64]
            with _lock:
                data = load()
            ballots = [normalize(v) for v in data.values()]
            me = normalize(data[voter]) if voter in data else None
            self._json(200, {
                "ballots": ballots,
                "me": ({"name": me["name"], "likes": me["likes"], "supers": me["supers"]} if me else None),
            })
            return
        self._send(404, b'{"error":"not found"}')

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json()
        if body is None:
            self._json(400, {"error": "bad json"})
            return
        voter = str(body.get("voter", ""))[:64].strip()
        if not voter:
            self._json(400, {"error": "missing voter"})
            return

        if path == "/api/vote":
            name = str(body.get("name", "")).strip()[:24]
            supers = clean_ids(body.get("supers"), MAX_SUPERS)
            likes = [g for g in clean_ids(body.get("likes"), len(GAME_IDS)) if g not in supers]
            if not name:
                self._json(400, {"error": "missing name"})
                return
            with _lock:
                data = load()
                if likes or supers:
                    data[voter] = {"name": name, "likes": likes, "supers": supers, "ts": int(time.time() * 1000)}
                else:
                    data.pop(voter, None)
                save(data)
            self._json(200, {"ok": True})
            return

        if path == "/api/clear":
            with _lock:
                data = load()
                data.pop(voter, None)
                save(data)
            self._json(200, {"ok": True})
            return

        self._send(404, b'{"error":"not found"}')

    def log_message(self, *args):
        pass  # stay quiet; systemd/Caddy already log


if __name__ == "__main__":
    with _lock:  # one-time consolidation of any duplicate / legacy ballots
        _data = load()
        _merged = merge_by_name(_data)
        if _merged != _data:
            save(_merged)
            print(f"merged {len(_data)} ballot(s) -> {len(_merged)} by name")
    print(f"vote server → http://{HOST}:{PORT}   (ballots stored in {VOTES_FILE})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
