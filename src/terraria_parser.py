"""Terraria save metadata helpers.

This parser focuses on robust, user-facing metadata:
- readable player/world names
- decrypted player total playtime from .plr when possible
"""

from __future__ import annotations

import os
import re
import struct
import unicodedata
from datetime import datetime, timezone

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except Exception:  # pragma: no cover
    Cipher = None
    algorithms = None
    modes = None

_SCAN_LIMIT_BYTES = 768 * 1024
_CANDIDATE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _'\\-]{2,80}")
_NOISE_WORDS = {"relogic", "logic", "true", "false", "master", "expert"}

_PLAYER_KEY_SEED = "h3y_gUyZ"
_PLAYER_AES_KEY = _PLAYER_KEY_SEED.encode("utf-16le")
_MAX_REASONABLE_PLAYTIME_TICKS = 3_600_000_000_000_000  # ~100 000 hours


def _collapse_spaces(value: str) -> str:
    return " ".join(value.split())


def _display_name_from_filename(file_path: str) -> str:
    base = os.path.splitext(os.path.basename(file_path))[0]
    return _collapse_spaces(base.replace("_", " "))


def _normalize_tokens(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return {tok for tok in re.split(r"[^a-z0-9]+", folded.lower()) if tok}


def _cleanup_candidate(candidate: str) -> str:
    cleaned = _collapse_spaces(candidate)
    # Seeds may be appended as trailing long numeric chunks.
    cleaned = re.sub(r"\s+\d{5,}$", "", cleaned)
    return _collapse_spaces(cleaned)


def _extract_world_name(world_file_path: str, fallback_name: str) -> str:
    try:
        with open(world_file_path, "rb") as f:
            raw = f.read(_SCAN_LIMIT_BYTES)
    except OSError:
        return fallback_name

    text = raw.decode("utf-8", errors="ignore")
    clean_text = "".join(ch if ch.isprintable() and ch != "\x00" else " " for ch in text)

    fallback_tokens = _normalize_tokens(fallback_name)
    if not fallback_tokens:
        return fallback_name

    best_name = fallback_name
    best_score = float("-inf")

    for match in _CANDIDATE_RE.finditer(clean_text):
        candidate = _cleanup_candidate(match.group(0).strip())
        if len(candidate) < 3:
            continue

        candidate_tokens = _normalize_tokens(candidate)
        if not candidate_tokens:
            continue
        if candidate.lower() in _NOISE_WORDS:
            continue

        overlap = len(candidate_tokens & fallback_tokens)
        if overlap == 0:
            continue

        letter_count = sum(ch.isalpha() for ch in candidate)
        digit_count = sum(ch.isdigit() for ch in candidate)
        alpha_ratio = letter_count / max(1, len(candidate))
        if alpha_ratio < 0.40:
            continue

        score = (overlap * 14.0) + (alpha_ratio * 3.0) - (digit_count * 0.25)
        if 3 <= len(candidate) <= 48:
            score += 1.0

        if score > best_score:
            best_score = score
            best_name = candidate

    return best_name


def _file_stats(file_path: str) -> dict:
    try:
        st = os.stat(file_path)
    except OSError:
        return {}

    modified_ms = int(st.st_mtime * 1000)
    modified_iso = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "file_size_bytes": int(st.st_size),
        "last_modified_ms": modified_ms,
        "last_modified_iso": modified_iso,
    }


def _looks_like_player_payload(raw: bytes) -> bool:
    return len(raw) >= 20 and raw[4:11] == b"relogic"


def _decrypt_player_bytes(raw: bytes) -> bytes:
    if len(raw) == 0 or _looks_like_player_payload(raw):
        return raw
    if Cipher is None or len(raw) % 16 != 0:
        return raw
    try:
        decryptor = Cipher(algorithms.AES(_PLAYER_AES_KEY), modes.CBC(_PLAYER_AES_KEY)).decryptor()
        return decryptor.update(raw) + decryptor.finalize()
    except Exception:
        return raw


def _read_7bit_int(raw: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(5):
        if pos >= len(raw):
            raise ValueError("unexpected end while reading 7-bit int")
        b = raw[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return value, pos
        shift += 7
    raise ValueError("invalid 7-bit int encoding")


def _read_lp_string(raw: bytes, pos: int) -> tuple[str, int]:
    size, pos = _read_7bit_int(raw, pos)
    if size < 0 or pos + size > len(raw):
        raise ValueError("invalid string size")
    value = raw[pos : pos + size].decode("utf-8", errors="ignore")
    return value, pos + size


def _skip_player_header_map(raw: bytes, pos: int) -> int:
    if pos + 2 > len(raw):
        raise ValueError("missing metadata map length")
    map_len = struct.unpack_from("<H", raw, pos)[0]
    pos += 2

    for _ in range(map_len):
        _, pos = _read_lp_string(raw, pos)
        if pos >= len(raw):
            raise ValueError("invalid map value type")
        value_type = raw[pos]
        pos += 1

        if value_type == 0:  # int32
            pos += 4
        elif value_type == 1:  # string
            _, pos = _read_lp_string(raw, pos)
        elif value_type == 2:  # bool
            pos += 1
        elif value_type == 3:  # bytes
            if pos + 4 > len(raw):
                raise ValueError("invalid bytes length")
            byte_len = struct.unpack_from("<I", raw, pos)[0]
            pos += 4 + byte_len
        elif value_type in (4, 5):  # int64 / double
            pos += 8
        else:
            raise ValueError("unsupported metadata type")

        if pos > len(raw):
            raise ValueError("metadata map overflow")
    return pos


def _player_name_candidates(fallback_name: str) -> list[bytes]:
    options = []
    raw = str(fallback_name or "").strip()
    if raw:
        options.append(raw)
        options.append(raw.replace(" ", "_"))
        options.append(raw.replace("_", " "))
    seen = set()
    out = []
    for item in options:
        if not item:
            continue
        b = item.encode("utf-8", errors="ignore")
        if not b or b in seen:
            continue
        seen.add(b)
        out.append(b)
    return out


def _is_reasonable_name(name: str) -> bool:
    n = _collapse_spaces(name)
    if len(n) < 1 or len(n) > 32:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9 _'\-]+", n))


def _try_extract_name_and_playtime(raw: bytes, fallback_name: str):
    # 1) Prefer explicit file-name based hits for stability.
    for candidate in _player_name_candidates(fallback_name):
        start = 0
        while True:
            idx = raw.find(candidate, start)
            if idx < 0:
                break
            start = idx + 1
            if idx == 0:
                continue
            if raw[idx - 1] != len(candidate):
                continue
            after_name = idx + len(candidate)
            if after_name + 9 > len(raw):
                continue
            difficulty = int(raw[after_name])
            if not (0 <= difficulty <= 3):
                continue
            ticks = struct.unpack_from("<q", raw, after_name + 1)[0]
            if ticks < 0 or ticks > _MAX_REASONABLE_PLAYTIME_TICKS:
                continue
            name = candidate.decode("utf-8", errors="ignore")
            return _collapse_spaces(name), difficulty, ticks

    # 2) Generic scan fallback near header area.
    scan_limit = min(len(raw), 220)
    for pos in range(16, scan_limit - 12):
        name_len = int(raw[pos])
        if name_len <= 0 or name_len > 32:
            continue
        name_start = pos + 1
        name_end = name_start + name_len
        if name_end + 9 > len(raw):
            continue

        try:
            name = raw[name_start:name_end].decode("utf-8", errors="ignore")
        except Exception:
            continue
        if not _is_reasonable_name(name):
            continue

        difficulty = int(raw[name_end])
        if not (0 <= difficulty <= 3):
            continue
        ticks = struct.unpack_from("<q", raw, name_end + 1)[0]
        if ticks < 0 or ticks > _MAX_REASONABLE_PLAYTIME_TICKS:
            continue
        return _collapse_spaces(name), difficulty, ticks

    raise ValueError("unable to locate player name/playtime fields")


def _parse_player_payload(raw: bytes, fallback_name: str = "") -> dict:
    if not _looks_like_player_payload(raw):
        raise ValueError("not a Terraria player payload")
    if len(raw) < 26:
        raise ValueError("payload too small")

    version = struct.unpack_from("<I", raw, 0)[0]
    file_type = int(raw[11])
    revision = struct.unpack_from("<I", raw, 12)[0]
    is_favorite = bool(raw[16])
    name, difficulty, playtime_ticks = _try_extract_name_and_playtime(raw, fallback_name)

    playtime_ms = max(0, int(playtime_ticks // 10_000))
    return {
        "name": _collapse_spaces(name),
        "version": int(version),
        "file_type": file_type,
        "revision": int(revision),
        "is_favorite": bool(is_favorite),
        "difficulty": int(difficulty),
        "playtime_ticks": int(playtime_ticks),
        "playtime_ms": int(playtime_ms),
        "playtime_hours": round(playtime_ms / 3_600_000, 2),
        "playtime_label": format_playtime(playtime_ms),
    }


def get_player_data(player_file_path: str) -> dict:
    fallback_name = _display_name_from_filename(player_file_path)
    payload = {
        "name": fallback_name,
        "filename": os.path.splitext(os.path.basename(player_file_path))[0],
        "health": 0,
        "mana": 0,
        "difficulty": 0,
        "playtime_ticks": 0,
        "playtime_ms": 0,
        "playtime_hours": 0,
        "playtime_label": "0h 0m",
    }

    try:
        with open(player_file_path, "rb") as f:
            encrypted = f.read()
        decrypted = _decrypt_player_bytes(encrypted)
        parsed = _parse_player_payload(decrypted, fallback_name=fallback_name)
        payload.update(parsed)
        if not payload.get("name"):
            payload["name"] = fallback_name
    except Exception:
        # Keep fallback payload if decrypt/parse fails.
        pass

    payload.update(_file_stats(player_file_path))
    return payload


def get_world_data(world_file_path: str) -> dict:
    fallback_name = _display_name_from_filename(world_file_path)
    parsed_name = _extract_world_name(world_file_path, fallback_name)
    payload = {
        "name": parsed_name,
        "filename": os.path.splitext(os.path.basename(world_file_path))[0],
    }
    payload.update(_file_stats(world_file_path))
    return payload


def format_playtime(milliseconds: int) -> str:
    if milliseconds <= 0:
        return "0h 0m"

    seconds = int(milliseconds // 1000)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


if __name__ == "__main__":
    terraria_root = os.environ.get(
        "TERRARIA_ROOT",
        os.path.join(os.path.expanduser("~"), "Documents", "My Games", "Terraria"),
    )
    players_path = os.environ.get("TERRARIA_PLAYERS_PATH", os.path.join(terraria_root, "Players"))
    worlds_path = os.environ.get("TERRARIA_WORLDS_PATH", os.path.join(terraria_root, "Worlds"))

    if os.path.exists(players_path):
        players = [f for f in os.listdir(players_path) if f.endswith(".plr")]
        if players:
            player_file = os.path.join(players_path, players[0])
            print("Player:", get_player_data(player_file))

    if os.path.exists(worlds_path):
        worlds = [f for f in os.listdir(worlds_path) if f.endswith(".wld")]
        if worlds:
            world_file = os.path.join(worlds_path, worlds[0])
            print("World:", get_world_data(world_file))
