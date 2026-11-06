import sys
import os
import time
import json
import asyncio
import socket
import struct
import re
import base64
import collections
import random
import logging
from pathlib import Path
from enum import Enum
from typing import Optional, Any, Dict, List, Tuple, Set

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

BG_MODE = "--bg" in sys.argv

if BG_MODE:
    if os.name == "nt" and sys.executable.lower().endswith("python.exe"):
        try:
            import subprocess
            script_path = os.path.abspath(__file__)
            script_dir = os.path.dirname(script_path)
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            info.wShowWindow = 0
            pythonw_path = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if os.path.exists(pythonw_path):
                subprocess.Popen(
                    [pythonw_path, script_path, "--bg"],
                    cwd=script_dir,
                    startupinfo=info,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                subprocess.Popen(
                    [sys.executable, script_path, "--bg"],
                    cwd=script_dir,
                    startupinfo=info,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        except Exception:
            pass
        sys.exit(0)
    try:
        BG_LOG_FILE = open(VOICE_BG_LOG, "a", encoding="utf-8", buffering=1)
        sys.stdout = BG_LOG_FILE
        sys.stderr = BG_LOG_FILE
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "setting.json"
TOKENS_FILE_PATH = SCRIPT_DIR / "tokens.txt"
VOICE_BG_LOG = SCRIPT_DIR / "voice_bg.log"
API_BASE = "https://discord.com/api/v10"
MAIN_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
COMMUNITY_LINK = "https://discord.com/kasumi"
APP_TITLE = "PJI - VOICE DISCORD"
REQUIRED_PACKAGES = ["aiohttp", "cryptography"]

def bootstrap_runtime():
    missing = []
    for pkg in REQUIRED_PACKAGES:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        import subprocess
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", *missing],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])

bootstrap_runtime()

import aiohttp

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTO = True
except Exception:
    HAS_CRYPTO = False
    AESGCM = None

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

SUPER_PROPERTIES_PAYLOAD = {
    "os": "Windows",
    "browser": "Discord Client",
    "release_channel": "stable",
    "client_version": "1.0.9171",
    "os_version": "10.0.19045",
    "os_arch": "x64",
    "app_arch": "x64",
    "system_locale": "vi-VN",
    "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9171 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36",
    "browser_version": "32.2.7",
    "client_build_number": 367890,
    "native_build_number": None,
    "client_event_source": None
}
SUPER_PROPERTIES = base64.b64encode(json.dumps(SUPER_PROPERTIES_PAYLOAD).encode("utf-8")).decode("utf-8")

COMMON_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9171 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36",
    "X-Super-Properties": SUPER_PROPERTIES,
    "X-Discord-Locale": "vi",
    "X-Discord-Timezone": "Asia/Ho_Chi_Minh"
}

def clean_text(text: Any) -> str:
    if not text:
        return ""
    s = str(text)
    s = re.sub(r'[\u200b-\u200f\ufeff]', '', s)
    s = re.sub(r'[\U00010000-\U0010ffff]', '', s)
    return s.strip()

def enable_termux_wakelock():
    if "com.termux" in os.environ.get("PREFIX", "") or os.path.exists("/data/data/com.termux"):
        import subprocess
        try:
            subprocess.Popen(["termux-wake-lock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

def disable_termux_wakelock():
    if "com.termux" in os.environ.get("PREFIX", "") or os.path.exists("/data/data/com.termux"):
        import subprocess
        try:
            subprocess.Popen(["termux-wake-unlock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

def get_clipboard_text() -> str:
    try:
        if os.name == "nt":
            import ctypes
            if ctypes.windll.user32.OpenClipboard(None):
                try:
                    if ctypes.windll.user32.IsClipboardFormatAvailable(13):
                        h_data = ctypes.windll.user32.GetClipboardData(13)
                        if h_data:
                            p_data = ctypes.windll.kernel32.GlobalLock(h_data)
                            if p_data:
                                text = ctypes.c_wchar_p(p_data).value
                                ctypes.windll.kernel32.GlobalUnlock(h_data)
                                return text or ""
                finally:
                    ctypes.windll.user32.CloseClipboard()
        elif sys.platform == "darwin":
            import subprocess
            return subprocess.check_output(["pbpaste"], universal_newlines=True)
        else:
            import subprocess
            try:
                return subprocess.check_output(["xclip", "-selection", "clipboard", "-o"], stderr=subprocess.DEVNULL, universal_newlines=True)
            except Exception:
                try:
                    return subprocess.check_output(["xsel", "-b", "-o"], stderr=subprocess.DEVNULL, universal_newlines=True)
                except Exception:
                    pass
    except Exception:
        pass
    return ""

class KeyReader:
    @staticmethod
    def poll_key() -> Optional[str]:
        if os.name == "nt":
            try:
                import msvcrt
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch in (b"\x00", b"\xe0"):
                        msvcrt.getch()
                        return None
                    if ch in (b"q", b"Q"):
                        return "Q"
                    if ch == b"\x03":
                        raise KeyboardInterrupt
            except Exception:
                pass
        return None

async def ask_input(prompt: str) -> str:
    try:
        return await asyncio.to_thread(input, prompt)
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt

def print_header(title: str = ""):
    pass

def print_menu(title: str, options: List[str], footer: str = ""):
    print("-"*60)
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    print(f"  0. Quay lai / Thoat")
    print("-"*60)

async def select_single(title: str, options: List[str], footer: str = "") -> Optional[int]:
    while True:
        print_menu(title, options, footer)
        s = await ask_input(f"Chon [0-{len(options)}]: ")
        s = s.strip()
        if s == "":
            continue
        if s.lower() == "q":
            raise KeyboardInterrupt
        try:
            n = int(s)
            if n == 0:
                return None
            if 1 <= n <= len(options):
                return n-1
        except ValueError:
            pass
        print("! Lua chon khong hop le, thu lai.")

async def select_multiple(title: str, items: List[str]) -> Optional[List[int]]:
    while True:
        print_header(title)
        print("Chon nhieu tai khoan (nhap so cach nhau boi dau phay)")
        print("-"*60)
        for i, it in enumerate(items, 1):
            print(f"  {i}. {it}")
        print("-"*60)
        print("  a = chon tat ca | 0 = quay lai")
        s = await ask_input("Nhap lua chon (1,2,3): ")
        s = s.strip().lower()
        if s == "0" or s == "":
            return None
        if s == "a":
            return list(range(len(items)))
        try:
            parts = re.split(r"[\s,;]+", s)
            idxs = []
            for p in parts:
                if not p:
                    continue
                n = int(p)
                if 1 <= n <= len(items):
                    idxs.append(n-1)
            idxs = sorted(set(idxs))
            if idxs:
                return idxs
        except ValueError:
            pass
        print("! Cu phap khong hop le.")

async def select_guild(title: str, guilds: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not guilds:
        print("! Khong co server nao.")
        return None
    filtered = guilds
    while True:
        print_header(title)
        print(f"Tim thay {len(guilds)} server. Go tu khoa de loc, Enter = hien tat ca")
        kw = await ask_input("Tu khoa loc (Enter=tat ca, 0=quay lai): ")
        kw = kw.strip()
        if kw == "0":
            return None
        if kw:
            filtered = [g for g in guilds if kw.lower() in clean_text(g.get("name","")).lower() or kw in str(g.get("id",""))]
            if not filtered:
                print(f"! Khong tim thay server nao voi tu khoa '{kw}'")
                continue
        else:
            filtered = guilds
        print("-"*60)
        for i, g in enumerate(filtered, 1):
            print(f"  {i}. {clean_text(g.get('name','Unknown'))}  ({g.get('id')})")
        print("-"*60)
        print(f"  0. Loc lai  |  Tong {len(filtered)} server")
        s = await ask_input(f"Chon server [0-{len(filtered)}]: ")
        s = s.strip()
        try:
            n = int(s)
            if n == 0:
                continue
            if 1 <= n <= len(filtered):
                return filtered[n-1]
        except ValueError:
            pass
        print("! Lua chon khong hop le.")

async def select_channel(server_name: str, channels: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    categories = {str(c["id"]): clean_text(c.get("name","")) for c in channels if c.get("type") == 4}
    voice_channels = [c for c in channels if c.get("type") in (2, 13)]
    if not voice_channels:
        print(f"! Server '{server_name}' khong co phong voice nao.")
        await ask_input("Nhan Enter de quay lai...")
        return None
    grouped: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    for vc in voice_channels:
        cat = categories.get(str(vc.get("parent_id","")), "KHONG CO DANH MUC")
        grouped[cat].append(vc)
    # Build flat mapping
    mapping: Dict[int, Dict[str, Any]] = {}
    while True:
        print_header(f"PHONG VOICE - {server_name}")
        idx = 1
        mapping.clear()
        for cat in sorted(grouped.keys(), key=lambda x: (x == "KHONG CO DANH MUC", x.lower())):
            print(f"\n[{cat.upper()}]")
            vcs = sorted(grouped[cat], key=lambda x: clean_text(x.get("name","")).lower())
            for vc in vcs:
                name = clean_text(vc.get("name","Unknown"))
                print(f"  {idx}. {name} ({vc.get('id')})")
                mapping[idx] = vc
                idx += 1
        print("-"*60)
        print("  0. Quay lai")
        s = await ask_input(f"Chon phong [0-{len(mapping)}]: ")
        s = s.strip()
        try:
            n = int(s)
            if n == 0:
                return None
            if n in mapping:
                return mapping[n]
        except ValueError:
            pass
        print("! Lua chon khong hop le.")

async def input_tokens_manual() -> str:
    print_header("DAN TOKEN THU CONG")
    print("Dan 1 hoac nhieu token, cach nhau boi xuong dong / dau phay / space")
    print("De trong + Enter = quay lai")
    print("-"*60)
    # doc nhieu dong cho den khi gap dong trong 2 lan? don gian: input 1 dong dai
    # cho phep paste nhieu token bang cach nhap lien tuc ket thuc bang dong trong
    print("Paste xong nhan Enter 2 lan de xac nhan (hoac nhap xong 1 dong roi Enter):")
    lines = []
    while True:
        try:
            line = await asyncio.to_thread(input)
        except (EOFError, KeyboardInterrupt):
            raise KeyboardInterrupt
        if line == "" and not lines:
            return ""
        if line == "" and lines:
            break
        if line.strip() == "" and lines:
            break
        lines.append(line)
        if len(lines) == 1 and "," not in line and " " not in line.strip():
            pass
        if len(lines) >= 1:
            continue
    return "\n".join(lines)
class ClientStatus(Enum):
    STARTUP = "Startup"
    CONNECTING = "Connecting"
    IDENTIFYING = "Identifying"
    RESUMING = "Resuming"
    CONNECTED = "Connected"
    VOICE_CONNECTING = "Voice Connecting"
    STREAMING = "Streaming"
    RECONNECTING = "Reconnecting"
    HEARTBEAT_TIMEOUT = "Timeout"
    STOPPING = "Stopping"
    SHUTDOWN = "Shutdown"
class SimpleLogHandler(logging.Handler):
    def __init__(self, maxlen: int = 100) -> None:
        super().__init__()
        self.records = collections.deque(maxlen=maxlen)
    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = time.strftime("%H:%M:%S", time.localtime(record.created))
            msg = record.getMessage()
            self.records.append(f"{ts} [{record.levelname}] {msg}")
        except Exception:
            pass
    def get_lines(self, count: int = 20) -> List[str]:
        return list(self.records)[-count:]

live_logger = SimpleLogHandler(maxlen=100)
logger = logging.getLogger("Voice")
logger.setLevel(logging.INFO)
logger.addHandler(live_logger)
# console handler for non-BG
_console_h = logging.StreamHandler(sys.stdout)
_console_h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
# only add console handler when not BG (BG already redirects)
if not BG_MODE:
    logger.addHandler(_console_h)

if BG_MODE:
    try:
        _bg_h = logging.FileHandler(VOICE_BG_LOG, encoding="utf-8")
        _bg_h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
        logger.addHandler(_bg_h)
    except Exception:
        pass

class SystemMonitor:
    def __init__(self) -> None:
        self.last_proc_time = time.process_time()
        self.last_proc_sample = time.monotonic()
        self.cpu_pct = 0.0
    def get_memory(self) -> str:
        try:
            if os.name == "nt":
                class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                        ("PrivateUsage", ctypes.c_size_t),
                    ]
                counters = PROCESS_MEMORY_COUNTERS_EX()
                counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
                handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, os.getpid())
                if handle:
                    try:
                        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                            return f"{counters.WorkingSetSize / (1024*1024):.1f} MB"
                    finally:
                        ctypes.windll.kernel32.CloseHandle(handle)
            else:
                import resource
                usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                return f"{usage / (1024*1024):.1f} MB" if sys.platform == "darwin" else f"{usage / 1024:.1f} MB"
        except Exception:
            pass
        return "N/A"
    def compute_cpu(self) -> str:
        try:
            now_proc = time.process_time()
            now_mono = time.monotonic()
            d_proc = now_proc - self.last_proc_time
            d_mono = now_mono - self.last_proc_sample
            cores = os.cpu_count() or 1
            if d_mono >= 0.2:
                self.cpu_pct = (d_proc / (d_mono * cores)) * 100.0
                self.last_proc_time = now_proc
                self.last_proc_sample = now_mono
            return f"{self.cpu_pct:.1f}%"
        except Exception:
            pass
        return "N/A"

system_monitor = SystemMonitor()
class TokenDecryptor:
    TOKEN_REGEX = re.compile(rb"[A-Za-z0-9_-]{24,34}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}")
    MFA_REGEX = re.compile(rb"mfa\.[A-Za-z0-9_-]{84}")
    @staticmethod
    def get_windows_master_key(local_state_path: Path) -> Optional[bytes]:
        if not HAS_CRYPTO or os.name != "nt" or not local_state_path.exists():
            return None
        try:
            data = json.loads(local_state_path.read_text(encoding="utf-8"))
            enc_key = base64.b64decode(data["os_crypt"]["encrypted_key"])
            if not enc_key.startswith(b"DPAPI"):
                return None
            enc_key = enc_key[5:]
            class DATA_BLOB(ctypes.Structure):
                _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
            blob_in = DATA_BLOB(len(enc_key), ctypes.cast(ctypes.create_string_buffer(enc_key), ctypes.POINTER(ctypes.c_byte)))
            blob_out = DATA_BLOB()
            if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
                key = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                return key
        except Exception:
            pass
        return None
    @classmethod
    def extract_from_directory(cls, dir_path: Path, master_key: Optional[bytes] = None) -> List[str]:
        tokens = set()
        if not dir_path.exists():
            return []
        for file in list(dir_path.glob("*.ldb")) + list(dir_path.glob("*.log")):
            try:
                content = file.read_bytes()
                if master_key and HAS_CRYPTO:
                    for match in re.findall(rb"dQw4w9WgXcQ:[^\"]*", content):
                        try:
                            enc_bytes = base64.b64decode(match.split(b"dQw4w9WgXcQ:")[1])
                            iv = enc_bytes[3:15]
                            payload = enc_bytes[15:]
                            cipher = AESGCM(master_key)
                            decrypted = cipher.decrypt(iv, payload, None)
                            tokens.add(decrypted.decode("utf-8"))
                        except Exception:
                            continue
                for match in cls.TOKEN_REGEX.findall(content):
                    try:
                        tokens.add(match.decode("utf-8"))
                    except Exception:
                        pass
                for match in cls.MFA_REGEX.findall(content):
                    try:
                        tokens.add(match.decode("utf-8"))
                    except Exception:
                        pass
            except Exception:
                continue
        return list(tokens)
    @classmethod
    def harvest_local_tokens(cls) -> List[str]:
        all_tokens = set()
        appdata = os.environ.get("APPDATA")
        localappdata = os.environ.get("LOCALAPPDATA")
        home = str(Path.home())
        targets = []
        if os.name == "nt":
            if appdata:
                targets.append((Path(appdata) / "discord", Path(appdata) / "discord" / "Local Storage" / "leveldb"))
                targets.append((Path(appdata) / "discordcanary", Path(appdata) / "discordcanary" / "Local Storage" / "leveldb"))
                targets.append((Path(appdata) / "discordptb", Path(appdata) / "discordptb" / "Local Storage" / "leveldb"))
                targets.append((Path(localappdata) / "Google" / "Chrome" / "User Data", Path(localappdata) / "Google" / "Chrome" / "User Data" / "Default" / "Local Storage" / "leveldb"))
                targets.append((Path(localappdata) / "Microsoft" / "Edge" / "User Data", Path(localappdata) / "Microsoft" / "Edge" / "User Data" / "Default" / "Local Storage" / "leveldb"))
                targets.append((Path(localappdata) / "BraveSoftware" / "Brave-Browser" / "User Data", Path(localappdata) / "BraveSoftware" / "Brave-Browser" / "User Data" / "Default" / "Local Storage" / "leveldb"))
            else:
                pass
        else:
            targets.append((Path(home) / ".config" / "discord", Path(home) / ".config" / "discord" / "Local Storage" / "leveldb"))
            targets.append((Path(home) / ".config" / "google-chrome", Path(home) / ".config" / "google-chrome" / "Default" / "Local Storage" / "leveldb"))
        for base_path, db_path in targets:
            if not db_path.exists():
                continue
            master_key = cls.get_windows_master_key(base_path / "Local State")
            found = cls.extract_from_directory(db_path, master_key)
            all_tokens.update(found)
        return list(all_tokens)
class VoiceProtocolSession:
    def __init__(self, token: str, guild_id: str, channel_id: str, user_id: str, session: aiohttp.ClientSession, on_ready_callback: Optional[Any] = None) -> None:
        self.token = token
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.user_id = user_id
        self.session = session
        self.on_ready_callback = on_ready_callback
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.udp_transport: Optional[asyncio.DatagramTransport] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.keepalive_task: Optional[asyncio.Task] = None
        self.is_running = True
        self.ssrc: int = 0
        self.voice_port: int = 0
        self.voice_ip: str = ""
        self.my_ip: str = ""
        self.my_port: int = 0
        self.heartbeat_interval: float = 20.0
        self.voice_rtt: float = 0.0
        self.last_voice_hb_sent: float = 0.0
    class VoiceUdpProtocol(asyncio.DatagramProtocol):
        def __init__(self, on_discovery: asyncio.Future) -> None:
            self.on_discovery = on_discovery
        def connection_made(self, transport: asyncio.DatagramTransport) -> None:
            self.transport = transport
        def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
            if len(data) >= 74 and not self.on_discovery.done():
                ip = data[8:72].decode("utf-8").rstrip("\x00")
                port = struct.unpack_from(">H", data, 72)[0]
                self.on_discovery.set_result((ip, port))
        def error_received(self, exc: Exception) -> None:
            if not self.on_discovery.done():
                self.on_discovery.set_exception(exc)
    async def start(self, endpoint: str, voice_token: str, session_id: str) -> None:
        clean_endpoint = endpoint.split(":")[0]
        ws_url = f"wss://{clean_endpoint}/?v=8"
        async with self.session.ws_connect(ws_url) as ws:
            self.ws = ws
            await ws.send_json({"op": 0, "d": {"server_id": self.guild_id, "user_id": self.user_id, "session_id": session_id, "token": voice_token}})
            async for msg in ws:
                if not self.is_running or msg.type != aiohttp.WSMsgType.TEXT:
                    break
                payload = json.loads(msg.data)
                op = payload.get("op")
                d = payload.get("d")
                if op == 2:
                    self.ssrc = d.get("ssrc")
                    self.voice_ip = d.get("ip")
                    self.voice_port = d.get("port")
                    modes = d.get("modes", [])
                    selected_mode = "xsalsa20_poly1305_lite" if "xsalsa20_poly1305_lite" in modes else modes[0] if modes else "xsalsa20_poly1305"
                    loop = asyncio.get_running_loop()
                    discovery_future = loop.create_future()
                    transport, _ = await loop.create_datagram_endpoint(lambda: self.VoiceUdpProtocol(discovery_future), remote_addr=(self.voice_ip, self.voice_port))
                    self.udp_transport = transport
                    discovery_packet = bytearray(74)
                    struct.pack_into(">H", discovery_packet, 0, 1)
                    struct.pack_into(">H", discovery_packet, 2, 70)
                    struct.pack_into(">I", discovery_packet, 4, self.ssrc)
                    self.udp_transport.sendto(discovery_packet)
                    try:
                        self.my_ip, self.my_port = await asyncio.wait_for(discovery_future, timeout=5.0)
                    except Exception:
                        self.my_ip, self.my_port = "0.0.0.0", 0
                    await ws.send_json({"op": 1, "d": {"protocol": "udp", "data": {"address": self.my_ip, "port": self.my_port, "mode": selected_mode}}})
                elif op == 8:
                    self.heartbeat_interval = d.get("heartbeat_interval", 20000) / 1000.0
                    if self.heartbeat_task:
                        self.heartbeat_task.cancel()
                    self.heartbeat_task = asyncio.create_task(self._voice_heartbeat_loop())
                    if self.keepalive_task:
                        self.keepalive_task.cancel()
                    self.keepalive_task = asyncio.create_task(self._voice_keepalive_loop())
                elif op == 4:
                    if self.on_ready_callback:
                        self.on_ready_callback()
                    await ws.send_json({"op": 5, "d": {"speaking": 0, "delay": 0, "ssrc": self.ssrc}})
                elif op == 6:
                    if self.last_voice_hb_sent > 0:
                        self.voice_rtt = (time.monotonic() - self.last_voice_hb_sent) * 1000.0
    async def _voice_heartbeat_loop(self) -> None:
        try:
            while self.is_running and self.ws and not self.ws.closed:
                self.last_voice_hb_sent = time.monotonic()
                await self.ws.send_json({"op": 3, "d": int(time.time() * 1000)})
                await asyncio.sleep(self.heartbeat_interval)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    async def _voice_keepalive_loop(self) -> None:
        try:
            while self.is_running and self.udp_transport:
                discovery_packet = bytearray(74)
                struct.pack_into(">H", discovery_packet, 0, 1)
                struct.pack_into(">H", discovery_packet, 2, 70)
                struct.pack_into(">I", discovery_packet, 4, self.ssrc)
                self.udp_transport.sendto(discovery_packet)
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    async def stop(self) -> None:
        self.is_running = False
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.keepalive_task:
            self.keepalive_task.cancel()
        if self.udp_transport:
            self.udp_transport.close()
        if self.ws and not self.ws.closed:
            await self.ws.close()

class AccountWorker:
    def __init__(self, token: str, username: str, user_id: str, session: aiohttp.ClientSession) -> None:
        self.token = token
        self.username = username
        self.user_id = user_id
        self.session = session
        self.guild_id = ""
        self.guild_name = "Unknown"
        self.channel_id = ""
        self.channel_name = "Unknown"
        self.status = ClientStatus.STARTUP
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session_id: Optional[str] = None
        self.sequence: Optional[int] = None
        self.is_running = True
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.voice_session: Optional[VoiceProtocolSession] = None
        self.voice_task: Optional[asyncio.Task] = None
        self.voice_state_event = asyncio.Event()
        self.voice_server_event = asyncio.Event()
        self.voice_token: Optional[str] = None
        self.voice_endpoint: Optional[str] = None
        self.last_heartbeat_sent: float = 0.0
        self.last_heartbeat_ack: float = 0.0
        self.gateway_rtt: float = 0.0
        self.reconnect_count: int = 0
        self.start_time: float = time.monotonic()
    @property
    def display_latency(self) -> float:
        if self.voice_session and self.voice_session.voice_rtt > 0:
            return self.voice_session.voice_rtt
        return self.gateway_rtt
    def mark_streaming_ready(self) -> None:
        self.status = ClientStatus.STREAMING
        logger.info(f"[{self.username}] Voice OK ({self.channel_name})")
    async def main_heartbeat_loop(self, interval_ms: float) -> None:
        interval = interval_ms / 1000.0
        try:
            while self.is_running and self.ws and not self.ws.closed:
                if self.last_heartbeat_sent > self.last_heartbeat_ack and (time.monotonic() - self.last_heartbeat_sent) > (interval * 1.5 + 2.0):
                    self.status = ClientStatus.HEARTBEAT_TIMEOUT
                    await self.ws.close(code=4000)
                    break
                self.last_heartbeat_sent = time.monotonic()
                await self.ws.send_json({"op": 1, "d": self.sequence})
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
    async def voice_coordinator_task(self) -> None:
        while self.is_running:
            await self.voice_state_event.wait()
            await self.voice_server_event.wait()
            if not self.is_running:
                break
            if self.voice_endpoint and self.voice_token and self.session_id:
                self.status = ClientStatus.VOICE_CONNECTING
                if self.voice_session:
                    await self.voice_session.stop()
                self.voice_session = VoiceProtocolSession(self.token, self.guild_id, self.channel_id, self.user_id, self.session, on_ready_callback=self.mark_streaming_ready)
                if self.voice_task:
                    self.voice_task.cancel()
                self.voice_task = asyncio.create_task(self.voice_session.start(self.voice_endpoint, self.voice_token, self.session_id))
            self.voice_state_event.clear()
            self.voice_server_event.clear()
    async def handle_gateway_dispatch(self, text: str) -> None:
        data = json.loads(text)
        op = data.get("op")
        s = data.get("s")
        t = data.get("t")
        d = data.get("d")
        if s is not None:
            self.sequence = s
        if op == 10:
            interval = d.get("heartbeat_interval", 41250)
            self.last_heartbeat_sent = time.monotonic()
            self.last_heartbeat_ack = time.monotonic()
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
            self.heartbeat_task = asyncio.create_task(self.main_heartbeat_loop(interval))
            if self.session_id and self.sequence is not None:
                self.status = ClientStatus.RESUMING
                await self.ws.send_json({"op": 6, "d": {"token": self.token, "session_id": self.session_id, "seq": self.sequence}})
            else:
                self.status = ClientStatus.IDENTIFYING
                await self.ws.send_json({"op": 2, "d": {"token": self.token, "capabilities": 16381, "properties": SUPER_PROPERTIES_PAYLOAD, "presence": {"status": "online", "since": 0, "activities": [], "afk": False}, "compress": False, "client_state": {"guild_versions": {}, "highest_last_message_id": "0", "read_state_version": 0, "user_guild_settings_version": -1, "user_settings_version": -1}}})
        elif op == 11:
            self.last_heartbeat_ack = time.monotonic()
            self.gateway_rtt = (self.last_heartbeat_ack - self.last_heartbeat_sent) * 1000.0
        elif op == 7:
            await self.ws.close(code=4000)
        elif op == 9:
            if not d:
                self.session_id = None
                self.sequence = None
            await self.ws.close(code=4000)
        elif op == 0:
            if t in ("READY", "RESUMED"):
                if t == "READY":
                    self.session_id = d.get("session_id")
                    self.user_id = d.get("user", {}).get("id", self.user_id)
                self.status = ClientStatus.CONNECTED
                logger.info(f"[{self.username}] Gateway OK")
                logger.info(f"[{self.username}] Dang vao phong: {self.channel_name}")
                await self.ws.send_json({"op": 4, "d": {"guild_id": self.guild_id, "channel_id": self.channel_id, "self_mute": True, "self_deaf": True}})
            elif t == "VOICE_STATE_UPDATE":
                if d.get("user_id") == self.user_id:
                    self.voice_state_event.set()
                    current_c = d.get("channel_id")
                    if current_c is None or current_c != self.channel_id:
                        jitter_wait = random.uniform(2.5, 5.0)
                        logger.warning(f"[{self.username}] Bi doi phong/ngat voice. Vao lai sau {jitter_wait:.1f}s...")
                        await asyncio.sleep(jitter_wait)
                        await self.ws.send_json({"op": 4, "d": {"guild_id": self.guild_id, "channel_id": self.channel_id, "self_mute": True, "self_deaf": True}})
            elif t == "VOICE_SERVER_UPDATE":
                self.voice_token = d.get("token")
                self.voice_endpoint = d.get("endpoint")
                self.voice_server_event.set()
    async def run(self) -> None:
        coordinator = asyncio.create_task(self.voice_coordinator_task())
        try:
            while self.is_running:
                self.status = ClientStatus.CONNECTING
                try:
                    async with self.session.ws_connect(MAIN_GATEWAY_URL, max_msg_size=0) as ws:
                        self.ws = ws
                        async for msg in ws:
                            if not self.is_running:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self.handle_gateway_dispatch(msg.data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                except Exception as e:
                    logger.error(f"[{self.username}] Loi Gateway: {e}")
                finally:
                    self.ws = None
                if not self.is_running:
                    break
                self.status = ClientStatus.RECONNECTING
                self.reconnect_count += 1
                if self.heartbeat_task:
                    self.heartbeat_task.cancel()
                if self.voice_session:
                    await self.voice_session.stop()
                await asyncio.sleep(min(30.0, 2.0 ** min(self.reconnect_count, 5)) + random.uniform(0.5, 1.5))
        finally:
            coordinator.cancel()
            await self.shutdown()
    async def shutdown(self) -> None:
        self.is_running = False
        self.status = ClientStatus.STOPPING
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.voice_session:
            await self.voice_session.stop()
        if self.voice_task:
            self.voice_task.cancel()
        if self.ws and not self.ws.closed:
            await self.ws.close()

# --- chim ---
class MultiAccountManager:
    def __init__(self) -> None:
        self.session: Optional[aiohttp.ClientSession] = None
        self.workers: List[AccountWorker] = []
        self.is_running = True
        self.start_time = time.monotonic()

    async def request_api(self, token: str, endpoint: str) -> Optional[Any]:
        headers = dict(COMMON_HEADERS)
        headers["Authorization"] = token
        for _ in range(3):
            try:
                async with self.session.get(f"{API_BASE}{endpoint}", headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        try:
                            data = await resp.json()
                            await asyncio.sleep(data.get("retry_after", 2.0))
                        except Exception:
                            await asyncio.sleep(2.0)
                    else:
                        return None
            except Exception:
                await asyncio.sleep(1.0)
        return None

    def load_saved_config(self) -> Dict[str, Any]:
        if CONFIG_PATH.exists():
            try:
                return json.loads(CONFIG_PATH.read_text("utf-8"))
            except Exception:
                pass
        return {}

    def save_current_config(self, profiles: List[Dict[str, Any]], mode: str) -> None:
        try:
            data = {"lang": "VI", "mode": mode, "profiles": profiles}
            CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        except Exception:
            pass

    def read_tokens_file(self) -> List[str]:
        if not TOKENS_FILE_PATH.exists():
            return []
        try:
            content = TOKENS_FILE_PATH.read_text(encoding="utf-8")
            extracted = TokenDecryptor.TOKEN_REGEX.findall(content.encode("utf-8")) + TokenDecryptor.MFA_REGEX.findall(content.encode("utf-8"))
            tokens = [t.decode("utf-8", errors="ignore") for t in extracted]
            if not tokens:
                tokens = [line.strip() for line in content.splitlines() if line.strip()]
            # dedup
            return list(dict.fromkeys(tokens))
        except Exception:
            return []

    def create_template_tokens_file(self) -> str:
        abs_path = TOKENS_FILE_PATH.resolve()
        if not TOKENS_FILE_PATH.exists():
            try:
                TOKENS_FILE_PATH.write_text("# Moi dong 1 token\n", encoding="utf-8")
            except Exception:
                pass
        return str(abs_path)

    async def deduplicate_and_validate(self, raw_tokens: List[str]) -> List[Tuple[str, str, str]]:
        clean_tokens = []
        for t in raw_tokens:
            cleaned = re.sub(r'[\r\n\t"\']', '', str(t)).strip()
            if cleaned.lower().startswith("bot "):
                cleaned = cleaned[4:].strip()
            if cleaned:
                clean_tokens.append(cleaned)
        unique_tokens = list(dict.fromkeys(clean_tokens))
        if not unique_tokens:
            return []
        print(f"Dang kiem tra {len(unique_tokens)} token...")
        tasks = [self.request_api(t, "/users/@me") for t in unique_tokens]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        seen: Set[str] = set()
        valid: List[Tuple[str, str, str]] = []
        for token, res in zip(unique_tokens, results):
            if isinstance(res, dict) and "id" in res:
                uid = str(res["id"])
                uname = clean_text(f"{res.get('username')}#{res.get('discriminator','0')}")
                if res.get("discriminator") in (None, "0", 0):
                    uname = clean_text(res.get("username") or res.get("global_name") or uid)
                if uid not in seen:
                    seen.add(uid)
                    valid.append((token, uname, uid))
                    print(f"  + {uname} ({uid}) hop le")
                else:
                    print(f"  ! Trung user {uid} bo qua")
            else:
                print(f"  - Token ...{token[-6:]} khong hop le / het han")
        print(f"=> Hop le: {len(valid)}/{len(unique_tokens)}")
        return valid

    async def ingest_accounts(self) -> List[Tuple[str, str, str]]:
        saved_cfg = self.load_saved_config()
        saved_profiles = saved_cfg.get("profiles", [])
        while True:
            clipboard_content = get_clipboard_text()
            clipboard_tokens = TokenDecryptor.TOKEN_REGEX.findall(clipboard_content.encode("utf-8")) + TokenDecryptor.MFA_REGEX.findall(clipboard_content.encode("utf-8"))
            str_clip_tokens = [t.decode("utf-8", errors="ignore") for t in clipboard_tokens]
            file_tokens = self.read_tokens_file()
            has_file = TOKENS_FILE_PATH.exists()

            opts = []
            opt_map = []
            opts.append("Dan token thu cong")
            opt_map.append("manual")

            choice = await select_single("CHON CACH NAP TOKEN", opts)
            if choice is None:
                print("Chon 0 de thoat? Bam Ctrl+C de thoat chuong trinh.")
                continue
            action = opt_map[choice]

            if action == "vault":
                tokens = [p["token"] for p in saved_profiles if p.get("token")]
                valid = await self.deduplicate_and_validate(tokens)
                if valid:
                    # cho chon acc neu nhieu
                    if len(valid) > 1:
                        labels = [f"{a[1]} ({a[2]})" for a in valid]
                        sel = await select_multiple("CHON ACC DE CHAY", labels)
                        if sel:
                            return [valid[i] for i in sel]
                        else:
                            continue
                    return valid
                else:
                    print("! Token trong setting.json het han, chon cach khac.")
            elif action == "clipboard":
                valid = await self.deduplicate_and_validate(str_clip_tokens)
                if valid:
                    if len(valid) > 1:
                        labels = [f"{a[1]} ({a[2]})" for a in valid]
                        sel = await select_multiple("CHON ACC DE CHAY", labels)
                        if sel:
                            return [valid[i] for i in sel]
                        continue
                    return valid
            elif action == "file":
                if not file_tokens:
                    print(f"! File {TOKENS_FILE_PATH} trong hoac khong co token hop le.")
                    await ask_input("Nhan Enter de tiep tuc...")
                    continue
                valid = await self.deduplicate_and_validate(file_tokens)
                if valid:
                    if len(valid) == 1:
                        return valid
                    labels = [f"{a[1]} ({a[2]})" for a in valid]
                    sel = await select_multiple("CHON ACC DE CHAY", labels)
                    if sel:
                        return [valid[i] for i in sel]
                else:
                    print("! Khong co token hop le trong file.")
            elif action == "create_file":
                p = self.create_template_tokens_file()
                print(f"Da tao file: {p}")
                print("Hay mo file va dan token, moi dong 1 token, roi chon lai 'Nap tu tokens.txt'")
                await ask_input("Nhan Enter de tiep tuc...")
            elif action == "extract":
                print("Dang quet token tu may (Discord/Chrome/Edge/Brave)...")
                raw = TokenDecryptor.harvest_local_tokens()
                print(f"Tim thay {len(raw)} token tho")
                if not raw:
                    print("! Khong tim thay token nao.")
                    await ask_input("Nhan Enter de tiep tuc...")
                    continue
                valid = await self.deduplicate_and_validate(raw)
                if not valid:
                    print("! Khong co token hop le sau khi quet.")
                    await ask_input("Nhan Enter...")
                    continue
                labels = [f"{a[1]} ({a[2]})" for a in valid]
                sel = await select_multiple("CHON ACC DE CHAY", labels)
                if sel is None:
                    continue
                chosen = [valid[i] for i in sel]
                if chosen:
                    return chosen
            elif action == "manual":
                while True:
                    raw_text = await input_tokens_manual()
                    if not raw_text.strip():
                        break
                    extracted = TokenDecryptor.TOKEN_REGEX.findall(raw_text.encode("utf-8")) + TokenDecryptor.MFA_REGEX.findall(raw_text.encode("utf-8"))
                    str_tokens = [t.decode("utf-8", errors="ignore") for t in extracted]
                    if not str_tokens:
                        # fallback split
                        str_tokens = [t.strip() for t in re.split(r"[\s,;]+", raw_text) if t.strip()]
                    valid = await self.deduplicate_and_validate(str_tokens)
                    if valid:
                        if len(valid) == 1:
                            return valid
                        labels = [f"{a[1]} ({a[2]})" for a in valid]
                        sel = await select_multiple("CHON ACC DE CHAY", labels)
                        if sel is None:
                            break
                        chosen = [valid[i] for i in sel]
                        if chosen:
                            return chosen
                    print("! Khong tim thay token hop le.")
                    c = await select_single("TOKEN KHONG HOP LE", ["Thu lai", "Quay lai menu chinh"])
                    if c is None or c == 1:
                        break

    async def routing_configuration_flow(self, accounts: List[Tuple[str, str, str]]) -> bool:
        # Nhap ID server thu cong -> chon phong voice -> tat cmd van chay nen
        self.workers.clear()
        while True:
            gid = await ask_input("Nhap ID server (nhom Discord) can treo [0=quay lai]: ")
            gid = gid.strip().replace(" ", "")
            if gid == "0" or gid == "":
                return False
            if not gid.isdigit():
                print("! ID server phai la so (vd 1492081680008351744)")
                continue
            base_token = accounts[0][0]
            print(f"Dang kiem tra server {gid}...")
            # lay ten server (neu co)
            gname = f"Server {gid}"
            try:
                raw_guilds = await self.request_api(base_token, "/users/@me/guilds")
                if raw_guilds:
                    for g in raw_guilds:
                        if str(g.get("id")) == gid:
                            gname = clean_text(g.get("name", gname))
                            break
                    has = any(str(g.get("id")) == gid for g in raw_guilds)
                    if not has:
                        print(f"! Token {accounts[0][1]} chua join server {gid} hoac ID sai")
                        continue
                # lay phong voice
                channels = await self.request_api(base_token, f"/guilds/{gid}/channels")
                if not channels:
                    print("! Khong lay duoc phong voice (kiem tra quyen / ID dung chua)")
                    continue
                sel_vc = await select_channel(gname, channels)
                if sel_vc is None:
                    print("! Chua chon phong, nhap lai ID server khac?")
                    continue
                cname = clean_text(sel_vc.get("name", "Unknown"))
                cid = str(sel_vc.get("id"))
                configured: List[Dict[str, Any]] = []
                for acc in accounts:
                    # kiem tra tung acc co join server khong
                    acc_guilds = await self.request_api(acc[0], "/users/@me/guilds")
                    has2 = any(str(g.get("id")) == gid for g in (acc_guilds or [])) if acc_guilds else False
                    if not has2:
                        # van cho phep thu lay channels truc tiep de xac nhan
                        ch2 = await self.request_api(acc[0], f"/guilds/{gid}/channels")
                        if not ch2:
                            print(f"! Canh bao: {acc[1]} chua join server {gname} -> bo qua")
                            continue
                    w = AccountWorker(acc[0], acc[1], acc[2], self.session)
                    w.guild_id = gid
                    w.guild_name = gname
                    w.channel_id = cid
                    w.channel_name = cname
                    self.workers.append(w)
                    configured.append({"token": acc[0], "username": acc[1], "user_id": acc[2], "guild_id": gid, "guild_name": gname, "channel_id": cid, "channel_name": cname})
                if configured:
                    self.save_current_config(configured, "cluster")
                    print(f"Da cau hinh {len(configured)} acc vao {gname} / {cname}")
                    return True
                else:
                    print("! Khong co acc nao join server do, nhap ID khac")
                    self.workers.clear()
                    continue
            except Exception as e:
                print(f"! Loi: {e}")
                continue

    async def dashboard_loop(self) -> None:
        # vong lap hien thi trang thai don gian, khong dung rich
        while self.is_running:
            try:
                if os.name == "nt":
                    os.system("cls")
                else:
                    os.system("clear")
            except Exception:
                pass
            uptime = int(time.monotonic() - self.start_time)
            h, m, s = uptime//3600, (uptime%3600)//60, uptime%60
            up_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
            online = sum(1 for w in self.workers if w.status == ClientStatus.STREAMING)
            total = len(self.workers)
            print("="*60)
            print(f"{APP_TITLE} | {COMMUNITY_LINK}")
            print(f"Streaming: {online}/{total} | Uptime: {up_str} | RAM: {system_monitor.get_memory()} | CPU: {system_monitor.compute_cpu()}")
            print("="*60)
            print(f"{'#':<3} {'Account':<22} {'Server':<18} {'Voice':<18} {'Ping':<8} {'Status'}")
            print("-"*60)
            for i, w in enumerate(self.workers, 1):
                lat = f"{w.display_latency:.0f}ms" if w.display_latency>0 else "..."
                # cat ngan
                acc = clean_text(w.username)[:20]
                srv = clean_text(w.guild_name)[:16]
                ch = clean_text(w.channel_name)[:16]
                print(f"{i:<3} {acc:<22} {srv:<18} {ch:<18} {lat:<8} {w.status.value}")
            print("-"*60)
            print("LOG (10 dong cuoi):")
            for line in live_logger.get_lines(10):
                print("  " + line)
            print("-"*60)
            print("Nhan Q roi Enter hoac Ctrl+C de dung | De chay nen: dung start_bg.bat")
            # doi 2 giay nhung check Q lien tuc
            for _ in range(20):
                if not self.is_running:
                    break
                k = KeyReader.poll_key()
                if k == "Q":
                    self.is_running = False
                    return
                await asyncio.sleep(0.1)

    async def execute(self) -> None:
        enable_termux_wakelock()
        connector = aiohttp.TCPConnector(family=socket.AF_INET, use_dns_cache=True, keepalive_timeout=60.0, limit=0, limit_per_host=0)
        timeout = aiohttp.ClientTimeout(total=45.0)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            self.session = session
            if BG_MODE:
                cfg = self.load_saved_config()
                for p in cfg.get("profiles", []):
                    if not (p.get("token") and p.get("guild_id") and p.get("channel_id")):
                        continue
                    w = AccountWorker(p["token"], p.get("username","Unknown"), str(p.get("user_id","")), self.session)
                    w.guild_id = p["guild_id"]
                    w.guild_name = p.get("guild_name","Saved")
                    w.channel_id = p["channel_id"]
                    w.channel_name = p.get("channel_name","Saved")
                    self.workers.append(w)
                if not self.workers:
                    print(f"[BG] Khong tim thay profile hop le trong {CONFIG_PATH}")
                    return
                print(f"[BG] Khoi dong nen: {len(self.workers)} acc, log -> {VOICE_BG_LOG}")
                logger.info(f"[BG] Khoi dong {len(self.workers)} acc")
            else:
                # chon acc -> nhap ID server -> chon phong -> chay nen
                while self.is_running:
                    accounts = await self.ingest_accounts()
                    if not accounts:
                        print("! Chua chon acc nao.")
                        continue
                    ok = await self.routing_configuration_flow(accounts)
                    if ok and self.workers:
                        break
                    print("! Chua cau hinh xong, thu lai.")
                # Da cau hinh xong, tu dong chuyen sang chay nen de tat cmd van chay
                print(f"\nDa cau hinh {len(self.workers)} acc. Dang chuyen sang chay nen...")
                try:
                    import subprocess
                    script_path = str(SCRIPT_DIR / "voice.py")
                    pythonw_path = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                    if os.path.exists(pythonw_path):
                        subprocess.Popen([pythonw_path, script_path, "--bg"], cwd=str(SCRIPT_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        subprocess.Popen([sys.executable, script_path, "--bg"], cwd=str(SCRIPT_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name=="nt" else 0)
                    await asyncio.sleep(1)
                    # Thoat luon de tranh chay trung 2 lan (nen da chay roi)
                    return
                except Exception as e:
                    print(f"! Khong chay nen duoc: {e}, se chay thuong")
                    print(f"\nDa cau hinh {len(self.workers)} acc. Dang ket noi...")
                    await asyncio.sleep(1)

            # start workers
            worker_tasks = []
            for w in self.workers:
                worker_tasks.append(asyncio.create_task(w.run()))
                await asyncio.sleep(random.uniform(1.0, 2.0))

            dashboard_task = None
            if not BG_MODE:
                dashboard_task = asyncio.create_task(self.dashboard_loop())

            try:
                if BG_MODE:
                    await asyncio.Event().wait()
                else:
                    # doi dashboard ket thuc (khi user nhan Q) hoac worker die
                    if dashboard_task:
                        await dashboard_task
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                self.is_running = False
                if dashboard_task:
                    dashboard_task.cancel()
                    try:
                        await dashboard_task
                    except asyncio.CancelledError:
                        pass
                for w in self.workers:
                    await w.shutdown()
                for t in worker_tasks:
                    t.cancel()
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass
                disable_termux_wakelock()
                if not BG_MODE:
                    print("\nDa dung. Nhan Enter de thoat.")
                    try:
                        input()
                    except Exception:
                        pass

if __name__ == "__main__":
    m = MultiAccountManager()
    try:
        asyncio.run(m.execute())
    except (KeyboardInterrupt, SystemExit):
        disable_termux_wakelock()
        sys.exit(0)
