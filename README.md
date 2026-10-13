# NexFlow

Elegant **desktop flow scheduler** (PySide6) — configure once, one click to launch emulators, games, and assistants end-to-end.

Formerly *Game Runner* in local folders; the product idea is the same.

- **Own scripts** → official [MaaFramework](https://github.com/MaaXYZ/MaaFramework) PI projects (`type=maafw`, run via `MaaPiCli -d`)
- **Other helpers** → external black boxes (MAA.exe, BetterGI, March7th, …)
- **Distribution model** → **whole folder / source** (same idea as MAA). Packaging is deferred until the product is done.

## Layout

```text
nexflow/                     ← keep this folder together
├── main.py / start.bat      # daily entry
├── cli.py
├── runner/                  # scheduler engine
├── ui/                      # PySide6
├── projects/                # MaaFW PI projects
├── maafw/                   # MaaPiCli runtime (tools\setup_maafw.bat)
├── library/                 # installed assistants (not in git)
├── config.example.json      # copy → config.json
├── clean.bat                # caches / logs / old dist leftovers
└── build.bat                # packaging DEFERRED (optional: build.bat --force)
```

## Docs

- **中文使用说明（推荐）** → [`docs/使用说明.md`](docs/使用说明.md)
- **功能接口与布局** → [`docs/功能接口与布局.md`](docs/功能接口与布局.md)
- **需求澄清 / 拓扑 / 模糊点** → [`docs/需求澄清与模糊点.md`](docs/需求澄清与模糊点.md)
- **AI 分层规则** → [`AGENTS.md`](AGENTS.md) + `.cursor/rules/`
- 识图点按练手 → [`projects/click_lab/DEV.md`](projects/click_lab/DEV.md)
- 架构检测 → `python tools/check_architecture.py`

## Run（日常）

```powershell
python tools\doctor.py          # optional self-check
start.bat                       # installs deps / maafw if missing, then UI
# or: python main.py
```

`maafw\` must be v5.14.2 (matches pip `MaaFw`). Prefer always launching from this folder.

CLI:

```powershell
python cli.py list
python cli.py run-list "Morning chain"
```

## Packaging（以后再说）

功能做完前请用 **源码目录 + `start.bat`**，不要依赖 `dist\GameRunner.exe`。  
若临时需要目录版发布：`build.bat --force` → `dist\GameRunner\`（onedir，非整包单文件）。

## Architecture

```text
[PySide6 UI / CLI]
      ↓
[runner executor]  sequential · timeout · retry · fallback · kill tree
      ↓
  maafw → MaaPiCli -d   |   exe/python/bat → external tools
```

Studio uses in-process MaaFw; scheduled `type=maafw` still uses `MaaPiCli -d`.

## Script content (image → click)

[`projects/click_lab/DEV.md`](projects/click_lab/DEV.md)

```bat
tools\setup_maafw.bat
tools\setup_ocr.bat
tools\open_click_lab.bat
```
