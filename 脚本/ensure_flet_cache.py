# -*- coding: utf-8 -*-
"""Pre-download Flet client archive (flet-windows.zip) with mirror fallback,
then extract into the Flet client cache dir so `flet pack` can skip the download.

Runs BEFORE `flet pack` as part of the build.
"""
import os, sys, zipfile, tempfile, time, urllib.request, urllib.parse, ssl
from pathlib import Path

FLET_VERSION = "0.86.5"
ARTIFACT = "flet-windows.zip"
FLAVOR = "full"

ORIG_URL = f"https://github.com/flet-dev/flet/releases/download/v{FLET_VERSION}/{ARTIFACT}"
MIRRORS = [
    f"https://gh.api.99988866.xyz/{ORIG_URL}",
    f"https://ghproxy.net/{ORIG_URL}",
    f"https://mirror.ghproxy.com/{ORIG_URL}",
    ORIG_URL,
]

CACHE_DIR = (Path(__file__).parent.parent / "_flet_client").resolve()  # 脚本/ 的上级 = 项目根

# 允许的下载源域名白名单 (仅官方 GitHub 与已知镜像, 防 SSRF)
_ALLOWED_DL_HOSTS = {
    'github.com',
    'gh.api.99988866.xyz',
    'ghproxy.net',
    'mirror.ghproxy.com',
}


def _validate_download_url(url):
    """校验下载 URL: 仅 http/https + 域名白名单 (防 SSRF 访问内网/元数据)"""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ('http', 'https'):
        raise ValueError(f"仅允许 http/https 协议: {url}")
    host = (p.hostname or '').lower()
    if not host or host not in _ALLOWED_DL_HOSTS:
        raise ValueError(f"下载域名不在白名单: {host}")
    return url


def log(msg=""):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def benchmark_sample(url, sample=1024*1024, timeout=20):
    """GET first `sample` bytes via Range; return (speed_MBps or None, info)."""
    _validate_download_url(url)  # 安全校验 (防 SSRF)
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"Range": f"bytes=0-{sample-1}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            total = 0
            last = time.time()
            while total < sample:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                now = time.time()
                if now - last > timeout:
                    return None, "stalled"
                last = now
            dt = max(time.time() - t0, 0.001)
            return total / 1048576 / dt, f"{total/1048576:.2f}MB {dt:.1f}s"
    except Exception as exc:
        return None, f"{exc.__class__.__name__}: {exc}"[:120]

def download(url, dest, stall_s=10):
    """Full download with per-chunk stall detection. Returns bytes received."""
    # 安全校验 (防 SSRF): 协议 + 域名白名单 + 公网地址
    _p = urllib.parse.urlparse(url)
    if _p.scheme not in ('http', 'https') or (_p.hostname or '').lower() not in _ALLOWED_DL_HOSTS:
        raise ValueError(f"非法下载地址: {url}")
    import ipaddress as _ipa
    try:
        _ip = _ipa.ip_address(_p.hostname)
        if _ip.is_private or _ip.is_loopback or _ip.is_link_local \
                or _ip.is_reserved or _ip.is_multicast or _ip.is_unspecified:
            raise ValueError(f"内网地址: {url}")
    except ValueError as _ve:
        if '内网' in str(_ve):
            raise
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=30, context=ctx) as resp:
        total = resp.headers.get("Content-Length")
        total = int(total) if total else None
        got = 0
        start = last = time.time()
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                now = time.time()
                if now - last > stall_s:
                    raise TimeoutError(f"stalled {stall_s}s at {got}/{total or '?'} bytes")
                last = now
                if total:
                    pct = 100 * got / total
                    spd = got / 1048576 / max(now - start, 0.001)
                    bar = "=" * max(0, int(pct / 5))
                    sys.stdout.write(
                        f"\r  [{bar:<20}] {pct:5.1f}%  {got/1048576:6.1f}/"
                        f"{total/1048576:5.1f}MB  {spd:5.2f}MB/s   "
                    )
                else:
                    sys.stdout.write(f"\r  received {got/1048576:6.1f}MB ...   ")
                sys.stdout.flush()
        sys.stdout.write("\n")
    return got

def extract(archive_path: str, target: Path):
    log(f"  Extract -> {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f"{target.name}.tmp{os.getpid()}"
    import shutil
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        if archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                # 安全: zip-slip 防护 — 拒绝绝对路径与 ../ 穿越成员
                for member in zf.infolist():
                    name = member.filename.replace('\\', '/')
                    if name.startswith('/') or '..' in name.split('/'):
                        raise ValueError(f"压缩包含非法路径: {member.filename}")
                zf.extractall(str(tmp))
        else:
            import tarfile
            with tarfile.open(archive_path, "r:gz") as tf:
                # filter='data' 拒绝绝对路径与 .. 穿越 (Python 3.12+)
                tf.extractall(str(tmp), filter='data')
        # FLET_VIEW_PATH expected layout: flet.exe DIRECTLY under view path
        # But default zips use root dir "flet/", so flatten one level if needed
        contents = list(tmp.iterdir())
        if len(contents) == 1 and contents[0].is_dir():
            inner = contents[0]
            # Move every child of inner/ -> tmp/
            for child in inner.iterdir():
                shutil.move(str(child), str(tmp / child.name))
            inner.rmdir()
        try:
            os.rename(str(tmp), str(target))
        except OSError:
            shutil.move(str(tmp), str(target))
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

def main():
    log("=" * 56)
    log("Novel Crawler - Flet Client Pre-Download & Cache")
    log("=" * 56)

    if CACHE_DIR.exists():
        log(f"[OK] Already cached -> {CACHE_DIR}")
        return 0
    log(f"[INFO] Target cache : {CACHE_DIR}")
    log(f"[INFO] Artifact     : {ARTIFACT} v{FLET_VERSION}")
    log("")
    log("[1/3] Benchmarking mirrors (1MB speed sample, ~1 min total)...")

    scored = []  # (speed_MBps, url, host)
    for m in MIRRORS:
        host = urllib.parse.urlparse(m).hostname
        sys.stdout.write(f"[{time.strftime('%H:%M:%S')}]       {host:30s}  testing 1MB ... ")
        sys.stdout.flush()
        speed, info = benchmark_sample(m)
        if speed is not None:
            sys.stdout.write(f"OK   {speed:6.2f} MB/s  ({info})\n")
            sys.stdout.flush()
            scored.append((speed, m, host))
        else:
            sys.stdout.write(f"FAIL ({info})\n")
            sys.stdout.flush()

    if not scored:
        log("[FATAL] All mirrors failed. Check network / proxy, then retry.")
        return 2
    scored.sort(key=lambda x: -x[0])
    best_speed, best_url, best_host = scored[0]
    log(f"[PICK] {best_host} @ {best_speed:.2f} MB/s")

    log("")
    log("[2/3] Full download (~38MB)...")
    tmp_dir = Path(tempfile.gettempdir()) / f"novelcrawler_flet_{os.getpid()}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    archive = tmp_dir / ARTIFACT

    # Build candidate list: fastest first, then rest descending speed, then original
    queue = [best_url] + [u for (_, u, _) in scored[1:]]
    # append remaining (failed) mirrors at the end as final fallback
    tried = set(queue)
    for m in MIRRORS:
        if m not in tried:
            queue.append(m)

    ok = False
    max_attempts = max(6, 2 * len(queue))
    attempts = 0
    cursor = 0
    while attempts < max_attempts and cursor < len(queue):
        url = queue[cursor]
        # allow retry each mirror twice: wrap around cursor until we've done all twice
        attempts += 1
        log(f"  Attempt {attempts}/{max_attempts}  via {urllib.parse.urlparse(url).hostname}")
        if archive.exists():
            archive.unlink()
        try:
            size = download(url, str(archive))
            # flet-windows.zip full binary is ~38..110MB depending on flavor/version
            if size and size >= 20_000_000:
                ok = True
                log(f"  OK {size/1048576:.1f} MB")
                break
            log(f"  Result too small ({size/1024:.0f} KB) - likely error HTML. Try next mirror.")
            archive.unlink(missing_ok=True)
            cursor += 1
        except Exception as exc:
            log(f"  FAIL {exc.__class__.__name__}: {exc}")
            archive.unlink(missing_ok=True)
            cursor += 1

    if not ok:
        import shutil as _s
        _s.rmtree(str(tmp_dir), ignore_errors=True)
        log("[FATAL] All mirrors failed to deliver the archive.")
        return 3

    log("")
    log("[3/3] Extract archive to cache...")
    try:
        extract(str(archive), CACHE_DIR)
    except Exception as exc:
        log(f"[FATAL] Extract failed: {exc}")
        return 4
    finally:
        import shutil as _s
        _s.rmtree(str(tmp_dir), ignore_errors=True)

    log(f"[SUCCESS] Client cached -> {CACHE_DIR}")
    # Quick sanity listing
    log("  Contents preview:")
    n = 0
    for p in sorted(CACHE_DIR.rglob("*")):
        if n >= 10:
            break
        rel = p.relative_to(CACHE_DIR)
        pre = "[D]" if p.is_dir() else f"{p.stat().st_size/1024:6.0f}KB"
        log(f"    {pre}  {rel}")
        n += 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
