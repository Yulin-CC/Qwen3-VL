# 🔺 金字塔迭代预标注（Pyramid Label）

  - **概述**: 用户说「开始做金字塔预标注 / pyramid label / 小样本扩标注」时触发。流程与具体检测/分割后端无关（YOLO / SAM3 / GroundingDINO 等均可）：在同一数据集内按样本量台阶扩标 → check 人审入 `gold/` → 伪标入 `pseudo/`；终态只落双库。须先确认 **项目名**、**数据根目录**、**工作目录 `work_root`**（禁止猜测）。
  - **日期**: 2026-07-28

---

## 0 执行前检查

  - **工作目录 `work_root`（强制确认）**：训练配置、台账、轮次清单与 run 产物写此处；**不固定路径**。开跑前与用户确认（或沿用台账已有值）；不存在则创建。示例：`…/5-Agent-pyramidlabel`（YOLO）、`…/5-Agent-sam3`、`…/5-Agent-grounding` 等。
  - **后端 / 模型族**：由用户指定本轮用的训练与推理栈（默认可为当前仓库的 YOLO 工具链）；换 SAM3 / GroundingDINO 等时，**§3 台阶与双库约定不变**，仅 [§4] 训练/推理入口与导出格式按该后端替换。
  - **项目名（强制）**：开跑前询问短标识（如 `boat` / `wildfishing`）；未提供禁止继续。产物按项目隔离：`<work_root>/{datasets,config,todo,runs}/…/<project>/`。
  - **进度台账**：`<work_root>/todo-<project>.md`（见 [§1]）；开跑先读，每可恢复节点后更新。
  - **数据根目录**：用户给出的单数据集根（如 `sample-boat/`）；**不是** automerge 的「N 子集 + collection」。本流程按样本量分批扩标（类别数随任务而定）。
  - **环境**：conda / 设备随后端确认（YOLO 例：`yulin`）。训练集只许软链大图；**例外**：向 `gold/` / `pseudo/` 拷贝对应子集。

  **默认阈值（检测框任务常用；其它后端可改，须写入台账）**：

  | 项 | 默认（YOLO detect 参考） |
  | --- | --- |
  | pass1 | `conf>=0.35`，NMS `iou=0.45` |
  | pass2 / keep | `conf>=0.5`，同 `iou=0.45` |
  | check | 默认开；优先 conf band `[0.35, 0.5]`；约 `|S_k|*20%`（不足从有框样本补） |
  | 台阶参考 | 相对 \(N\) 或 \(U\)：5% / 10% / 15% / 30% / 40%；**须与用户确认**实际 `|S_k|` |

  **终态双库（互不混写；与后端无关）**：

  | 库 | 内容 | 结构 |
  | --- | --- | --- |
  | `gold/` | 种子 + 各轮人审 \(C_k\) | `images/` + `jsons/`（可另有训练用标签） |
  | `pseudo/` | 各轮 \(R_k^{\mathrm{keep}}\) + **末轮残留空检** | `images/` + 标签（如 `labels/`）+ `jsons/` |
  | `pre/round-k/` | 过程缓存（非交付主库） | check、预标缓存等 |

  - **强制**：\(\lvert\mathrm{gold}\cup\mathrm{pseudo}\rvert=N\)；同 stem 不得同时在两边。正式根级 `labels/` 默认不写（§6 可选）。

  工作区结构（均相对 `work_root`）：

    ```markdown
    <work_root>/
    ├── config/<project>/round-k/…
    ├── datasets/<project>/
    │   ├── L0.txt / U0.txt / A{k}.txt / L{k}.txt / U{k}.txt
    │   └── round-k/{train,val,sample}.txt + images/ + labels/   # 软链图
    ├── runs/…/<project>/Model-round-k/     # 目录名随后端习惯
    ├── utils/                              # 可选；本仓库 YOLO 辅助脚本
    └── todo-<project>.md
    ```

---

## 1 进度台账（todo-\<project\>.md）

  - **路径**：`<work_root>/todo-<project>.md`
  - **目的**：断点续跑；多项目 / 多后端工作区互不覆盖。

### 1.1 何时读写

  **(1)** 开跑 / 续跑：确认 `project` 与 `work_root` → Read 台账；禁止无故重做已 `done` 轮次。

  **(2)** 每可恢复节点后立即更新（状态、路径、统计、`next`）。

  **(3)** 每轮结束：核对 `<work_root>/runs/…/<project>/`、`data_root/pre/round-k/`、`gold/`、`pseudo/`、`<work_root>/datasets/<project>/` 与台账一致。

  **(4)** 用户说「继续 / check 进度」：读台账 → 摘要 → 执行 `next`。

  **(5)** 文件不存在：按 [1.2] 新建。

### 1.2 模板（可增行，勿删节字段）

  状态：`pending` / `in_progress` / `done` / `blocked` / `skipped`。

    ```markdown
    # Agent-pyramidlabel TODO

    - **updated**: YYYY-MM-DD HH:MM
    - **project**: boat
    - **work_root**: /path/to/work_root
    - **backend**: yolo | sam3 | grounding-dino | …
    - **data_root**: /path/to/dataset
    - **phase**: plan | round | deliver | done
    - **current**: …
    - **next**: …
    - **blocked**: 无 | …

    ## Meta
    - N / n0 / U: …
    - conf_pass1 / conf_pass2 / iou_nms: …（按后端写入）
    - check_band / check_enabled: …
    - schedule: |S|=…（已确认）
    - gold_dir / pseudo_dir: .../gold/ | .../pseudo/
    - classes / conda: …
    - work_datasets / work_config: <work_root>/datasets|config/<project>/

    ## Checklist
    - [ ] §2 确认 project / work_root / backend / 规模
    - [ ] §2 冻结台阶表
    - [ ] §3 全部轮次
    - [ ] §5 双库交付核验
    - [ ] §6 可选合并正式 labels（默认跳过）

    ## Rounds
    | k | |S| | L | C | pass2_keep | empty | U_left | status | note |
    | --- | --- | --- | --- | --- | --- | --- | --- | --- |
    | 1 | | | | | | | pending | |

    ## Notes
    - ...
    ```

### 1.3 更新规则

  - 保留历史 `done` 行；`current` / `next` 始终非空。
  - `done` 但缺 `best.pt`，或未写入本轮应付的 `gold/` / `pseudo/` → 改回 `pending`/`blocked`。
  - 对话与文件冲突时，以**台账 + 磁盘**为准。

---

## 2 确认项目名、数据集与台阶

  **(0)** 确认 `project`、`work_root`、`backend` → 在 `work_root` 下创建 `datasets/<project>/`、`config/<project>/`、`todo-<project>.md`。

  **(1)** 确认 `data_root`，写入台账。

  **(2)** 检查数据可用性（标注交换优先 LabelMe `jsons/`；训练格式随后端，YOLO 可参考 `standard-dataset_merge`）：

  - **a** 全量图源（`images/` 或 `gold/images` + `toclean/images` 等，由用户确认）。
  - **b** 种子有 `gold/jsons/`（YOLO 可转 `gold/labels/`）。
  - **c** 类别表（如 `classes.yaml`）；否则从种子统计后与用户确认。
  - **d** 创建 `gold/{images,jsons}/`、`pseudo/{images,labels,jsons}/`（`pseudo` 开跑可空；`labels/` 名可按后端调整）。

  **(3)** 统计并与用户确认：\(N\)、\(n_0=\lvert\mathrm{gold}\rvert\)、\(U=N-n_0\)、类别。`toclean` 等脏标**不**算金标，只作 \(U\) 图源。

  **(4)** 写 `data_root/seed.txt`（初始 `gold/` stems）；禁止改写种子；禁止伪标覆盖 `gold/`。

  **(5)** 打印实际 `|S_k|` 表（参考 §0 台阶；可对 \(U\) 同比例；末轮吃剩余）→ **用户确认后**勾选 Checklist §2，`phase=round`，`next=开始 round-1`。

---

## 3 迭代工作流

  记号：\(L_{k-1}\) 累计已标；\(U_{k-1}\) 未采纳池；\(S_k\) 本轮采样；\(C_k\) 人审 check（→`gold/`）；\(R_k=S_k\setminus C_k\)；\(R_k^{\mathrm{keep}}\) pass2 过线（→`pseudo/`）；\(A_k=C_k\cup R_k^{\mathrm{keep}}\)。

  每轮顺序（下轮主模型热启本轮 `Model-round-k-check`）：

  **选样 → 训主模型 → pass1 → check 人审 → \(C_k\)→`gold/` → 训校验模型 → pass2 → keep→`pseudo/` → 更新 \(L_k,U_k\)**

### 3.1 选样

  从 \(U_{k-1}\) 随机无放回抽 \(S_k\)（固定 seed）；末轮取剩余全部。写 `datasets/<project>/round-k/sample.txt`。

### 3.2 主模型

  用 \(L_{k-1}\) 建软链训练集 → 训 `Model-round-k`（\(k=1\)：该后端预训练/底座；\(k\ge2\)：热启上轮 check 模型）。更新台账 weights。

### 3.3 pass1 + check

  **(1)** 对 \(S_k\) 推理：§0 的 pass1 阈值；产物进 `pre/round-k/`。

  **(2)** 抽 check → `pre/round-k/check/`（images 软链 + LabelMe jsons + `check.txt`）；规则见 §0。

  **(3)** `blocked=等待用户校验 check`；**暂停**（人审前不得训校验模型 / 开下一轮）。

### 3.4 入库 gold + 校验模型 + 入库 pseudo

  **(1)** \(C_k\)：解析 check 软链，**拷贝**实体图 + 人审 json → `gold/`。禁止 pass2 写入 `gold/`。

  **(2)** 用 \(L_{k-1}\cup C_k\) 训 `Model-round-k-check`（热启本轮主模型）。

  **(3)** 对 \(R_k\) pass2（§0 阈值）→ `pre/round-k/labels-pre/`；将 \(R_k^{\mathrm{keep}}\) 拷入 `pseudo/`（images + labels + jsons；jsons 用 `pyramid_txt2json.py`）。已在 `gold/` 的 stem 不得入 `pseudo/`。

  **(4)** 空检回 \(U\)（非末轮）。\(L_k=L_{k-1}\cup A_k\)；\(U_k=U_{k-1}\setminus A_k\)。Rounds 行标 `done`。

  **(5)** **末轮强制**：\(U\) 残留（多为空检）全部写入 `pseudo/`（空 txt + `shapes=[]` 的 json），使 \(\lvert\mathrm{gold}\cup\mathrm{pseudo}\rvert=N\)。

### 3.5 循环条件

  - \(U\) 空或计划轮次完成 → [§5]。
  - 连续两轮采纳过低 → 暂停询问。
  - `check_enabled: false`（须用户原话）：跳过 check / 校验模型 / `gold/` 增补，伪标直接入 `pseudo/`；仍禁止写入 `gold/`。

---

## 4 工具索引

  > **流程通用，入口随 `backend`。** 下表为当前仓库 **YOLO** 默认实现；SAM3 / GroundingDINO 等替换「训练 / 伪标」两行即可，选样清单与双库落盘仍按 §3。

  | 步骤 | 工具（YOLO 默认） | 用途 |
  |------|------|------|
  | 台账 | `<work_root>/todo-<project>.md` | 断点续跑 |
  | YOLO 整理 | `.cursor/skills/standard-dataset_merge/SKILL.md` | 划分等参考 |
  | json→txt | `/home/yulin/1-project/1-PROCESS/utils/convert_json2txt.py` | LabelMe → YOLO |
  | 划分 | `/home/yulin/1-project/1-PROCESS/tools/yolo_dataset_division.py` | train/val |
  | 训练 | `<work_root>/0-QuickStart/scripts/train.py` | `--project <project>/Model-round-k` |
  | 选样建集 | `<work_root>/utils/pyramid_build_round.py` | `datasets/<project>/round-k` |
  | 伪标 + check | `<work_root>/utils/pyramid_prelabel.py` | `--conf` / `--iou`；`--check-dir` |
  | labels→jsons | `<work_root>/utils/pyramid_txt2json.py` | `pseudo/jsons/` |

  YOLO 训练示例（`work_root` 换成实际路径）：

    ```bash
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate yulin
    cd <work_root>
    python 0-QuickStart/scripts/train.py \
      --task detect --devices 0 \
      --project boat/Model-round-1 \
      --model weights/yolo26n.pt \
      --dataset config/boat/round-1/0-data.yaml \
      --epochs 80 --batch 4 --imgsz 1280 --workers 4
    ```

---

## 5 双库交付

  **(1)** 对账：`pseudo` 为 images+labels+jsons 三件套；含末轮空检；与 `gold` 无交叉；\(\lvert g\cup p\rvert=N\)。缺 jsons 则跑 `pyramid_txt2json.py`。

  **(2)** 向用户摘要：各轮 C / keep / empty、双库对数、最终权重、`pre/` 路径、空检 stem（`shapes=[]`）。

  **(3)** 台账：勾选 §5，`phase=done`，`next=无 | 用户要求 §6`。

---

## 6 可选：合并正式 labels

  > 默认不做。仅用户明确要求时：确认 `gold` 覆盖同 stem 的 `pseudo` 后合并；可参考 automerge 写回后的缓存清理。

---

## 7 拍板摘要

  | 项 | 结论 |
  | --- | --- |
  | `work_root` | **不固定**；开跑确认（例：YOLO → `5-Agent-pyramidlabel`） |
  | 后端 | 可换（YOLO / SAM3 / GroundingDINO…）；台阶与双库通用 |
  | 台阶 | 5→10→15→30→40（%）；须确认实际 `|S_k|` |
  | 训练 | 主模型 \(L_{k-1}\)；校验模型 \(L_{k-1}\cup C_k\) |
  | 阈值 | YOLO 参考：pass1 `>=0.35` / pass2 `>=0.5`；NMS `iou=0.45`（其它后端写入台账） |
  | check | 默认开；约 20% \(S_k\) |
  | 双库 | `gold`=种子+check；`pseudo`=keep+末轮空检；覆盖 \(N\) |
  | 热启 | 下轮主模型 ← 上轮校验模型 |
  | 正式 labels | 默认不合并（§6） |
