"""Studio user service: auth + per-user projects & model library.

Stdlib-only (http.server + sqlite3 + hashlib/secrets), same house pattern as the CAD/Track-B
bridges — no new deps, safe next to a running eval. Fronted by Caddy at /api/studio/*.

Auth: email + password → PBKDF2-HMAC-SHA256 (240k iters, per-user salt); opaque bearer tokens in a
sessions table (no JWT — revocable, zero crypto surface). Every data row is scoped by user_id.

Storage: SQLite for users/sessions/projects/model METADATA; the heavy artifacts (STL/STEP/GLB b64,
code, spec, assembly, per-part meshes) live as one JSON file per model under DATA_DIR/artifacts —
list endpoints stay light (metadata + thumbnail only), the full payload is fetched on open.

  POST /signup {email,password,first,last}      → {token, user}
  POST /login  {email,password}                 → {token, user}
  POST /logout                                  → {}                    (auth)
  GET  /me                                      → {user}                (auth)
  PATCH /me {first?,last?,password?}            → {user}                (auth)
  GET  /projects                                → {projects:[{name,models,ts}]}
  POST /projects {name}                         → {name}
  GET  /models?project=&limit=                  → {models:[metadata]}   (no artifacts)
  POST /models {model incl. artifacts}          → {id}
  GET  /models/<id>                             → full model (metadata + artifacts)
  DELETE /models/<id>                           → {}
  GET  /health                                  → {ok, users}

Run:  python3 -m studio_api.server  [port]   (default 8092)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

DATA_DIR = os.environ.get("STUDIO_DATA", "/home/abdelrahman/MotionLab/studio_data")
DB_PATH = os.path.join(DATA_DIR, "studio.db")
ART_DIR = os.path.join(DATA_DIR, "artifacts")
PBKDF2_ITERS = 240_000
TOKEN_TTL = 60 * 60 * 24 * 45          # 45 days — internal tool, sliding on use
MAX_BODY = 512 * 1024 * 1024           # hero GLBs are ~40 MB b64; parts add more
BUG_DIR = os.environ.get("STUDIO_BUGS", "/home/abdelrahman/MotionLab/bug_reports")

_lock = threading.Lock()               # sqlite is opened per-request; the lock guards artifact files


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    os.makedirs(ART_DIR, exist_ok=True)
    con = _db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, salt BLOB NOT NULL, pw BLOB NOT NULL,
      first TEXT DEFAULT '', last TEXT DEFAULT '', created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(
      token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created REAL NOT NULL, seen REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS projects(
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name TEXT NOT NULL, created REAL NOT NULL, UNIQUE(user_id, name));
    CREATE TABLE IF NOT EXISTS models(
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      project TEXT NOT NULL DEFAULT 'My Project', name TEXT NOT NULL, engine TEXT NOT NULL,
      status TEXT NOT NULL, prompt TEXT DEFAULT '', ts REAL NOT NULL,
      thumb TEXT, meta TEXT NOT NULL DEFAULT '{}', artifact TEXT);
    CREATE INDEX IF NOT EXISTS idx_models_user_ts ON models(user_id, ts DESC);
    """)
    con.commit()
    con.close()


def _hash_pw(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERS)


def _user_json(row) -> dict:
    return {"email": row["email"], "first": row["first"], "last": row["last"]}


# metadata keys kept in the models table / list responses; everything else is an artifact
_META_KEYS = {"id", "name", "project", "engine", "status", "prompt", "ts", "thumb",
              "tier", "seconds", "attempts", "inspection"}


class Handler(BaseHTTPRequestHandler):
    server_version = "MotionLabStudio/1"

    # ---------- plumbing ----------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204); self._cors(); self.end_headers()

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if n <= 0:
            return {}
        if n > MAX_BODY:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def _auth(self, con) -> "sqlite3.Row | None":
        h = self.headers.get("Authorization", "")
        if not h.startswith("Bearer "):
            return None
        token = h[7:].strip()
        row = con.execute(
            "SELECT u.*, s.token FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token=?",
            (token,)).fetchone()
        if row is None:
            return None
        sess = con.execute("SELECT seen FROM sessions WHERE token=?", (token,)).fetchone()
        if time.time() - sess["seen"] > TOKEN_TTL:
            con.execute("DELETE FROM sessions WHERE token=?", (token,)); con.commit()
            return None
        con.execute("UPDATE sessions SET seen=? WHERE token=?", (time.time(), token)); con.commit()
        return row

    def log_message(self, *_):  # quiet
        pass

    # ---------- routes ----------
    def do_POST(self):  # noqa: N802
        con = _db()
        try:
            path = urlparse(self.path).path.rstrip("/")
            if path == "/signup":
                return self._signup(con)
            if path == "/login":
                return self._login(con)
            user = self._auth(con)
            if user is None:
                return self._json(401, {"error": "not signed in"})
            if path == "/logout":
                con.execute("DELETE FROM sessions WHERE token=?", (user["token"],)); con.commit()
                return self._json(200, {})
            if path == "/projects":
                return self._create_project(con, user)
            if path == "/models":
                return self._create_model(con, user)
            if path == "/bugs":
                return self._report_bug(user)
            return self._json(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._json(400, {"error": f"{type(e).__name__}: {e}"})
        finally:
            con.close()

    def do_GET(self):  # noqa: N802
        con = _db()
        try:
            url = urlparse(self.path)
            path = url.path.rstrip("/")
            if path in ("/health", ""):
                n = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
                return self._json(200, {"ok": True, "users": n})
            user = self._auth(con)
            if user is None:
                return self._json(401, {"error": "not signed in"})
            if path == "/me":
                return self._json(200, {"user": _user_json(user)})
            if path == "/projects":
                rows = con.execute(
                    "SELECT p.name, p.created, COUNT(m.id) models FROM projects p "
                    "LEFT JOIN models m ON m.user_id = p.user_id AND m.project = p.name "
                    "WHERE p.user_id=? GROUP BY p.id ORDER BY p.created", (user["id"],)).fetchall()
                return self._json(200, {"projects": [
                    {"name": r["name"], "models": r["models"], "ts": r["created"]} for r in rows]})
            if path == "/models":
                q = parse_qs(url.query)
                proj = (q.get("project") or [None])[0]
                limit = min(500, int((q.get("limit") or ["200"])[0]))
                sql = "SELECT id,project,name,engine,status,prompt,ts,thumb,meta FROM models WHERE user_id=?"
                args: list = [user["id"]]
                if proj:
                    sql += " AND project=?"; args.append(proj)
                sql += " ORDER BY ts DESC LIMIT ?"; args.append(limit)
                out = []
                for r in con.execute(sql, args):
                    m = json.loads(r["meta"])
                    m.update({"id": r["id"], "project": r["project"], "name": r["name"],
                              "engine": r["engine"], "status": r["status"], "prompt": r["prompt"],
                              "ts": r["ts"], "thumb": r["thumb"]})
                    out.append(m)
                return self._json(200, {"models": out})
            m = re.fullmatch(r"/models/([A-Za-z0-9_-]+)", path)
            if m:
                row = con.execute("SELECT * FROM models WHERE id=? AND user_id=?",
                                  (m.group(1), user["id"])).fetchone()
                if row is None:
                    return self._json(404, {"error": "unknown model"})
                full = json.loads(row["meta"])
                if row["artifact"]:
                    try:
                        with open(os.path.join(ART_DIR, row["artifact"])) as fh:
                            full.update(json.load(fh))
                    except OSError:
                        pass
                full.update({"id": row["id"], "project": row["project"], "name": row["name"],
                             "engine": row["engine"], "status": row["status"], "prompt": row["prompt"],
                             "ts": row["ts"], "thumb": row["thumb"]})
                return self._json(200, full)
            return self._json(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._json(400, {"error": f"{type(e).__name__}: {e}"})
        finally:
            con.close()

    def do_PATCH(self):  # noqa: N802
        con = _db()
        try:
            path = urlparse(self.path).path.rstrip("/")
            user = self._auth(con)
            if user is None:
                return self._json(401, {"error": "not signed in"})
            if path == "/me":
                b = self._body()
                first = str(b.get("first", user["first"]))[:80]
                last = str(b.get("last", user["last"]))[:80]
                con.execute("UPDATE users SET first=?, last=? WHERE id=?", (first, last, user["id"]))
                if b.get("password"):
                    salt = secrets.token_bytes(16)
                    con.execute("UPDATE users SET salt=?, pw=? WHERE id=?",
                                (salt, _hash_pw(str(b["password"]), salt), user["id"]))
                con.commit()
                row = con.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
                return self._json(200, {"user": _user_json(row)})
            m = re.fullmatch(r"/models/([A-Za-z0-9_-]+)", path)
            if m:
                # light metadata update — move a model between projects / rename it (no artifact touch)
                b = self._body()
                row = con.execute("SELECT id FROM models WHERE id=? AND user_id=?",
                                  (m.group(1), user["id"])).fetchone()
                if row is None:
                    return self._json(404, {"error": "unknown model"})
                if b.get("project"):
                    project = str(b["project"]).strip()[:80]
                    con.execute("INSERT OR IGNORE INTO projects(id,user_id,name,created) VALUES(?,?,?,?)",
                                (uuid.uuid4().hex[:12], user["id"], project, time.time()))
                    con.execute("UPDATE models SET project=? WHERE id=? AND user_id=?",
                                (project, m.group(1), user["id"]))
                if b.get("name"):
                    con.execute("UPDATE models SET name=? WHERE id=? AND user_id=?",
                                (str(b["name"]).strip()[:120], m.group(1), user["id"]))
                con.commit()
                return self._json(200, {})
            return self._json(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._json(400, {"error": f"{type(e).__name__}: {e}"})
        finally:
            con.close()

    def do_DELETE(self):  # noqa: N802
        con = _db()
        try:
            path = urlparse(self.path).path.rstrip("/")
            user = self._auth(con)
            if user is None:
                return self._json(401, {"error": "not signed in"})
            m = re.fullmatch(r"/models/([A-Za-z0-9_-]+)", path)
            if m:
                row = con.execute("SELECT artifact FROM models WHERE id=? AND user_id=?",
                                  (m.group(1), user["id"])).fetchone()
                if row is None:
                    return self._json(404, {"error": "unknown model"})
                con.execute("DELETE FROM models WHERE id=? AND user_id=?", (m.group(1), user["id"]))
                con.commit()
                if row["artifact"]:
                    with _lock:
                        try:
                            os.remove(os.path.join(ART_DIR, row["artifact"]))
                        except OSError:
                            pass
                return self._json(200, {})
            pm = re.fullmatch(r"/projects/(.+)", path)
            if pm:
                name = unquote(pm.group(1)).strip()[:80]
                prow = con.execute("SELECT id FROM projects WHERE user_id=? AND name=?",
                                   (user["id"], name)).fetchone()
                if prow is None:
                    return self._json(404, {"error": "unknown project"})
                arts = [r["artifact"] for r in con.execute(
                    "SELECT artifact FROM models WHERE user_id=? AND project=?",
                    (user["id"], name)) if r["artifact"]]
                con.execute("DELETE FROM models WHERE user_id=? AND project=?", (user["id"], name))
                con.execute("DELETE FROM projects WHERE user_id=? AND name=?", (user["id"], name))
                con.commit()
                with _lock:
                    for a in arts:
                        try:
                            os.remove(os.path.join(ART_DIR, a))
                        except OSError:
                            pass
                return self._json(200, {"deleted_models": len(arts)})
            return self._json(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._json(400, {"error": f"{type(e).__name__}: {e}"})
        finally:
            con.close()

    # ---------- handlers ----------
    def _signup(self, con):
        b = self._body()
        email = str(b.get("email", "")).strip().lower()
        password = str(b.get("password", ""))
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return self._json(400, {"error": "enter a valid email address"})
        if len(password) < 6:
            return self._json(400, {"error": "password must be at least 6 characters"})
        if con.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return self._json(409, {"error": "an account with this email already exists"})
        uid = uuid.uuid4().hex[:12]
        salt = secrets.token_bytes(16)
        con.execute("INSERT INTO users(id,email,salt,pw,first,last,created) VALUES(?,?,?,?,?,?,?)",
                    (uid, email, salt, _hash_pw(password, salt),
                     str(b.get("first", ""))[:80], str(b.get("last", ""))[:80], time.time()))
        con.execute("INSERT INTO projects(id,user_id,name,created) VALUES(?,?,?,?)",
                    (uuid.uuid4().hex[:12], uid, "My Project", time.time()))
        _seed_models(con, uid)
        token = secrets.token_hex(32)
        con.execute("INSERT INTO sessions(token,user_id,created,seen) VALUES(?,?,?,?)",
                    (token, uid, time.time(), time.time()))
        con.commit()
        row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return self._json(200, {"token": token, "user": _user_json(row)})

    def _login(self, con):
        b = self._body()
        email = str(b.get("email", "")).strip().lower()
        row = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        # constant-shape response on both failure modes — don't leak which emails exist
        if row is None or not hmac.compare_digest(_hash_pw(str(b.get("password", "")), row["salt"]), row["pw"]):
            return self._json(401, {"error": "wrong email or password"})
        token = secrets.token_hex(32)
        con.execute("INSERT INTO sessions(token,user_id,created,seen) VALUES(?,?,?,?)",
                    (token, row["id"], time.time(), time.time()))
        con.commit()
        return self._json(200, {"token": token, "user": _user_json(row)})

    def _report_bug(self, user):
        """Save a user bug report (description + optional screenshot) into BUG_DIR — one JSON
        record per report, screenshot alongside it, for the team to triage from the repo."""
        b = self._body()
        desc = (b.get("description") or "").strip()
        if not desc:
            return self._json(400, {"error": "describe the bug first"})
        os.makedirs(BUG_DIR, exist_ok=True)
        rid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        img = b.get("image_b64")
        shot = None
        if img:
            ext = "jpg" if (b.get("mime") or "").endswith("jpeg") else "png"
            shot = f"{rid}.{ext}"
            with open(os.path.join(BUG_DIR, shot), "wb") as f:
                f.write(base64.b64decode(img))
        rec = {"id": rid, "when": time.strftime("%Y-%m-%d %H:%M:%S"),
               "user": user["email"], "description": desc[:8000],
               "context": b.get("context") or {}, "screenshot": shot}
        with open(os.path.join(BUG_DIR, rid + ".json"), "w") as f:
            json.dump(rec, f, indent=2, ensure_ascii=False)
        return self._json(200, {"id": rid})

    def _create_project(self, con, user):
        b = self._body()
        name = str(b.get("name", "")).strip()[:80]
        if not name:
            return self._json(400, {"error": "project name required"})
        try:
            con.execute("INSERT INTO projects(id,user_id,name,created) VALUES(?,?,?,?)",
                        (uuid.uuid4().hex[:12], user["id"], name, time.time()))
            con.commit()
        except sqlite3.IntegrityError:
            return self._json(409, {"error": "a project with this name already exists"})
        return self._json(200, {"name": name})

    def _create_model(self, con, user):
        b = self._body()
        mid = str(b.get("id") or uuid.uuid4().hex[:12])[:40]
        meta = {k: b[k] for k in b if k in _META_KEYS and k not in
                ("id", "name", "project", "engine", "status", "prompt", "ts", "thumb")}
        artifacts = {k: v for k, v in b.items() if k not in _META_KEYS}
        art_name = None
        if artifacts:
            art_name = mid + ".json"
            with _lock:
                with open(os.path.join(ART_DIR, art_name), "w") as fh:
                    json.dump(artifacts, fh)
        project = str(b.get("project") or "My Project")[:80]
        con.execute("INSERT OR IGNORE INTO projects(id,user_id,name,created) VALUES(?,?,?,?)",
                    (uuid.uuid4().hex[:12], user["id"], project, time.time()))
        con.execute(
            "INSERT OR REPLACE INTO models(id,user_id,project,name,engine,status,prompt,ts,thumb,meta,artifact) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (mid, user["id"], project, str(b.get("name", "Untitled"))[:120],
             str(b.get("engine", "cad")), str(b.get("status", "verified")),
             str(b.get("prompt", ""))[:2000], float(b.get("ts") or time.time() * 1000) ,
             b.get("thumb"), json.dumps(meta), art_name))
        con.commit()
        return self._json(200, {"id": mid})


def _seed_models(con, uid: str) -> None:
    """Curated example models for a fresh account (an articulated door, a jointed cart, a terrain
    hero) — the first 30 seconds should demo the product, not show an empty library. Artifacts are
    copied per user (small, and it keeps DELETE semantics trivial). Best-effort: a missing seeds
    dir just means an empty start."""
    import glob
    seeds = sorted(glob.glob(os.path.join(DATA_DIR, "seeds", "*.json")))
    if not seeds:
        return
    con.execute("INSERT OR IGNORE INTO projects(id,user_id,name,created) VALUES(?,?,?,?)",
                (uuid.uuid4().hex[:12], uid, "Examples", time.time()))
    for i, path in enumerate(seeds):
        try:
            with open(path) as fh:
                seed = json.load(fh)
            mid = f"seed{i}-{uid}"
            meta = {k: seed[k] for k in seed if k in _META_KEYS and k not in
                    ("id", "name", "project", "engine", "status", "prompt", "ts", "thumb")}
            artifacts = {k: v for k, v in seed.items() if k not in _META_KEYS}
            art_name = None
            if artifacts:
                art_name = mid + ".json"
                with open(os.path.join(ART_DIR, art_name), "w") as fh:
                    json.dump(artifacts, fh)
            con.execute(
                "INSERT OR REPLACE INTO models(id,user_id,project,name,engine,status,prompt,ts,thumb,meta,artifact) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (mid, uid, "Examples", seed.get("name", "Example"), seed.get("engine", "cad"),
                 seed.get("status", "verified"), seed.get("prompt", ""), time.time() * 1000 - i,
                 seed.get("thumb"), json.dumps(meta), art_name))
        except Exception:  # noqa: BLE001 — a bad seed must never block a signup
            continue


def main() -> int:
    init_db()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8092
    host = os.environ.get("STUDIO_BIND", "127.0.0.1")
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"studio API on http://{host}:{port}  (auth + per-user projects/models; data={DATA_DIR})", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
