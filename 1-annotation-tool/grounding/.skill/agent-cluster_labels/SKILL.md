---
name: agent-cluster_labels
description: >-
  Organizes 标签概览 phrase chips by semantic groups via the currently selected
  vLLM service. Display-only (draft/label_clusters). Use when the user says
  整理, 芯片整理, 一键整理, cluster labels, 芯片分组, or wants to extend grouping
  policy / batch organize / taxonomy.
---

# 🧩 Agent-Cluster Labels（芯片整理）

  - **概述**: 用户要「整理芯片 / 同类挨在一起 / 扩整理策略」时触发。只改**展示顺序**，不改 phrases / chosen / caption。必须走顶栏**当前所选**模型服务。
  - **日期**: 2026-08-21

---

## 0 执行前检查

  - **触发场景**：整理、芯片整理、一键整理、芯片分组、上衣夹克衬衫放一起、扩整理规则。
  - **本 Skill 位置**：`grounding/.skill/agent-cluster_labels/`（包内专用；尚未迁入通用技能库）。
  - **工具根目录**：本包（`.skill/` 的上一级）。
  - **范围边界**：只写 `draft/label_clusters/`；**不写**正式 `labels/`；**不改** `auto/`、`yoloe/`。
  - **进度台账**：单图点按钮即可，**不需要** `todo.md`。批量全库整理另开台账（见 [4]）。
  - **改 Python 路由后必须重启审阅台**（HTML 热更，Flask 路由不热更）。

---

## 1 现状（v0.6.8）

  **入口**：审阅台右侧「标签概览」→ 每张**类别卡**标题行绿色「整理」（同「目标描述」刷新）。芯片 < 3 条不显示按钮。

  **前端**：`util/templates/index.html`
  - `clusterLabelChips(classKey)` 只提交该类 `phrases`
  - `POST /api/cluster_labels`，body 带 `stem`、`service_id`、`phrases`
  - 整理中只改按钮（`syncLabelClusterBusyUi`），不重绘缩略图；切图优先 `/api/image`
  - 结果进 `labelClusters`，`collectLabelGroups()` 按 `phrase_groups` 排序并画小组标题

  **后端**：`util/app.py`
  - `cluster_label_chips(classes, phrases)`：短 prompt、`temperature=0`、`max_tokens≤512`、关 thinking
  - `_apply_service_from_request`：用请求里的 `service_id`，禁止静默落到 `server.json` 默认
  - `_merge_label_clusters`：只替换本次 scope 的 phrase keys，其它类别顺序保留
  - 落盘：`<data_root>/draft/label_clusters/{stem}.json`

  **JSON 形态**：

    ```json
    {
      "class_groups": [{"title": "上装", "keys": ["jacket"]}],
      "phrase_groups": [
        {"title": "上装", "keys": ["red jacket", "white shirt"]},
        {"title": "头戴", "keys": ["helmet"]}
      ]
    }
    ```

  `keys` 一律小写，与前端 `phraseKey` / `objClassKey` 对齐。

  **分组口吻（当前写死在 prompt）**：上衣/夹克/衬衫；帽/盔/口罩；裤/牛仔裤。车辆按种类不按颜色。

---

## 2 改整理时怎么动

  按改动面选入口，避免把策略写进 UI。

  | 要改什么 | 动哪里 |
  |---|---|
  | 分组例子 / 禁按颜色 | `cluster_label_chips()` 的 prompt |
  | 速度 / thinking / max_tokens | 同上 + `util/vllm_client.py` 的 `enable_thinking` |
  | 按钮位置 / 只整理一类 | `index.html` 的 `.cluster-btn`、`clusterLabelChips` |
  | 切图后仍保持顺序 | `draft/label_clusters/{stem}.json` + `_load_item_payload` |
  | 新场景不同分组策略 | 见 [3]，不要把 scene 逻辑写死在 HTML |

  **硬约束**：
  1. 始终传并应用**当前** `service_id`。
  2. 整理失败不得覆盖已有 `label_clusters`（当前是先算 `new` 再 merge 写盘；失败应在写盘前 return）。
  3. 不得把整理结果写进 descriptions / captions。
  4. 单卡整理必须 merge，禁止用本次结果整文件覆盖导致其它类顺序丢失。

---

## 3 扩展位（以后加，先不要实现除非用户点名）

  预留，保持文件边界清晰：

  **(1) 规则文件**  
  `rules/cluster_rules.md` + `rules/cluster_rules_<slug>.md`，与 describe 一样按 `rules_scene` 切换。prompt 从 md 读，不再写死在 `app.py`。登记可走 `scenes.json` 新字段（如 `cluster: true`），**不要**为了整理去改 `describe.py`。

  **(2) 数据集级词表缓存**  
  `draft/label_clusters/_vocab.json`：同类短语跨图复用分组，避免每张卡都打模型。命中则跳过 vLLM。

  **(3) 批量整理**  
  审阅或 CLI：扫 `draft/descriptions/`，按类别聚合 unique phrases，一次（或分块）聚类后回写各 `{stem}.json`。台账用 `<data_root>/draft/todo-cluster.md`。仍禁止 `--force` 覆盖用户未点过的顺序，除非用户明确要求。

  **(4) 无模型回退**  
  条数极少或服务不可用：按中英关键词启发式（jacket/shirt/coat → 上装）只作 fallback，并在 status 标明「未走模型」。

  **(5) 类别卡之间的分组**  
  已有 `class_groups` 字段但单卡整理不更新。若以后要「夹克卡和衬衫卡挨在一起」，单独做整页/全库整理，不要塞进单卡按钮。

---

## 4 若用户要批量 / 新策略

  **(1)** 先确认：范围（当前图 / 当前数据集）、是否覆盖已有 `label_clusters`、用哪条模型服务。  
  **(2)** 未确认不写规则 md、不扫全库。  
  **(3)** 实现时优先抽 prompt 到 `rules/cluster_rules*.md`，API 保持 `POST /api/cluster_labels`。  
  **(4)** 改完 `app.py` 提醒重启 `1-start_review.bat`；只改 HTML 刷新页面即可。

---

## 5 交付检查

  - 工具根目录：本包（`.skill/` 上一级）
  - 数据：只动 `draft/label_clusters/`
  - 服务：请求里的 `service_id` = 顶栏所选
  - 旧包：未改 `auto/`、`yoloe/`
  - 审阅：Python 有改 → 重启后再点「整理」
