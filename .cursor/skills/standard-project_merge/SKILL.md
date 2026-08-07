
# 🔀 上游项目合并规范

  - **概述**: 当**将上游开源项目（如 Meta SAM3）合并/整理为本团队标准结构**时，按本 Skill 的四步流程执行：充分阅读官方文档 → 整理 QuickStart → 归档根目录散落文件到 `z-others/` → 重写根目录 `README.md`。
  - **日期**: 2026-06-11

---

## 0 执行前检查

  - **触发场景**：用户要求「合并项目」「整理项目结构」「按标准改造上游仓库」等。
  - **依赖 Skill**：执行过程中须交叉引用：
    - `.cursor/skills/standard-quickstart/SKILL.md` — QuickStart 脚本与配置分层
    - `.cursor/skills/standard-create_readme/SKILL.md` — 新 README 结构与排版
    - `.cursor/skills/standart-create_script/SKILL.md` — `0-QuickStart/scripts/*.py` 文件头与代码风格
  - **原则**：先读懂再动手；保留上游核心代码目录不动；根目录 loose 文件仅保留 **`README.md`** 与 **`.gitignore`**（安装用符号链接在 clone 后按 README 创建，**不提交**到仓库）。

---

## 1 充分阅读项目 README

  合并前必须**完整阅读**项目内所有与安装、训练、推理相关的文档，形成结构化笔记，再进入后续步骤。

### 1.1 必读文件清单

  按优先级依次查找并通读（路径因项目而异，用 `find` / `glob` 定位）：

  | 优先级 | 典型路径 | 关注内容 |
  |--------|----------|----------|
  | P0 | 根目录 `README.md` | 安装、依赖、快速推理、权重下载 |
  | P0 | `README_TRAIN.md`、`docs/` | 微调、分布式、配置体系 |
  | P1 | `pyproject.toml` / `setup.py` / `requirements*.txt` | Python 版本、extras（如 `[train]`）、关键依赖 |
  | P1 | `CONTRIBUTING.md`、`RELEASE*.md` | 版本差异、环境补充说明 |
  | P2 | `examples/`、`scripts/` 内 README | 示例用法、评测脚本 |

  ```bash
  # 列出所有 README 类文档
  find . -maxdepth 4 \( -iname 'readme*.md' -o -iname 'install*.md' \) ! -path './.git/*'
  ```

### 1.2 阅读产出（内部笔记）

  阅读完成后，整理以下要点（供步骤 2、4 使用）：

  - **环境**：Python 版本、conda/venv 名称建议、`pip install` 完整命令（含 extras）
  - **硬件**：CUDA 版本、GPU 显存建议
  - **权重**：本地路径约定 vs HuggingFace 自动下载
  - **入口**：官方训练脚本路径、推理脚本路径、配置格式（Hydra / argparse / yaml）
  - **数据**：官方数据集目录约定、标注格式
  - **本团队差异**：哪些流程需用 `0-QuickStart/` 封装，哪些保留在 `z-others/` 仅供参考

  - **注意**：不要跳过官方安装步骤；新 README 的「环境搭建」必须能独立复现，不能只写「见官方文档」。

---

## 2 整理 QuickStart

  在步骤 1 笔记基础上，按 `standard-quickstart` 规范建立 `0-QuickStart/`。

### 2.1 目录结构

  ```
  0-QuickStart/
  ├── 0-train.sh              # 训练（或微调）入口
  ├── 1-predict.sh            # 推理入口（命名可与项目一致，如 1-inference.sh）
  ├── 2-eval.sh               # 评估入口（可选）
  └── scripts/                # Python CLI 封装
      ├── train.py
      ├── inference.py
      └── eval.py
  ```

  序号从 `0` 起递增；仅推理项目可只保留 `1-predict.sh`。

### 2.2 封装原则

  - **Shell 脚本**：严格遵循 `standard-quickstart` 的文件头、变量区（`devices` / `project` / `weights` / `dataset` / `output`）、功能块顺序。
  - **Python 脚本**：调用上游核心逻辑，不复制大段官方代码；参数通过 argparse 暴露，默认值读 `config/default.yaml`。
  - **配置分层**：新建或补齐 `config/default.yaml`，分 `dataset` / `train` / `predict` / `eval` 命名空间；优先级：**脚本 CLI > yaml > 代码默认**。
  - **路径解析**：脚本内用 `ROOT_DIR` 解析相对路径，避免硬编码绝对路径。

  ```bash
  WORK_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  ROOT_DIR=$(cd "$WORK_DIR/.." && pwd)
  ```

### 2.3 与上游入口的映射

  为每个 QuickStart 脚本建立映射表（写入新 README 的「快速流程」）：

  | QuickStart | 上游原始入口 | 说明 |
  |------------|--------------|------|
  | `0-train.sh` | 如 `sam3/train/train.py -c ...` | 收敛为 yaml + 少量 shell 变量 |
  | `1-predict.sh` | 如官方 notebook / examples | 固定 `weights`、`dataset`、`text_prompt` |
  | `2-eval.sh` | 如 `scripts/eval/...` | 可选 |

  - **注意**：若上游使用 Hydra，在 `scripts/train.py` 内转换为团队统一的 yaml + CLI，避免用户直接面对冗长 Hydra 路径。

---

## 3 新建 `z-others` 并归档根目录文件

  目标：**根目录只保留编号业务目录 + 核心代码包 + 新 `README.md`**，上游自带的零散文件统一收入 `z-others/`。

### 3.1 目标根目录形态

  ```
  项目名/
  ├── README.md                 # 步骤 4 新建的使用指南（根目录唯一 md 文件）
  ├── .gitignore                # 根目录唯一配置类 loose 文件
  ├── 0-QuickStart/             # 日常入口
  ├── 1-data-process/           # 数据处理（按需）
  ├── config/
  ├── data/
  ├── weights/
  ├── runs/
  ├── sam3/                     # 上游核心包（目录名保持原样，不移动）
  └── z-others/                 # 上游散落文件归档
      ├── pyproject.toml        # pip 安装清单（canonical 副本）
      ├── requirements.txt      # editable 依赖列表（canonical 副本）
      ├── LICENSE
      ├── README.md             # 官方原始 README（从根目录移入并重命名保留）
      ├── README_TRAIN.md
      ├── CONTRIBUTING.md
      ├── examples/
      └── scripts/              # 官方评测/工具脚本（非 QuickStart）
  ```

  - **根目录 loose 文件约束**：除 `README.md`、`.gitignore` 外，**不得**在仓库中保留 `pyproject.toml`、`requirements.txt`、`LICENSE` 等安装文件的实体或符号链接；这些文件 canonical 副本一律在 `z-others/`，用户安装时临时 `ln -sf` 到根目录。

### 3.2 移动规则

  **(1) 创建目录**

  ```bash
  mkdir -p z-others
  ```

  **(2) 移动对象**：项目根目录下所有**普通文件**（非目录、非符号链接目标冲突项）。

  ```bash
  # 示例：移动根目录文件（排除新 README 与隐藏项）
  for f in *; do
    [ -f "$f" ] || continue
    [ "$f" = "README.md" ] && continue   # 保留步骤 4 将写入的新 README
    mv "$f" z-others/
  done
  ```

  **(3) 不移动**

  - 所有**子目录**（`0-QuickStart/`、`sam3/`、`config/` 等保持原位）
  - 根目录**新** `README.md`（步骤 4 产出）
  - `.git/`、`.cursor/` 等隐藏目录

  **(4) 建议一并迁入 `z-others/` 的上游目录**（若仍在根目录）：

  - `examples/`、`test/`、`.github/`
  - 官方 `scripts/`（与 `0-QuickStart/scripts/` 区分：后者是团队封装入口）

  ```bash
  for d in examples test scripts .github; do
    [ -d "$d" ] && [ "$d" != "0-QuickStart" ] && mv "$d" z-others/
  done
  ```

### 3.3 安装文件归档与符号链接策略

  `pip install -e .` 要求 `pyproject.toml` 与核心代码包（如 `ultralytics/`、`sam3/`）**同级**，位于项目根目录。合并后安装文件收入 `z-others/`，通过**安装时临时符号链接**桥接，既保证可安装，又保持根目录简洁。

  **(1) 迁入 `z-others/` 的安装相关文件**

  | 文件 | 说明 |
  | ---- | ---- |
  | `pyproject.toml` / `setup.py` | 包定义；`[tool.setuptools.packages]` 中 `where = ["."]` 相对**根目录** |
  | `requirements.txt` | 依赖列表；含 `-e .` 及 `third_party/*` 时路径相对**根目录** |
  | `LICENSE` | 许可证（可选链，仅上游 license 检查需要时） |
  | 官方 `README.md` 等 | 参考文档，不参与安装 |

  **(2) 编写 `z-others/requirements.txt`**

  将官方 `pip install` 步骤转为 editable 列表，示例：

  ```text
  -e .
  -e third_party/<pkg-a>
  -e third_party/<pkg-b>
  ```

  - `-e .` 表示根目录当前包；**必须在根目录执行** `pip install -r requirements.txt`（先完成步骤 3 的 `ln -sf`）。
  - 若官方使用 extras（如 `pip install -e ".[train]"`），在 `requirements.txt` 写为 `-e ".[train]"` 或在 README 单独一行说明。
  - **禁止**使用 `z_others` 等错误目录名；归档目录固定为 **`z-others/`**（连字符）。

  **(3) 安装时创建符号链接（用户按 README 执行，不提交 Git）**

  ```bash
  cd <项目根目录>/
  ln -sf z-others/pyproject.toml pyproject.toml
  ln -sf z-others/requirements.txt requirements.txt
  # 可选，仅 license 检查需要时：
  # ln -sf z-others/LICENSE LICENSE
  ```

  **(4) 可选：`.gitignore` 忽略安装时生成的链接**

  ```gitignore
  /pyproject.toml
  /requirements.txt
  /LICENSE
  ```

  - **注意**：移动后须在**干净 conda 环境**中跑通完整安装流程（见 §4.2）；`ln -sf` 后执行 `pip install -r requirements.txt` 验证 `-e .` 能定位根目录核心包。

---

## 4 新建根目录 README.md

  按 `standard-create_readme` 规范**重写**根目录 `README.md`（覆盖或替换合并前的说明文档）。

### 4.1 必备章节

  ```markdown
  # 🚀 项目名称 / 使用指南

  一两句简介 + 目录锚点

  ---

  ## 1 环境搭建
  （重点：根据官方 README / pyproject.toml 写清完整步骤）

  ---

  ## 2 快速流程
  ### 2.1 数据准备
  ### 2.2 训练
  ### 2.3 推理
  ### 2.4 评估（可选）

  ---

  ## 3 进阶说明
  ### 3.1 项目结构
  ### 3.2 常用参数

  ---

  ## 参考
  - 上游仓库链接
  - 官方文档在 z-others 中的路径
  ```

### 4.2 环境搭建（重点）

  必须根据步骤 1 阅读的**官方文档**写全，且**clone 后按 README 逐步执行即可成功**（不得依赖未文档化的手动步骤）。至少包含：

  - **Python 环境**：`conda create` 版本号与环境名（与 QuickStart 脚本中 `conda activate` 一致）
  - **符号链接**：安装前 `ln -sf z-others/pyproject.toml` 与 `z-others/requirements.txt` 到根目录（见 §3.3；**不提交**仓库）
  - **PyTorch**：若官方单独安装 CUDA 版 torch，写在 `pip install -r requirements.txt` **之前**，并注释 cu128 / cu121 / cu118 备选
  - **安装命令**：根目录执行 `pip install -r requirements.txt`（链完成后 `-e .` 才有效）
  - **额外依赖**：官方 README 中未纳入 `requirements.txt` 的包（如 `pycocotools`）单独一行
  - **权重**：`mkdir -p weights/` + HuggingFace / wget 下载说明
  - **验证**：一条可复制的 smoke test（如 `python -c "import <core_pkg>"` 或 `bash 0-QuickStart/1-inference.sh`）

  **README 推荐模板**（简洁版，按实际上游内容改写，勿照搬无关项目）：

  ```bash
  conda create -n <env_name> python=3.10 -y
  conda activate <env_name>

  cd <项目根目录>/
  ln -sf z-others/pyproject.toml pyproject.toml
  ln -sf z-others/requirements.txt requirements.txt

  pip install --upgrade pip setuptools wheel
  pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu128   # 按 CUDA 版本调整
  pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

  python -c "import <core_pkg>; print('环境 OK')"
  ```

  **合并时自检（Agent 必须执行一次）**：

  1. 确认 `z-others/pyproject.toml` 存在且非坏软链
  2. 确认 `z-others/requirements.txt` 中 `-e .` 与 `third_party/` 路径相对根目录正确
  3. 在临时环境中按上述模板完整跑通，或至少 `pip install -r requirements.txt --dry-run` 无报错
  4. 确认 `git status` 根目录无新增 loose 文件待提交（仅 `z-others/` 内变更）

### 4.3 快速流程

  - 每个子节对应一个 `0-QuickStart/*.sh`，写清**改哪些变量**、**运行哪条命令**、**输出目录约定**。
  - 数据目录用 ASCII 树形图（无语言标记），注释左对齐。

### 4.4 项目结构图

  必须体现合并后的清爽根目录 + `z-others/` 归档关系，例如：

  ```
  sam3/
  ├── 0-QuickStart/              # 训练 / 推理 / 评估入口
  ├── 1-data-process/            # 数据与标注流程
  ├── config/default.yaml        # 默认超参
  ├── data/                      # 数据集 yaml
  ├── weights/                   # 预训练权重
  ├── runs/                      # 训练输出
  ├── sam3/                      # 上游核心代码
  └── z-others/                  # 官方 README、pyproject、examples 等
  ```

### 4.5 参考链接

  文末保留上游仓库 URL，并注明 `z-others/README.md`、`z-others/README_TRAIN.md` 等原始文档路径，便于查阅细节。

---

## 5 合并后自检清单

  完成四步后逐项确认：

  - [ ] 官方 README / 安装文档已通读，环境搭建章节可独立执行
  - [ ] `0-QuickStart/` 脚本可 `bash` 运行，变量区与 `config/default.yaml` 对齐
  - [ ] 根目录 loose 文件仅 `README.md` + `.gitignore`（无 `pyproject.toml` / `requirements.txt` 实体或 symlink 被提交）
  - [ ] `z-others/` 含 `pyproject.toml`、`requirements.txt`、`LICENSE`、原始 README
  - [ ] 按 README 执行 `ln -sf` + `pip install -r requirements.txt` 在干净 conda 环境中成功
  - [ ] 新 `README.md` 符合 `standard-create_readme` 排版（编号章节、`---` 分隔、代码块带语言标记）

---

按「先读懂 → 再封装 QuickStart → 再归档 → 最后写 README」顺序执行，可避免漏装依赖、路径断裂或官方入口丢失。
