#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
苏州大学校园网自动登录守护脚本
================================

功能
----
1. 每隔一段时间（默认 5 分钟）检测本机是否能访问公网；
2. 一旦检测失败（例如账号在别处登录把本机顶下线），自动向
   http://10.9.1.3:801/eportal/?c=Portal&a=login 提交账号密码重新登录；
3. 登录后再次校验公网连通性，失败则按退避策略重试；
4. 所有动作写入日志，便于排查。

只使用 Python 标准库，无需安装任何第三方依赖。

常用命令
--------
    python auto_login.py                 # 前台常驻运行
    python auto_login.py --once          # 只跑一轮（适合任务计划程序）
    python auto_login.py --check         # 只检测当前网络状态，不登录
    python auto_login.py --force-login   # 跳过检测，直接尝试登录（调试用）
"""

from __future__ import annotations

import argparse
import atexit
import base64
import configparser
import json
import logging
import logging.handlers
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

APP_NAME = "校园网自动登录"
APP_VERSION = "1.0.1"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def _exe_dir() -> Path:
    """exe 所在目录；未打包时是脚本目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _ensure_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("x", encoding="ascii")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _resolve_data_dir() -> Path:
    """配置与日志的落地目录。

    优先放在 exe 旁边（绿色版习惯）；不可写时依次退回
    %LOCALAPPDATA%\\SoochowCampusNet、用户主目录，保证总有可写位置。
    """
    base = _exe_dir()
    if _ensure_dir(base):
        return base

    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "SoochowCampusNet")
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "SoochowCampusNet")
    candidates.append(Path.home() / ".campus-net")
    candidates.append(Path(os.environ.get("TEMP", ".")) / "SoochowCampusNet")

    for cand in candidates:
        if _ensure_dir(cand):
            return cand
    return base


APP_DIR = _resolve_data_dir()
DEFAULT_CONFIG = APP_DIR / "config.ini"
PID_FILE = APP_DIR / "auto_login.pid"
STATE_FILE = APP_DIR / "status.json"
STOP_FILE = APP_DIR / "stop.request"
LOG_FILE = APP_DIR / "logs" / "auto_login.log"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 显式禁用系统代理：校园网门户是本机内网地址，走代理只会带来误判
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 门户页面特征，用于识别"被劫持到登录页"这种情况
PORTAL_MARKERS = ("eportal", "dr.com", "drcom", "10.9.1.3", "上网登录")

# Dr.COM 门户返回码含义（来自登录页 a42.js 的 portal_login_err）
RET_CODE_MSG = {
    1: "账号或密码不对",
    2: "终端 IP 已经在线",
    3: "系统繁忙",
    4: "未知错误",
    5: "REQ_CHALLENGE 失败",
    6: "REQ_CHALLENGE 超时",
    7: "Radius 认证失败",
    8: "Radius 认证超时",
    9: "Radius 下线失败",
    10: "Radius 下线超时",
    11: "其他错误",
    998: "Portal 协议参数不全",
}

log = logging.getLogger("campus-net")


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
class Config:
    """解析后的配置项。"""

    def __init__(self) -> None:
        self.username = ""
        self.password = ""
        self.suffix = ""            # 运营商后缀，如 @cucc / @ctc / @zgyd
        self.prefix = ",0,"         # PC 端账号前缀，登录页默认添加
        self.mac = ""               # 留空表示自动探测

        self.host = "10.9.1.3"
        self.port = 801
        self.login_path = "/eportal/?c=Portal&a=login"
        self.login_method = 1
        self.js_version = "3.3.3"
        self.request_timeout = 8.0

        self.interval = 300.0       # 检测周期（秒）
        self.probe_rounds = 2       # 判定掉线前重复检测的轮数
        self.probe_gap = 3.0        # 两轮检测之间的间隔（秒）
        self.probe_timeout = 5.0
        self.probes: list[tuple[str, int, str]] = []

        self.retry_delay = 30.0     # 登录失败后的首次重试间隔
        self.max_retry_delay = 600.0
        self.log_file = "logs/auto_login.log"
        self.log_max_bytes = 1024 * 1024
        self.log_backup_count = 3

    @property
    def portal_base(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def login_url(self) -> str:
        return self.portal_base + self.login_path


def _get_str(section: configparser.SectionProxy, key: str, default: str) -> str:
    try:
        value = section.get(key)
    except Exception:
        return default
    return default if value is None else value.strip()


def _get_float(section, key: str, default: float) -> float:
    try:
        return float(str(section.get(key)).strip())
    except Exception:
        return default


def _get_int(section, key: str, default: int) -> int:
    try:
        return int(float(str(section.get(key)).strip()))
    except Exception:
        return default


def _parse_probes(raw: str) -> list[tuple[str, int, str]]:
    """把配置里的探测地址解析成 (url, 期望状态码, 期望包含的文本) 列表。"""
    probes: list[tuple[str, int, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        url = parts[0]
        if not url.lower().startswith(("http://", "https://")):
            continue
        try:
            status = int(parts[1]) if len(parts) > 1 and parts[1] else 204
        except ValueError:
            status = 204
        contains = parts[2] if len(parts) > 2 else ""
        probes.append((url, status, contains))
    return probes


DEFAULT_PROBES = """\
http://connect.rom.miui.com/generate_204|204|
http://www.msftconnecttest.com/connecttest.txt|200|Microsoft Connect Test
http://www.baidu.com|200|
"""


def load_config(path: Path) -> Config:
    cfg = Config()
    if not path.is_file():
        raise SystemExit(f"找不到配置文件：{path}")

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8-sig")

    if parser.has_section("account"):
        sec = parser["account"]
        cfg.username = _get_str(sec, "username", "")
        # 密码不做 strip：首尾空格有可能是密码的一部分
        cfg.password = sec.get("password", "").strip("\r\n") if "password" in sec else ""
        cfg.suffix = _get_str(sec, "suffix", "")
        cfg.prefix = _get_str(sec, "prefix", ",0,")
        cfg.mac = _get_str(sec, "mac", "")

    if parser.has_section("portal"):
        sec = parser["portal"]
        cfg.host = _get_str(sec, "host", cfg.host)
        cfg.port = _get_int(sec, "port", cfg.port)
        cfg.login_path = _get_str(sec, "login_path", cfg.login_path)
        cfg.login_method = _get_int(sec, "login_method", cfg.login_method)
        cfg.js_version = _get_str(sec, "js_version", cfg.js_version)
        cfg.request_timeout = _get_float(sec, "timeout", cfg.request_timeout)

    if parser.has_section("check"):
        sec = parser["check"]
        cfg.interval = max(30.0, _get_float(sec, "interval", cfg.interval))
        cfg.probe_rounds = max(1, _get_int(sec, "probe_rounds", cfg.probe_rounds))
        cfg.probe_gap = max(0.0, _get_float(sec, "probe_gap", cfg.probe_gap))
        cfg.probe_timeout = max(1.0, _get_float(sec, "timeout", cfg.probe_timeout))
        raw = _get_str(sec, "probes", "")
        cfg.probes = _parse_probes(raw) if raw else _parse_probes(DEFAULT_PROBES)

    if parser.has_section("daemon"):
        sec = parser["daemon"]
        cfg.retry_delay = max(5.0, _get_float(sec, "retry_delay", cfg.retry_delay))
        cfg.max_retry_delay = max(
            cfg.retry_delay, _get_float(sec, "max_retry_delay", cfg.max_retry_delay)
        )
        cfg.log_file = _get_str(sec, "log_file", cfg.log_file)
        cfg.log_max_bytes = max(64 * 1024, _get_int(sec, "log_max_bytes", cfg.log_max_bytes))
        cfg.log_backup_count = max(1, _get_int(sec, "log_backup_count", cfg.log_backup_count))

    if not cfg.probes:
        cfg.probes = _parse_probes(DEFAULT_PROBES)
    return cfg


# --------------------------------------------------------------------------- #
# 日志
# --------------------------------------------------------------------------- #
def setup_logging(cfg: Config, verbose: bool) -> None:
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s", "%Y-%m-%d %H:%M:%S")

    log_path = Path(cfg.log_file)
    if not log_path.is_absolute():
        log_path = APP_DIR / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=cfg.log_max_bytes,
        backupCount=cfg.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    log.addHandler(file_handler)

    # pythonw 运行时没有控制台，attach 失败就忽略
    try:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.DEBUG if verbose else logging.INFO)
        console.setFormatter(fmt)
        log.addHandler(console)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def http_get(
    url: str,
    timeout: float,
    headers: dict[str, str] | None = None,
    max_bytes: int = 8192,
) -> tuple[int, str, bytes]:
    """发起 GET 请求，返回 (状态码, 最终地址, 响应体)。不抛出网络异常。"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            **(headers or {}),
        },
    )
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.geturl(), resp.read(max_bytes)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(max_bytes)
        except Exception:
            body = b""
        return exc.code, getattr(exc, "url", url), body
    except Exception:
        return 0, url, b""


def decode_body(body: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return body.decode(encoding)
        except Exception:
            continue
    return ""


def write_json_atomic(path: Path, payload: dict) -> None:
    """原子写 JSON，避免界面读到写了一半的文件。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _is_virtual_ip(ip: str) -> bool:
    """识别虚拟网卡 / 代理软件常用的保留地址，这类 IP 不能作为校园网身份。"""
    if not ip:
        return True
    if ip.startswith("127.") or ip == "0.0.0.0":
        return True
    # 198.18.0.0/15 是 RFC 2544 基准测试网段，Clash / 迅游等代理常占用
    try:
        parts = [int(p) for p in ip.split(".")]
    except Exception:
        return True
    if len(parts) != 4:
        return True
    a, b = parts[0], parts[1]
    if a == 198 and b in (18, 19):
        return True
    # 169.254/16 链路本地，192.0.2/24 文档示例网段
    if a == 169 and b == 254:
        return True
    if a == 192 and b == 0 and parts[2] == 2:
        return True
    return False


def _candidate_ips() -> list[str]:
    """列出所有网卡 IPv4，排除虚拟网卡，按可用性排序。"""
    found: list[str] = []
    try:
        proc = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = proc.stdout
        for encoding in ("oem", "mbcs", "gb18030", "utf-8"):
            try:
                text = raw.decode(encoding)
                break
            except Exception:
                continue
        else:
            text = raw.decode("latin-1", "ignore")
        for line in text.splitlines():
            match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
            if match and ("IPv4" in line or "IP Address" in line or "IP 地址" in line):
                ip = match.group(1)
                if ip not in found:
                    found.append(ip)
    except Exception:
        pass
    return found


def _portal_source_ip(host: str, port: int) -> str:
    """到门户本身的路由会用哪个源地址——这才是门户看到的真实身份。"""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.5)
        sock.connect((host, port))
        ip = sock.getsockname()[0]
        return ip if ip and not ip.startswith("127.") else ""
    except Exception:
        return ""
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def get_local_ip(host: str = "10.9.1.3", port: int = 801) -> str:
    """取本机在校园网中的真实 IP。

    直接问系统「访问门户时用哪个源地址」最准；但装了代理 / 虚拟网卡时，
    默认路由可能把门户流量也劫走，返回 198.18.x.x 之类的假地址。
    这时退回枚举网卡，挑第一个非虚拟、看起来像校园内网的地址。
    """
    route_ip = _portal_source_ip(host, port)
    if route_ip and not _is_virtual_ip(route_ip):
        return route_ip

    candidates = [ip for ip in _candidate_ips() if not _is_virtual_ip(ip)]
    # 优先 10.x（校园网典型网段），其次其它私网地址
    for ip in candidates:
        if ip.startswith("10."):
            return ip
    if candidates:
        return candidates[0]

    # 实在没有可用的，退回路由给出的地址（总比空着好）
    return route_ip


_MAC_RE = re.compile(r"\b([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})\b")


def _mac_from_ipconfig(local_ip: str) -> str:
    """从 ipconfig /all 中找出与 local_ip 同一网卡块的物理地址。

    逐块解析、只认 MAC 的文本形态，因此不受系统语言影响。
    """
    try:
        proc = subprocess.run(
            ["ipconfig", "/all"],
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = proc.stdout
        for encoding in ("oem", "mbcs", "gb18030", "utf-8"):
            try:
                text = raw.decode(encoding)
                break
            except Exception:
                continue
        else:
            text = raw.decode("latin-1", "ignore")
    except Exception:
        return ""

    blocks: list[list[str]] = [[]]
    for line in text.splitlines():
        if line.strip():
            blocks[-1].append(line)
        elif blocks[-1]:
            blocks.append([])

    for block in blocks:
        joined = "\n".join(block)
        if local_ip and local_ip not in joined:
            continue
        match = _MAC_RE.search(joined)
        if match:
            mac = re.sub(r"[-:]", "", match.group(1)).lower()
            if mac not in ("000000000000", "ffffffffffff"):
                return mac
    return ""


def get_mac(local_ip: str) -> str:
    """尽力获取本机 MAC：本机 ipconfig -> getmac -> uuid.getnode。"""
    mac = _mac_from_ipconfig(local_ip)
    if mac:
        return mac
    try:
        proc = subprocess.run(
            ["getmac", "/fo", "csv", "/nh"],
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        match = _MAC_RE.search(proc.stdout.decode("latin-1", "ignore"))
        if match:
            return re.sub(r"[-:]", "", match.group(1)).lower()
    except Exception:
        pass
    try:
        node = __import__("uuid").getnode()
        # 随机生成的 MAC 会把多播位置 1，这种不可用
        if not (node & (1 << 40)):
            return f"{node:012x}"
    except Exception:
        pass
    return ""


def portal_reachable(cfg: Config) -> bool:
    """门户服务器是否可达（判断是否真的接在校园网里）。"""
    sock = None
    try:
        sock = socket.create_connection((cfg.host, cfg.port), timeout=4.0)
        return True
    except Exception:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# 公网连通性检测
# --------------------------------------------------------------------------- #
def _probe_one(url: str, expect_status: int, expect_text: str, timeout: float) -> tuple[bool, str]:
    status, final_url, body = http_get(url, timeout)

    if status == 0:
        return False, f"{url} 无响应"

    if status != expect_status:
        # 302 跳转到门户首页，说明被重定向到了认证页
        if final_url and cfg_host_in(final_url):
            return False, f"{url} 被重定向到登录页"
        return False, f"{url} 状态码 {status}（期望 {expect_status}）"

    if expect_text:
        text = decode_body(body)
        if expect_text.lower() not in text.lower():
            return False, f"{url} 内容不符（可能被劫持）"
        return True, f"{url} 正常"

    if expect_status == 204:
        if body.strip():
            return False, f"{url} 返回了非空内容（可能被劫持）"
        return True, f"{url} 正常"

    text = decode_body(body).lower()
    for marker in PORTAL_MARKERS:
        if marker in text:
            return False, f"{url} 返回登录页内容（被劫持）"
    return True, f"{url} 正常"


def cfg_host_in(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in ("10.9.1.3", "/eportal", "dr.com", "drcom"))


def check_internet(cfg: Config) -> tuple[bool, str]:
    """多地址、多轮探测，任意一个通过即认为公网可用。"""
    last_detail = ""
    for round_index in range(cfg.probe_rounds):
        if round_index:
            time.sleep(cfg.probe_gap)
        for url, status, text in cfg.probes:
            ok, detail = _probe_one(url, status, text, cfg.probe_timeout)
            if ok:
                return True, detail
            last_detail = detail
            log.debug("探测失败：%s", detail)
    return False, last_detail or "全部探测地址均不可达"


# --------------------------------------------------------------------------- #
# 门户登录
# --------------------------------------------------------------------------- #
def build_account(cfg: Config) -> str:
    """按登录页的规则拼出真正提交的账号。

    登录页逻辑：user_account = 前缀 + 用户名 + 运营商后缀
    （前缀 PC 端为 ",0,"，后缀来自运营商下拉框，如 @cucc）。
    """
    account = cfg.username.strip()
    if not account:
        return ""
    if cfg.suffix and "@" not in account:
        account += cfg.suffix
    if cfg.prefix and not account.startswith(","):
        account = cfg.prefix + account
    return account


def parse_portal_json(text: str) -> dict | None:
    """解析门户返回：可能是 JSON，也可能是 JSONP 或带括号的 JSON。"""
    text = text.strip()
    if not text:
        return None
    match = re.match(r"^[A-Za-z_$][\w$.]*\s*\((.*)\)\s*;?$", text, re.S)
    if match:
        text = match.group(1).strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    try:
        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def decode_portal_msg(msg: str) -> str:
    """门户有时把详细错误放进 msg 字段：base64(GBK 文本)，尽力还原成中文。"""
    msg = (msg or "").strip()
    if not msg:
        return ""
    if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", msg) and len(msg) % 4 == 0:
        try:
            raw = base64.b64decode(msg)
        except Exception:
            return msg
        for encoding in ("gb18030", "utf-8"):
            try:
                text = raw.decode(encoding)
            except Exception:
                continue
            if text and text.isprintable():
                return text.strip()
    return msg


def query_portal_error(cfg: Config, local_ip: str, mac: str) -> str:
    """msg 为空时，向门户查询一次 AC 侧的具体错误码。"""
    if not local_ip:
        return ""
    url = f"{cfg.portal_base}/eportal/?c=Portal&a=getErrCode&" + urllib.parse.urlencode(
        {"ip": local_ip, "mac": mac}
    )
    status, _, body = http_get(url, cfg.request_timeout)
    if status != 200:
        return ""
    data = parse_portal_json(decode_body(body))
    if not data or str(data.get("result")) != "1":
        return ""
    errcode = str(data.get("errcode") or "")
    match = re.search(r"ret='(.*?)';", errcode)
    return match.group(1) if match else errcode


def ac_online_state(cfg: Config) -> str:
    """查询 AC 侧记录的在线状态，仅用于诊断日志。返回 '', 'online' 或 'offline'。"""
    url = f"http://{cfg.host}/drcom/chkstatus?callback=dr1"
    status, _, body = http_get(url, min(cfg.request_timeout, 5.0))
    if status != 200:
        return ""
    data = parse_portal_json(decode_body(body))
    if not data:
        return ""
    if str(data.get("result")) == "1":
        return "online"
    if str(data.get("result")) == "0":
        return "offline"
    return ""


def do_login(cfg: Config, local_ip: str, mac: str) -> tuple[bool, str]:
    """向门户提交登录请求。返回 (是否成功, 说明)。"""
    account = build_account(cfg)
    # 参数与登录页 a42.js 的 login_portal 完全一致（login_method=1 的 PORTAL 协议）
    params = {
        "login_method": str(cfg.login_method),
        "user_account": account,
        "user_password": cfg.password,
        "wlan_user_ip": local_ip,
        "wlan_user_ipv6": "",
        "wlan_user_mac": mac,
        "wlan_ac_ip": "",
        "wlan_ac_name": "",
        "jsVersion": cfg.js_version,
    }
    query = urllib.parse.urlencode(params)
    separator = "&" if "?" in cfg.login_url else "?"
    url = f"{cfg.login_url}{separator}{query}"

    log.info("向门户提交登录：账号=%s，本机 IP=%s，MAC=%s", account, local_ip, mac or "(未获取)")
    status, _, body = http_get(
        url,
        cfg.request_timeout,
        headers={"Referer": f"http://{cfg.host}/", "Accept": "*/*"},
    )
    text = decode_body(body).strip()

    if status == 0:
        return False, "门户无响应"
    if status != 200:
        return False, f"门户返回 HTTP {status}"

    data = parse_portal_json(text)
    if data is None:
        return False, f"无法解析门户响应：{text[:120]!r}"

    result = str(data.get("result", "")).strip().lower()
    ret_code = data.get("ret_code")
    msg = (data.get("msg") or "").strip()

    if result in ("1", "ok", "success") or str(ret_code) == "2":
        if str(ret_code) == "2":
            return True, "服务器提示该 IP 已在线，视为登录成功"
        return True, msg or "登录成功"

    try:
        code = int(ret_code) if ret_code is not None else -1
    except Exception:
        code = -1
    reason = RET_CODE_MSG.get(code) or "认证失败"
    detail = decode_portal_msg(msg)
    if not detail:
        detail = query_portal_error(cfg, local_ip, mac)
    if detail and detail not in reason:
        reason = f"{reason}：{detail}"
    # 认证被拒时把实际提交的 IP 一起报出来：装了代理/虚拟网卡时
    # 常常是 IP 取错（例如 198.18.x.x），只看"密码错误"会误判
    hint = ""
    if code in (1, 4) and local_ip:
        hint = f"（提交的 IP 为 {local_ip}，若本机装了代理或虚拟网卡请检查网卡地址）"
    return False, f"登录失败，ret_code={ret_code}，{reason}{hint}"


# --------------------------------------------------------------------------- #
# 守护主循环
# --------------------------------------------------------------------------- #
class Daemon:
    def __init__(
        self,
        cfg: Config,
        once: bool = False,
        force_login: bool = False,
        standalone: bool = False,
    ) -> None:
        self.cfg = cfg
        self.once = once
        self.force_login = force_login
        self.standalone = standalone
        self.local_ip = ""
        self.mac = ""
        self.last_online: bool | None = None
        self.fail_streak = 0
        self.started_at = time.time()
        self.checks = 0
        self.logins = 0
        self.last_detail = ""
        self.last_action = ""
        self.next_check_at = 0.0

    def refresh_identity(self) -> None:
        self.local_ip = get_local_ip()
        self.mac = self.cfg.mac or get_mac(self.local_ip)

    def write_status(self, running: bool = True) -> None:
        """把运行状态写到 status.json，供图形界面读取。"""
        if self.standalone:
            # --once / --force-login 是一次性调用，不覆盖守护进程的状态文件
            return
        payload = {
            "running": running,
            "pid": os.getpid(),
            "started_at": self.started_at,
            "updated_at": time.time(),
            "interval": self.cfg.interval,
            "online": self.last_online,
            "detail": self.last_detail,
            "last_action": self.last_action,
            "checks": self.checks,
            "logins": self.logins,
            "fail_streak": self.fail_streak,
            "local_ip": self.local_ip,
            "mac": self.mac,
            "account": build_account(self.cfg),
            "next_check_at": self.next_check_at,
        }
        write_json_atomic(STATE_FILE, payload)

    def _report_state(self, online: bool, detail: str) -> None:
        if self.last_online is None:
            level = logging.INFO if online else logging.WARNING
            log.log(level, "当前网络状态：%s（%s）", "已联网" if online else "未联网", detail)
        elif online != self.last_online:
            if online:
                log.info("网络已恢复：%s", detail)
            else:
                log.warning("检测到公网不可用：%s", detail)
        else:
            log.debug("网络状态未变：%s（%s）", "在线" if online else "离线", detail)
        self.last_online = online
        self.last_detail = detail

    def run_once(self) -> bool:
        """执行一次检测/登录流程，返回最终是否在线。"""
        self.checks += 1
        # 每轮都刷新一次身份信息，界面上在线时也能看到 IP/MAC
        self.refresh_identity()
        if self.force_login:
            online, detail = False, "强制登录模式"
        else:
            online, detail = check_internet(self.cfg)
            self._report_state(online, detail)
            if online:
                self.fail_streak = 0
                self.last_action = "在线，无需登录"
                self.write_status()
                return True

        if not self.local_ip:
            log.error("未能获取本机 IP，可能未接入任何网络，跳过本次登录")
            self.last_action = "未获取到本机 IP"
            self.write_status()
            return False

        if not portal_reachable(self.cfg):
            log.warning("校园网门户 %s:%s 不可达，可能不在校园网环境，跳过登录", self.cfg.host, self.cfg.port)
            self.last_action = "门户不可达，未尝试登录"
            self.write_status()
            return False

        ok, message = do_login(self.cfg, self.local_ip, self.mac)
        self.logins += 1
        if not ok:
            self.fail_streak += 1
            state = ac_online_state(self.cfg)
            if state == "online":
                # AC 认为在线但公网不通，通常是链路/计费侧问题，重登没有意义
                log.error("%s（连续失败 %d 次）；AC 侧显示本机仍在线", message, self.fail_streak)
            else:
                log.error("%s（连续失败 %d 次）", message, self.fail_streak)
            self.last_action = f"登录失败：{message}"
            self.write_status()
            return False

        self.fail_streak = 0
        log.info("%s；开始校验网络……", message)
        self.last_action = f"已提交登录：{message}"
        self.write_status()
        time.sleep(2)
        online, detail = check_internet(self.cfg)
        if online:
            log.info("登录后校验通过：%s", detail)
            self.last_online = True
            self.last_detail = detail
            self.last_action = "登录成功"
            self.write_status()
            return True

        log.error("登录接口返回成功，但公网仍不可用：%s", detail)
        self.last_online = False
        self.last_detail = detail
        self.last_action = "登录返回成功但公网仍不通"
        self.write_status()
        return False

    def run_forever(self) -> None:
        log.info("自动登录守护已启动，检测周期 %.0f 秒，门户 %s", self.cfg.interval, self.cfg.portal_base)
        log.info("登录账号：%s", build_account(self.cfg))
        self.write_status()
        try:
            while True:
                if stop_requested():
                    log.info("收到停止请求，守护进程退出")
                    break
                try:
                    ok = self.run_once()
                except Exception:
                    log.exception("本轮检测出现未预期的异常，稍后继续")
                    ok = False
                delay = self.cfg.interval
                if not ok:
                    # 失败后按指数退避重试，避免密码错误时把账号锁死
                    backoff = min(
                        self.cfg.retry_delay * (2 ** max(0, self.fail_streak - 1)),
                        self.cfg.max_retry_delay,
                    )
                    delay = min(delay, backoff)
                    log.info("%.0f 秒后重试", delay)
                self.next_check_at = time.time() + delay
                self.write_status()
                if sleep_until(delay):
                    log.info("收到停止请求，守护进程退出")
                    break
        except KeyboardInterrupt:
            log.info("收到中断信号，守护进程退出")
        finally:
            self.write_status(running=False)
            clear_stop_request()


def another_instance_running() -> bool:
    """检查是否有另一个守护进程在跑，避免两个实例同时登录把账号顶来顶去。"""
    return running_pid() is not None


def running_pid() -> int | None:
    """返回正在运行的守护进程 PID；没有在跑则返回 None。"""
    try:
        if not PID_FILE.is_file():
            return None
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
    except Exception:
        return None
    if pid <= 0:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            # 拒绝访问说明进程存在，只是权限不够查询；找不到进程则视为未运行
            return pid if ctypes.get_last_error() == 5 else None
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return pid
            return pid if exit_code.value == 259 else None  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def stop_requested() -> bool:
    """界面停止守护时写的标记文件。"""
    try:
        return STOP_FILE.is_file()
    except Exception:
        return False


def request_stop() -> None:
    try:
        STOP_FILE.write_text(str(time.time()), encoding="ascii")
    except Exception:
        pass


def clear_stop_request() -> None:
    try:
        STOP_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def sleep_until(seconds: float, step: float = 0.5) -> bool:
    """可被停止请求打断的等待。返回 True 表示收到了停止请求。"""
    deadline = time.time() + seconds
    while True:
        if stop_requested():
            return True
        remaining = deadline - time.time()
        if remaining <= 0:
            return False
        time.sleep(min(step, remaining))


def stop_daemon(timeout: float = 10.0) -> bool:
    """结束正在运行的守护进程，返回是否已停止。

    先用 stop.request 标记文件请它自己退出（干净，能写日志），
    超时再退回强制结束进程。
    """
    pid = running_pid()
    if pid is None:
        clear_stop_request()
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        return True

    request_stop()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if running_pid() is None:
            clear_stop_request()
            try:
                PID_FILE.unlink(missing_ok=True)
            except Exception:
                pass
            return True
        time.sleep(0.3)

    # 兜底：直接结束进程
    killed = _force_kill(pid)
    for _ in range(40):
        if running_pid() is None:
            clear_stop_request()
            try:
                PID_FILE.unlink(missing_ok=True)
            except Exception:
                pass
            return True
        time.sleep(0.25)
    return False


def _force_kill(pid: int) -> bool:
    """强制结束指定进程，先试 Win32 API，再试 taskkill。"""
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_TERMINATE = 0x0001
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            try:
                return bool(kernel32.TerminateProcess(handle, 1))
            finally:
                kernel32.CloseHandle(handle)
    except Exception:
        pass
    try:
        proc = subprocess.run(
            ["taskkill", "/pid", str(pid), "/f", "/t"],
            capture_output=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode == 0
    except Exception:
        return False


def pythonw_path() -> str:
    """找一个不弹控制台的解释器；找不到就退回当前解释器。"""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    if candidate.is_file():
        return str(candidate)
    return str(exe)


def start_daemon(config_path: Path | None = None) -> tuple[bool, str]:
    """在后台启动守护进程，返回 (是否成功, 说明)。"""
    if running_pid() is not None:
        return True, "守护进程已在运行"
    args = ["--daemon"]
    if config_path is not None:
        args += ["-c", str(config_path)]
    cmd = app_command(args)
    clear_stop_request()
    try:
        subprocess.Popen(
            cmd,
            cwd=str(APP_DIR),
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception as exc:
        return False, f"启动失败：{exc}"
    for _ in range(40):
        time.sleep(0.25)
        if running_pid() is not None:
            return True, "守护进程已启动"
    return False, "进程已拉起但未能确认运行状态，请查看日志"


# --------------------------------------------------------------------------- #
# 配置文件读写（供图形界面使用）
# --------------------------------------------------------------------------- #
CONFIG_COMMENTS = {
    "account": [
        "校园网账号（统一身份认证的用户名，一般就是学号 / 工号）",
    ],
}

OPERATOR_SUFFIX = {
    "校园网": "",
    "中国联通": "@cucc",
    "中国电信": "@ctc",
    "中国移动": "@zgyd",
}


def read_config_values(path: Path) -> dict:
    """把配置文件读成扁平字典，界面上直接绑定。"""
    cfg = load_config(path) if path.is_file() else Config()
    return {
        "username": cfg.username,
        "password": cfg.password,
        "suffix": cfg.suffix,
        "prefix": cfg.prefix,
        "mac": cfg.mac,
        "host": cfg.host,
        "port": cfg.port,
        "interval": int(cfg.interval),
        "probe_rounds": cfg.probe_rounds,
        "retry_delay": int(cfg.retry_delay),
        "max_retry_delay": cfg.max_retry_delay,
    }


def render_config(values: dict) -> str:
    """按模板生成 config.ini 全文。"""
    interval = int(round(float(values.get("interval", 300))))
    suffix = str(values.get("suffix", "")).strip()
    prefix = str(values.get("prefix", ",0,")).strip()
    # 读取端使用 interpolation=None，% 会按字面值读回，这里不做转义
    esc = lambda s: str(s).replace("\r", " ").replace("\n", " ")
    lines = [
        "# ============================================================",
        "#  校园网自动登录配置",
        "#  由图形界面保存时自动生成，也可以手动编辑",
        "# ============================================================",
        "",
        "[account]",
        "# 校园网账号（统一身份认证的用户名，一般就是学号 / 工号）",
        f"username = {esc(values.get('username', ''))}",
        "",
        "# 校园网密码（明文保存在本机，请勿把此文件发给别人）",
        f"password = {esc(values.get('password', ''))}",
        "",
        "# 运营商后缀：校园网留空；中国联通 @cucc；中国电信 @ctc；中国移动 @zgyd",
        "# 对应登录页上“请选择运营商”的下拉框",
        f"suffix = {esc(suffix)}",
        "",
        "# 账号前缀：登录页在 PC 端会自动给账号加 \",0,\"，一般不用改",
        f"prefix = {esc(prefix)}",
        "",
        "# 本机 MAC 地址，留空 = 自动探测（推荐）",
        f"mac = {esc(values.get('mac', ''))}",
        "",
        "[portal]",
        "# 校园网认证门户",
        f"host = {esc(values.get('host', '10.9.1.3'))}",
        f"port = {int(values.get('port', 801))}",
        "login_path = /eportal/?c=Portal&a=login",
        "login_method = 1",
        "js_version = 3.3.3",
        "timeout = 8",
        "",
        "[check]",
        f"# 每轮检测的间隔（秒），当前 {interval} 秒（{interval // 60} 分 {interval % 60} 秒）",
        f"interval = {interval}",
        "",
        "# 判定掉线前重复检测的轮数；只有连续全部失败才算断网，避免误判",
        f"probe_rounds = {int(values.get('probe_rounds', 2))}",
        "probe_gap = 3",
        "",
        "# 单个探测请求的超时（秒）",
        "timeout = 5",
        "",
        "# 公网探测地址，格式：URL|期望状态码|期望包含的文本",
        "# 只要有一个地址通过就认为公网正常；全部失败才判定为掉线",
        "probes =",
        "    http://connect.rom.miui.com/generate_204|204|",
        "    http://www.msftconnecttest.com/connecttest.txt|200|Microsoft Connect Test",
        "    http://www.baidu.com|200|",
        "",
        "[daemon]",
        "# 登录失败后的首次重试间隔（秒），之后按 2 倍递增",
        f"retry_delay = {int(values.get('retry_delay', 30))}",
        f"max_retry_delay = {int(values.get('max_retry_delay', 600))}",
        "",
        "# 日志文件（相对本脚本所在目录）",
        "log_file = logs/auto_login.log",
        "log_max_bytes = 1048576",
        "log_backup_count = 3",
        "",
    ]
    return "\r\n".join(lines)


def save_config_values(path: Path, values: dict) -> tuple[bool, str]:
    """校验并保存配置，返回 (是否成功, 说明)。"""
    username = str(values.get("username", "")).strip()
    password = str(values.get("password", ""))
    if not username:
        return False, "请填写账号"
    if not password:
        return False, "请填写密码"
    try:
        interval = int(round(float(values.get("interval", 300))))
    except Exception:
        return False, "检测间隔必须是数字"
    if interval < 30:
        return False, "检测间隔不能小于 30 秒"
    if interval > 86400:
        return False, "检测间隔不能超过 24 小时"

    merged = dict(values)
    merged["interval"] = interval
    merged["username"] = username
    merged["password"] = password

    text = render_config(merged)
    # 写完先自检一遍，确保能被正常解析回来
    probe = configparser.ConfigParser(interpolation=None)
    try:
        probe.read_string(text)
    except Exception as exc:
        return False, f"配置格式有误：{exc}"

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except Exception as exc:
        return False, f"写入配置失败：{exc}"
    return True, "配置已保存"


# --------------------------------------------------------------------------- #
# 开机自启（当前用户，无需管理员权限）
# --------------------------------------------------------------------------- #
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE = "CampusAutoLogin"
AUTOSTART_STARTUP_LINK = "CampusAutoLogin.vbs"


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return APP_DIR
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_script_path() -> Path:
    return _startup_dir() / AUTOSTART_STARTUP_LINK


def app_command(args: list[str] | None = None) -> list[str]:
    """拉起本程序的命令行。

    打包后直接调用 exe 自身；未打包时用 pythonw.exe 跑 auto_login.py。
    打包后的 exe 是窗口程序，不会再弹控制台。
    """
    if is_frozen():
        cmd = [str(Path(sys.executable).resolve())]
    else:
        cmd = [pythonw_path(), str(Path(__file__).resolve())]
    return cmd + list(args or [])


def autostart_target() -> str:
    """开机自启实际执行的命令行：直接以 --daemon 模式静默启动。"""
    cmd = app_command(["--daemon"])
    return subprocess.list2cmdline(cmd)


def autostart_enabled() -> bool:
    """检查是否已设置开机自启（注册表或启动文件夹任一存在即算）。"""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
            value, _ = winreg.QueryValueEx(key, AUTOSTART_VALUE)
            if value:
                return True
    except Exception:
        pass
    return _startup_script_path().is_file()


def enable_autostart() -> tuple[bool, str]:
    """设置开机自启：优先写当前用户注册表 Run 键，失败则退回启动文件夹。"""
    command = autostart_target()
    errors: list[str] = []

    try:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, AUTOSTART_VALUE, 0, winreg.REG_SZ, command)
        if autostart_enabled():
            return True, "已开启开机自启（注册表 Run 键）"
    except Exception as exc:
        errors.append(f"注册表：{exc}")

    # 退路：往“启动”文件夹放一个 VBS 启动器
    try:
        startup = _startup_dir()
        startup.mkdir(parents=True, exist_ok=True)
        vbs = "\r\n".join(
            [
                'Set shell = CreateObject("WScript.Shell")',
                f'shell.CurrentDirectory = "{APP_DIR}"',
                f'shell.Run {vbs_quote(command)}, 0, False',
                "",
            ]
        )
        _startup_script_path().write_text(vbs, encoding="mbcs")
        if autostart_enabled():
            return True, "已开启开机自启（启动文件夹）"
        errors.append("启动文件夹：写入后校验失败")
    except Exception as exc:
        errors.append(f"启动文件夹：{exc}")

    return False, "设置开机自启失败。" + "；".join(errors)


def vbs_quote(command: str) -> str:
    """把命令行包成 VBS 字符串字面量。"""
    # shell.Run 需要 "路径" "参数" 形式，内部引号用 "" 转义
    return '"' + command.replace('"', '""') + '"'


def disable_autostart() -> tuple[bool, str]:
    """取消开机自启，两条路径都清理。"""
    removed = False
    errors: list[str] = []

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, AUTOSTART_VALUE)
        removed = True
    except FileNotFoundError:
        pass
    except Exception as exc:
        errors.append(f"注册表：{exc}")

    try:
        script = _startup_script_path()
        if script.is_file():
            script.unlink()
            removed = True
    except Exception as exc:
        errors.append(f"启动文件夹：{exc}")

    if autostart_enabled():
        return False, "取消开机自启失败。" + "；".join(errors)
    return True, "已关闭开机自启" if removed else "开机自启本来就是关闭的"



# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def write_pid() -> None:
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    except Exception:
        pass


def remove_pid() -> None:
    try:
        if PID_FILE.is_file() and PID_FILE.read_text(encoding="ascii").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except Exception:
        pass


def setup_console_encoding() -> None:
    """控制台被重定向（如写日志、任务计划程序）时按 UTF-8 输出，避免中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    setup_console_encoding()
    parser = argparse.ArgumentParser(description="校园网自动登录")
    parser.add_argument("-c", "--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--once", action="store_true", help="只执行一轮后退出")
    parser.add_argument("--check", action="store_true", help="只检测网络状态，不做登录")
    parser.add_argument("--force-login", action="store_true", help="跳过检测，直接尝试登录")
    parser.add_argument("--daemon", action="store_true", help="静默后台守护（开机自启使用）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试信息")
    args = parser.parse_args(argv)

    # 打包成窗口程序后 stdout/stderr 为 None，任何 print 都会炸，这里兜底
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    cfg = load_config(Path(args.config))
    setup_logging(cfg, args.verbose)

    if args.check:
        online, detail = check_internet(cfg)
        print(f"{'已联网' if online else '未联网'}：{detail}")
        return 0 if online else 1

    if not cfg.username or not cfg.password:
        message = f"请先填写账号和密码：{args.config}"
        log.error(message)
        print(message, file=sys.stderr)
        return 2

    # --once / --force-login 只是一次性调用，不要覆盖守护进程的状态文件
    daemon = Daemon(cfg, once=args.once, force_login=args.force_login, standalone=False)
    if args.once or args.force_login:
        daemon.standalone = True
        ok = daemon.run_once()
        return 0 if ok else 1

    if another_instance_running():
        message = "已有一个自动登录进程在运行（见 auto_login.pid），本次退出"
        log.warning(message)
        print(message, file=sys.stderr)
        return 3

    write_pid()
    atexit.register(remove_pid)
    daemon.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
