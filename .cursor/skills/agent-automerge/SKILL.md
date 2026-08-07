# 🔁 YOLO 基类自动合并流程

  - **概述**: 当用户说「开始做 YOLO 基类数据处理」「跑基类预标注流程」「对 M 类做训练+伪标签+Qwen 筛选」等时，按本 Skill 执行：确认目录与规范 → 建 pos/neg 表 → 循环训练 M 个模型 → 循环预标注并 Qwen 过滤 → 汇总待人工核查项。
  - **日期**: 2026-07-15

---

## 0 执行前检查

  - **触发场景**：基类数据处理、基类预标注、automerge、训练+伪标签+Qwen。
  - **工作目录**：`/home/yulin/1-project/2-YOLO/yolo26/4-Agent-automerge`（训练配置与产物写此处，不污染源数据工程目录）。
  - **进度台账**：`4-Agent-automerge/todo.md`（⭐ 强制维护，见 [1 进度台账]）；开跑前先读，每完成一步就更新。
  - **数据根目录**：由用户给出；结构须为 **N 个任务子集 + 1 个 `[collection]`**。
  - **`[collection]` 角色**：固定金标小合集，含全部 **M** 基类（各任务抽约 1% 并人工补齐），充当规划中的 \(T_{neg}×prop\) 来源；本流程**不**向其写入伪标签。
  - **范围边界**：伪标签**不写回**正式 `labels/`；正式写回留给人工校验后的后续流程。
  - **循环策略**：先完整训练 **M** 个 `Model-C_i`，再循环「推理 → 裁图 → Qwen → 过滤」；pos/neg 以 §3.2 表格为准并**冻结**。

---

## 1 进度台账（todo.md）

  - **路径**：`/home/yulin/1-project/2-YOLO/yolo26/4-Agent-automerge/todo.md`
  - **目的**：对抗上下文截断；新会话 / 长任务中途以文件为准续跑，不依赖对话记忆。

### 1.1 何时读写

  **(1)** **开跑 / 续跑前（强制）**：先 Read `todo.md`；若存在未完成项，从「当前步骤」继续，禁止无故重做已 `done` 项。

  **(2)** **每完成一个可恢复节点后（强制）**：立即更新 `todo.md`（状态、路径、统计、Next），再继续下一步。

  **(3)** **定期自检**：长循环中至少每完成 **1 个 \(C_i\)**（训练或预标注），或单步耗时较长（训练/Qwen）结束时，重读一遍 `todo.md` 核对与磁盘产物是否一致。

  **(4)** **用户说「继续」「接着跑」「check 一下进度」**：先读 `todo.md`，向用户摘要进度，再执行 Next。

  **(5)** **文件不存在**：按 [1.2 模板] 新建后再开跑；不得只在对话里记进度。

### 1.2 模板（须保持结构，可增行不可删节）

  Agent 创建或重置时写入如下结构（字段按实填；状态枚举：`pending` / `in_progress` / `done` / `blocked` / `skipped`）：

    ```markdown
    # Agent-automerge TODO

    - **updated**: YYYY-MM-DD HH:MM
    - **data_root**: /path/to/data
    - **phase**: check_dir | stats | train | prelabel | deliver
    - **current**: 一句话描述当前正在做的事
    - **next**: 下一步具体动作（可直接执行）
    - **blocked**: 无 | 阻塞原因（等人/缺文件/服务未起）

    ## Meta
    - M 基类: ...
    - 基类文件: ...
    - names 映射: ...
    - collection: collection

    ## Checklist
    - [ ] §2 确认目录与规范
    - [ ] §3.1 确认基类 + check_label
    - [ ] §3.2 冻结 pos/neg 表（附件或粘贴摘要）
    - [ ] §3.3 训练 M 个 Model-C_i
    - [ ] §3.4 预标注+Qwen 过滤全部 Tneg
    - [ ] §3.5 终态检查
    - [ ] §5 交付汇总

    ## Train (Model-C_i)
    | C_i | status | Tpos | config | weights | note |
    | --- | --- | --- | --- | --- | --- |
    | person | pending | | | | |

    ## Prelabel (C_i × Tneg)
    | C_i | Tneg | infer | crop | qwen | apply | review_n | note |
    | --- | --- | --- | --- | --- | --- | --- | --- |
    | person | smoke | pending | pending | pending | pending | | |

    ## Notes
    - ...
    ```

### 1.3 更新规则

  - **只改本流程相关字段**；保留历史 `done` 行，便于续跑跳过。
  - **status 与磁盘一致**：若 `todo` 写 `done` 但权重/标签不存在，改回 `pending` 或 `blocked` 并注明。
  - **`current` / `next` 始终非空**（暂停等人时 `next` 写清等待什么）。
  - **大表可外置**：pos/neg 全表可另存 `4-Agent-automerge/tables/`，`todo.md` 里只留路径链接。
  - **注意**：`todo.md` 是进度真相源；对话摘要与文件冲突时以文件 + 磁盘产物为准。

---

## 2 确认数据集目录

  **(1)** 向用户确认数据根目录；未提供则询问。写入 `todo.md` 的 `data_root`。

  **(2)** 总结并确认结构：N 个任务子集（一文件夹一任务）+ 1 个 `[collection]`。

  **(3)** 检查 N 个任务子集是否符合下列规范。符合则继续；不符合则以**表格**列出问题，询问是否继续：

  - **a** 文件命名：图像/标签前缀须含任务关键词。例：烟火任务参考 `GEOAI-SmokeFire-<date>-<basename>.<suffix>`，须含 `SmokeFire`。
  - **b** 标签体系：类别名不得含中文。
  - **c** 文件匹配：images / labels 按 stem 对齐，不得差异过大。

  **(4)** 检查 `[collection]` 是否符合下列规范。符合则继续；不符合则以表格列出问题，询问是否继续：

  - **a** 标签体系：不得含中文；警惕近义类名（如 `qiche` 与 `car`）。
  - **b** 文件匹配：stem 对齐率 **≥ 95%**。

  **(5)** 本节完成后：勾选 Checklist「§2」，`phase=stats`，更新 `next`。

---

## 3 工作流

### 3.1 确认基类

  **(1)** 读取根目录 `*基类M.yaml` 或 `*基类M.txt`，确认 M 个基类名；记某一类为 \(C_i\)。

  **(2)** 调用 `check_label.py`（见 [4 工具索引]）分析 N+1 个子集标签。

  - **a** **强约束**：至少 `[collection]` 须覆盖全部 M 基类；未覆盖则报错并与用户确认。
  - **b** N 个任务子集只登记各自类别（用于 pos/neg），不要求单子集含全部 M 类。

### 3.2 保存数据集基本信息

  **(1)** 子集概况表：

  | 序号 | N+1 任务子集 | 图像数据量 | 标签数据量 | 全部类别 |
  | --- | --- | --- | --- | --- |

  **(2)** 类别_数据集表（此后冻结，训练/推理只查此表）：

  | 序号 | 类别 \(C_i\) | 样本个数(以框数为主) | pos 任务子集(含 \(C_i\)) | neg 任务子集(不含 \(C_i\)) |
  | --- | --- | --- | --- | --- |

  **(3)** 将两表写入 `todo.md`（或 `tables/` + 链接）；按表初始化 **Train** / **Prelabel** 行；`phase=train`。

### 3.3 循环训练 M 个子模型

  对每个 \(C_i\)（\(i∈M\)）依次执行（跳过 Train 表中已 `done` 的 \(C_i\)）：

  **(1)** 查类别_数据集表得 \(T_{pos}\)，仅配置这些子集参与本轮训练。

  - 例：`car` 的 \(T_{pos}\) 为 `[car]`、`[person_boat_car]`、`[collection]`。

  **(2)** 按 YOLO 规范整理 \(T_{pos}\)（参考 `.cursor/skills/standard-dataset_merge/SKILL.md`）；训练标签**仅保留** \(C_i\)。

  **(3)** **源标注保护**（\(T_{pos}\) 含 collection 与其它 pos 子集；二选一，**优先不污染源** `labels/`）：

  - **a** 首轮：若无 `labels-cache/`，将当前 `labels/` 完整缓存为 `labels-cache/`。
  - **b** 每个 \(C_i\) 开训前：从 `labels-cache/` 恢复到 `labels/`，再滤成仅含 \(C_i\)（类别 id remap 为 `0`）后训练。
  - **c** M 轮训练全部结束后：从 `labels-cache/` 恢复全量 `labels/`。
  - **d** 或在工作区建训练副本、不改源目录 `labels/`。

  **(4)** 在工作目录写本轮配置并训练 `Model-C_i`：

    ```markdown
    ├── 4-Agent-automerge/
    │   ├── 0-QuickStart/           # 快速启动
    │   ├── config-C_i/
    │   │   ├── 0-C_i.yaml          # 数据集读取
    │   │   └── default-C_i.yaml    # 训练配置
    │   ├── utils/                  # 工具脚本
    │   ├── runs/                   # Model-C_i 输出
    │   └── todo.md                 # ⭐ 进度台账
    ```

  - **注意**：调用 `0-QuickStart/0-train.sh`（或等价 `scripts/train.py`）；conda 环境默认 `yolo`。
  - **注意**：单个 \(C_i\) 训完即更新 Train 表（`status=done`、weights 路径），再开下一个。

### 3.4 循环推理与预标注过滤

  - 全部 Train `done` 后，将 `phase=prelabel`。对每个 \(C_i\)，用 `Model-C_i` 推理该行的全部 \(T_{neg}\)（Prelabel 已 `done` 的格子跳过）：

  **(1)** 推理结果写入各 Tneg 的 `pre/labels-pre-C_i/`，仅保留 `conf > 0.2` 的框。

  - **a** `conf > 0.6`：保留标签。
  - **b** `0.2 < conf < 0.6`：送入裁图。

  **(2)** 调用 `BoxCrop_cls.py --status crop`（外扩比例按流程取 **2.0**），保存到 `pre/crops-pre-C_i/`。截图命名须为 `{stem}_{idx:02d}.jpg`，`idx` 对应 `labels-pre` 行号。

  **(3)** 确认 vLLM 已启动（参考 `/home/yulin/1-project/0-VLM/z-OpenAI/2-vllm`），调用 `qwen_filter.py` 对截图逐张打分（是否为 \(C_i\)）。

  **(4)** 按 Qwen 分数过滤（可用 `qwen_filter.py --apply`）：

  - **a** `qwen_conf < 0.3`：舍弃——删除对应 crop，并从 `labels-pre-C_i` 删除该框。
  - **b** `qwen_conf >= 0.6`：保留——删除 crop，**不改** `labels-pre-C_i`。
  - **c** `0.3 <= qwen_conf < 0.6`：人工核查——保留 crop，记录每个 Tneg 待核查数量。

  - **注意**：本步只改 `labels-pre-*` / `crops-pre-*`；人工核查后的正式 `labels/` 写回不在本 Skill 范围。中档遗留可由人工分文件夹后，再用 `BoxCrop_cls.py --status update` 处理（后续流程）。
  - **注意**：每完成一个 `C_i × Tneg` 格子，立即更新 Prelabel 表对应行（含 `review_n`）。

### 3.5 终态检查

  全自动段结束后、进入人工核查前，结构应如下（正式 `labels/` 保持原标注；产物在 `pre/`）：

    ```markdown
    ├── T_1/
    │   ├── images/
    │   ├── pre/
    │   │   ├── labels-pre-C_i/    # ⭐ 伪标签
    │   │   └── crops-pre-C_i/     # ⭐ 待人工/已过滤后残留截图
    │   ├── labels/                # 源标注（本流程不写回）
    │   ├── train.txt
    │   └── val.txt
    ├── T_2/
    ├── ...
    ├── T_N/
    └── collection/                # 已人工校验、含全部 M 类、本流程不更新
    ```

  - 检查通过后：`phase=deliver`，勾选终态 Checklist。

---

## 4 工具索引

  | 步骤 | 工具 | 用途 |
  |------|------|------|
  | 进度台账 | `4-Agent-automerge/todo.md` | 断点续跑；强制读写 |
  | 标签统计 / pos-neg | `/home/yulin/1-project/1-PROCESS/tools/check_label.py` | 子集概况、基类覆盖、类别表 |
  | YOLO 规范整理 | `.cursor/skills/standard-dataset_merge/SKILL.md` | Tpos 整理为可训练 YOLO |
  | 训练 | `4-Agent-automerge/0-QuickStart/0-train.sh` | 训 `Model-C_i` |
  | 推理 | `4-Agent-automerge/0-QuickStart/1-inference.sh` | 对 Tneg 预标注（输出需落到 `labels-pre-C_i`） |
  | 裁图 | `4-Agent-automerge/utils/BoxCrop_cls.py` | `--status crop` / 后续人工 `--status update` |
  | Qwen 过滤 | `4-Agent-automerge/utils/qwen_filter.py` | 打分；`--apply` 按阈值更新 pre |
  | vLLM 服务 | `/home/yulin/1-project/0-VLM/z-OpenAI/2-vllm` | Qwen 多模态打分服务 |

  - **注意**：`check_label.py` 示例：

    ```bash
    python /home/yulin/1-project/1-PROCESS/tools/check_label.py \
      --root /path/to/data \
      --base /path/to/基类M.yaml \
      --names /path/to/classes.yaml \
      --save /path/to/out
    ```

  - **注意**：`qwen_filter.py` 示例（须先起 vLLM；环境可用 `qwen`）：

    ```bash
    python /home/yulin/1-project/2-YOLO/yolo26/4-Agent-automerge/utils/qwen_filter.py \
      --crop_dir /path/to/T_j/pre/crops-pre-car \
      --label_dir /path/to/T_j/pre/labels-pre-car \
      --class_name car \
      --apply
    ```

---

## 5 交付

  **(1)** 打印或保存：子集概况表、类别_数据集表、各 `Model-C_i` 训练路径、各 Tneg 的 keep / review / discard 统计。

  **(2)** 明确列出待人工核查的 crop 数量（按 Tneg × \(C_i\)），并指向 `crops-pre-C_i/_qwen_filter/review_list.txt`（若已生成）。

  **(3)** 提醒用户：本流程**未**将伪标签写入正式 `labels/`。

  **(4)** 更新 `todo.md`：Checklist 全部勾选，`phase=deliver`，`current=已完成`，`next=等待人工核查`。
