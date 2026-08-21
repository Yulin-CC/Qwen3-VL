# 🏷️ Grounding 标注工具 [v0.6.9]

裁目标 → vLLM 描述 → 组合 caption → Web 审阅 → 导出 `jsons-GD`。

标注员操作见 [`z-others/标注规则.md`](./z-others/标注规则.md)。

![](./z-others/pic/image_-sHthNRu2H.png)

---

## 1 项目结构

```
grounding/
├── 1-start_review.bat      # Windows 启动审阅（默认 8090）
├── model/server.json       # 多模态服务列表
├── rules/                  # describe / caption 规则 + scenes.json
├── util/                   # 审阅后端、生成、裁剪、描述、导出
└── z-others/
    ├── 0-generate.sh       # Linux 批量生成
    ├── 1-start_review.sh   # Linux 启动审阅（默认 8082）
    └── 标注规则.md          # 标注员规范
```

---

## 2 环境搭建

- **Python 3** + `flask` / `pillow` / `tqdm` / `requests`
- **vLLM** 多模态服务（OpenAI 兼容 `/v1`）；顶栏可切换，配置在 `model/server.json`
- Windows 默认 conda `yulin`（须 `PYTHONUTF8=1`）；Linux 默认 `qwen`

---

## 3 数据集约定

选择向导：**图像目录** → **标签目录**，按同名 stem 配对。CLI 未指定 `--jsons` 时自动：`jsons-segm` → `jsons-detect` → `jsons`。

```
YOUR_DATA_DIR/
├── images/          # 或 JPEGImages / 根目录直接放图
├── jsons-segm/      # 优先：多边形
├── jsons-detect/    # 检测框（jsons-det 为别名）
├── jsons/           # LabelMe
├── draft/           # 运行时中间结果
└── jsons-GD/        # 导出产物
```

续跑默认缺啥补啥。打开 auto 已跑的 `draft/` 可直接审。

---

## 4 使用方式

### 4.1 启动审阅

```bat
1-start_review.bat
1-start_review.bat --port 8090 --dataset D:\data\your_dataset
```

```bash
bash z-others/1-start_review.sh --port 8082 --dataset /path/to/dataset
```

关控制台 / `Ctrl+C` 释放本实例端口。可多开，端口占用自动 +1。

### 4.2 审阅

1. 顶栏选服务、选规则 →「选择图像数据集」（先图像、再标签）
2. 需要时「描述生成」：优先**续跑补齐**；换规则下拉**不自动重跑**
3. 右侧三个页签：**目标描述**（填空）/ **标签概览**（点目标出对话框）/ **文件概览**
4. 导出 `jsons-GD`（当前文件或整个文件夹）

快捷键与标签概览操作见 [`z-others/标注规则.md`](./z-others/标注规则.md)。

### 4.3 命令行批量生成

```bash
bash z-others/0-generate.sh
bash z-others/0-generate.sh --rules-scene appearance --limit 1
bash z-others/0-generate.sh --export
```

- `--rules-scene`：空 / `default` = 通用；`appearance` = 只写外观
- `--stages`：`all` / `check` / `crop` / `describe` / `caption` / `export`
- `--force` 覆盖已有结果；`--no_llm` 仅调试

---

## 5 规则

规则 md 与 `describe_<slug>.py` **一一对应**；策略登记在 `rules/scenes.json`。

| 规则 | 用途 |
|------|------|
| `describe_rules.md` | 通用：最多 8 条，允许子类/动作/方位 |
| `describe_rules_appearance.md` | 外观：1–3 条，禁子类，穷尽检查 |
| `caption_rules.md` | 短语锁定组句 |

界面「刷新」只改句式，**不改**已选短语。

---

## 6 常见问题

- **离线**：`draft/` 已完整可直接审阅
- **正式数据不要 `--no_llm`**；覆盖用 `--force` 或界面「重新生成」
- **失败占位续跑**：不要 `--force`，会自动重试
- **迭代细节**：`z-others/开发日志.md`
