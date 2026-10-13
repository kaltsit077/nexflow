Game Runner · 全部项目（library）
==============================

目录约定（类似 mod 管理器）：

  library/                 ← 全部项目
    <分项目 id>/
      app/                 ← 项目本体（助手程序本体）
      scripts/             ← 项目脚本（说明、bat、自写补充）
      meta.json            ← 安装记录

请勿把「项目本体」直接塞在分项目根下；安装器会解压到 app\。
国内 GitHub 慢时可设环境变量 GAME_RUNNER_GH_PROXY（如 https://ghproxy.net）。
