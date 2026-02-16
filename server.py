import json
import os
import threading
import time
from collections import defaultdict, deque
from email.utils import formatdate, parsedate_to_datetime
from hashlib import sha1
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HOST = "127.0.0.1"
PORT = int(os.environ.get("OVERLAY_PORT", "8787"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "state.json")
DEATHS_PATH = os.path.join(BASE_DIR, "deaths.txt")

BOSS_NAME_BY_SLUG = {
    "king-slime": "King Slime",
    "eye-of-cthulhu": "Eye of Cthulhu",
    "eater-of-worlds": "Eater of Worlds",
    "brain-of-cthulhu": "Brain of Cthulhu",
    "queen-bee": "Queen Bee",
    "skeletron": "Skeletron",
    "deerclops": "Deerclops",
    "wall-of-flesh": "Wall of Flesh",
    "queen-slime": "Queen Slime",
    "the-twins": "The Twins",
    "the-destroyer": "The Destroyer",
    "skeletron-prime": "Skeletron Prime",
    "plantera": "Plantera",
    "golem": "Golem",
    "duke-fishron": "Duke Fishron",
    "empress-of-light": "Empress of Light",
    "lunatic-cultist": "Lunatic Cultist",
    "moon-lord": "Moon Lord",
}

DEFAULT_STATE = {
    "label": "MASTER MODE",
    "goal": "",
    "worldName": "",
    "seed": "",
    "language": "fr",
    "scrollSeconds": 22,
    "cycleSeconds": 10,
    "uiRightGutter": 320,
    "focusNextBoss": False,
    "marqueeModeLock": "auto",  # auto | boss | npc
    "showLastBossNotif": True,
    "doneBoss": {},
    "doneNpc": {},
    "runTimer": {
        "running": False,
        "elapsedMs": 0,
        "startedAt": None,
    },
    "lastDefeatedBoss": None,
}

STATE_LOCK = threading.Lock()

RATE_WINDOW_SECONDS = 2.0
RATE_MAX_REQUESTS = 25
REQUEST_LOG = defaultdict(deque)

_last_deaths_read = 0.0
_last_deaths_val = "-"


def now_ms() -> int:
    return int(time.time() * 1000)


def ensure_run_timer(state: dict) -> dict:
    rt = state.get("runTimer")
    if not isinstance(rt, dict):
        rt = {}
    fixed = {
        "running": bool(rt.get("running", False)),
        "elapsedMs": int(rt.get("elapsedMs", 0) or 0),
        "startedAt": rt.get("startedAt"),
    }
    if fixed["startedAt"] is not None:
        try:
            fixed["startedAt"] = int(fixed["startedAt"])
        except Exception:
            fixed["startedAt"] = None
    state["runTimer"] = fixed
    return fixed


def read_deaths() -> str:
    global _last_deaths_read, _last_deaths_val
    now = time.time()
    if now - _last_deaths_read < 0.5:
        return _last_deaths_val
    _last_deaths_read = now
    try:
        with open(DEATHS_PATH, "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read().strip()
            _last_deaths_val = txt if txt != "" else "0"
    except FileNotFoundError:
        _last_deaths_val = "-"
    return _last_deaths_val


def write_deaths(val: str) -> None:
    with open(DEATHS_PATH, "w", encoding="utf-8") as f:
        f.write(val)
    global _last_deaths_read, _last_deaths_val
    _last_deaths_read = 0.0
    _last_deaths_val = val


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        state = dict(DEFAULT_STATE)
        ensure_run_timer(state)
        return state
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            state = dict(DEFAULT_STATE)
            ensure_run_timer(state)
            return state
        merged = dict(DEFAULT_STATE)
        merged.update(data)
        ensure_run_timer(merged)
        return merged
    except Exception:
        state = dict(DEFAULT_STATE)
        ensure_run_timer(state)
        return state


def save_state(data: dict) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def state_last_modified_epoch() -> int:
    mtimes = []
    for path in (STATE_PATH, DEATHS_PATH):
        try:
            mtimes.append(int(os.path.getmtime(path)))
        except OSError:
            continue
    return max(mtimes) if mtimes else int(time.time())


def build_public_state() -> dict:
    state = load_state()
    rt = ensure_run_timer(state)
    elapsed = int(rt.get("elapsedMs", 0) or 0)
    if rt.get("running") and isinstance(rt.get("startedAt"), int):
        elapsed += max(0, now_ms() - rt["startedAt"])
    state["runElapsedMs"] = elapsed
    state["deaths"] = read_deaths()
    return state


def etag_for_payload(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return '"' + sha1(raw).hexdigest() + '"'


def check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    q = REQUEST_LOG[client_ip]
    while q and now - q[0] > RATE_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= RATE_MAX_REQUESTS:
        return False
    q.append(now)
    return True


def parse_http_date(value: str):
    try:
        dt = parsedate_to_datetime(value)
        return int(dt.timestamp())
    except Exception:
        return None


class Handler(SimpleHTTPRequestHandler):
    def _send_json(self, payload: dict, code: int = 200, extra_headers: dict | None = None):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_304(self, extra_headers: dict | None = None):
        self.send_response(304)
        self.send_header("Cache-Control", "no-cache")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/state"):
            payload = build_public_state()
            etag = etag_for_payload(payload)
            lm_epoch = state_last_modified_epoch()
            lm_http = formatdate(lm_epoch, usegmt=True)

            inm = (self.headers.get("If-None-Match") or "").strip()
            ims = (self.headers.get("If-Modified-Since") or "").strip()

            not_modified = False
            # RFC behavior: If-None-Match has precedence over If-Modified-Since.
            if inm:
                not_modified = (inm == etag or inm == "*")
            elif ims:
                ims_epoch = parse_http_date(ims)
                if ims_epoch is not None and ims_epoch >= lm_epoch:
                    not_modified = True

            headers = {"ETag": etag, "Last-Modified": lm_http}
            if not_modified:
                self._send_304(headers)
                return

            self._send_json(payload, extra_headers=headers)
            return
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/state"):
            client_ip = self.client_address[0] if self.client_address else "unknown"
            if not check_rate_limit(client_ip):
                self._send_json({"error": "rate_limited"}, code=429, extra_headers={"Retry-After": "1"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b"{}"
                patch = json.loads(body.decode("utf-8"))
                if not isinstance(patch, dict):
                    raise ValueError("patch must be object")

                with STATE_LOCK:
                    state = load_state()
                    prev_done_boss = dict(state.get("doneBoss") or {})

                    allowed = {
                        "label",
                        "goal",
                        "worldName",
                        "seed",
                        "language",
                        "scrollSeconds",
                        "cycleSeconds",
                        "uiRightGutter",
                        "focusNextBoss",
                        "marqueeModeLock",
                        "showLastBossNotif",
                        "doneBoss",
                        "doneNpc",
                    }
                    for k, v in patch.items():
                        if k in allowed:
                            state[k] = v

                    ensure_run_timer(state)

                    timer_cmd = patch.get("timerCmd")
                    if timer_cmd in {"start", "pause", "reset"}:
                        rt = state["runTimer"]
                        tnow = now_ms()
                        if timer_cmd == "start":
                            if not rt["running"]:
                                rt["running"] = True
                                rt["startedAt"] = tnow
                        elif timer_cmd == "pause":
                            if rt["running"] and isinstance(rt["startedAt"], int):
                                rt["elapsedMs"] += max(0, tnow - rt["startedAt"])
                            rt["running"] = False
                            rt["startedAt"] = None
                        elif timer_cmd == "reset":
                            rt["elapsedMs"] = 0
                            if rt["running"]:
                                rt["startedAt"] = tnow
                            else:
                                rt["startedAt"] = None

                    deaths_op = patch.get("deathsOp")
                    if deaths_op in {"inc", "reset"}:
                        cur_raw = read_deaths()
                        try:
                            cur_num = int(cur_raw)
                        except Exception:
                            cur_num = 0
                        if deaths_op == "inc":
                            write_deaths(str(cur_num + 1))
                        else:
                            write_deaths("0")

                    new_done_boss = dict(state.get("doneBoss") or {})
                    newly_done = [
                        slug
                        for slug, is_done in new_done_boss.items()
                        if is_done and not bool(prev_done_boss.get(slug))
                    ]
                    if newly_done:
                        slug = newly_done[-1]
                        state["lastDefeatedBoss"] = {
                            "slug": slug,
                            "name": BOSS_NAME_BY_SLUG.get(slug, slug),
                            "at": now_ms(),
                        }

                    save_state(state)

                payload = build_public_state()
                self._send_json(payload)
            except Exception as e:
                self._send_json({"error": str(e)}, 400)
            return

        self.send_response(404)
        self.end_headers()


if __name__ == "__main__":
    os.chdir(BASE_DIR)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Server running on http://{HOST}:{PORT}")
    httpd.serve_forever()
