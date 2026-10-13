"""Known game / assistant catalog for in-app install & import."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class CatalogTool:
    id: str
    game: str
    name: str
    kind: str  # github_release | local_bundle | open_url | setup_bat
    description: str
    # github
    repo: str = ""  # owner/name
    asset_patterns: tuple[str, ...] = ()
    prefer_stable: bool = True  # skip prerelease when possible
    # after extract / download
    detect_hint: str = ""  # folder name under tools/ or relative
    # local
    local_path: str = ""
    # open browser only
    homepage: str = ""
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


# Install root: <app>/tools/<id>/
TOOLS: list[CatalogTool] = [
    CatalogTool(
        id="maa_arknights",
        game="明日方舟",
        name="MAA（官方）",
        kind="github_release",
        description="MaaAssistantArknights 完整包。下载解压后自动登记为 exe 脚本。",
        repo="MaaAssistantArknights/MaaAssistantArknights",
        asset_patterns=("MAA-*-win-x64.zip", "MAA-*win*x64*.zip"),
        prefer_stable=True,
        homepage="https://github.com/MaaAssistantArknights/MaaAssistantArknights/releases",
        notes="体积约 250MB+。国内慢可设环境变量 GAME_RUNNER_GH_PROXY。",
        tags=("arknights", "maa", "exe"),
    ),
    CatalogTool(
        id="bettergi",
        game="原神",
        name="BetterGI",
        kind="github_release",
        description="更好的原神。优先便携 7z/zip；若只有安装包则下载后请手动安装。",
        repo="babalae/better-genshin-impact",
        asset_patterns=(
            "BetterGI_v*.7z",
            "BetterGI_v*.zip",
            "BetterGI*.7z",
            "BetterGI.Install.*.exe",
        ),
        prefer_stable=True,
        homepage="https://bettergi.com/download.html",
        notes="7z 需本机已装 7-Zip，或改用安装版 exe。",
        tags=("genshin", "bettergi", "exe"),
    ),
    CatalogTool(
        id="march7th",
        game="崩坏：星穹铁道",
        name="三月七助手",
        kind="github_release",
        description="March7thAssistant 完整包（优先 zip）。",
        repo="moesnow/March7thAssistant",
        asset_patterns=(
            "March7thAssistant_full.zip",
            "March7thAssistant_full.7z",
            "*full*.zip",
        ),
        prefer_stable=True,
        homepage="https://github.com/moesnow/March7thAssistant/releases",
        notes="解压后入口多为 March7thAssistant.exe / March7th Launcher.exe。",
        tags=("starrail", "march7th", "exe"),
    ),
    CatalogTool(
        id="ok_ww",
        game="鸣潮",
        name="ok-ww",
        kind="github_release",
        description="鸣潮自动化。下载官方 setup 安装包（非 SourceCode）。",
        repo="ok-oldking/ok-wuthering-waves",
        asset_patterns=(
            "ok-ww-win32-China-setup.exe",
            "ok-ww-win32-Global-setup.exe",
            "ok-ww-win32*setup*.exe",
        ),
        prefer_stable=True,
        homepage="https://github.com/ok-oldking/ok-wuthering-waves/releases",
        notes="安装程序需你点几下向导；装完后可在目录里「扫描导入」或手动导入 ok-ww.exe。",
        tags=("wuthering", "ok-ww", "setup"),
    ),
    CatalogTool(
        id="alas",
        game="碧蓝航线",
        name="Alas",
        kind="github_release",
        description="AzurLaneAutoScript 整合包（7z）。",
        repo="LmeSzinc/AzurLaneAutoScript",
        asset_patterns=(
            "AlasApp_*_fullcn.7z",
            "AlasApp_*_full.7z",
            "AlasApp_*.7z",
        ),
        prefer_stable=True,
        homepage="https://github.com/LmeSzinc/AzurLaneAutoScript/releases",
        notes="需 7-Zip。不要下 Source Code。",
        tags=("azurlane", "alas", "exe"),
    ),
    CatalogTool(
        id="mfabd2",
        game="棕色尘埃2",
        name="MFABD2 / MaaBD2",
        kind="github_release",
        description="棕色尘埃2 MaaFW 助手发行包（sunyink/MFABD2）。",
        repo="sunyink/MFABD2",
        asset_patterns=(
            "*win*x64*.zip",
            "*win*.zip",
            "*.zip",
        ),
        prefer_stable=True,
        homepage="https://github.com/sunyink/MFABD2/releases",
        notes="若本机已有 BD2MAA 文件夹，也可直接「导入」该目录。",
        tags=("browndust", "maafw"),
    ),
    CatalogTool(
        id="maayuan",
        game="代号鸢 / 如鸢",
        name="MaaYuan",
        kind="github_release",
        description="代号鸢/如鸢 MaaFW 小助手。",
        repo="syoius/MaaYuan",
        asset_patterns=("*win*.zip", "*Windows*.zip", "*.zip"),
        prefer_stable=True,
        homepage="https://github.com/syoius/MaaYuan/releases",
        tags=("yuan", "maafw"),
    ),
    CatalogTool(
        id="maanikke",
        game="胜利女神：NIKKE",
        name="MaaNikke",
        kind="github_release",
        description="NIKKE 日常助手（MaaFW）。",
        repo="Shinarin/MaaNikke",
        asset_patterns=("*win*.zip", "*.zip", "*.7z"),
        prefer_stable=True,
        homepage="https://github.com/Shinarin/MaaNikke/releases",
        tags=("nikke", "maafw"),
    ),
    CatalogTool(
        id="mxu",
        game="通用（MaaFW GUI）",
        name="MXU",
        kind="github_release",
        description="MaaFramework 通用 GUI。解压 mxu.exe 后需自备 maafw 与 interface 项目。",
        repo="MistEO/MXU",
        asset_patterns=("MXU-win-x86_64*.zip", "MXU-win*.zip"),
        prefer_stable=True,
        homepage="https://github.com/MistEO/MXU/releases",
        notes="调度无人值守仍推荐 MaaPiCli；MXU 适合交互编写。",
        tags=("maafw", "mxu", "gui"),
    ),
    CatalogTool(
        id="maafw_runtime",
        game="运行时",
        name="MaaFramework 运行时",
        kind="setup_bat",
        description="安装与 pip MaaFw 对齐的官方 maafw\\（录制连控 / MaaPiCli）。",
        local_path="tools/setup_maafw.bat",
        homepage="https://github.com/MaaXYZ/MaaFramework/releases",
        notes="默认 v5.14.2。也可用 tools\\setup_maafw.bat。",
        tags=("maafw", "runtime"),
    ),
    CatalogTool(
        id="click_lab",
        game="练习 / 自建",
        name="识图点按实验 click_lab",
        kind="local_bundle",
        description="附带 MaaFW 练手项目（OCR/模板）。已在 projects\\click_lab。",
        local_path="projects/click_lab",
        homepage="",
        notes="可在脚本「编辑」→录制页导出 pipeline。",
        tags=("maafw", "demo"),
    ),
    CatalogTool(
        id="lcba",
        game="边狱公司",
        name="LCBA",
        kind="open_url",
        description="Limbus 小助手。作者多在 B 站分发，无稳定 GitHub 自动包。",
        homepage="https://www.bilibili.com/video/BV11G411t7fb",
        notes="下载解压后用顶栏「导入」选 Start.exe 所在目录。路径请用英文。",
        tags=("limbus", "manual"),
    ),
    CatalogTool(
        id="kaa",
        game="其它",
        name="KAA（bootstrap）",
        kind="open_url",
        description="kaa-bootstrap / ksaa 需 pip 安装，不适合整包 zip 直装。",
        homepage="https://pypi.org/project/ksaa/",
        notes="本机若有 kaa-bootstrap，可用 bat 启动；或自行 pip install ksaa。",
        tags=("kaa", "manual"),
    ),
]


def list_tools() -> list[CatalogTool]:
    return list(TOOLS)


def get_tool(tool_id: str) -> Optional[CatalogTool]:
    for t in TOOLS:
        if t.id == tool_id:
            return t
    return None


def tools_as_dicts() -> list[dict[str, Any]]:
    out = []
    for t in TOOLS:
        out.append(
            {
                "id": t.id,
                "game": t.game,
                "name": t.name,
                "kind": t.kind,
                "description": t.description,
                "repo": t.repo,
                "homepage": t.homepage,
                "notes": t.notes,
                "tags": list(t.tags),
            }
        )
    return out
