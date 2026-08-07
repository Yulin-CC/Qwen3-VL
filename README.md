# 🚀 Qwen3-VL 使用指南

本仓库为团队整理的 Qwen3-VL 工作流：环境安装、标注、微调、推理与 vLLM 服务；官方源码在 `Qwen/`，归档资料在 `z-others/`。

---

## 1 项目结构

```
Qwen3-VL/
├── 0-QuickStart/                 # 训练 / 推理入口脚本
│   ├── 0-train.sh
│   └── 1-inference.sh
├── 1-annotation-tool/            # 标注工具
│   ├── qwen/                     # 图像问答对标注（Flask）
│   └── yoloe/                    # Grounding 描述生成与检验
├── 2-vllm/                       # vLLM OpenAI 兼容服务
├── Qwen/                         # 上游官方代码（finetune / utils / eval）
├── config/default.yaml           # 微调默认配置
├── data/                         # 数据集清单与生成脚本
├── train.py                      # 训练入口
├── inference.py                  # 推理入口
└── z-others/                     # 官方 README、依赖、Demo 等归档
    ├── requirements.txt
    └── README.md                 # 上游原始说明
```

---

## 2 环境搭建

- **创建并激活虚拟环境**

  ```bash
  conda create -n qwen python=3.12
  conda activate qwen
  ```

- **安装 torch**

  ```bash
  pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu128
  ```

- **安装 flash-attn（可选，需外网）**：可先跳过，但须在 `config/default.yaml` 将 `data_flatten` 设为 `false`

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

---

## 3 官方模型推理

支持单文件、文件夹、图像与视频（先改脚本内权重/路径）：

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

### 4.2 Grounding 标注（可选）

检测/分割框 → 目标描述 → caption → 导出 `jsons-GD`，见：

- [`1-annotation-tool/yoloe/README.md`](1-annotation-tool/yoloe/README.md)
- 独立 GitLab：[grounding-review](http://doc.geoai.com:5002/geoai/ai/grounding-review.git)

### 4.3 生成训练读取文件

```bash
cd data
python create_dataset.py   # 修改脚本内关键路径
```

产物：

- 项目内：`data/0-*.yaml`
- 各数据集目录：`train.jsonl`，以及汇总 `*_train.jsonl`

### 4.4 启动训练

1. 确认 `config/default.yaml`（LoRA、batch、`data_flatten` 等）
2. 修改并运行：

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
