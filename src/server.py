import json
import logging
import os
import sys
import threading
import time
from collections import defaultdict, deque
from copy import deepcopy
from email.utils import formatdate, parsedate_to_datetime
from functools import partial
from hashlib import sha1
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlsplit

from terraria_parser import get_player_data, get_world_data

HOST = "127.0.0.1"
PORT = int(os.environ.get("OVERLAY_PORT", "8787"))

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    BUNDLE_DIR = os.path.abspath(getattr(sys, "_MEIPASS", CODE_DIR))
    APP_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    BUNDLE_DIR = os.path.dirname(CODE_DIR)
    APP_ROOT = BUNDLE_DIR

WEB_DIR = os.path.join(BUNDLE_DIR, "web")
if not os.path.isdir(WEB_DIR):
    WEB_DIR = BUNDLE_DIR

BASE_DIR = APP_ROOT
DATA_DIR = os.environ.get("OVERLAY_DATA_DIR", os.path.join(APP_ROOT, "data"))
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except OSError:
    DATA_DIR = APP_ROOT
STATE_PATH = os.path.join(DATA_DIR, "state.json")
DEATHS_PATH = os.path.join(DATA_DIR, "deaths.txt")
LOG_PATH = os.path.join(DATA_DIR, "server.log")

_DEFAULT_TERRARIA_ROOT = os.path.join(
    os.path.expanduser("~"),
    "Documents",
    "My Games",
    "Terraria",
)
TERRARIA_PLAYERS_PATH = os.environ.get(
    "TERRARIA_PLAYERS_PATH",
    os.path.join(_DEFAULT_TERRARIA_ROOT, "Players"),
)
TERRARIA_WORLDS_PATH = os.environ.get(
    "TERRARIA_WORLDS_PATH",
    os.path.join(_DEFAULT_TERRARIA_ROOT, "Worlds"),
)

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
    "selectedPlayerFile": "",
    "selectedWorldFile": "",
    "language": "fr",
    "scrollSeconds": 22,
    "cycleSeconds": 10,
    "uiRightGutter": 320,
    "focusNextBoss": False,
    "marqueeModeLock": "auto",  # auto | boss | npc
    "showLastBossNotif": True,
    "antiSpoilCarousel": False,
    "syncRunTimerWithSave": True,
    "layoutEditMode": False,
    "timerSyncedSignature": "",
    "islandVisibility": {
        "bossToast": True,
        "marqueeBar": True,
        "webcamBox": True,
        "sessionCard": True,
        "bottomLabelCard": True,
        "bottomTimerCard": True,
        "bottomGoalCard": True,
    },
    "layoutOffsets": {
        "marqueeBar": {"x": 0, "y": 0},
        "webcamBox": {"x": 0, "y": 0},
        "sessionCard": {"x": 0, "y": 0},
        "bottomWrap": {"x": 0, "y": 0},
    },
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
MAX_REQUEST_BODY_BYTES = 32 * 1024

_last_deaths_read = 0.0
_last_deaths_val = "-"

TERRARIA_LOCK = threading.Lock()
_TERRARIA_CACHE_SIGNATURE = None
_TERRARIA_CACHE_PAYLOAD = None

LABEL_MAX_LEN = 80
GOAL_MAX_LEN = 180
WORLD_MAX_LEN = 80
SEED_MAX_LEN = 80
FILE_SELECTION_MAX_LEN = 140
MIN_SCROLL_SECONDS = 10
MAX_SCROLL_SECONDS = 120
MIN_CYCLE_SECONDS = 4
MAX_CYCLE_SECONDS = 120
MIN_UI_RIGHT_GUTTER = 0
MAX_UI_RIGHT_GUTTER = 600
MAX_TRACKED_FLAGS = 128
ALLOWED_LANGUAGES = {"fr", "en"}
ALLOWED_MARQUEE_MODES = {"auto", "boss", "npc"}
ALLOWED_TIMER_CMDS = {"start", "pause", "reset"}
ALLOWED_DEATHS_OPS = {"inc", "reset"}
MIN_LAYOUT_OFFSET = -2200
MAX_LAYOUT_OFFSET = 2200

ISLAND_VISIBILITY_DEFAULTS = {
    "bossToast": True,
    "marqueeBar": True,
    "webcamBox": True,
    "sessionCard": True,
    "bottomLabelCard": True,
    "bottomTimerCard": True,
    "bottomGoalCard": True,
}

MOVABLE_ISLAND_IDS = ("marqueeBar", "webcamBox", "sessionCard", "bottomWrap")
LAYOUT_DEFAULTS = {island_id: {"x": 0, "y": 0} for island_id in MOVABLE_ISLAND_IDS}

ERROR_MESSAGES = {
    "rate_limited": "Trop de requetes. Reessayez dans quelques secondes.",
    "content_type_must_be_application_json": "Le type de contenu doit etre application/json.",
    "invalid_json": "Le JSON envoye est invalide.",
    "patch_must_be_object": "Le patch JSON doit etre un objet.",
    "payload_too_large": "La requete est trop volumineuse pour cette API locale.",
    "invalid_language": "Langue invalide. Valeurs autorisees: fr, en.",
    "invalid_scroll_seconds": "Scroll invalide. Valeurs autorisees: 10 a 120.",
    "invalid_cycle_seconds": "Cycle invalide. Valeurs autorisees: 4 a 120.",
    "invalid_ui_right_gutter": "Valeur UI droite invalide. Autorisee: 0 a 600.",
    "invalid_marquee_mode_lock": "Mode marquee invalide. Valeurs: auto, boss, npc.",
    "invalid_done_boss": "Format doneBoss invalide.",
    "invalid_done_npc": "Format doneNpc invalide.",
    "invalid_island_visibility": "Format islandVisibility invalide.",
    "invalid_layout_offsets": "Format layoutOffsets invalide.",
    "invalid_timer_cmd": "Commande timer invalide. Valeurs: start, pause, reset.",
    "invalid_deaths_op": "Commande deaths invalide. Valeurs: inc, reset.",
    "invalid_request": "Requete invalide.",
    "internal_error": "Erreur interne serveur.",
}

_VALIDATION_ERROR_MAP = {
    "patch must be object": "patch_must_be_object",
    "invalid language": "invalid_language",
    "invalid scrollSeconds": "invalid_scroll_seconds",
    "invalid cycleSeconds": "invalid_cycle_seconds",
    "invalid uiRightGutter": "invalid_ui_right_gutter",
    "invalid marqueeModeLock": "invalid_marquee_mode_lock",
    "invalid doneBoss": "invalid_done_boss",
    "invalid doneNpc": "invalid_done_npc",
    "invalid islandVisibility": "invalid_island_visibility",
    "invalid layoutOffsets": "invalid_layout_offsets",
    "invalid layoutOffsets entry": "invalid_layout_offsets",
    "invalid layoutOffsets value": "invalid_layout_offsets",
    "invalid timerCmd": "invalid_timer_cmd",
    "invalid deathsOp": "invalid_deaths_op",
}


def _configure_logging() -> logging.Logger:
    logger = logging.getLogger("overlay_server")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(message)s")
    try:
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    except Exception:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


LOGGER = _configure_logging()


def log_event(event: str, level: str = "info", **fields):
    payload = {
        "ts": now_ms() if "now_ms" in globals() else int(time.time() * 1000),
        "event": str(event),
    }
    for key, value in fields.items():
        if value is None:
            continue
        payload[str(key)] = value
    message = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if level == "error":
        LOGGER.error(message)
    elif level == "warning":
        LOGGER.warning(message)
    else:
        LOGGER.info(message)


def new_default_state() -> dict:
    return deepcopy(DEFAULT_STATE)


def now_ms() -> int:
    return int(time.time() * 1000)


def classify_validation_error(message: str) -> str:
    key = str(message or "").strip()
    return _VALIDATION_ERROR_MAP.get(key, "invalid_request")


def api_error_payload(error_code: str, detail: str | None = None) -> dict:
    code = str(error_code or "internal_error")
    message = ERROR_MESSAGES.get(code, ERROR_MESSAGES["internal_error"])
    payload = {
        "ok": False,
        "error": code,
        "errorCode": code,
        "errorMessage": message,
    }
    if detail:
        payload["detail"] = str(detail)[:300]
    return payload


def _as_trimmed_text(value, max_len: int) -> str:
    txt = str(value).strip()
    return txt[:max_len]


def _as_int_clamped(value, minimum: int, maximum: int):
    try:
        parsed = int(value)
    except Exception:
        return None
    return max(minimum, min(maximum, parsed))


def _normalize_bool_map(value):
    if not isinstance(value, dict):
        return None
    out = {}
    for k, v in value.items():
        if len(out) >= MAX_TRACKED_FLAGS:
            break
        key = str(k).strip()
        if not key:
            continue
        out[key] = bool(v)
    return out


def _as_non_negative_int(value, maximum: int | None = None):
    try:
        parsed = int(value)
    except Exception:
        return 0
    if parsed < 0:
        return 0
    if isinstance(maximum, int):
        return min(parsed, maximum)
    return parsed


def _normalize_island_visibility_patch(value):
    if not isinstance(value, dict):
        return None
    out = {}
    for raw_key, raw_val in value.items():
        key = str(raw_key).strip()
        if key not in ISLAND_VISIBILITY_DEFAULTS:
            continue
        out[key] = bool(raw_val)
    return out


def _normalize_layout_offsets_patch(value):
    if not isinstance(value, dict):
        return None
    out = {}
    for raw_key, raw_val in value.items():
        key = str(raw_key).strip()
        if key not in LAYOUT_DEFAULTS:
            continue
        if not isinstance(raw_val, dict):
            raise ValueError("invalid layoutOffsets entry")
        x_val = _as_int_clamped(raw_val.get("x"), MIN_LAYOUT_OFFSET, MAX_LAYOUT_OFFSET)
        y_val = _as_int_clamped(raw_val.get("y"), MIN_LAYOUT_OFFSET, MAX_LAYOUT_OFFSET)
        if x_val is None or y_val is None:
            raise ValueError("invalid layoutOffsets value")
        out[key] = {"x": x_val, "y": y_val}
    return out


def ensure_overlay_layout(state: dict):
    vis = state.get("islandVisibility")
    merged_vis = dict(ISLAND_VISIBILITY_DEFAULTS)
    if isinstance(vis, dict):
        for key in ISLAND_VISIBILITY_DEFAULTS:
            if key in vis:
                merged_vis[key] = bool(vis[key])
    state["islandVisibility"] = merged_vis

    layout_offsets = state.get("layoutOffsets")
    merged_offsets = {}
    for island_id, defaults in LAYOUT_DEFAULTS.items():
        x_val = defaults["x"]
        y_val = defaults["y"]
        if isinstance(layout_offsets, dict) and isinstance(layout_offsets.get(island_id), dict):
            raw_entry = layout_offsets[island_id]
            parsed_x = _as_int_clamped(raw_entry.get("x"), MIN_LAYOUT_OFFSET, MAX_LAYOUT_OFFSET)
            parsed_y = _as_int_clamped(raw_entry.get("y"), MIN_LAYOUT_OFFSET, MAX_LAYOUT_OFFSET)
            if parsed_x is not None:
                x_val = parsed_x
            if parsed_y is not None:
                y_val = parsed_y
        merged_offsets[island_id] = {"x": x_val, "y": y_val}
    state["layoutOffsets"] = merged_offsets

    state["layoutEditMode"] = bool(state.get("layoutEditMode", False))
    state["antiSpoilCarousel"] = bool(state.get("antiSpoilCarousel", False))
    state["syncRunTimerWithSave"] = bool(state.get("syncRunTimerWithSave", True))
    state["timerSyncedSignature"] = str(state.get("timerSyncedSignature") or "")


def _timer_sync_signature(active_player: dict) -> str:
    filename = str(active_player.get("filename") or "").strip()
    if not filename:
        return ""
    playtime_ms = _as_non_negative_int(active_player.get("playtimeMs"), 3_600_000_000_000)
    mtime_ms = _as_non_negative_int(active_player.get("mtimeMs"), 9_999_999_999_999)
    return f"{filename}|{mtime_ms}|{playtime_ms}"


def sync_timer_from_save_if_needed(state: dict, terraria_payload: dict | None) -> bool:
    ensure_run_timer(state)
    ensure_overlay_layout(state)
    if not state.get("syncRunTimerWithSave", True):
        return False

    run_timer = state["runTimer"]
    if run_timer.get("running"):
        return False

    active_player = None
    if isinstance(terraria_payload, dict):
        active_player = terraria_payload.get("activePlayer")
    if not isinstance(active_player, dict):
        return False

    next_signature = _timer_sync_signature(active_player)
    if not next_signature:
        return False

    prev_signature = str(state.get("timerSyncedSignature") or "")
    if next_signature == prev_signature:
        return False

    run_timer["elapsedMs"] = _as_non_negative_int(active_player.get("playtimeMs"), 3_600_000_000_000)
    run_timer["startedAt"] = None
    run_timer["running"] = False
    state["timerSyncedSignature"] = next_signature
    return True


def validate_patch_input(patch: dict):
    if not isinstance(patch, dict):
        raise ValueError("patch must be object")

    cleaned = {}

    if "label" in patch:
        cleaned["label"] = _as_trimmed_text(patch["label"], LABEL_MAX_LEN)
    if "goal" in patch:
        cleaned["goal"] = _as_trimmed_text(patch["goal"], GOAL_MAX_LEN)
    if "worldName" in patch:
        cleaned["worldName"] = _as_trimmed_text(patch["worldName"], WORLD_MAX_LEN)
    if "seed" in patch:
        cleaned["seed"] = _as_trimmed_text(patch["seed"], SEED_MAX_LEN)
    if "selectedPlayerFile" in patch:
        cleaned["selectedPlayerFile"] = _as_trimmed_text(patch["selectedPlayerFile"], FILE_SELECTION_MAX_LEN)
    if "selectedWorldFile" in patch:
        cleaned["selectedWorldFile"] = _as_trimmed_text(patch["selectedWorldFile"], FILE_SELECTION_MAX_LEN)

    if "language" in patch:
        lang = str(patch["language"]).strip().lower()
        if lang in ALLOWED_LANGUAGES:
            cleaned["language"] = lang
        else:
            raise ValueError("invalid language")

    if "scrollSeconds" in patch:
        val = _as_int_clamped(patch["scrollSeconds"], MIN_SCROLL_SECONDS, MAX_SCROLL_SECONDS)
        if val is None:
            raise ValueError("invalid scrollSeconds")
        cleaned["scrollSeconds"] = val

    if "cycleSeconds" in patch:
        val = _as_int_clamped(patch["cycleSeconds"], MIN_CYCLE_SECONDS, MAX_CYCLE_SECONDS)
        if val is None:
            raise ValueError("invalid cycleSeconds")
        cleaned["cycleSeconds"] = val

    if "uiRightGutter" in patch:
        val = _as_int_clamped(patch["uiRightGutter"], MIN_UI_RIGHT_GUTTER, MAX_UI_RIGHT_GUTTER)
        if val is None:
            raise ValueError("invalid uiRightGutter")
        cleaned["uiRightGutter"] = val

    if "focusNextBoss" in patch:
        cleaned["focusNextBoss"] = bool(patch["focusNextBoss"])

    if "showLastBossNotif" in patch:
        cleaned["showLastBossNotif"] = bool(patch["showLastBossNotif"])

    if "antiSpoilCarousel" in patch:
        cleaned["antiSpoilCarousel"] = bool(patch["antiSpoilCarousel"])

    if "syncRunTimerWithSave" in patch:
        cleaned["syncRunTimerWithSave"] = bool(patch["syncRunTimerWithSave"])

    if "layoutEditMode" in patch:
        cleaned["layoutEditMode"] = bool(patch["layoutEditMode"])

    if "marqueeModeLock" in patch:
        mode = str(patch["marqueeModeLock"]).strip().lower()
        if mode in ALLOWED_MARQUEE_MODES:
            cleaned["marqueeModeLock"] = mode
        else:
            raise ValueError("invalid marqueeModeLock")

    if "doneBoss" in patch:
        norm = _normalize_bool_map(patch["doneBoss"])
        if norm is None:
            raise ValueError("invalid doneBoss")
        cleaned["doneBoss"] = norm

    if "doneNpc" in patch:
        norm = _normalize_bool_map(patch["doneNpc"])
        if norm is None:
            raise ValueError("invalid doneNpc")
        cleaned["doneNpc"] = norm

    if "islandVisibility" in patch:
        norm = _normalize_island_visibility_patch(patch["islandVisibility"])
        if norm is None:
            raise ValueError("invalid islandVisibility")
        cleaned["islandVisibility"] = norm

    if "layoutOffsets" in patch:
        norm = _normalize_layout_offsets_patch(patch["layoutOffsets"])
        if norm is None:
            raise ValueError("invalid layoutOffsets")
        cleaned["layoutOffsets"] = norm

    timer_cmd = None
    if "timerCmd" in patch:
        cmd = str(patch["timerCmd"]).strip().lower()
        if cmd in ALLOWED_TIMER_CMDS:
            timer_cmd = cmd
        else:
            raise ValueError("invalid timerCmd")

    deaths_op = None
    if "deathsOp" in patch:
        op = str(patch["deathsOp"]).strip().lower()
        if op in ALLOWED_DEATHS_OPS:
            deaths_op = op
        else:
            raise ValueError("invalid deathsOp")

    return cleaned, timer_cmd, deaths_op


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
    except Exception as exc:
        log_event("deaths_read_error", level="warning", path=DEATHS_PATH, detail=str(exc))
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
        state = new_default_state()
        ensure_run_timer(state)
        ensure_overlay_layout(state)
        return state
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            state = new_default_state()
            ensure_run_timer(state)
            ensure_overlay_layout(state)
            return state
        merged = new_default_state()
        merged.update(data)
        ensure_run_timer(merged)
        ensure_overlay_layout(merged)
        return merged
    except Exception:
        log_event("state_load_error", level="warning", path=STATE_PATH)
        state = new_default_state()
        ensure_run_timer(state)
        ensure_overlay_layout(state)
        return state


def save_state(data: dict) -> None:
    tmp = STATE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception as exc:
        log_event("state_save_error", level="error", path=STATE_PATH, detail=str(exc))
        raise


def state_last_modified_epoch() -> int:
    mtimes = []
    for path in (STATE_PATH, DEATHS_PATH):
        try:
            mtimes.append(int(os.path.getmtime(path)))
        except OSError:
            continue
    return max(mtimes) if mtimes else int(time.time())


def build_public_state() -> dict:
    with STATE_LOCK:
        state = load_state()
        terraria_payload = None
        try:
            terraria_payload = build_terraria_state(state_override=state)
        except Exception as exc:
            log_event("terraria_state_build_error", level="warning", detail=str(exc))
            terraria_payload = None

        if sync_timer_from_save_if_needed(state, terraria_payload):
            save_state(state)
            log_event("timer_synced_from_save", elapsed_ms=state["runTimer"].get("elapsedMs", 0))

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


def drain_request_body(stream, total_bytes: int) -> None:
    remaining = max(0, int(total_bytes))
    while remaining > 0:
        chunk = stream.read(min(remaining, 8192))
        if not chunk:
            break
        remaining -= len(chunk)


def _safe_display_name(value, fallback: str) -> str:
    txt = str(value or "").replace("\x00", " ").strip()
    txt = " ".join(txt.split())
    if not txt:
        txt = fallback
    return txt[:80]


def _list_save_files(folder_path: str, suffix: str):
    if not os.path.isdir(folder_path):
        return []

    rows = []
    for name in os.listdir(folder_path):
        if not name.lower().endswith(suffix):
            continue
        full = os.path.join(folder_path, name)
        try:
            st = os.stat(full)
        except OSError:
            continue
        rows.append(
            {
                "filename": name,
                "path": full,
                "mtimeMs": int(st.st_mtime * 1000),
                "sizeBytes": int(st.st_size),
            }
        )
    rows.sort(key=lambda it: it["mtimeMs"], reverse=True)
    return rows


def _snapshot_signature(players_raw, worlds_raw, selected_player_file: str, selected_world_file: str):
    players_sig = tuple((it["filename"], it["mtimeMs"], it["sizeBytes"]) for it in players_raw)
    worlds_sig = tuple((it["filename"], it["mtimeMs"], it["sizeBytes"]) for it in worlds_raw)
    return players_sig, worlds_sig, selected_player_file, selected_world_file


def _player_entity(row: dict) -> dict:
    fallback = os.path.splitext(row["filename"])[0].replace("_", " ")
    parsed = get_player_data(row["path"])
    playtime_ms = int(parsed.get("playtime_ms", 0) or 0)
    return {
        "filename": row["filename"],
        "displayName": _safe_display_name(parsed.get("name"), fallback),
        "mtimeMs": row["mtimeMs"],
        "sizeBytes": row["sizeBytes"],
        "difficulty": int(parsed.get("difficulty", 0) or 0),
        "playtimeMs": playtime_ms,
        "playtimeHours": float(parsed.get("playtime_hours", 0) or 0),
        "playtimeLabel": str(parsed.get("playtime_label", "0h 0m") or "0h 0m"),
    }


def _world_entity(row: dict) -> dict:
    fallback = os.path.splitext(row["filename"])[0].replace("_", " ")
    parsed = get_world_data(row["path"])
    return {
        "filename": row["filename"],
        "displayName": _safe_display_name(parsed.get("name"), fallback),
        "mtimeMs": row["mtimeMs"],
        "sizeBytes": row["sizeBytes"],
    }


def _pick_active_entity(items: list[dict], selected_filename: str):
    chosen = (selected_filename or "").strip()
    if chosen:
        for item in items:
            if item.get("filename") == chosen:
                return item
    if items:
        return items[0]
    return None


def build_terraria_state(state_override: dict | None = None) -> dict:
    global _TERRARIA_CACHE_PAYLOAD, _TERRARIA_CACHE_SIGNATURE

    state = state_override if isinstance(state_override, dict) else load_state()
    selected_player = str(state.get("selectedPlayerFile") or "").strip()
    selected_world = str(state.get("selectedWorldFile") or "").strip()

    players_raw = _list_save_files(TERRARIA_PLAYERS_PATH, ".plr")
    worlds_raw = _list_save_files(TERRARIA_WORLDS_PATH, ".wld")
    signature = _snapshot_signature(players_raw, worlds_raw, selected_player, selected_world)

    with TERRARIA_LOCK:
        if _TERRARIA_CACHE_SIGNATURE == signature and isinstance(_TERRARIA_CACHE_PAYLOAD, dict):
            return dict(_TERRARIA_CACHE_PAYLOAD)

    players = [_player_entity(row) for row in players_raw]
    worlds = [_world_entity(row) for row in worlds_raw]
    active_player = _pick_active_entity(players, selected_player)
    active_world = _pick_active_entity(worlds, selected_world)

    payload = {
        "playersPath": TERRARIA_PLAYERS_PATH,
        "worldsPath": TERRARIA_WORLDS_PATH,
        "players": players,
        "worlds": worlds,
        "selectedPlayerFile": selected_player,
        "selectedWorldFile": selected_world,
        "activePlayer": active_player,
        "activeWorld": active_world,
        "effectivePlayerFile": active_player["filename"] if active_player else "",
        "effectiveWorldFile": active_world["filename"] if active_world else "",
        "updatedAt": now_ms(),
    }

    with TERRARIA_LOCK:
        _TERRARIA_CACHE_SIGNATURE = signature
        _TERRARIA_CACHE_PAYLOAD = dict(payload)

    return payload


def terraria_last_modified_epoch(payload: dict) -> int:
    latest_ms = 0
    for item in payload.get("players", []):
        latest_ms = max(latest_ms, int(item.get("mtimeMs", 0) or 0))
    for item in payload.get("worlds", []):
        latest_ms = max(latest_ms, int(item.get("mtimeMs", 0) or 0))
    if latest_ms <= 0:
        return int(time.time())
    return latest_ms // 1000


def perform_boot_sync():
    """Synchronise le timer avec la save active au demarrage."""
    try:
        with STATE_LOCK:
            state = load_state()
            terraria_payload = build_terraria_state(state_override=state)
            if sync_timer_from_save_if_needed(state, terraria_payload):
                save_state(state)
                log_event("boot_timer_sync_applied", elapsed_ms=state["runTimer"].get("elapsedMs", 0))
    except Exception as exc:
        log_event("boot_timer_sync_error", level="warning", detail=str(exc))


class Handler(SimpleHTTPRequestHandler):
    server_version = "TerrariaOverlay/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args):
        # Logs HTTP standards in structured format.
        try:
            message = fmt % args
        except Exception:
            message = fmt
        log_event(
            "http_access",
            method=getattr(self, "command", ""),
            path=getattr(self, "path", ""),
            client_ip=self.client_address[0] if self.client_address else "unknown",
            message=message,
        )

    def _path(self) -> str:
        return urlsplit(self.path).path

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

    def _send_api_error(self, error_code: str, http_code: int = 400, detail: str | None = None, extra_headers: dict | None = None):
        payload = api_error_payload(error_code, detail)
        self._send_json(payload, code=http_code, extra_headers=extra_headers)

    def _send_redirect(self, location: str):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def do_GET(self):
        if self._path() == "/":
            self._send_redirect("/control.html")
            return
        if self._path() == "/api/state":
            payload = build_public_state()
            etag = etag_for_payload(payload)
            lm_epoch = state_last_modified_epoch()
            lm_http = formatdate(lm_epoch, usegmt=True)

            inm = (self.headers.get("If-None-Match") or "").strip()
            ims = (self.headers.get("If-Modified-Since") or "").strip()

            not_modified = False
            # Regle: If-None-Match est prioritaire; If-Modified-Since sert de repli.
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
        if self._path() == "/api/terraria":
            payload = build_terraria_state()
            etag = etag_for_payload(payload)
            lm_epoch = terraria_last_modified_epoch(payload)
            lm_http = formatdate(lm_epoch, usegmt=True)

            inm = (self.headers.get("If-None-Match") or "").strip()
            ims = (self.headers.get("If-Modified-Since") or "").strip()

            not_modified = False
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
        if self._path() == "/api/state":
            client_ip = self.client_address[0] if self.client_address else "unknown"
            if not check_rate_limit(client_ip):
                log_event("api_state_rate_limited", level="warning", client_ip=client_ip)
                self._send_api_error("rate_limited", http_code=429, extra_headers={"Retry-After": "1"})
                return

            ctype = (self.headers.get("Content-Type") or "").lower()
            if "application/json" not in ctype:
                log_event("api_state_invalid_content_type", level="warning", content_type=ctype, client_ip=client_ip)
                self._send_api_error("content_type_must_be_application_json", http_code=415)
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0:
                    raise ValueError("negative content length")
                if length > MAX_REQUEST_BODY_BYTES:
                    drain_request_body(self.rfile, length)
                    log_event(
                        "api_state_payload_too_large",
                        level="warning",
                        client_ip=client_ip,
                        content_length=length,
                        max_bytes=MAX_REQUEST_BODY_BYTES,
                    )
                    self._send_api_error("payload_too_large", http_code=413)
                    return
                body = self.rfile.read(length) if length > 0 else b"{}"
                patch = json.loads(body.decode("utf-8"))
                cleaned, timer_cmd, deaths_op = validate_patch_input(patch)

                with STATE_LOCK:
                    state = load_state()
                    prev_done_boss = dict(state.get("doneBoss") or {})

                    for k, v in cleaned.items():
                        if k == "islandVisibility" and isinstance(v, dict):
                            merged_vis = dict(state.get("islandVisibility") or {})
                            merged_vis.update(v)
                            state["islandVisibility"] = merged_vis
                            continue
                        if k == "layoutOffsets" and isinstance(v, dict):
                            merged_layout = dict(state.get("layoutOffsets") or {})
                            for island_id, offset in v.items():
                                merged_layout[island_id] = offset
                            state["layoutOffsets"] = merged_layout
                            continue
                        state[k] = v

                    ensure_run_timer(state)
                    ensure_overlay_layout(state)

                    if timer_cmd:
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

                    if deaths_op:
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

                    try:
                        terraria_payload = build_terraria_state(state_override=state)
                    except Exception:
                        terraria_payload = None

                    sync_timer_from_save_if_needed(state, terraria_payload)

                    save_state(state)

                payload = build_public_state()
                log_event(
                    "api_state_patch_ok",
                    client_ip=client_ip,
                    fields=list(cleaned.keys()),
                    timer_cmd=timer_cmd,
                    deaths_op=deaths_op,
                )
                self._send_json(payload)
            except json.JSONDecodeError as exc:
                log_event("api_state_invalid_json", level="warning", client_ip=client_ip, detail=str(exc))
                self._send_api_error("invalid_json", http_code=400)
            except ValueError as exc:
                code = classify_validation_error(str(exc))
                log_event("api_state_validation_error", level="warning", client_ip=client_ip, error_code=code, detail=str(exc))
                self._send_api_error(code, http_code=400)
            except Exception as exc:
                log_event("api_state_unhandled_error", level="error", client_ip=client_ip, detail=str(exc))
                self._send_api_error("internal_error", http_code=500)
            return

        self.send_response(404)
        self.end_headers()


def create_http_server(port: int):
    return ThreadingHTTPServer((HOST, port), partial(Handler, directory=WEB_DIR))


if __name__ == "__main__":
    perform_boot_sync()
    log_event(
        "server_starting",
        host=HOST,
        port=PORT,
        app_root=APP_ROOT,
        code_dir=CODE_DIR,
        web_dir=WEB_DIR,
        data_dir=DATA_DIR,
        players_path=TERRARIA_PLAYERS_PATH,
        worlds_path=TERRARIA_WORLDS_PATH,
    )
    httpd = create_http_server(PORT)
    print(f"Server running on http://{HOST}:{PORT}")
    httpd.serve_forever()
