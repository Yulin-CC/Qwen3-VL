# 🚀 QuickStart 脚本规范

- **概述**: 当**为本项目新建 `0-QuickStart/` 目录或其中的 Shell 脚本**时，按以下规范生成文件结构与脚本内容。
- **日期**: 2026-07-09

---

## 1 目录结构

```
0-QuickStart/
├── 0-train.sh       # 训练启动脚本
├── 1-predict.sh     # 推理启动脚本
├── 2-eval.sh        # 评估启动脚本
├── scripts/         # 可执行 Python 入口（CLI，含 argparse + main）
│   ├── train.py
│   ├── inference.py
│   └── eval.py
├── utils/                 # 纯工具函数（禁止作为主入口）
│   ├── __init__.py
│   ├── inference_utils.py # 推理逻辑封装
│   └── vis_export.py      # 可视化绘制 + 结果保存（推理必备）
```

如需补充其他脚本，依次命名为 `3-export.sh`，序号递增。

---

## 2 配置分层设计

本项目采用 **`config/defual.yaml` + `0-QuickStart/*.sh`** 两层配置：

- `config/defual.yaml`：统一存放所有参数的**默认值**，分 `dataset` / `train` / `predict` / `eval` 四个命名空间。
- `0-QuickStart/*.sh`：每个脚本在顶部**声明常用变量**，通过 CLI 参数传入 Python 脚本，**覆盖** yaml 中对应字段。

优先级：**脚本变量（CLI） > config/defual.yaml > 代码默认值**

`config/defual.yaml` 结构示意：

```yaml
# SAM-CD 默认配置
# 脚本中若传入同名参数（如 0-QuickStart/*.sh），脚本参数优先于此文件
# =============================================================================
# 调参思路
# =============================================================================
# 【防止过拟合】
# A. 先调 xxx
# B. 再调 yyy
#
# 【防止曲线震荡】
# A. 先调 xxx
# B. 再调 yyy
# =============================================================================

# ========== 数据集参数 ==========
dataset:
  root: "/path/to/data"  # 数据集根目录（包含 train/val/test）

# ========== 训练参数 ==========
train:
  project: "exp01"              # [项目] 训练任务名（用于 runs 目录命名）
  run_base_dir: "runs/0-train"  # [项目] 训练输出根目录
  dev_id: 0                     # [设备] 单卡训练时的 GPU ID
  epochs: 50                    # [训练参数] 训练轮数
  train_batch_size: 4           # [训练参数] 训练 batch size
  lr: 0.1                       # [训练参数] 初始学习率
  crop_size: 512                # [训练参数] 训练/验证裁剪尺寸
  # ...其余训练参数

# ========== 推理参数 ==========
predict:
  dev_id: 0                                                     # [设备] 推理 GPU ID
  crop_size: [1024, 1024]                                       # [推理参数] 推理裁剪尺寸 [H, W]
  tta: true                                                     # [推理参数] 是否启用测试时增强
  test_dir: "/path/to/test"                                     # [推理参数] 测试集目录（包含 A/B）
  pred_dir: "/path/to/test/repro"                               # [日志/输出] 推理结果输出目录
  chkpt_path: "runs/0-train/<project>/best.pth"                 # [日志/输出] 与训练写出 best.pth 对齐

# ========== 评估参数 ==========
eval:
  gt_dir: "/path/to/label"                                      # [验证参数] GT 标签目录
  pred_dir: "/path/to/test/repro"                               # [验证参数] 待评估预测目录
```

---

## 3 脚本文件头

每个 `.sh` 第一行固定 `#!/bin/bash`，紧跟注释块：

```bash
#!/bin/bash
###
 # @Author: 算法组 蔡雨霖
 # @Date: YYYY-MM-DD HH:MM:SS
 # @LastEditTime: YYYY-MM-DD
 # @Description:
###
```

---

## 4 变量命名规范

脚本变量区统一使用以下 **5 个标准变量名**：

| 变量 | 含义 | 示例 |
|---|---|---|
| `devices` | GPU 设备 ID | `0` |
| `project` | 权重保存文件夹名 | `"exp01"` |
| `weights` | 预训练权重完整路径（predict/eval 用） | `"./runs/0-train/$project/best_ckpt.pt"` |
| `dataset` | 数据集路径；推理脚本支持**单文件或目录** | `"/path/to/test"` 或 `"./assets/bus.jpg"` |
| `output` | 结果保存路径（**固定规则派生，无需手动设置**） | 见下方固定路径规则 |

### 固定路径规则

- **训练权重保存**：`./runs/0-train/$project`
- **推理结果保存**：根据 `dataset` 输入类型**智能派生**
  - 单文件输入（如 `./assets/bus.jpg`）→ 输出到 `<文件所在目录>/repro/`
  - 目录输入（如 `./assets/`）→ 输出到 `<目录>/repro/`
- **评估结果保存**：`$dataset/repro`

`output` 在脚本「固定路径」区由规则自动赋值，用户不需要手动修改。推理脚本的派生逻辑如下：

```bash
# 固定路径（无需修改，cd 后判断确保相对路径正确）
# 单文件输入 → <文件所在目录>/repro/
# 目录输入   → <目录>/repro/
if [ -f "$dataset" ]; then
    output="$(dirname "$dataset")/repro/"
elif [ -d "$dataset" ]; then
    output="$dataset/repro"
else
    echo "Error: dataset not found: $dataset"
    exit 1
fi
```

> **⚠️ 注意**：`-f` 判断必须在 `cd $ROOT_DIR` **之后**执行，否则相对路径会因当前目录不同而判断失败。

### 训练配置备份规则

训练脚本（`train.py`）在训练开始前，自动将以下配置文件备份到 `$output/configs/`，便于事后复现：

| 备份文件 | 来源 |
|---|---|
| `default.yaml` | `config/default.yaml`（全局训练配置） |
| `*.yaml` | `data/` 目录下所有数据集 yaml |

备份逻辑写在 Python 训练脚本中，`run_dir` 创建之后、模型加载之前执行：

```python
cfg_backup_dir = run_dir / "configs"
cfg_backup_dir.mkdir(parents=True, exist_ok=True)
_backup_files = (
    [ROOT_DIR / "config" / "default.yaml"]
    + sorted((ROOT_DIR / "data").glob("*.yaml"))
)
for src in _backup_files:
    if src.exists():
        shutil.copy2(src, cfg_backup_dir / src.name)
```

最终 run_dir 结构：

```
runs/0-train/{task}/{project}/
├── configs/          ← 配置快照（训练开始时自动生成）
│   ├── default.yaml
│   ├── 0-xxx.yaml
│   └── ...
├── weights/
│   ├── best.pt
│   └── last.pt
└── ...
```

---

## 5 变量配置区格式

文件头之后紧跟**可修改变量区**，格式规则：

- 整个区域由 `#--------------------------------------#` 首尾包裹，标题行固定为「需要修改的值」
- **每个变量（或紧密相关的小组）之间都插入一条 `#--------------------------------------#`**，所有分隔线**长度一致**，不使用更长的 `#----------------------------------------------#`
- 变量排列顺序固定为：**devices → project → weights + net_G（可选）→ dataset → 超参（epochs / batch_size 等）**
- 行尾注释左对齐
- 「固定路径（无需修改）」块紧跟在 `cd $ROOT_DIR` 之后，含 `output` 赋值及派生内部变量（`_ckpt_root` / `_ckpt_name` 等），用户不需要修改此区域

---

## 6 功能区块

变量区之后依次排列功能块，每块用固定格式标注：

```bash
#---------------#
# 块标题
#---------------#
```

顺序固定为：
1. 切换到虚拟环境（见 §6.1）
2. `cd $ROOT_DIR`（**必须在 output 派生之前**）
3. 固定路径派生（`output` 赋值）
4. 运行程序（传入脚本变量作 CLI 参数）

### 6.1 切换到虚拟环境

clone 仓库的用户 conda 安装路径**各不相同**，禁止在脚本中硬编码 `/home/<user>/miniconda3` 等绝对路径。统一使用 `CONDA_BASE` 变量 + 注释指引：

```bash
#---------------#
# 切换到虚拟环境（conda 路径因机器而异，clone 后请修改 CONDA_BASE）
#   常见：$HOME/miniconda3 | $HOME/anaconda3 | /opt/conda
#   查找：dirname "$(dirname "$(which conda)")"
#   环境名须与 README §0 环境 中 conda create -n 一致
#---------------#
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"   # 本机示例：/home/ubuntu/miniconda3
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate <env_name>
```

- **默认值**：`CONDA_BASE` 默认 `$HOME/miniconda3`；本机路径不同时改脚本默认值，或运行前 `export CONDA_BASE=/path/to/conda`。
- **环境名**：`<env_name>` 与 README「环境搭建」中 `conda create -n` 保持一致（如 `yoloe`）。
- **禁止**：写死 `/home/ubuntu/...` 且无任何修改说明。

---

## 7 完整模板

### 7.1 `0-train.sh`

```bash
#!/bin/bash
###
 # @Author: 算法组 蔡雨霖
 # @Date: YYYY-MM-DD HH:MM:SS
 # @LastEditTime: YYYY-MM-DD
 # @Description:
###
WORK_DIR=$(pwd)

#--------------------------------------#
# 需要修改的值
#--------------------------------------#
devices=0                              # GPU 设备 ID
#--------------------------------------#
project="exp01"                        # 权重保存文件夹名 → ./runs/0-train/$project
#--------------------------------------#
net_G="xxx"                            # 网络结构
#--------------------------------------#
dataset="/path/to/data"               # 训练数据集根目录
#--------------------------------------#
epochs=50                              # 训练轮数
batch=4                                # 批大小
lr=0.1                                 # 学习率
#--------------------------------------#


#---------------#
# 切换到虚拟环境（conda 路径因机器而异，clone 后请修改 CONDA_BASE）
#   常见：$HOME/miniconda3 | $HOME/anaconda3 | /opt/conda
#   查找：dirname "$(dirname "$(which conda)")"
#   环境名须与 README §0 环境 中 conda create -n 一致
#---------------#
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"   # 本机示例：/home/ubuntu/miniconda3
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate <env_name>


#---------------#
# 运行训练程序
#---------------#
cd $WORK_DIR/..

# 固定路径（无需修改）
output="./runs/0-train/$project"

mkdir -p "$output"
python train.py \
  --devices  "$devices" \
  --project  "$project" \
  --net_G    "$net_G" \
  --dataset  "$dataset" \
  --epochs   "$epochs" \
  --batch    "$batch" \
  --lr       "$lr"
```

### 7.2 `1-predict.sh`

```bash
#!/bin/bash
###
 # @Author: 算法组 蔡雨霖
 # @Date: YYYY-MM-DD HH:MM:SS
 # @LastEditTime: YYYY-MM-DD
 # @Description:
###
WORK_DIR=$(pwd)

#--------------------------------------#
# 需要修改的值
#--------------------------------------#
devices=0                                         # GPU 设备 ID
#--------------------------------------#
project="exp01"                                   # 权重保存文件夹名（与训练时一致）
#--------------------------------------#
weights="./runs/0-train/$project/best_ckpt.pt"   # 预训练权重完整路径
net_G="xxx"                                       # 网络结构（与训练时一致）
#--------------------------------------#
dataset="/path/to/test"                           # 测试输入（单张图片/视频/目录）
#--------------------------------------#
img_size=256                                      # 输入图像尺寸
#--------------------------------------#


#---------------#
# 切换到虚拟环境（conda 路径因机器而异，clone 后请修改 CONDA_BASE）
#   常见：$HOME/miniconda3 | $HOME/anaconda3 | /opt/conda
#   查找：dirname "$(dirname "$(which conda)")"
#   环境名须与 README §0 环境 中 conda create -n 一致
#---------------#
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"   # 本机示例：/home/ubuntu/miniconda3
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate <env_name>


#---------------#
# 运行推理程序
#---------------#
cd $WORK_DIR/..

# 固定路径（无需修改，cd 后判断确保相对路径正确）
# 单文件输入 → <文件所在目录>/repro/
# 目录输入   → <目录>/repro/
if [ -f "$dataset" ]; then
    output="$(dirname "$dataset")/repro/"
elif [ -d "$dataset" ]; then
    output="$dataset/repro"
else
    echo "Error: dataset not found: $dataset"
    exit 1
fi
_ckpt_root=$(dirname "$(dirname "$weights")")
_ckpt_name=$(basename "$weights")

mkdir -p "$output"
python predict.py \
  --devices  "$devices" \
  --weights  "$weights" \
  --dataset  "$dataset" \
  --output   "$output"
```

### 7.3 `2-eval.sh`

```bash
#!/bin/bash
###
 # @Author: 算法组 蔡雨霖
 # @Date: YYYY-MM-DD HH:MM:SS
 # @LastEditTime: YYYY-MM-DD
 # @Description:
###
WORK_DIR=$(pwd)

#--------------------------------------#
# 需要修改的值
#--------------------------------------#
devices=0                                         # GPU 设备 ID
#--------------------------------------#
project="exp01"                                   # 权重保存文件夹名（与训练时一致）
#--------------------------------------#
weights="./runs/0-train/$project/best_ckpt.pt"   # 预训练权重完整路径
net_G="xxx"                                       # 网络结构（与训练时一致）
#--------------------------------------#
dataset="/path/to/test"                           # 评估数据集根目录（含 label/ 子目录）
#--------------------------------------#
img_size=256                                      # 输入图像尺寸
batch=4                                           # 批大小
#--------------------------------------#


#---------------#
# 切换到虚拟环境（conda 路径因机器而异，clone 后请修改 CONDA_BASE）
#   常见：$HOME/miniconda3 | $HOME/anaconda3 | /opt/conda
#   查找：dirname "$(dirname "$(which conda)")"
#   环境名须与 README §0 环境 中 conda create -n 一致
#---------------#
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"   # 本机示例：/home/ubuntu/miniconda3
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate <env_name>


#---------------#
# 运行评估程序
#---------------#
cd $WORK_DIR/..

# 固定路径（无需修改）
output="$dataset/repro"
_ckpt_root=$(dirname "$(dirname "$weights")")
_ckpt_name=$(basename "$weights")

mkdir -p "$output"
python eval.py \
  --devices  "$devices" \
  --weights  "$weights" \
  --dataset  "$dataset" \
  --output   "$output"
```
