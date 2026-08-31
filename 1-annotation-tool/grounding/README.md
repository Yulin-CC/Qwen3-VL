# 🏷️ Grounding 标注工具 [v0.6.12]

裁目标 → vLLM 描述 → 组合 caption → Web 审阅 → 导出 `jsons-GD`。

继承自 **yoloe v0.5.6** 审阅台 + **auto** 批量生成；独立包 `grounding/`，**不改** `auto/`、`yoloe/`。

![](./z-others/pic/image_-sHthNRu2H.png)

标注员操作（流程 / Tips / 快捷键）见 [`z-others/标注规则.md`](./z-others/标注规则.md)。

---

## 1 项目结构

```
grounding/
├── 1-start_review.bat      # Windows 启动审阅（默认 8090）
├── model/server.json       # 多模态服务列表
├── rules/                  # describe / caption 规则 + scenes.json
├── util/
│   ├── app.py              # Flask 审阅后端 + Web UI
│   ├── generate.py         # 批量生成（check→crop→describe→caption）
│   ├── crop_objects.py     # 目标裁剪
│   ├── describe.py         # 调度：按 scene 加载 describe_<slug>.py
│   ├── describe_default.py # ↔ rules/describe_rules.md
│   ├── describe_appearance.py  # ↔ rules/describe_rules_appearance.md
│   ├── describe_common.py  # 短语去重等共用
│   ├── caption.py          # caption 组合 / 刷新 / 覆盖补句
│   ├── export_gd.py        # 导出 jsons-GD
│   └── validate_dataset.py # 数据集校验
├── .skill/                 # 包内专用 Skill（尚未迁入通用库）
│   ├── agent-auto_generate/
│   ├── agent-cluster_labels/
│   └── standard-rules/
└── z-others/
    ├── 0-generate.sh       # Linux 批量生成
    ├── 1-start_review.sh   # Linux 启动审阅（默认 8082）
    ├── 标注规则.md          # 标注员规范（含配图）
    └── 开发日志.md          # 迭代记录
```

---

## 2 环境搭建

- **Python 3** + `flask` / `pillow` / `tqdm` / `requests`（启动脚本缺依赖时会尝试自动安装）
- **vLLM** 多模态服务（OpenAI 兼容 `/v1`）
- Windows 选文件夹需要 **tkinter**
- Windows 默认 conda `yulin`（须 `PYTHONUTF8=1`）；Linux 默认 `qwen`

编辑 `model/server.json`：

```json
{
  "services": [
    {
      "id": "0",
      "name": "Qwen3.6-35B",
      "base_url": "http://HOST:8081/v1",
      "port": 8081,
      "model": "qwen3.6-35b-a3b",
      "default": true
    }
  ]
}
```

界面顶栏可切换服务（绿/红点），与规则下拉分开。也可用 `VLLM_BASE_URL` / `VLLM_MODEL`。空 `--base_url` / `--model` 时 CLI 读清单里 `default: true`。

**便携包：** 本轮（v0.6.12）不搬；审阅仍用 `1-start_review.bat`。yoloe 最后一版为 `GroundingReview-portable-v0.5.6.zip`。

---

## 3 数据集约定

选择向导：**图像目录** → **标签目录**。按 **同名 stem** 配对。CLI 未指定 `--jsons` 时自动：`jsons-segm` → `jsons-detect` → `jsons`。

```
YOUR_DATA_DIR/
├── images/          # 或 JPEGImages / 根目录直接放图
├── jsons-segm/      # 优先：多边形（jsons-sem 为别名）
├── jsons-detect/    # 可选：检测框（jsons-det 为别名）
├── jsons/           # 可选：LabelMe .json（rectangle / polygon / mixed）
├── annotations/     # 可选：VOC .xml
├── draft/           # 运行时：objects / descriptions / captions / config.json
└── jsons-GD/        # 仅 --export
```

续跑默认「缺啥补啥」，不覆盖已有非占位结果。`draft/config.json` 记下 `rules_scene`。格式校验缓存在 `draft/validate_log.json`。打开 auto 已跑的 `draft/` 可直接审。

---

## 4 使用方式

### 4.1 启动审阅

```bat
1-start_review.bat
1-start_review.bat --port 8090
1-start_review.bat --dataset D:\data\your_dataset
```

```bash
bash z-others/1-start_review.sh --port 8082 --dataset /path/to/dataset
python util/app.py --port 8082
```

关控制台 / `Ctrl+C` 释放本实例端口（关网页不退出）。可多开：端口占用自动 +1。

### 4.2 审阅

1. 顶栏选服务、选规则场景（通用 / appearance / 其它 slug）→「选择图像数据集」（先图像、再标签）
2. 需要时「描述生成」：**续跑补齐**只补缺失；**重新生成**强制重跑 describe + caption。换下拉**不自动重跑**
3. 右侧「标签概览」按类别成卡；点图中目标弹出漫画对话框。**F** 改单目标：**+** 后点芯片新增；点框内描述再点芯片替换；垃圾桶删除（回候选池，无确认）。**V** 批量改目标：点右侧一条描述后点亮/点灭，再按 **V**（或 Esc / 切图）退出即保存。点灭后空槽用源标签。类别卡「整理」只排该类芯片
4. 审阅后导出 `jsons-GD`（当前文件或整个文件夹）

顶栏快捷键：`W/S 切 caption · T 前图匹配 · R 框显隐 · F 改单目标 · V 批量改目标`。`A`/`D` 仍切图；匹配中 **F** 确认配对。细则与配图见 [`z-others/标注规则.md`](./z-others/标注规则.md)。

### 4.3 命令行批量生成

```bash
# 改 z-others/0-generate.sh 内 dataset / rules_scene 后：
bash z-others/0-generate.sh
bash z-others/0-generate.sh --rules-scene appearance --limit 1
bash z-others/0-generate.sh --export
```

```bash
python util/generate.py --dataset /path/to/dataset \
  --rules-scene appearance --limit 1 --workers 4 --timeout 600
python util/generate.py --dataset /path/to/dataset \
  --base_url http://HOST:8081/v1 --model qwen3.8-27b
```

- `--rules-scene`：空 / `default` = 通用；`appearance` = 只写外观；与审阅台下拉同一套
- `--stages`：`all` / `check` / `crop` / `describe` / `caption` / `export`
- `--jsons` / `--images`：空则自动探测
- `--timeout`：vLLM HTTP 超时秒数（默认 600）
- `--force`：覆盖已有结果；`--no_llm` 仅调试（正式数据不要用）

---

## 5 规则与导出

规则 md 与 describe 引擎 **一一对应**；新增场景不必改调度 `describe.py`。

| 规则 | 引擎 | 用途 |
|------|------|------|
| `rules/describe_rules.md` | `util/describe_default.py` | 通用：最多 8 条，允许子类/动作/方位 |
| `rules/describe_rules_appearance.md` | `util/describe_appearance.py` | 外观：1–3 条，禁 sedan，穷尽 |
| `rules/describe_rules_<slug>.md` | `util/describe_<slug>.py` | 新场景：复制上列之一再改 |
| `rules/caption_rules.md` / `caption_rules_<slug>.md` | `util/caption.py` | 短语锁定组句；appearance 另开覆盖补句 |
| `rules/scenes.json` | `util/rules_io.py` | 下拉 label + `max_phrases` / 禁子类 / exhaustive / coverage |
| `z-others/标注规则.md` | — | 标注员流程 |

人改策略：改对应 md（给模型看）+ 改 `scenes.json` 一行（给程序执行）+ 复制一份 `describe_<slug>.py`。缺 py 会回退 default。

界面「刷新」按**当前**规则重组句式 / 生成候选，**不改**已选短语。切规则后点目标「刷新」会按新场景补候选。导出：UI 弹窗，或 `python util/export_gd.py --dataset /path/to/dataset`。

包内 Skill（`.skill/`）：`agent-auto_generate` 确认后批量生成；`standard-rules` 填空后加新场景；`agent-cluster_labels` 标签概览芯片整理（及后续扩展）。

---

## 6 常见问题

- **离线 / vLLM 不可用**：`draft/` 已完整可直接审阅；仅缺 describe/caption 时才探测服务
- **`--no_llm` 占位**：正式重跑不要加该参数；覆盖用 `--force` 或界面「重新生成」
- **失败占位续跑**：不要 `--force`，`source=failed` / timeout 会自动重试
- **大数据集启动慢**：签名未变会复用 `draft/validate_log.json`
- **多开窗口**：再双击 bat，端口自动递增
- **改远程地址**：`1-start_review.bat` 顶部或 `model/server.json`
- **迭代细节**：`z-others/开发日志.md`
