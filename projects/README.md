# MaaFW 项目目录

每个子目录是一个官方 **ProjectInterface v2** 包。

## 从零写「截图点按钮」

从这里开始：

1. `tools\setup_maafw.bat`
2. `tools\setup_ocr.bat`
3. 打开 [`click_lab/DEV.md`](click_lab/DEV.md)
4. `tools\open_click_lab.bat`（或用 MXU 打开 `click_lab`）

| 项目 | 说明 |
|---|---|
| `click_lab/` | **识图点按实验**：OCR / 模板匹配 / 流程链 |
| `demo_click/` | 最早的最小样例（可忽略） |

## 目录约定

```text
my_game/
├── interface.json
├── resource/
│   ├── image/           # 按钮截图 PNG
│   ├── model/ocr/       # det.onnx rec.onnx keys.txt
│   └── pipeline/*.json  # 识别+点击节点
└── config/maa_pi_config.json   # MaaPiCli 交互配置后生成
```

## 一句话公式

**识别（TemplateMatch / OCR）→ Click → next**

与 BD2 的 `resource/pipeline/*.json` 同一种写法。
