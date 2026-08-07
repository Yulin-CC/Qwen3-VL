
# 📦 数据集整理规范

  - **概述**: 当用户要求**整理数据集**、**规范化数据集**、**做数据集合并/转换**时，按本 Skill 执行：确认路径与规范类型 → 检查合规性 → 调用工具补齐 → 最终校验并报告。
  - **日期**: 2026-07-30

---

## 0 执行前检查

  - **触发场景**：「帮我做一下数据集整理」「整理成 YOLO/Grounding/CD 规范」等。
  - **目标**：将目标数据集整理到可用于 **[训练]** 或 **[发布]** 的程度。
  - **原则**：已合规则跳过；不合规则最小改动补齐；关键字段符合即可，不要求逐字节一致；**合规检查由 Agent 按 §4.x.2 检查流程执行**，不依赖独立校验脚本。

---

## 1 执行步骤

  **(1)** 确认数据集路径；用户未提供则询问。

  **(2)** 分析路径下文件结构，判断单个或批量处理。

  **(3)** 向用户确认目标规范：

  - **a** YOLO → [4.1 规范-YOLO 数据集]
  - **b** Grounding → [4.2 规范-Grounding 数据集]
  - **c** CD（变化检测）→ [4.3 规范-CD 数据集]

  **(4)** 检查是否已符合目标规范：

  - **a** 查找工具目录：默认 `/home/yulin/1-project/1-PROCESS`；不存在或功能不足时询问用户工具路径。
  - **b** 调用 [3 工具索引] 中对应脚本逐一调整，后台监督执行。
  - **c** 完成后由 Agent 按对应规范的 **检查流程**（§4.1.2 / §4.2.2 / §4.3.2）做最终核对，向用户报告并打印数据集统计（文件数、train/val 划分等）。

---

## 2 通用约束

  - 各数据子目录下应为**平铺文件**，无二级目录；如有 `train/`、`val/` 等，分析后将文件拢到上级并删除空目录。
  - 标注软件产物（`annotations/`、`jsons/`、`json/`）仅作中间格式，合规后可保留，不作为最终训练必需项（除非规范另有说明）。
  - 格式不合但关键字段可识别时，先尝试已有工具；无法转换时再分析结构并考虑新建工具。

---

## 3 工具索引

  | 规范 | 工具路径（相对 `1-PROCESS/`） | 用途 |
  |------|----------|------|
  | YOLO | `utils/convert_json2txt.py` | Labelme JSON → `labels/`（`detect` / `segment`） |
  | YOLO | `utils/convert_txt2json.py` | YOLO txt → LabelMe `jsons-segm/` / `jsons-detect/`（`detect` / `segment`） |
  | YOLO | `utils/merge_jsons_det_segm.py` | `jsons-det` + `jsons-segm` → `jsons/`（同时保留 rectangle 与 polygon） |
  | YOLO | `utils/convert_xml2txt.py` | VOC XML → `labels/` |
  | YOLO | `utils/convert_labelme2coco.py` | LabelMe → **多类** COCO bbox JSON（供 SAM / `convert_coco2txt`） |
  | YOLO | `utils/convert_coco2txt.py` | COCO instances JSON → `labels/`（`detect` / `segment`） |
  | YOLO | `tools/yolo_dataset_division.py` | 生成 `train.txt` / `val.txt` |
  | Grounding | `utils/convert_json2coco.py` | jsons/ → `xxx_train_segm.json` |
  | Grounding | `utils/convert_geoai2coco.py` | jsons/ → `xxx_train_segm.json`（rectangle 仅 bbox；需 `description_en`） |
  | YOLO / Grounding | `tools/generate_sam_masks.py` | 对 COCO JSON 中的 **bbox** 补 `segmentation`，输出 `*_segm.json` |
  | Grounding | `tools/grounding_generate_cache.py` | 由 `*_segm.json` 生成 `xxx_train_segm.cache` |
  | CD | `utils/convert_json2mask.py` | json/ → label/ mask |
  | CD | `tools/cd_dataset_division.py` | 生成 `train.txt` / `val.txt` |

  - **注意**：执行前确认 `classes.yaml`（YOLO）等依赖文件是否存在；多子目录/多年份共用**同一份** `names` 顺序，保证 class id 一致。
  - **注意**：`generate_sam_masks.py` 输入是带 **bbox** 的 COCO JSON（`--json-path`）+ `images/`（`--img-path`），**不是** `.cache`。默认权重优先 `yoloe-main/weights/sam2.1_hiera_large.pt`，可用 `--checkpoint` 覆盖；默认 `--gpus 0,1,2,3`。密框图请加 **`--batch`**（单图框很多时按块推理，降低显存峰值）。调用前确认 **sam2** 环境可用。
  - **注意**：`tools/grounding_generate_cache.py` **唯一依赖 ultralytics**；调用前须询问用户 **yoloe 环境是否已装好**，确认后在 yoloe 环境中执行：

    ```bash
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate yoloe
    python /home/yulin/1-project/1-PROCESS/tools/grounding_generate_cache.py \
      --json-path /path/to/xxx_train_segm.json \
      --img-path /path/to/images
    ```

    可用 `conda run -n yoloe python -c "import ultralytics"` 快速验证环境；未安装则提示用户先配置 yoloe，**不得**用系统 Python 强行运行。

---

## 4 数据集规范

### 4.1 规范-YOLO 数据集

#### 4.1.1 文件夹结构

  ⭐ 为必须存在的项。

  ```markdown
  ├── dataset
  │   ├── annotations/       # 标签[.xml]
  │   │   ├── `xxx.xml`
  │   │   └── ...
  │   ├── images/            # ⭐ 图像[.jpg]/[.png]
  │   │   ├── `xxx.jpg`
  │   │   └── ...
  │   ├── jsons/             # 标签[.json] 标注软件产生
  │   │   ├── `xxx.json`
  │   │   └── ...
  │   ├── labels/            # ⭐ 标签[.txt]
  │   │   ├── `xxx.txt`
  │   │   └── ...
  │   ├── `train.txt`        # ⭐ 训练读取文件
  │   └── `val.txt`          # ⭐ 验证读取文件
  ```

#### 4.1.2 检查流程

  - 向用户确认任务类型：`detect` | `segment`。
  - 最小合规：`images/`、`labels/`、`train.txt`、`val.txt`。
    - 无 `images/` → 报错 ❌
    - 缺 `labels/` 或划分文件 → 调用工具生成
  - 有 `annotations/` 或 `jsons/` → 检查关键字段，符合则转换生成 `labels/`。
      - **a** `detect`：`rectangle` / bbox → `convert_json2txt.py --task detect`（或 XML / COCO 对应工具）。
      - **b** `segment` 且源为 **polygon** → `convert_json2txt.py --task segment`（或 `convert_coco2txt.py --task segment`）。
      - **c** `segment` 但源仅有 **rectangle / bbox**（无 polygon）→ **可选**走 SAM 补分割后再转 YOLO txt：
        - **(a)** `convert_labelme2coco.py` + 共用 `classes.yaml` → 多类 `*_bbox.json`（保留真实 categories）
        - **(b)** 确认 sam2 可用后：`generate_sam_masks.py --gpus 0,1,2,3 --batch` → `*_bbox_segm.json`
        - **(c)** `convert_coco2txt.py --task segment` → `labels/`（SAM 过滤掉的实例可丢弃；无有效 mask 的图可无 txt，划分时只收成对样本）
        - **(d)** 若用户明确接受「框当 4 点伪 mask」、不跑 SAM，再另议；默认优先询问是否用 SAM
        - **(e)** 多年份/子目录先逐年整理，合并放到第二阶段；合并前 class id 必须一致
  - 最终检查：
    - `images/` 与 `labels/` 的 **数量** 和 **basename** 一致
    - `train.txt` / `val.txt` 中路径均有对应图像和标签
    - 可选：规范命名 `Train-[project_name]-[date]-xxxxx`
  - 通过 → ✅

#### 4.1.3 数据结构示例

  - **images/**：图像为 `.jpg` / `.png`；不合规则统一转 `.jpg`。

  - **annotations/xxx.xml**

    ```xml
    <annotation>
    <folder>DATA</folder>
    <filename>Train-Fall_elevator01-2509-0009.jpg</filename>
    <size>
       <width>1920</width>
       <height>1080</height>
       <depth>3</depth>
    </size>
    <object>
       <name>fall</name>
       <bndbox>
          <xmin>700</xmin><ymin>402</ymin>
          <xmax>898</xmax><ymax>744</ymax>
       </bndbox>
    </object>
    </annotation>
    ```

  - **jsons/xxx.json**（Labelme）

    ```json
    {
      "version": "0.1.4",
      "shapes": [
        {
          "label": "person",
          "points": [[112.0, 73.0], [175.0, 73.0], [175.0, 187.0], [112.0, 187.0]],
          "shape_type": "rectangle"
        },
        {
          "label": "person",
          "points": [[124.0, 73.0], [121.0, 75.0], ...],
          "shape_type": "polygon"
        }
      ],
      "imagePath": "..\\images\\Public_VOC_0016.jpg",
      "imageHeight": 333,
      "imageWidth": 500
    }
    ```

  - **labels/xxx.txt**

    ```markdown
    # detect
    25 0.475759 0.414523 0.951518 0.672422

    # segment
    0 0.381688 0.589417 0.341203 0.585667 0.316719 0.581896 ...
    ```

  - **train.txt | val.txt**

    ```markdown
    ./images/000000182611.jpg
    ./images/000000182612.jpg
    ...
    ```

---

### 4.2 规范-Grounding 数据集

#### 4.2.1 文件夹结构

  ```markdown
  ├── dataset
  │   ├── images/                  # ⭐ 图像[.jpg]/[.png]
  │   │   ├── `xxx.jpg`
  │   │   └── ...
  │   ├── jsons/                   # 标签[.json] 标注软件产生
  │   │   ├── `xxx.json`
  │   │   └── ...
  │   ├── `xxx_train_segm.json`    # ⭐ 合并 COCO Grounding 标注
  │   └── `xxx_train_segm.cache`   # ⭐ 训练缓存
  ```

#### 4.2.2 检查流程

  - 向用户确认任务类型：`detect` | `segment`。
  - 最小合规：`images/`、`xxx_train_segm.json`、
  `xxx_train_segm.cache`。

    - 无 `images/` → 报错 ❌
    - 缺合并 JSON 或 cache → 调用工具生成

  - 有 `jsons/` → 检查 Grounding 关键字段，符合则调用合适的转换工具合并生成大 JSON 及 cache。
      - **a** `*_segm.json`：先确认 `jsons/` 为 polygon | rectangle。已有 polygon 可直接合并；仅有 bbox/`rectangle` 时，先合并出带 bbox 的 COCO JSON，再调用 `generate_sam_masks.py`（见 [3 工具索引]）补 `segmentation`（输入为该 JSON，**非** `.cache`；事先确认 sam2 可用）。
      - **b** `.cache`：基于已含 `segmentation` 的 `*_segm.json` 运行 `grounding_generate_cache.py`（见 [3 工具索引]），生成 `.cache`（事先确认 yoloe 可用）。
  - 最终检查：
    - `images/` 与 `jsons/` 的 **数量** 和 **basename** 一致（如有 jsons/）
    - `xxx_train_segm.json` 中 `images[].file_name` 对应 `images/` 实际文件
  - 通过 → ✅

#### 4.2.3 数据结构示例

  - **images/**：图像为 `.jpg` / `.png`；不合规则统一转 `.jpg`。

  - **`xxx_train_segm.json`**

    ```json
    {
      "info": [],
      "licenses": [],
      "categories": [{"id": 1, "name": "object", "supercategory": "object"}],
      "images": [
        {
          "id": 0,
          "file_name": "3359636318.jpg",
          "height": "334",
          "width": "500",
          "original_img_id": 3359636318,
          "sentence_id": 0,
          "caption": "Two people are talking outside of the video game shop ...",
          "tokens_negative": [[0, 91]],
          "tokens_positive_eval": [[[0, 10]], [[34, 53]], ...],
          "dataset_name": "flickr"
        }
      ],
      "annotations": [
        {
          "id": 0,
          "image_id": 0,
          "category_id": 1,
          "bbox": [144.0, 166.0, 64.0, 168.0],
          "segmentation": [[163.0, 168.0, ...]],
          "tokens_positive": [[0, 10]],
          "iscrowd": 0,
          "area": 10752.0
        }
      ]
    }
    ```

  - **jsons/xxx.json**（按物理图拆分，每图多条 caption）

    ```json
    {
      "info": [],
      "categories": [{"id": 1, "name": "object", "supercategory": "object"}],
      "images": [
        {
          "id": 0,
          "file_name": "1000092795.jpg",
          "height": "500",
          "width": "333",
          "original_img_id": 1000092795,
          "sentence_id": 0,
          "caption": "Two young guys with shaggy hair look at their hands ...",
          "tokens_negative": [[0, 83]],
          "tokens_positive_eval": [[[0, 14]], [[20, 31]], ...],
          "dataset_name": "flickr"
        }
      ],
      "annotations": [
        {
          "id": 0,
          "image_id": 0,
          "category_id": 1,
          "bbox": [180.0, 125.0, 26.0, 31.0],
          "segmentation": [[192.0, 124.0, ...]],
          "tokens_positive": [[20, 31]],
          "iscrowd": 0,
          "area": 806.0
        }
      ]
    }
    ```

  - **注意**：`images[].id` 按 caption 条目编号（如 Flickr 每图 5 句 → 5 条 image 记录）。

---

### 4.3 规范-CD 数据集

#### 4.3.1 文件夹结构

  ```markdown
  ├── dataset
  │   ├── A/                   # ⭐ 时相 A 图像[.jpg]/[.png]
  │   │   ├── `xxx.jpg`
  │   │   └── ...
  │   ├── B/                   # ⭐ 时相 B 图像[.jpg]/[.png]
  │   │   ├── `xxx.jpg`
  │   │   └── ...
  │   ├── label/               # ⭐ 变化 mask[.png]
  │   │   ├── `xxx.png`
  │   │   └── ...
  │   ├── json/                # 标签[.json] 标注软件产生
  │   │   ├── `xxx.json`
  │   │   └── ...
  │   ├── `train.txt`          # ⭐ 训练读取文件
  │   └── `val.txt`            # ⭐ 验证读取文件
  ```

#### 4.3.2 检查流程

  - 最小合规：`A/`、`B/`、`label/`、`train.txt`、`val.txt`。
    - 无 `A/` 或 `B/` → 报错 ❌
    - 缺 `label/` 或划分文件 → 调用工具生成
  - 有 `json/` → 检查 CD 关键字段，符合则转换生成 `label/` mask。
  - 最终检查：
    - `A/`、`B/`、`label/` 的 **basename** 一致（label 扩展名为 `.png`）
    - `train.txt` / `val.txt` 中文件名在 `A/`、`B/`、`label/` 均有对应文件
  - 通过 → ✅

#### 4.3.3 数据结构示例

  - **A/ | B/**：图像为 `.jpg` / `.png`；同名文件为一对时相图。

  - **label/xxx.png**：二值 mask，灰度图，`0`=背景，`255`=变化区域。

  - **json/xxx.json**（Labelme + CD 扩展字段）

    ```json
    {
      "version": "0.1.4",
      "shapes": [
        {
          "label": "change",
          "points": [[201.0, 717.0], [204.0, 725.0], ...],
          "shape_type": "polygon"
        }
      ],
      "imagePath": "Train-baijiachi_vis-260617-0002.jpg",
      "imageHeight": 1024,
      "imageWidth": 1024,
      "change_detection": true,
      "imagePathA": "Train-baijiachi_vis-260617-0002.jpg",
      "imagePathB": "Train-baijiachi_vis-260617-0002.jpg",
      "maskPath": "Train-baijiachi_vis-260617-0002.png"
    }
    ```

  - **train.txt | val.txt**

    ```markdown
    Train-baijiachi_vis-260617-0002.jpg
    Train-baijiachi_vis-260617-0003.jpg
    ...
    ```
