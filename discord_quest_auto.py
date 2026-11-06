"""
discord_quest_auto.py - Tự động hoàn thành Discord Quests (schema mới 2026).

ĐÃ VERIFY THỰC TẾ trên tài khoản thật:
    GET   /quests/@me                    -> danh sách quest
    POST  /quests/{id}/enroll            {"location": 0}
    POST  /quests/{id}/heartbeat         {"event_name": "PLAY_ON_DESKTOP", "timestamp": ...}
    POST  /quests/{id}/video-progress    {"timestamp": <giây, nhảy tối đa ~40s/lần>}
    POST  /quests/{id}/claim-reward      {"platform": 0, "location": 0}

CÁCH DÙNG
    python discord_quest_auto.py <token>             # làm tất cả (mặc định)
    python discord_quest_auto.py <token> --list      # chỉ xem danh sách
    python discord_quest_auto.py <token> --id <id>   # làm 1 quest

    # Colab:
    #   from google.colab import files; files.upload()
    #   !python discord_quest_auto.py TOKEN_O_DAY

TOKEN
    tham số 1 (positional)  ->  --token  ->  $DISCORD_TOKEN  ->  token.txt  ->  hỏi tay

GHI CHÚ
    - Quest PLAY_ON_DESKTOP không cần chạy game thật: /heartbeat tự cộng tiến độ
      theo thời gian (server chặn ~1 value/giây nên 900s quest = ~15 phút thật).
      Nhiều quest chạy song song cùng lúc nên 15 phút là xong hết.
    - Quest WATCH_VIDEO dùng /video-progress với timestamp (GIÂY). Mỗi call server
      cho nhảy tối đa ~40s -> video 142s xong trong ~4 call.
    - Bước claim có thể bị hCaptcha -> script báo rõ, bạn bấm Claim trong app.
    - Tự động hoá tài khoản vi phạm ToS Discord. Tự chịu rủi ro.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://discord.com/api/v10"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) discord/1.0.9186 Chrome/128.0.6613.186 "
    "Electron/32.2.7 Safari/537.36"
)

# Discord ẩn hết quest nếu client_build_number quá cũ (339450 -> 0 quest,
# 380000 -> 33 quest). Script tự dò build cho tới khi thấy quest.
BUILD_CANDIDATES: list[tuple[int, str]] = [
    (410000, "1.0.9195"),   # thấy cả quest WATCH_VIDEO
    (400000, "1.0.9192"),
    (380000, "1.0.9186"),
    (339450, "1.0.9175"),
]

TASK_LABELS = {
    "PLAY_ON_DESKTOP": "Chơi game trên PC",
    "PLAY_ON_XBOX": "Chơi trên Xbox",
    "PLAY_ON_PLAYSTATION": "Chơi trên PlayStation",
    "WATCH_VIDEO": "Xem video",
    "WATCH_VIDEO_ON_MOBILE": "Xem video (mobile)",
    "STREAM_ON_DESKTOP": "Stream game",
    "PLAY_ACTIVITY": "Chơi activity",
    "ACHIEVEMENT_IN_ACTIVITY": "Thành tích activity",
}

# Quest xem video dùng /video-progress (timestamp = vị trí video, ms, <= 600000)
VIDEO_TASKS = {"WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE"}

try:
    from curl_cffi import requests as _cffi
except Exception:  # pragma: no cover
    _cffi = None

try:
    import requests as _requests
except Exception:  # pragma: no cover
    _requests = None


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def _b64(obj: object) -> str:
    return base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()


_SP_CACHE: dict[tuple[int, str], str] = {}


def super_props(build: int, version: str) -> str:
    key = (build, version)
    if key not in _SP_CACHE:
        _SP_CACHE[key] = _b64({
            "os": "Windows",
            "browser": "Discord Client",
            "release_channel": "stable",
            "client_version": version,
            "os_version": "10.0.22631",
            "os_arch": "x64",
            "app_arch": "x64",
            "system_locale": "en-US",
            "client_build_number": build,
            "native_build_number": 55566,
            "client_event_source": None,
            "launch_signature": "b1a4c9b8-6f2e-4c1e-9d3a-8c2d5f7a1b3e",
        })
    return _SP_CACHE[key]


class Api:
    def __init__(self, token: str, debug: bool = False,
                 build: tuple[int, str] = BUILD_CANDIDATES[0]) -> None:
        self.token = token.strip()
        self.debug = debug
        self.build = build
        self.probed = False
        self._sess = None
        if _cffi:
            self._sess = _cffi.Session(impersonate="chrome")
        elif _requests:
            self._sess = _requests.Session()

    def _headers(self) -> dict:
        return {
            "Authorization": self.token,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/",
            "User-Agent": UA,
            "X-Discord-Locale": "en-US",
            "X-Discord-Timezone": "Asia/Ho_Chi_Minh",
            "X-Super-Properties": super_props(*self.build),
            "X-Debug-Options": "bugReporterEnabled",
        }

    def _send(self, method: str, url: str, data: bytes | None):
        headers = self._headers()
        if self._sess is not None:
            r = self._sess.request(method, url, data=data, headers=headers, timeout=30)
            return r.status_code, r.text
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode("utf-8", "replace")
        except Exception as err:
            return 0, str(err)

    def call(self, method: str, path: str, body: dict | None = None,
             retries: int = 4) -> tuple[int, dict]:
        url = path if path.startswith("http") else API + path
        data = None if body is None else json.dumps(body).encode()
        status, payload = 0, {}

        for attempt in range(retries):
            try:
                status, text = self._send(method, url, data)
            except Exception as err:
                status, text = 0, str(err)

            payload = {}
            if text:
                try:
                    payload = json.loads(text)
                except ValueError:
                    payload = {"raw": text[:400]}

            if self.debug:
                print(f"    [debug] {method} {path} -> {status}")
                print("    [debug] " + json.dumps(payload, ensure_ascii=False)[:500])

            if status == 429:
                wait = 2.0
                try:
                    wait = float(payload.get("retry_after", 2.0))
                except (TypeError, ValueError, AttributeError):
                    pass
                time.sleep(min(wait + 0.7, 30.0))
                continue

            if status in (500, 502, 503, 504) and attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
                continue

            return status, payload if isinstance(payload, dict) else {"data": payload}

        return status, payload


# --------------------------------------------------------------------------- #
# Đọc dữ liệu quest (schema task_config_v2)
# --------------------------------------------------------------------------- #

def _cfg(quest: dict) -> dict:
    return quest.get("config") or quest.get("quest_config") or {}


def tasks_of(quest: dict) -> dict[str, dict]:
    """Trả về {task_type: task_dict}. Hỗ trợ cả schema cũ và mới."""
    cfg = _cfg(quest)
    v2 = cfg.get("task_config_v2") or cfg.get("taskConfigV2")
    if isinstance(v2, dict) and isinstance(v2.get("tasks"), dict):
        return {str(k).upper(): (v or {}) for k, v in v2["tasks"].items()}

    old = cfg.get("task_config") or cfg.get("taskConfig") or {}
    if isinstance(old, dict) and old.get("type"):
        return {str(old["type"]).upper(): old}
    return {}


def task_type(quest: dict) -> str:
    tasks = tasks_of(quest)
    for preferred in ("PLAY_ON_DESKTOP", "WATCH_VIDEO", "PLAY_ACTIVITY"):
        if preferred in tasks:
            return preferred
    return next(iter(tasks), "UNKNOWN")


def target_of(quest: dict) -> float:
    task = tasks_of(quest).get(task_type(quest)) or {}
    for key in ("target", "target_seconds", "duration"):
        val = task.get(key)
        if isinstance(val, (int, float)) and val > 0:
            return float(val)
    return 900.0


def quest_name(quest: dict) -> str:
    cfg = _cfg(quest)
    app = cfg.get("application") or {}
    messages = cfg.get("messages") or {}
    for candidate in (app.get("name"), messages.get("game_title"),
                      messages.get("quest_name"), messages.get("game_publisher")):
        if candidate:
            return str(candidate)
    return f"Quest {str(quest.get('id'))[:8]}"


def status_of(quest: dict) -> dict:
    return quest.get("user_status") or quest.get("userStatus") or {}


def is_enrolled(quest: dict) -> bool:
    return bool(status_of(quest).get("enrolled_at"))


def is_completed(quest: dict) -> bool:
    return bool(status_of(quest).get("completed_at"))


def is_claimed(quest: dict) -> bool:
    return bool(status_of(quest).get("claimed_at"))


def progress_of(quest: dict) -> float:
    """Value hiện tại của task chính (0 nếu chưa có)."""
    prog = status_of(quest).get("progress") or {}
    entry = prog.get(task_type(quest))
    if isinstance(entry, dict):
        val = entry.get("value")
        if isinstance(val, (int, float)):
            return float(val)
    # fallback: lấy value lớn nhất trong mọi entry
    best = 0.0
    for item in prog.values():
        if isinstance(item, dict) and isinstance(item.get("value"), (int, float)):
            best = max(best, float(item["value"]))
    return best


def is_expired(quest: dict) -> bool:
    raw = _cfg(quest).get("expires_at")
    if not raw:
        return False
    try:
        return datetime.fromisoformat(raw) <= datetime.now(timezone.utc)
    except ValueError:
        return False


def claim_platform(quest: dict) -> int:
    platforms = (_cfg(quest).get("rewards_config") or {}).get("platforms") or []
    return int(platforms[0]) if platforms and isinstance(platforms[0], int) else 0


# --------------------------------------------------------------------------- #
# Gọi API
# --------------------------------------------------------------------------- #

def list_quests(api: Api) -> list[dict]:
    status, payload = api.call("GET", "/quests/@me")
    if status != 200:
        raise SystemExit(f"Không lấy được quest (HTTP {status}): "
                         f"{payload.get('message') or payload}")

    quests = [q for q in (payload.get("quests") or []) if isinstance(q, dict)]

    # Rỗng có thể do build quá cũ -> thử build khác (chỉ 1 lần).
    if not quests and not api.probed:
        api.probed = True
        for build in BUILD_CANDIDATES:
            if build == api.build:
                continue
            api.build = build
            status, payload = api.call("GET", "/quests/@me")
            if status != 200:
                continue
            quests = [q for q in (payload.get("quests") or []) if isinstance(q, dict)]
            if quests:
                print(f"  (thấy quest với client_build_number={build[0]})")
                break
    return quests


def get_quest(api: Api, quest_id: str) -> dict | None:
    try:
        for quest in list_quests(api):
            if str(quest.get("id")) == str(quest_id):
                return quest
    except SystemExit:
        raise
    except Exception:
        pass
    return None


def enroll(api: Api, quest: dict) -> bool:
    qid = str(quest.get("id"))
    status, payload = api.call("POST", f"/quests/{qid}/enroll", {"location": 0})
    if status in (200, 201, 204):
        return True
    msg = str(payload.get("message") or "").lower()
    if "already" in msg:
        return True
    print(f"    ! enroll {qid} lỗi {status}: {payload.get('message') or payload}")
    return False


def heartbeat(api: Api, quest: dict) -> bool:
    qid = str(quest.get("id"))
    ts = (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat()
    status, _ = api.call(
        "POST", f"/quests/{qid}/heartbeat",
        {"event_name": task_type(quest), "timestamp": ts},
    )
    if status in (200, 201, 204):
        return True
    # fallback body tối giản
    status, _ = api.call("POST", f"/quests/{qid}/heartbeat", {})
    return status in (200, 201, 204)


def complete_video(api: Api, quest: dict) -> bool:
    """Đẩy tiến độ quest xem video bằng /video-progress.

    timestamp = vị trí video tính bằng GIÂY (float). Server chặn nhảy cóc:
    mỗi lần chỉ nhận thêm ~40s so với progress hiện tại (đã test thực tế).
    """
    qid = str(quest.get("id"))
    total = max(1.0, target_of(quest))
    fails = 0

    for _ in range(60):
        fresh = get_quest(api, qid)
        if fresh and is_completed(fresh):
            return True
        cur = progress_of(fresh) if fresh else 0.0
        if cur >= total:
            break

        step = (40.0, 25.0, 10.0, 3.0)[min(fails, 3)]
        ts = round(min(total, cur + step), 3)
        status, _ = api.call("POST", f"/quests/{qid}/video-progress", {"timestamp": ts})

        if status == 404:
            return False  # không phải quest video
        if status in (200, 201, 204):
            fails = 0
            time.sleep(0.5)
        else:
            fails += 1
            if fails > 4:
                return False
            time.sleep(1.2)

    for _ in range(4):
        fresh = get_quest(api, qid)
        if fresh and is_completed(fresh):
            return True
        time.sleep(1.0)
    return False


def claim(api: Api, quest: dict) -> str:
    """Trả về 'ok' | 'captcha' | 'skip' | 'error'."""
    qid = str(quest.get("id"))
    body = {"platform": claim_platform(quest), "location": 0}
    status, payload = api.call("POST", f"/quests/{qid}/claim-reward", body)

    if status in (200, 201, 204):
        return "ok"
    if payload.get("captcha_key"):
        return "captcha"

    msg = str(payload.get("message") or "").lower()
    if "already" in msg:
        return "ok"
    if status == 404:
        return "skip"
    print(f"    ! claim {qid} lỗi {status}: {payload.get('message') or payload}")
    return "error"


# --------------------------------------------------------------------------- #
# In bảng
# --------------------------------------------------------------------------- #

def print_quests(quests: list[dict]) -> None:
    if not quests:
        print("Không có quest nào.")
        return

    print(f"{'#':<3}{'Tên':<34}{'Loại':<20}{'Trạng thái':<20}{'Tiến độ'}")
    print("-" * 96)
    for idx, quest in enumerate(quests, 1):
        name = quest_name(quest)[:32]
        kind = TASK_LABELS.get(task_type(quest), task_type(quest))[:18]
        target = target_of(quest)
        cur = progress_of(quest)

        if is_expired(quest) and not is_claimed(quest):
            state = "hết hạn"
        elif is_claimed(quest):
            state = "đã nhận thưởng"
        elif is_completed(quest):
            state = "xong, chờ claim"
        elif is_enrolled(quest):
            state = "đang làm"
        else:
            state = "chưa enroll"

        pct = min(100.0, cur / target * 100) if target else 0.0
        print(f"{idx:<3}{name:<34}{kind:<20}{state:<20}{cur:.0f}/{target:.0f} ({pct:.0f}%)")


# --------------------------------------------------------------------------- #
# Chạy
# --------------------------------------------------------------------------- #

def run(api: Api, quests: list[dict], interval: float, timeout: float) -> None:
    work = [
        q for q in quests
        if not is_expired(q) and not is_claimed(q)
    ]
    if not work:
        print("Không có quest nào còn hạn để làm.")
        return

    # 1. enroll
    print("Enroll:")
    for quest in work:
        if not is_enrolled(quest):
            ok = enroll(api, quest)
            print(f"  {'+' if ok else '-'} {quest_name(quest)}")
            time.sleep(0.6)

    # refresh sau enroll
    quests = list_quests(api)
    work = [q for q in work if not is_claimed(q)]
    work = [next((x for x in quests if x["id"] == q["id"]), q) for q in work]

    # 2. quest xem video: /video-progress xong trong vài giây
    videos = [q for q in work
              if task_type(q) in VIDEO_TASKS and not is_completed(q)]
    if videos:
        print("\nVideo quest:")
        for quest in videos:
            ok = complete_video(api, quest)
            print(f"  {'+' if ok else '-'} {quest_name(quest)}")
        fresh = {q["id"]: q for q in list_quests(api)}
        work = [fresh.get(q["id"], q) for q in work]

    # 3. beat song song tới khi xong
    start = time.time()
    rounds = 0
    print(f"\nChạy {len(work)} quest song song (tối đa {timeout:.0f}s):")

    while time.time() - start < timeout:
        pending = [q for q in work if not is_completed(q)]
        if not pending:
            break

        for quest in pending:
            heartbeat(api, quest)
        rounds += 1
        time.sleep(interval)

        if rounds % 3 == 0:
            fresh = {q["id"]: q for q in list_quests(api)}
            work = [fresh.get(q["id"], q) for q in work]
            elapsed = time.time() - start
            parts = []
            for quest in pending:
                cur = progress_of(quest)
                parts.append(f"{quest_name(quest)[:18]}={cur:.0f}/{target_of(quest):.0f}")
            sys.stdout.write(f"\r  {elapsed:4.0f}s | " + " | ".join(parts) + "   ")
            sys.stdout.flush()

    print()
    fresh = {q["id"]: q for q in list_quests(api)}
    work = [fresh.get(q["id"], q) for q in work]

    # 4. claim
    print("\nClaim:")
    captcha_needed = []
    for quest in work:
        name = quest_name(quest)
        if is_claimed(quest):
            print(f"  = {name}: đã nhận rồi")
            continue
        if not is_completed(quest):
            cur, tgt = progress_of(quest), target_of(quest)
            print(f"  - {name}: chưa xong ({cur:.0f}/{tgt:.0f})")
            continue

        result = claim(api, quest)
        if result == "ok":
            print(f"  + {name}: ĐÃ CLAIM")
        elif result == "captcha":
            captcha_needed.append(name)
            print(f"  ! {name}: cần captcha")
        else:
            print(f"  - {name}: không claim được")
        time.sleep(1.2)

    if captcha_needed:
        print("\n" + "=" * 60)
        print(f"{len(captcha_needed)} quest đã XONG nhưng Discord đòi hCaptcha khi claim.")
        print("Cách xử lý: mở app Discord > Quests > bấm Claim từng cái (1 lần captcha).")
        for name in captcha_needed:
            print(f"   - {name}")
        print("=" * 60)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Tự động hoàn thành Discord Quests.")
    parser.add_argument("token_pos", nargs="?", metavar="token",
                        help="dán token trực tiếp: python discord_quest_auto.py <token>")
    parser.add_argument("--token", dest="token_opt")
    parser.add_argument("--list", action="store_true", help="chỉ liệt kê")
    parser.add_argument("--all", action="store_true", help="làm tất cả quest còn hạn")
    parser.add_argument("--id", help="chỉ làm 1 quest")
    parser.add_argument("--interval", type=float, default=3.0,
                        help="giây giữa 2 heartbeat (mặc định 3)")
    parser.add_argument("--timeout", type=float, default=1500.0,
                        help="thời gian tối đa (mặc định 1500s)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    token = (args.token_pos or args.token_opt
             or os.environ.get("DISCORD_TOKEN") or "").strip()
    if not token:
        token_file = Path(__file__).with_name("token.txt")
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip().splitlines()[0]
        else:
            token = input("Dán token Discord: ").strip()
    if not token:
        raise SystemExit("Chưa có token.")

    api = Api(token, debug=args.debug)
    status, me = api.call("GET", "/users/@me")
    if status == 401:
        raise SystemExit("Token sai hoặc đã bị logout (401).")
    print(f"Tài khoản: {me.get('username')} ({me.get('id')})\n")

    quests = list_quests(api)

    if args.id:
        quests = [q for q in quests if str(q.get("id")) == str(args.id)]
        if not quests:
            raise SystemExit("Không thấy quest id đó.")

    if args.list:
        print_quests(quests)
        return

    run(api, quests, args.interval, args.timeout)

    print("\nSau khi chạy:")
    print_quests(list_quests(api))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDừng.")
