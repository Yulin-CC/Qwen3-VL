---
name: agent-auto_generate
description: >-
  Batch-generates grounding object phrases and captions via this package
  (grounding/.skill). Confirms dataset path, vLLM service, and rules_scene,
  then runs util/generate.py. Use when the user says 批量生成, 跑 generate,
  auto caption, 目标描述, 续跑 draft, or to pick default/appearance rules.
---

# 🚀 Agent-Auto Generate（批量描述 + Caption）

  - **概述**: 用户要「批量生成描述 / caption」「跑 generate」「续跑 draft」时触发。先确认数据集、模型服务、规则场景，再调用 `grounding` 生成；产物只进 `draft/`。
  - **日期**: 2026-08-21

---

## 0 执行前检查

  - **触发场景**：批量生成、跑 generate、auto caption、目标描述、续跑、缺啥补啥。
  - **本 Skill 位置**：`grounding/.skill/agent-auto_generate/`（包内专用；尚未迁入通用技能库）。
  - **工具根目录 `GROUNDING_ROOT`**：本包根目录（`.skill/` 的上一级）。仓库内完整路径为 `1-annotation-tool/grounding/`。
  - **数据根目录 `data_root`**：必须由用户给出或填空确认，**禁止猜测路径**。
  - **进度台账**：`<data_root>/draft/todo-generate.md`（⭐ 强制维护，见 [1]）。
  - **环境**：Windows 默认 conda `yulin`（控制台须 `PYTHONUTF8=1`）；Linux 默认 `qwen`。禁止写死 `/home/<user>/miniconda3`。
  - **范围边界**：只写 `draft/`（及用户明确要求时的 `jsons-GD/`）；**不写回**正式 `labels/`。
  - **旧包**：不要改、不要调用 `auto/` 或 `yoloe/` 的 `generate.py`。审阅 UI 用本包 `util/app.py`。

---

## 1 进度台账（todo-generate.md）

  - **路径**：`<data_root>/draft/todo-generate.md`
  - **目的**：对抗上下文截断；续跑以文件 + 磁盘为准。

### 1.1 何时读写

  **(1)** 开跑 / 续跑前先 Read；禁止无故重做已 `done`。
  **(2)** 每完成一个可恢复节点（confirm / check / crop / describe / caption / export）立即更新。
  **(3)** 用户说「继续 / check 进度」：读台账 → 摘要 → 执行 `next`。
  **(4)** 文件不存在：按 [1.2] 新建后再开跑。

### 1.2 模板（可增行，勿删节字段）

  状态：`pending` / `in_progress` / `done` / `blocked` / `skipped`。

    ```markdown
    # Agent-auto_generate TODO

    - **updated**: YYYY-MM-DD HH:MM
    - **data_root**: /path/to/data
    - **work_dir**: grounding 包根（`.skill/` 上一级）
    - **service**: name / base_url / model
    - **rules_scene**: default | appearance | <slug>
    - **conda**: yulin | qwen
    - **phase**: confirm | probe | check | crop | describe | caption | export | deliver
    - **current**: ...
    - **next**: ...
    - **blocked**: 无

    ## Meta
    - n_paired / n_objects: ...
    - stages: check,crop,describe,caption
    - limit: 无 | N
    - force: false
    - workers: 4
    - timeout: 600

    ## Checklist
    - [ ] §2 填空确认
    - [ ] §3 探测服务
    - [ ] §4 check
    - [ ] §5 试跑 --limit 1
    - [ ] §6 全量 / 续跑
    - [ ] §8 交付

    ## Notes
    - ...
    ```

  - **注意**：对话与文件冲突时，以 **台账 + 磁盘产物** 为准。

---

## 2 向用户确认（填空题，未确认不得开跑）

  把下面整块贴给用户，保留编号；用户改括号或直接回复即可。已从 `draft/config.json` / 台账读到的值填进括号当默认。

    ```markdown
    请确认后回复「按此开跑」（改括号即可）：

    1. 数据集目录：[必须是绝对路径；含 images/ + jsons-segm|jsons-detect|jsons]
    2. 规则场景：[default 通用 | appearance 只写外观 | 其它 slug ________]
    3. 模型服务：[用 server.json 的 default | 指定 base_url=________ model=________]
    4. 规模：[先 --limit 1 打通，再全量 | 直接全量]
    5. 续跑：[不 --force（默认，跳过已有非占位） | 强制重跑 --force]
    6. workers：[4]
    7. timeout 秒：[600]
    8. 导出 jsons-GD：[否 | 是 --export]
    ```

  **(1)** 路径未给 → 只问第 1 项，不要猜。
  **(2)** 用户一条消息已写全 1–5 → 复述填空结果，等一句确认再跑（用户已说「直接跑 / 开跑」可跳过二次确认）。
  **(3)** `rules_scene`：`default` / 空 / `general` 都当成通用（CLI `--rules-scene` 留空）。其它 slug 须在 `rules/describe_rules_<slug>.md` 存在，否则停止并建议走 `standard-rules`。
  **(4)** 确认后写入台账 Meta，`phase=probe`，勾选 Checklist「§2」。

  - **注意**：换 scene **不自动重跑**已有 draft；要覆盖必须第 5 项选 `--force`。

---

## 3 探测模型服务

  **(1)** 读 `GROUNDING_ROOT/model/server.json`。先试 `default: true`，没有则试列表第一条。

  **(2)** `GET {base_url}/models`，期望 200，且 `data[].id` 含将使用的 `model`。

  **(3)** 不通则改试清单其它条目，向用户报告哪条可达。全部失败 → `blocked=服务不可用`，停止。

  **(4)** 用户在填空里指定了 `base_url` / `model` → 以用户为准，仍须探测通过。

  **(5)** 选用的 `name` / `base_url` / `model` 写入台账 `service`。

  调用方式：

    ```bash
    # 期望 200，body 含 model id
    # GET {base_url}/models
    ```

  - **注意**：清单里可能一条内网通、一条公网拒。只用探测通过的那条，不要假设同端口能切模型。

---

## 4 数据集 check

  在 `GROUNDING_ROOT` 下执行（空 `--jsons` 时自动：`jsons-segm` → `jsons-detect` → `jsons`）：

    ```bash
    python util/generate.py --dataset "<data_root>" --stages check --rules-scene "<scene或空>"
    ```

  **(1)** 无配对 / 无 `images/` → 停止，把错误原文给用户。
  **(2)** 将 `n_paired`、标签目录、geometry 写入台账 Meta。
  **(3)** `phase=check` 完成后勾选 Checklist「§4」，`next` 写试跑命令。

---

## 5 先小后全

  填空第 4 项为「先 limit 1」或用户未指定规模时：

    ```bash
    # Windows：PYTHONUTF8=1
    python util/generate.py \
      --dataset "<data_root>" \
      --rules-scene "<appearance 或留空>" \
      --limit 1 \
      --workers 4 \
      --timeout 600 \
      --base_url "<url>" \
      --model "<id>"
    ```

  **(1)** 抽 1 张图的 `draft/descriptions/*_obj*.json` 给用户看短语形态（default 可含子类/动作；appearance 应无 sedan、条数 ≤ 3）。
  **(2)** 形态不对 → 停，问是否换 scene 或走 `standard-rules`，不要直接全量。
  **(3)** 用户点头后再全量。全量不要加 `--limit`；不要加 `--force` 除非填空第 5 项明确要求。

---

## 6 全量 / 续跑

    ```bash
    python util/generate.py \
      --dataset "<data_root>" \
      --rules-scene "<scene或空>" \
      --workers 4 \
      --timeout 600 \
      --base_url "<url>" \
      --model "<id>"
    ```

  **(1)** 长任务后台跑，阶段结束再汇报；不要空转轮询。
  **(2)** 失败占位（`source=failed` / timeout）续跑时**不要** `--force`，`is_placeholder_desc` 会重试。
  **(3)** 每完成 crop / describe / caption 更新台账 phase 与 Checklist。
  **(4)** 仅当填空第 8 项为「是」时加 `--export`。

  - **注意**：`--no_llm` 只许调试，禁止用于正式数据。

---

## 7 工具索引

  - 工具根目录：`GROUNDING_ROOT`（本包，`.skill/` 上一级）

  | 分类 | 工具路径 | 用途 |
  | --- | --- | --- |
  | 生成 | `util/generate.py` | check → crop → describe(+policy) → caption → 可选 export |
  | 入口 | `z-others/0-generate.sh` | Linux 改 `dataset` / `rules_scene` 后 bash |
  | 服务 | `model/server.json` | 服务列表；`default: true` |
  | 规则 | `rules/scenes.json` | scene 策略：条数 / 禁子类 / exhaustive / coverage |
  | 规则 | `rules/describe_rules.md` | default 通用短语 |
  | 规则 | `rules/describe_rules_appearance.md` | appearance 只写外观 |
  | 审阅 | `util/app.py` | Web 审阅；下拉切 scene；不替代 CLI |
  | 台账 | `<data_root>/draft/todo-generate.md` | 断点续跑；强制读写 |

  调用方式：

    ```bash
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate yulin   # Linux 用 qwen
    export PYTHONUTF8=1
    cd "$GROUNDING_ROOT"
    python util/generate.py --dataset "<data_root>" --rules-scene appearance --limit 1
    ```

  - **注意**：空 `--base_url` / `--model` 时读 `server.json` 的 default。先确认 `/v1/models` 可达再开全量。
  - **注意**：Windows 优先用已定位的 env `python.exe`，不要用系统 Python。

---

## 8 交付

  **(1)** 摘要：`data_root`、`rules_scene`、服务、`n_paired` / 目标数、各 stage、`draft/` 路径。
  **(2)** 声明：**未**写入正式 `labels/`；`jsons-GD/` 仅在 `--export` 时出现。
  **(3)** 提醒审阅：`python util/app.py`（或 `1-start_review.bat`）打开同一 `data_root`。
  **(4)** 台账：Checklist 勾选，`phase=deliver`，`next=等待人工审阅或换 scene 后按需重跑`。
