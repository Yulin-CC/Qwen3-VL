---
name: standard-rules
description: >-
  Authors a new grounding rules scene after a fill-in questionnaire. Writes
  describe_rules_<slug>.md, caption_rules_<slug>.md, describe_<slug>.py, and
  scenes.json in this package. Use when the user says 新规则, 加场景,
  改 describe 规则, 写 caption_rules, or wants a new rules_scene dropdown item.
---

# 🏷️ Standard-Rules（新场景规则 + describe 策略）

  - **概述**: 用户要「加场景 / 新规则 / 改 describe·caption 规则」时触发。先用填空题确认需求，**用户确认后再写文件**；参考现有 `rules/`，生成成对 md、对应的 `describe_<slug>.py`，并登记 `scenes.json`。
  - **日期**: 2026-08-21

---

## 0 执行前检查

  - **触发场景**：新规则、加场景、改短语规则、写 caption_rules、扩展 default/appearance。
  - **本 Skill 位置**：`grounding/.skill/standard-rules/`（包内专用；尚未迁入通用技能库）。
  - **规则根目录**：本包 `rules/`（`.skill/` 上一级下的 `rules/`）。
  - **引擎**：本包 `util/describe.py`（调度）+ `describe_default.py` / `describe_appearance.py` / `describe_<slug>.py`
  - **禁止**：改 `auto/`、`yoloe/`；为新场景去改调度 `describe.py`；未确认就写文件。
  - **进度台账**：本 Skill 为短确认 + 一次落盘，**不需要** `todo.md`。
  - **参考模板（落盘前必读）**：
    - 通用：`describe_rules.md` + `caption_rules.md`
    - 外观：`describe_rules_appearance.md` + `caption_rules_appearance.md`
    - 引擎：`util/describe_default.py`、`util/describe_appearance.py`
    - 策略：`scenes.json`
    - 章节骨架：可对照 `standard-gddata_rules`（若本机技能库有）

---

## 1 向用户确认（填空题，未确认不得写文件）

  把下面整块贴给用户。能从对话推断的项先填进括号当默认；未知留空。等用户回复「按此生成」或逐项改定后再进入 [2]。

    ```markdown
    请填空后回复「按此生成」（改括号即可）：

    1. 场景 id（slug，小写英文+下划线）：[________]  （例：appearance / vesthalmet）
    2. 下拉显示名：[________]
    3. 从哪套复制骨架：[default 通用 | appearance 只写外观]
    4. 每目标最多几条短语：[8 | 3 | ________]
    5. 允许的属性轴：
       - 外观（颜色/服装/涂装）：[是 | 否]
       - 子类/角色（sedan / student）：[是 | 否]
       - 动作/状态（walking / parked）：[是 | 否]
       - 方位（on the road / left）：[是 | 否]
    6. 车辆禁止子类词（sedan/SUV/taxi 等改写成中心词）：[是 | 否]
    7. 图内同类穷尽补查（exhaustive）：[是 | 否]
    8. caption 必须覆盖全部目标及其短语（caption_cover_all）：[是 | 否]
    9. 场景焦点（一句话，写进 describe 概述 + §1.2）：[________]
    10. 关键类别与推荐英文用词：[________]
    11. 看不清时：[不猜 | 中性描述 ________]
    12. caption 口吻补一句（可空）：[________]
    ```

  **(1)** slug 不能是 `default` / `base` / `general`（那是通用，改 `describe_rules.md` 本身）。
  **(2)** slug 已存在 → 先列出旧 `scenes.json` 行与 md 路径，问是覆盖还是换 id。
  **(3)** 第 3 项决定复制哪一对 md **和** 哪份 `describe_*.py`；第 5–8 项写入 `scenes.json`。**不要改**调度文件 `describe.py`。
  **(4)** 第 6 项=是 → `ban_vehicle_subtypes=true`（走外观清洗）。第 7=是 → `exhaustive=true`。第 8=是 → `caption_cover_all=true`。

  确认后在回复里复述一表（id / max_phrases / 四轴 / 三开关），再写盘。

---

## 2 落盘顺序

  全部写入本包（`.skill/` 上一级），不要动 `auto/`、`yoloe/`。

### 2.1 复制并改 md

  **(1)** 按填空第 3 项复制：

    ```text
    rules/describe_rules.md              → rules/describe_rules_<slug>.md
    rules/caption_rules.md               → rules/caption_rules_<slug>.md
    # 或 appearance 那一对 *_appearance.md
    ```

  **(2)** describe 必改：标题与概述（含第 9 项焦点、日期当天）；**§1.2 专用要求**写成紧致表（场景焦点、关键属性、用词、条数、禁止轴）；§2 类型表只保留第 5 项允许的轴；§4 JSON schema **不改**。

  **(3)** caption 必改：概述可加第 12 项一句；**§1 核心原则不要删行**（短语锁定必须保留）；§3 示例换成该场景短语（至少 1 个单句 + 1 个多句）；§4 JSON schema **不改**。

  **(4)** 表格用紧致写法 `|列|列|`，单元格两侧不加空格。

  描述规则 §1.2 表示例：

    ```markdown
    ### 1.2 专用要求

    |要求|说明|
    |---|---|
    |场景焦点|……|
    |条数上限|每个目标最多 N 条；不足不注水|
    |允许轴|……|
    |禁止轴|……|
    |用词偏好|……|
    |不确定|不猜 / ……|
    ```

### 2.2 登记 `scenes.json`

  在 `scenes` 数组追加一行（`id` 为 slug；通用那行 `id=""` 不要动）：

    ```json
    {
      "id": "<slug>",
      "label": "<下拉显示名>",
      "max_phrases": 3,
      "ban_vehicle_subtypes": true,
      "exhaustive": true,
      "caption_cover_all": true
    }
    ```

  字段与填空对应：`max_phrases`←4；`ban_vehicle_subtypes`←6；`exhaustive`←7；`caption_cover_all`←8。

  - **注意**：下拉靠扫描 `describe_rules_<slug>.md`；json 负责 **label + 机器策略**。缺 json 行则策略回退通用（最多 8 条、无穷尽），下拉会是假切换。

### 2.3 复制 `describe_<slug>.py`（与 md 一一对应）

  只换 md **不够**。调度 `util/describe.py` 按 scene 加载 `describe_<slug>.py`（通用是 `describe_default.py`）。新增场景：**复制引擎文件，不要改调度。**

    ```text
    util/describe_default.py      → util/describe_<slug>.py   # 骨架选 default 时
    util/describe_appearance.py   → util/describe_<slug>.py   # 骨架选 appearance 时
    ```

  **(1)** 文件头 `RULES_FILE` 改成 `describe_rules_<slug>.md`；改 `SYSTEM_PROMPT` / 清洗 / `check_phrases_apply` 以贴合填空第 5–7 项。

  **(2)** 必须导出 `describe_object(client, crop_abs, label, rules=..., ...)`，签名与 `describe_default.py` 一致。

  **(3)** 第 7 项=是：保留或实现 `check_phrases_apply`（appearance 已有）。第 7 项=否：可删该函数。

  **(4)** 缺 `describe_<slug>.py` 时调度会回退 `describe_default.py` 并打警告，等于假切换。

  **(5)** **禁止**改 `util/describe.py`。新建脚本才加文件头（`standard-create_script`）。

  - **注意**：`caption.py` 的覆盖补句读 `caption_cover_all`，一般只改 md 示例。

### 2.4 自检

  - [ ] `describe_rules_<slug>.md` 与 `caption_rules_<slug>.md` 成对
  - [ ] `util/describe_<slug>.py` 存在，且导出 `describe_object`
  - [ ] `scenes.json` 有该 id，四字段与填空一致
  - [ ] **未改** `util/describe.py`
  - [ ] 未改输出 JSON：`{"phrases":[...]}` / `{"caption":"..."}`
  - [ ] 未改 `auto/`、`yoloe/`

  用 `--no_llm` 或用户同意时 `--limit 1` 冒烟（调用 `agent-auto_generate` 的试跑约定）。

---

## 3 工具索引

  - 工具根目录：本包（`.skill/` 上一级）

  | 分类 | 工具路径 | 用途 |
  | --- | --- | --- |
  | 模板 | `rules/describe_rules.md` | default 通用 describe |
  | 模板 | `rules/caption_rules.md` | default caption（短语锁定） |
  | 模板 | `rules/describe_rules_appearance.md` | appearance describe |
  | 模板 | `rules/caption_rules_appearance.md` | appearance caption |
  | 策略 | `rules/scenes.json` | id/label/max_phrases/三开关 |
  | 扫描 | `util/rules_io.py` | 下拉 + `get_scene_policy()` |
  | 引擎 | `util/describe.py` | 调度：按 scene 加载 describe_<slug>.py |
  | 引擎 | `util/describe_default.py` | ↔ `describe_rules.md` |
  | 引擎 | `util/describe_appearance.py` | ↔ `describe_rules_appearance.md` |
  | 引擎 | `util/caption.py` | `caption_cover_all` 时覆盖补句 |
  | 试跑 | `util/generate.py` | `--rules-scene <slug> --limit 1` |

  - **注意**：Agent 必须先 Read 将要复制的那一对 md，再改写，避免凭记忆漏章节。

---

## 4 交付

  **(1)** 列出新文件：`describe_rules_<slug>.md`、`caption_rules_<slug>.md`、`describe_<slug>.py`、`scenes.json` 新增行。明确写：**未改** `describe.py`。
  **(2)** 告诉用户：审阅台刷新后下拉会出现该项；**换下拉不会自动重跑**，需再点生成或 CLI `--rules-scene <slug>`。
  **(3)** 给一条试跑命令：

    ```bash
    python util/generate.py --dataset "<data_root>" --rules-scene "<slug>" --limit 1
    ```
