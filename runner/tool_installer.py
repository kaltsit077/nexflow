"""Download / extract catalog tools into library/<id>/app/ and register scripts."""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

from .catalog import detect_tool
from .config import ROOT, load_config, save_config
from .github_auth import auth_headers, get_github_token
from .library import (
    LIBRARY_DIR,
    app_dir,
    ensure_library_root,
    ensure_project_layout,
    migrate_legacy_tools_dir,
    read_meta,
    scripts_dir,
    write_meta,
)
from .tool_catalog import CatalogTool, get_tool

LogFn = Callable[[str], None]

# Back-compat alias:「全部项目」根目录
TOOLS_DIR = LIBRARY_DIR
CACHE_DIR = ROOT / ".cache" / "tool_dl"


def _log(fn: Optional[LogFn], msg: str) -> None:
    if fn:
        fn(msg)


def prune_download_cache(*, keep_newest_per_tool: int = 1) -> int:
    """Remove old archives under .cache/tool_dl. Returns number of files deleted."""
    if not CACHE_DIR.is_dir():
        return 0
    groups: dict[str, list[Path]] = {}
    for p in CACHE_DIR.iterdir():
        if not p.is_file():
            continue
        tool_id = p.name.split("_", 1)[0] if "_" in p.name else p.stem
        groups.setdefault(tool_id, []).append(p)
    removed = 0
    for files in groups.values():
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for old in files[keep_newest_per_tool:]:
            try:
                old.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _gh_proxy(url: str) -> str:
    """Optional mirror prefix, e.g. https://ghproxy.net/"""
    proxy = (os.environ.get("GAME_RUNNER_GH_PROXY") or "").strip().rstrip("/")
    if not proxy:
        return url
    if url.startswith(proxy):
        return url
    return f"{proxy}/{url}"


def _using_proxy() -> bool:
    return bool((os.environ.get("GAME_RUNNER_GH_PROXY") or "").strip())


def _http_json(url: str, timeout: int = 60) -> Any:
    headers = {
        "User-Agent": "GameRunner-Catalog/1.0",
        "Accept": "application/vnd.github+json",
        **auth_headers(),
    }
    req = urllib.request.Request(_gh_proxy(url), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        err = str(e)
        if "403" in err or "rate limit" in err.lower():
            hint = (
                "已配置 Token 仍失败：可能是镜像不支持 API、Token 无效，或网络被拦。"
                if get_github_token()
                else "未配置 Token 时限额很低。请打开游戏目录 →「GitHub Token…」创建并保存。"
            )
            raise RuntimeError(
                "GitHub API 限流或拒绝访问。"
                f"{hint}"
                "也可点「主页」手动下载到 library\\<分项目>\\app\\ 后「扫描全部项目并导入」。"
            ) from e
        raise


def _download(url: str, dest: Path, log: Optional[LogFn] = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    final_url = _gh_proxy(url)
    _log(log, f"下载: {final_url}")
    headers = {"User-Agent": "GameRunner-Catalog/1.0", **auth_headers()}
    req = urllib.request.Request(final_url, headers=headers)
    with urllib.request.urlopen(req, timeout=600) as resp, dest.open("wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and done % (1024 * 1024 * 8) < len(chunk):
                _log(log, f"  … {done // (1024 * 1024)} / {total // (1024 * 1024)} MB")
    actual = dest.stat().st_size
    _log(log, f"已保存 {dest} ({actual // (1024 * 1024)} MB)")
    if total and actual < int(total * 0.95):
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"下载不完整: {actual} / {total} bytes")
    return dest


def _pick_asset(assets: list[dict], patterns: tuple[str, ...]) -> Optional[dict]:
    names = [(a.get("name") or "", a) for a in assets]
    for pat in patterns:
        for name, a in names:
            if fnmatch.fnmatch(name, pat):
                return a
    # fallback: first zip then 7z then exe setup
    for ext in (".zip", ".7z", ".exe"):
        for name, a in names:
            low = name.lower()
            if "source" in low or "debugsymbol" in low or "ota" in low:
                continue
            if low.endswith(ext):
                return a
    return None


def resolve_github_asset(tool: CatalogTool, log: Optional[LogFn] = None) -> dict[str, Any]:
    """Return {tag, name, url, size} for best matching release asset."""
    if not tool.repo:
        raise ValueError("no repo")
    releases = _http_json(f"https://api.github.com/repos/{tool.repo}/releases?per_page=15")
    if not isinstance(releases, list) or not releases:
        raise RuntimeError(f"无可用发行版: {tool.repo}")

    chosen = None
    for rel in releases:
        if tool.prefer_stable and rel.get("prerelease"):
            continue
        asset = _pick_asset(rel.get("assets") or [], tool.asset_patterns)
        if asset:
            chosen = (rel, asset)
            break
    if not chosen:
        # allow prerelease
        for rel in releases:
            asset = _pick_asset(rel.get("assets") or [], tool.asset_patterns)
            if asset:
                chosen = (rel, asset)
                break
    if not chosen:
        raise RuntimeError(f"未匹配到资源文件: {tool.repo} patterns={tool.asset_patterns}")

    rel, asset = chosen
    url = asset.get("browser_download_url") or ""
    info = {
        "tag": rel.get("tag_name") or "",
        "name": asset.get("name") or "",
        "url": url,
        "size": int(asset.get("size") or 0),
    }
    _log(log, f"选中 {tool.repo}@{info['tag']} → {info['name']}")
    return info


def _find_7z() -> Optional[str]:
    for cand in (
        shutil.which("7z"),
        shutil.which("7z.exe"),
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ):
        if cand and Path(cand).is_file():
            return cand
    return None


def _extract_archive(archive: Path, dest: Path, log: Optional[LogFn] = None) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    suf = archive.suffix.lower()
    if suf == ".zip":
        _log(log, f"解压 zip → {dest}")
        dest_r = dest.resolve()
        with zipfile.ZipFile(archive, "r") as zf:
            for info in zf.infolist():
                target = (dest_r / info.filename).resolve()
                try:
                    target.relative_to(dest_r)
                except ValueError as e:
                    raise RuntimeError(f"拒绝不安全 zip 路径: {info.filename}") from e
            zf.extractall(dest)
        return dest
    if suf == ".7z":
        seven = _find_7z()
        if not seven:
            raise RuntimeError(
                "需要 7-Zip 才能解压 .7z。请安装 https://www.7-zip.org/ 后重试，"
                "或手动解压后点「扫描导入」。"
            )
        _log(log, f"7z 解压 → {dest}")
        subprocess.run(
            [seven, "x", str(archive), f"-o{dest}", "-y"],
            check=True,
            capture_output=True,
        )
        return dest
    if suf == ".exe":
        # installer: copy beside and launch later
        target = dest / archive.name
        shutil.copy2(archive, target)
        return target
    raise RuntimeError(f"不支持的压缩格式: {suf}")


def _unwrap_single_root(folder: Path) -> Path:
    """If extract created one top-level dir, use it."""
    if not folder.is_dir():
        return folder
    kids = [p for p in folder.iterdir() if p.name not in (".DS_Store",)]
    if len(kids) == 1 and kids[0].is_dir():
        return kids[0]
    return folder


def register_detected(path: Path, cfg: Optional[dict] = None) -> dict[str, Any]:
    """detect_tool + append to config if new."""
    result = detect_tool(str(path))
    if not result.get("ok"):
        return result
    script = dict(result["script"])
    cfg = cfg if cfg is not None else load_config()
    existing = {s["id"] for s in cfg.get("scripts", [])}
    sid = script["id"]
    base = sid
    n = 2
    while sid in existing:
        # update path if same id already points elsewhere? keep unique
        sid = f"{base}_{n}"
        n += 1
    script["id"] = sid
    # if base id exists with same tool fingerprint, replace path instead
    for s in cfg.get("scripts", []):
        if s.get("id") == base and s.get("type") == script.get("type"):
            s.update({k: v for k, v in script.items() if k != "id"})
            s["id"] = base
            save_config(cfg)
            return {"ok": True, "script": s, "updated": True, "label": result.get("label")}
    cfg.setdefault("scripts", []).append(script)
    save_config(cfg)
    return {"ok": True, "script": script, "updated": False, "label": result.get("label")}


def scan_and_register(root: Path, log: Optional[LogFn] = None) -> dict[str, Any]:
    root = Path(root)
    if not root.exists():
        return {"ok": False, "error": f"路径不存在: {root}"}
    # try root then shallow children
    candidates = [root]
    if root.is_dir():
        for p in list(root.iterdir())[:30]:
            if p.is_dir():
                candidates.append(p)
            elif p.suffix.lower() == ".exe":
                candidates.append(p)
    last_err = "未识别"
    for c in candidates:
        r = detect_tool(str(c))
        if r.get("ok"):
            reg = register_detected(c)
            _log(log, f"已登记: {reg.get('script', {}).get('id')}")
            return reg
        last_err = r.get("error") or last_err
    return {"ok": False, "error": last_err}


def install_tool(tool_id: str, log: Optional[LogFn] = None) -> dict[str, Any]:
    """
    Install into library/<id>/app/（项目本体）, keep library/<id>/scripts/（项目脚本）.
    """
    tool = get_tool(tool_id)
    if not tool:
        return {"ok": False, "error": f"未知工具: {tool_id}"}

    msg = migrate_legacy_tools_dir()
    if msg:
        _log(log, msg)

    ensure_library_root()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ensure_project_layout(tool.id, title=f"{tool.game} · {tool.name}", notes=tool.notes)
    dest_app = app_dir(tool.id)

    if tool.kind == "open_url":
        return {
            "ok": True,
            "open_url": tool.homepage,
            "message": tool.notes or "请在浏览器下载后解压到对应分项目的 app\\，再「扫描导入」。",
        }

    if tool.kind == "local_bundle":
        path = ROOT / tool.local_path
        if not path.exists():
            return {"ok": False, "error": f"本地包不存在: {path}"}
        # Link-style: copy/symlink note into library scripts; register original path
        tip = scripts_dir(tool.id) / "source_path.txt"
        tip.write_text(str(path.resolve()) + "\n", encoding="utf-8")
        write_meta(tool.id, {"kind": "local_bundle", "source": str(path.resolve())})
        reg = register_detected(path)
        if not reg.get("ok"):
            if (path / "interface.json").is_file():
                cfg = load_config()
                script = {
                    "id": "click_lab",
                    "name": "识图点按实验 (click_lab)",
                    "type": "maafw",
                    "path": str(path.resolve()),
                    "args": ["-d"],
                    "timeout_sec": 600,
                    "tags": ["maafw", "demo"],
                }
                if not any(s["id"] == "click_lab" for s in cfg.get("scripts", [])):
                    cfg.setdefault("scripts", []).append(script)
                    save_config(cfg)
                return {
                    "ok": True,
                    "path": str(path),
                    "script": script,
                    "message": f"已登记 click_lab（本体仍在 projects\\；分项目见 library\\{tool.id}\\）",
                }
            return reg
        return {
            "ok": True,
            "path": str(path),
            "message": f"已登记；分项目目录 library\\{tool.id}\\",
            **{k: v for k, v in reg.items() if k not in ("ok",)},
        }

    if tool.kind == "setup_bat":
        bat = ROOT / tool.local_path
        if not bat.is_file():
            return {"ok": False, "error": f"缺少 {bat}"}
        _log(log, f"运行 {bat}")
        subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(ROOT), shell=False)
        write_meta(tool.id, {"kind": "setup_bat", "target": str(ROOT / "maafw")})
        return {
            "ok": True,
            "path": str(ROOT / "maafw"),
            "message": "已启动 setup_maafw.bat → maafw\\（运行时，非 library 本体）。",
            "opened_installer": True,
        }

    if tool.kind != "github_release":
        return {"ok": False, "error": f"不支持的安装类型: {tool.kind}"}

    if get_github_token():
        _log(log, "GitHub API：已携带 Token")
    else:
        _log(log, "GitHub API：未配置 Token（易限流）→ 游戏目录「GitHub Token…」")
    try:
        info = resolve_github_asset(tool, log=log)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "homepage": tool.homepage}

    if _using_proxy():
        _log(log, "注意: GAME_RUNNER_GH_PROXY 会改写下载地址，请只使用你信任的镜像。")

    asset_name = (info.get("name") or "").lower()
    if asset_name.endswith(".7z") and not _find_7z():
        return {
            "ok": False,
            "error": "该发行包是 .7z，需要先安装 7-Zip: https://www.7-zip.org/",
            "homepage": tool.homepage,
        }

    archive = CACHE_DIR / f"{tool.id}_{info['name']}"
    try:
        if not archive.is_file() or archive.stat().st_size < 1024:
            _download(info["url"], archive, log=log)
        else:
            _log(log, f"使用缓存 {archive.name}")
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"下载失败: {e}",
            "homepage": tool.homepage,
            "hint": "可设置 GAME_RUNNER_GH_PROXY=https://ghproxy.net 后重试",
        }

    name_l = archive.name.lower()
    if archive.suffix.lower() == ".exe" and ("setup" in name_l or "install" in name_l):
        target = dest_app / archive.name
        # clear old app contents carefully — keep folder
        dest_app.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive, target)
        write_meta(
            tool.id,
            {
                "kind": "setup_exe",
                "tag": info["tag"],
                "installer": archive.name,
                "app": str(dest_app),
            },
        )
        _log(log, f"启动安装程序 {target}")
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception:
            subprocess.Popen([str(target)], shell=True)
        return {
            "ok": True,
            "path": str(dest_app),
            "opened_installer": True,
            "message": (
                f"安装包已放到 library\\{tool.id}\\app\\ 并已启动。\n"
                f"装完后点「扫描全部项目」或手动导入本体目录。"
            ),
            "tag": info["tag"],
        }

    # extract into app/
    if dest_app.exists():
        for child in list(dest_app.iterdir()):
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
    dest_app.mkdir(parents=True, exist_ok=True)
    try:
        extracted = _extract_archive(archive, dest_app, log=log)
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(e),
            "archive": str(archive),
            "path": str(dest_app),
            "homepage": tool.homepage,
        }

    if extracted.is_file() and extracted.suffix.lower() == ".exe":
        try:
            os.startfile(str(extracted))  # type: ignore[attr-defined]
        except Exception:
            pass
        write_meta(tool.id, {"kind": "exe", "tag": info["tag"], "file": extracted.name})
        return {
            "ok": True,
            "path": str(dest_app),
            "opened_installer": True,
            "message": f"已打开安装包（位于 library\\{tool.id}\\app\\）。",
            "tag": info["tag"],
        }

    folder = _unwrap_single_root(dest_app)
    write_meta(
        tool.id,
        {
            "kind": "github_release",
            "tag": info["tag"],
            "asset": info["name"],
            "app": str(folder),
            "scripts": str(scripts_dir(tool.id)),
        },
    )
    try:
        n = prune_download_cache(keep_newest_per_tool=1)
        if n:
            _log(log, f"已清理旧下载缓存 {n} 个文件")
    except OSError:
        pass
    reg = scan_and_register(folder, log=log)
    if not reg.get("ok"):
        return {
            "ok": True,
            "path": str(folder),
            "message": (
                f"本体已解压到 library\\{tool.id}\\app\\，识别失败：{reg.get('error')}。"
                "请「导入」该 app 目录。"
            ),
            "tag": info["tag"],
            "need_import": True,
        }
    return {
        "ok": True,
        "path": str(folder),
        "script": reg.get("script"),
        "message": (
            f"已安装到 library\\{tool.id}\\app\\ 并登记 "
            f"{reg.get('script', {}).get('id')}；脚本目录 scripts\\"
        ),
        "tag": info["tag"],
        "label": reg.get("label"),
    }


def installed_status(tool_id: str) -> dict[str, Any]:
    """Prefer library/<id>/meta.json + app contents; then config path under library."""
    tool = get_tool(tool_id)
    path = app_dir(tool_id)
    meta = read_meta(tool_id)
    has_app = path.is_dir() and any(path.iterdir())
    cfg = load_config()
    scripts = cfg.get("scripts", [])
    hit = None
    lib_prefix = str((LIBRARY_DIR / tool_id).resolve()).replace("/", "\\")
    for s in scripts:
        sp = str(s.get("path", "")).replace("/", "\\")
        if lib_prefix and lib_prefix in sp:
            hit = s
            break
        if tool and tool.id == "click_lab" and s.get("id") == "click_lab":
            hit = s
            break
        if tool and tool.id == "maafw_runtime" and (ROOT / "maafw" / "MaaPiCli.exe").is_file():
            return {"installed": True, "path": str(ROOT / "maafw"), "script": None, "meta": meta}
    return {
        "installed": bool(meta) or has_app or bool(hit),
        "path": str(path) if path.exists() else "",
        "script": hit,
        "meta": meta,
    }
