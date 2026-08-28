---
name: standard-rules
description: >-
  Authors and extends grounding describe/caption rules in this package.
  Writes describe_rules_<slug>.md, caption_rules_<slug>.md, describe_<slug>.py,
  and scenes.json. Use when the user says 新规则, 加场景, 改 describe 规则,
  写 caption_rules, or wants a new rules_scene dropdown item.
---

# 🏷️ Standard-Rules（describe / caption 规则 + 新场景）

  - **概述**: 写/改短语与 caption 规则，或加一套新场景。规则在本包 `rules/`；新场景先填空、**确认后再写文件**。
  - **日期**: 2026-08-28

---

## 1 范围与路径

  - **做**：英文 describe 短语、caption 组句、新建/改场景规则。
  - **不做**：中文短语正文；caption 阶段改短语语义（只改句式）；改 `auto/`、`yoloe/`；改调度 `util/describe.py`。
  - **规则根**：本包 `rules/`（`.skill/` 上一级下的 `rules/`）。
  - **引擎**：`util/describe.py` 按 scene 加载 `describe_default.py` / `describe_appearance.py` / `describe_<slug>.py`。

|层|文件|作用|
|---|---|---|
|通用 describe|`describe_rules.md`|基线短语|
|通用 caption|`caption_rules.md`|基线组句（短语锁定）|
|场景 describe|`describe_rules_<slug>.md`|专用要求 + 类型表|
|场景 caption|`caption_rules_<slug>.md`|场景口吻 + 示例|
|策略|`scenes.json`|下拉 label + max_phrases / 三开关|
|引擎|`util/describe_<slug>.py`|与 md 一一对应；通用是 `describe_default.py`|

  - **注意**：表格用紧致写法 `|列|列|`。新场景 describe + caption **成对**新增。执行某场景以该文件为准，未覆盖条款回退通用。

---

## 2 写法要点

### 2.1 Describe

|要求|说明|
|---|---|
|目标描述|单个裁剪目标的短英文名词短语（2–8 词，不要整句）|
|类别|源标签为真值，描述须贴该类|
|视觉依据|只写看得见的；看不清的字/logo 不编|
|禁止|不提裁剪框、绿框、标注痕迹|

|类型|说明|示例|
|---|---|---|
|属性|子类/角色等|person → student；car → taxi|
|外观|颜色、服装、涂装|person in white jacket|
|动作/状态|可见姿态|person walking；car parked|

```json
{"phrases": ["...", "..."]}
```

  场景文件主要改：概述、**§1.2 专用要求**（必填紧致表）、§2 类型表、§3 口吻。**§4 JSON schema 不改**。

```markdown
### 1.2 专用要求

|要求|说明|
|---|---|
|场景焦点|……|
|条数上限|每目标最多 N 条；不足不注水|
|允许轴|……|
|禁止轴|……|
|用词偏好|……|
|不确定|不猜 / ……|
```

### 2.2 Caption

  - **原则**：只改句式，不改短语；一条 caption 可多句，短语必须全部**原样**出现。

|要求|说明|
|---|---|
|短语锁定|拼写、空格、连字符一致|
|禁止替换/增删|不改写成同类词，不省略、不塞未给定指称|
|禁止内容|不提框、crop、json、dataset、model|

```json
{"caption": "..."}
```

  场景文件：概述可加一句；**§1 核心原则不删行**；§3 示例换成该场景（至少 1 个单句 + 1 个多句）。**§4 schema 不改**。

---

## 3 加新场景（填空后落盘）

  触发：新规则、加场景、改 describe/caption 规则、扩展 default/appearance。  
  slug 不能是 `default` / `base` / `general`（那是改通用 md 本身）。已存在则先问覆盖还是换 id。

### 3.1 填空（未确认不得写文件）

```markdown
请填空后回复「按此生成」（改括号即可）：

1. 场景 id（slug，小写英文+下划线）：[________]  （例：appearance）
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
9. 场景焦点（一句话）：[________]
10. 关键类别与推荐英文用词：[________]
11. 看不清时：[不猜 | 中性描述 ________]
12. caption 口吻补一句（可空）：[________]
```

  第 3 项决定复制哪一对 md **和** 哪份 `describe_*.py`。第 6=是 → `ban_vehicle_subtypes`；第 7=是 → `exhaustive`；第 8=是 → `caption_cover_all`。确认后复述一表再写盘。

### 3.2 落盘

  **(1)** 先 Read 将要复制的那一对 md，再改写。

```text
rules/describe_rules.md                 → rules/describe_rules_<slug>.md
rules/caption_rules.md                  → rules/caption_rules_<slug>.md
util/describe_default.py                → util/describe_<slug>.py
# 或 appearance 那一套 *_appearance.md / describe_appearance.py
```

  **(2)** `scenes.json` 的 `scenes` 数组追加一行（不要动 `id=""` 的通用行）：

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

  **(3)** `describe_<slug>.py`：文件头 `RULES_FILE` 指向新 md；导出 `describe_object`（签名同 `describe_default.py`）。第 7 项=是则保留 `check_phrases_apply`。缺 py 或缺 json 行都是假切换。**禁止改** `util/describe.py`。

  **(4)** 下拉靠扫描 `describe_rules_<slug>.md`；json 负责 label + 机器策略。换下拉**不会**自动重跑 draft。

---

## 4 自检与试跑

  - [ ] describe / caption md 成对；§1.2 非空；表格紧致 `|列|列|`
  - [ ] `util/describe_<slug>.py` 存在且导出 `describe_object`
  - [ ] `scenes.json` 有该 id，四字段与填空一致
  - [ ] **未改** `util/describe.py`、输出 schema、`auto/`、`yoloe/`
  - [ ] 短语：英文短名词、贴类别、不编造、不提框
  - [ ] caption：短语原样全覆盖

```bash
python util/generate.py --dataset "<data_root>" --rules-scene "<slug>" --limit 1
```

  审阅台刷新后下拉会出现该项。试跑约定见 `agent-auto_generate`。
