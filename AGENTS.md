# Game Runner — AI 工作入口

产品目标：**配置一次 → 点一次跑通全流程**（含拉起游戏/模拟器/助手），不把「用户先手动开游戏」当正常路径。详见 `docs/需求澄清与模糊点.md` §1 / F8。

先读：

- [`docs/功能接口与布局.md`](docs/功能接口与布局.md)（链路=分区、接口一对一）
- [`docs/需求澄清与模糊点.md`](docs/需求澄清与模糊点.md)

分层硬规则：`.cursor/rules/*.mdc`

## 层一览

| 层 | 路径 | AI 可碰 | 禁止 |
|---|---|---|---|
| 入口 | `main.py`, `cli.py` | 接线、参数 | 业务策略 |
| 引擎 | `runner/` | 调度、配置、安装、Maa 会话、导出 | `import ui` |
| 展示 | `ui/` | 控件、样式、线程胶水 | 调度语义、进程杀树、指纹识别实现 |
| PI 内容 | `projects/` | `interface.json` / pipeline / image | Python 调度逻辑 |
| 运维 | `tools/`, `*.bat` | 安装脚本、`start.bat` | 改引擎语义；勿把单文件打包当日常入口 |
| 数据 | `library/`, `logs/`, `config.json` | 经 API 读写 | 手改二进制/乱删用户库 |

**分发：** 日常 = 源码整目录 + `start.bat`（对齐 MAA 文件夹形态）。`build.bat` 默认不打包；仅 `build.bat --force` 才打 onedir。

## 改代码前

1. 新行为落在哪一层？对照上表。  
2. 是否踩到模糊点 F1–F8？有则先改澄清文档再改代码。  
3. 做完跑：`python tools/check_architecture.py`  
4. 环境疑虑：`python tools/doctor.py`（日常入口始终是 `start.bat`）
