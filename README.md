# 🚀 Qwen3-VL 使用指南

本仓库为团队整理的 Qwen3-VL 工作流：环境安装、标注、微调、推理与 vLLM 服务；官方源码在 `Qwen/`，归档资料在 `z-others/`。

---

## 1 项目结构

```
Qwen3-VL/
├── 0-QuickStart/                 # 训练 / 推理入口
│   ├── 0-train.sh
│   ├── 1-inference.sh
│   ├── scripts/
│   │   ├── train.py              # 微调 CLI（调用 Qwen/qwen-vl-finetune）
│   │   └── inference.py          # 本地推理 CLI
│   └── utils/
│       └── inference_utils.py    # 官方 qwen-vl-utils 预处理
├── 0-Agent-demo/                 # Agent 训练 / 验证 / 推理工作目录
│   ├── _demo_train/
│   ├── _demo_eval/
│   └── _demo_infer/
├── 1-annotation-tool/            # 标注工具
│   ├── anylabel/                 # 画框 / 分割 / 旋转框（X-AnyLabeling）
│   ├── qwen/                     # 图像问答对标注（Flask）
│   └── grounding/                # Grounding 描述生成与检验
├── 2-vllm/                       # vLLM OpenAI 兼容服务
├── Qwen/                         # 上游官方代码（finetune / utils / eval）
├── config/default.yaml           # 微调默认配置
├── data/                         # 数据集清单与生成脚本
└── z-others/                     # 官方 README、依赖、Demo 等归档
    ├── requirements.txt
    └── README.md                 # 上游原始说明
```

---

## 2 环境搭建

默认 **conda** 环境 `qwen`（与 `0-QuickStart/` 脚本一致）。脚本里 conda 根目录用 `CONDA_BASE`（默认 `$HOME/miniconda3`，可改或 `export CONDA_BASE=...`）。无 conda 或想用项目 `.venv` 时走下方 uv 备选。

驱动 CUDA 12.8+ 用 `cu128`；12.4 / 12.6 改 `cu124`。有卡时 **必须先装 GPU torch，再装其它包**，避免 PyPI 把 torch 盖成 CPU 版。

### 2.1 conda

- **创建并激活虚拟环境**

  ```bash
  conda create -n qwen python=3.12
  conda activate qwen
  ```

- **安装 torch**

  ```bash
  pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu128
  ```

- **安装 flash-attn（官方训练路径，需外网）**：默认 `attn_implementation: flash_attention_2`。装不上时在 `config/default.yaml` 改为 `sdpa`，并把 `data_flatten` 设为 `false`

  ```bash
  export MAX_JOBS=24
  export MAKEFLAGS="-j24"
  ulimit -v 67108864

  pip install --no-cache-dir --force-reinstall --no-build-isolation --no-deps \
    git+https://github.com/Dao-AILab/flash-attention.git@v2.8.3
  ```

  验证：

  ```bash
  python -c "import flash_attn; print(flash_attn.__version__)"
  ```

- **安装依赖**

  ```bash
  pip install -r z-others/requirements.txt
  ```

- **从源码安装 vLLM（可选，服务端需要）**

  ```bash
  export MAX_JOBS=24
  ulimit -v 67108864
  git clone https://github.com/vllm-project/vllm.git
  cd vllm && pip install -e .
  python -c "import vllm; print(vllm.__version__)"
  ```

### 2.2 uv（备选）

未安装 uv 时先看 [安装说明](https://docs.astral.sh/uv/)。在仓库根目录建 `.venv`，后续命令一律用 `$PY`，不要用系统 `python`。QuickStart 脚本里的 `conda activate qwen` 需改成 `source .venv/bin/activate`，或把解释器指到 `$PY`。

```bash
uv venv --python 3.12 .venv
PY="$(pwd)/.venv/bin/python"    # Windows: .venv/Scripts/python.exe
```

- **安装 torch**（有卡）

  ```bash
  uv pip install --python "$PY" torch torchvision --index-url https://download.pytorch.org/whl/cu128
  "$PY" -c "import torch; print('torch', torch.__version__); print('cuda', torch.cuda.is_available())"
  ```

  有卡但 `cuda` 为 `False` 时停下核对驱动与 `cu128` / `cu124`，不要擅自改装 CPU 轮。

- **安装 flash-attn（官方训练路径，需外网）**：默认 `attn_implementation: flash_attention_2`。装不上时在 `config/default.yaml` 改为 `sdpa`，并把 `data_flatten` 设为 `false`

  ```bash
  export MAX_JOBS=24
  export MAKEFLAGS="-j24"
  ulimit -v 67108864

  uv pip install --python "$PY" --no-cache-dir --force-reinstall --no-build-isolation --no-deps \
    git+https://github.com/Dao-AILab/flash-attention.git@v2.8.3
  "$PY" -c "import flash_attn; print(flash_attn.__version__)"
  ```

- **安装依赖**

  ```bash
  uv pip install --python "$PY" -r z-others/requirements.txt
  ```

- **从源码安装 vLLM（可选，服务端需要）**

  ```bash
  export MAX_JOBS=24
  ulimit -v 67108864
  git clone https://github.com/vllm-project/vllm.git
  cd vllm && uv pip install --python "$PY" -e .
  "$PY" -c "import vllm; print(vllm.__version__)"
  ```

---

## 3 官方模型推理

支持单文件、文件夹、图像与视频。预处理走官方 `qwen-vl-utils`（`image_patch_size` / 像素 / 视频抽帧在 `config/default.yaml` 的 `predict:`）。先改 `1-inference.sh` 里权重和路径：

```bash
cd 0-QuickStart
bash 1-inference.sh
```

---

## 4 微调训练

### 4.1 数据集制作

图像目录约定：

```
YOUR_PROJECT/
├── dataset01/
│   └── images/          # [.jpg/.png]
└── dataset02/
    └── images/
```

使用 **`1-annotation-tool/qwen`** 制作图像文本问答对：

```bash
cd 1-annotation-tool/qwen
bash 0-start_tool.sh --port 8080
# 浏览器打开 http://127.0.0.1:8080 ，标签一般放在与 images 同级的 annotations/
```

标注后结构示例：

```
dataset01/
├── images/
└── annotations/         # [.json] 问答对
```

标签 JSON 示例：

```json
[
  {
    "id": 1,
    "image": "images/10095.png",
    "conversations": [
      {"from": "human", "value": "<image>\nIs the value of Favorable 38 in 2015?"},
      {"from": "gpt", "value": "Yes"}
    ]
  }
]
```

### 4.2 检测 / 分割框标注（可选）

桌面工具画矩形、多边形、旋转框，并可走 ONNX / SAM 预标，见 [`1-annotation-tool/anylabel/README.md`](1-annotation-tool/anylabel/README.md)：

```bash
cd 1-annotation-tool/anylabel
bash 0-start.sh
```

### 4.3 Grounding 标注（可选）

检测/分割框 → 目标描述 → caption → 导出 `jsons-GD`，见：

- [`1-annotation-tool/grounding/README.md`](1-annotation-tool/grounding/README.md)
- 独立 GitLab：[grounding-review](http://doc.geoai.com:5002/geoai/ai/grounding-review.git)

### 4.4 生成训练读取文件

```bash
cd data
python create_dataset.py   # 修改脚本内关键路径
```

产物：

- 项目内：`data/0-*.yaml`
- 各数据集目录：`train.jsonl`，以及汇总 `*_train.jsonl`

### 4.5 启动训练

1. 确认 `config/default.yaml`（LoRA、batch、`attn_implementation`、`deepspeed`、`data_flatten` 等）
2. `0-train.sh` 里 `deepspeed` 默认官方 `zero3.json`（MoE 改 `zero2.json`，不需要则留空）
3. 修改并运行：

```bash
cd 0-QuickStart
bash 0-train.sh
```

---

## 5 VLLM 模型服务

将 Qwen3-VL 挂到 GPU，提供 OpenAI 兼容 `/v1` 接口，供标注工具或业务请求调用。

```bash
cd 2-vllm
bash 0-start_server-qwen3.6-35B-A3B.sh   # 修改权重路径、GPU、端口等
bash 1-api_test.sh                       # 发测试请求
```

默认示例端口：`8081`。

---

## 6 相关链接

- 上游官方：[QwenLM/Qwen3-VL](https://github.com/QwenLM/Qwen3-VL)
- 本仓库 GitHub：[Yulin-CC/Qwen3-VL](https://github.com/Yulin-CC/Qwen3-VL)
- Grounding 检验工具 GitLab：[grounding-review](http://doc.geoai.com:5002/geoai/ai/grounding-review.git)
