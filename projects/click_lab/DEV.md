# 识图点按开发指南（MaaFramework）

目标：截取画面 → 识别按钮 → 模拟点击。  
本项目用**官方 MaaFW**，写法与 BD2 同族（`recognition.type` + `action.type`）。

## 0. 一次准备

```bat
cd /d "E:\AAAmobile game\game-runner"
tools\setup_maafw.bat
tools\setup_ocr.bat
```

- `setup_maafw.bat`：安装 `MaaPiCli.exe`
- `setup_ocr.bat`：把 OCR 模型拷到 `projects\click_lab\resource\model\ocr\`

推荐工具（任选）：

| 工具 | 用途 |
|---|---|
| Game Runner **脚本编辑 → ② 录制/连控** | 连游戏后点画面：默认裁模板（稳）/ 坐标（备选）；OR 候选；导出 pipeline 草稿 |
| [MXU](https://github.com/MistEO/MXU) / BD2 的 `mxu.exe` | 连窗口、截图、跑任务、看识别框 |
| [MaaPipelineEditor](https://mpe.codax.site/stable/) | 可视化编 pipeline / 精修 if-else |
| VS Code 插件 `nekosu.maa-support` | 截图裁切 + 跳转任务 |

## 1. 基本公式

每个节点 = **识别** +（可选）**动作** + **下一步**

```json
"节点名": {
  "recognition": {
    "type": "OCR",
    "param": {
      "expected": "确认",
      "threshold": 0.5,
      "roi": [左, 上, 宽, 高]
    }
  },
  "action": { "type": "Click" },
  "post_delay": 500,
  "next": ["下一个节点"]
}
```

常见识别：

- `TemplateMatch`：比对 `resource/image/` 里的小图（按钮图标）
- `OCR`：认屏幕上的文字（中文需 OCR 模型）

常见动作：

- `Click`：点识别结果中心（也可 `param.target: [x,y]` 固定坐标）
- `DoNothing` / `Swipe` / `Key` 等见官方 Pipeline 文档

`roi: [0,0,0,0]` 表示全屏；生产环境请缩小 ROI，又快又稳。

分辨率约定：素材按 **短边 720** 缩放后的画面裁切（和 BD2 / 官方一致）。

## 2. 练手 A：OCR 点「确认」

1. 打开记事本，输入两个字：`确认`
2. 在 MXU / MaaPiCli 里选控制器 **记事本练习**，任务 **OCR点确认**
3. 运行；应点击「确认」文字中心

改字：编辑 `resource/pipeline/01_ocr_click.json` 里的 `expected`。

## 3. 练手 B：模板匹配点按钮

1. 用 MXU / VS Code 插件截游戏（或任意）窗口  
2. 裁出按钮小图，无损 PNG，放到：

   `projects/click_lab/resource/image/my_button.png`

3. 跑任务 **模板点按钮**
4. 若不稳：降低 `threshold`（如 0.65），或收紧 `roi`

## 4. 流程链

`03_flow.json` 演示：

- `next`: 候选列表，谁先识别到就走谁  
- `[JumpBack]Xxx`: 临时去 Xxx，再跳回当前节点继续找  

适合「弹窗 / 加载 / 回主界面」等分支。

## 5. 换成真实游戏

1. 复制本目录为 `projects/我的游戏/`
2. 改 `interface.json` 里 `window_regex`（窗口标题正则）或改用 ADB
3. 清空示例 pipeline，按画面写任务
4. 在 Game Runner「脚本 / 导入」里导入该目录（type=maafw）

## 6. 无人值守

交互跑通一次（生成 `config/maa_pi_config.json`）后：

```bat
cd projects\click_lab
..\..\maafw\MaaPiCli.exe -d
```

或在调度器里登记 `type=maafw`，`args: ["-d"]`。

## 参考

- Pipeline：https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.1-PipelineProtocol.md  
- PI：https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.3-ProjectInterfaceV2协议.md  
- 可对照本地 BD2：`E:\AAAmobile game\BD2MAA\resource\pipeline\StartGame.json`
