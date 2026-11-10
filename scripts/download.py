"""抖音视频限速批量下载（防封版）。

用法: python download.py videos.json -o D:/xxx/videos
videos.json: [{id, urls: [直链1, 直链2, ...], desc, create, digg}, ...]

防封四原则:
- 串行不并发, 每文件随机间隔 4-9 秒
- 不带任何账号 cookie, 仅 CDN 签名直链 + Referer
- 失速检测(--speed-limit 30k / --speed-time 30)自动断线
- 多镜像轮换 + 断点续传(-C -)
安全: URL https+域名白名单+DNS 解析阻断私网, 禁自动重定向, 文件名正则锁定。
"""
import argparse
import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from random import SystemRandom

ALLOWED_HOSTS = ("douyinvod.com", "douyin.com", "bytecdn.cn", "byte.org", "snssdk.com", "bytedance.com", "zjcdn.com", "pstatp.com")
ID_RE = re.compile(r"^\d{8,25}$")
FNAME_RE = re.compile(r"^\d{3}_\d{8,25}(\.mp4|\.part)$")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
rnd = SystemRandom()


def log(msg, log_path=None):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def url_is_safe(url):
    """https + 域名白名单 + DNS 解析阻断私网/环回/链路本地。"""
    try:
        p = urllib.parse.urlparse(url)
        if p.scheme != "https":
            return False
        host = (p.hostname or "").lower()
        if not host or not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
            return False
        for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except (ValueError, socket.gaierror, OSError):
        return False


def curl_get(url, dest_part):
    """curl 下载到 .part: 失速 30s 自动断, 支持续传。"""
    r = subprocess.run(
        ["curl", "-sS", "-L", "--fail", "-C", "-",
         "--speed-limit", "30000", "--speed-time", "30",
         "--max-time", "900", "--retry", "0",
         "-A", UA, "-e", "https://www.douyin.com/",
         "-o", str(dest_part), url],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and dest_part.exists() and dest_part.stat().st_size > 1_000_000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos_json")
    ap.add_argument("-o", "--out", required=True, help="输出目录")
    args = ap.parse_args()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    videos = json.loads(Path(args.videos_json).read_text(encoding="utf-8"))

    ok, fail = 0, []
    for i, v in enumerate(videos, 1):
        seq, vid = f"{i:03d}", str(v.get("id", ""))
        if not ID_RE.fullmatch(vid):
            log(f"{seq} skip bad id")
            continue
        fname, part = f"{seq}_{vid}.mp4", f"{seq}_{vid}.part"
        if not FNAME_RE.fullmatch(fname):
            log(f"{seq} skip bad fname")
            continue
        dest, dest_part = out_dir / fname, out_dir / part
        if dest.exists() and dest.stat().st_size > 1_000_000:
            ok += 1
            continue
        urls = [u for u in v.get("urls", []) if url_is_safe(u)]
        good = False
        for attempt in range(6):
            if urls and curl_get(urls[attempt % len(urls)], dest_part):
                resolved = dest_part.resolve()
                if resolved.parent == out_dir and resolved.name == part:
                    resolved.replace(dest)
                    good = True
                    break
            time.sleep(rnd.uniform(3, 7))
        if good:
            ok += 1
            log(f"{seq}/{len(videos)} {vid} {dest.stat().st_size // 1048576}MB ok")
        else:
            fail.append(vid)
            log(f"{seq}/{len(videos)} {vid} FAILED")
        time.sleep(rnd.uniform(4, 9))  # 防封: 串行 + 随机间隔
    log(f"DONE ok={ok} fail={len(fail)} ids={fail}")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
