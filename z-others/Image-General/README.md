# 🎨 Qwen-Image-2.1 使用指南

基于 **SGLang Diffusion** 部署 Qwen-Image-2.1，提供文生图与图像编辑服务。接口是 OpenAI Images API，**不是** `/v1/chat/completions`。

---

## 1 环境搭建

### 1.1 前提

- Linux + NVIDIA GPU（当前环境为 2 × A800 80GB）
- Docker Engine + NVIDIA Container Toolkit
- 模型权重放在 `/home/ubuntu/qwen/Qwen-Image-2.1`

### 1.2 拉取镜像

直连 Docker Hub 可能超时，建议走 DaoCloud：

```bash
docker pull docker.m.daocloud.io/lmsysorg/sglang:latest
docker tag docker.m.daocloud.io/lmsysorg/sglang:latest lmsysorg/sglang:latest
docker rmi docker.m.daocloud.io/lmsysorg/sglang:latest
docker images
```

镜像约 **15GB**（展开后约 53GB），请预留足够磁盘。

### 1.3 创建容器

```bash
docker run -d \
  --name sglang \
  --gpus all \
  --shm-size 32g \
  --ipc=host \
  --network=host \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  -v /home/ubuntu:/home/ubuntu \
  -w /home/ubuntu \
  lmsysorg/sglang:latest \
  sleep infinity
```

进入容器：

```bash
docker exec -it sglang bash
```

---

## 2 启动服务

宿主机一键启动（容器不存在会自动创建）：

```bash
bash /home/ubuntu/qwen/0-Quickstart/0-start_server-qwen-image-2.1.sh
```

或在容器内手动启动：

```bash
sglang serve \
  --model-path /home/ubuntu/qwen/Qwen-Image-2.1 \
  --model-id Qwen-Image-2.1 \
  --served-model-name Qwen-Image-2.1 \
  --performance-mode speed \
  --num-gpus 2 \
  --tp-size 2 \
  --host 0.0.0.0 \
  --port 30000 \
  --strict-ports
```

GPU、端口、权重路径可在脚本顶部修改。日志默认写到 `0-Quickstart/sglang_30000.log`。

检查是否就绪：

```bash
curl http://127.0.0.1:30000/liveness
curl http://127.0.0.1:30000/v1/models
```

- API：`http://127.0.0.1:30000`
- 文档：`http://127.0.0.1:30000/docs`

首次请求可能较慢（warmup）。

---

## 3 调用模型

Qwen-Image-2.1 是 **文生图 / 修图** 模型，不要用普通 Qwen 的 Chat Completions。

| 能力     | 接口                     | 说明                         |
| -------- | ------------------------ | ---------------------------- |
| 文生图   | `POST /v1/images/generations` | JSON，`prompt` 必填      |
| 图像编辑 | `POST /v1/images/edits`       | `multipart/form-data` 上传原图 |
| 模型列表 | `GET /v1/models`              | 确认服务名 `Qwen-Image-2.1` |

常用字段：

- **prompt**：文本描述
- **model**：`Qwen-Image-2.1`
- **size**：如 `1024x1024`（宽高需为 32 的倍数）
- **n**：生成张数，默认 1
- **seed**：随机种子
- **num_inference_steps**：去噪步数，默认约 40
- **response_format**：`url` 或 `b64_json`
- **background**：`auto` / `transparent`（透明背景需在 prompt 里说明 RGBA）

---

## 4 使用示例

### 4.1 文生图（curl）

```bash
curl http://127.0.0.1:30000/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen-Image-2.1",
    "prompt": "一只水豚在烛光下看书",
    "size": "1024x1024",
    "n": 1,
    "seed": 42,
    "response_format": "b64_json"
  }' > response.json
```

把返回的 base64 存成图片：

```bash
python3 - <<'PY'
import base64, json
from pathlib import Path
data = json.loads(Path("response.json").read_text())["data"]
for i, item in enumerate(data):
    Path(f"output-{i}.png").write_bytes(base64.b64decode(item["b64_json"]))
PY
```

### 4.2 文生图（Python）

```python
import base64
from pathlib import Path
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:30000/v1", api_key="EMPTY")
resp = client.images.generate(
    model="Qwen-Image-2.1",
    prompt="霓虹店招写着 QWEN IMAGE 2.1，雨夜，路面反光",
    size="1024x1024",
    response_format="b64_json",
)
Path("t2i.png").write_bytes(base64.b64decode(resp.data[0].b64_json))
```

### 4.3 图像编辑

```bash
curl http://127.0.0.1:30000/v1/images/edits \
  -F "model=Qwen-Image-2.1" \
  -F "prompt=把背景改成日落海滩" \
  -F "image=@input.png" \
  -F "response_format=b64_json"
```

### 4.4 透明背景（RGBA）

```bash
curl http://127.0.0.1:30000/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen-Image-2.1",
    "prompt": "This is an RGBA image with transparency. A cute cartoon dragon sticker. The image has alpha channel and the background is transparent.",
    "size": "1024x1024",
    "background": "transparent",
    "response_format": "b64_json"
  }'
```

---

## 5 目录结构

```
qwen/
├── 0-Quickstart/                            # 启动脚本
│   └── 0-start_server-qwen-image-2.1.sh     # 一键启动服务
├── Qwen-Image-2.1/                          # 模型权重
│   ├── model_index.json
│   ├── processor/
│   ├── text_encoder/
│   ├── transformer/
│   ├── vae/
│   └── scheduler/
└── README.md
```
