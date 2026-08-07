用户说，开始做 YOLO 基类数据处理流程，Agent 需要做的事情

1. 与用户确认数据集目录
  a. 总结并与用户确认数据结构是否为 N 个任务子集 (一个文件夹代表一个任务子集) + 1 个任务小合集([collection] 固定、含全部 M 类、充当全类金标小集」)。
  b. 检查 N 个子集是否符合流程规范。符合则继续；不符合则报错，并以表格的形式打印给用户展示，再询问是否继续。
      任务子集流程规范如下：

      (a) 文件命名：图像/标签的文件名须与任务子集(文件夹名)具有相关性，Agent 检查前缀包含任务关键词，如 [烟火] 任务，命名参考为 “YOLO-SmokeFire-<date>-<basename>.<suffix\>”。包含了 "SmokeFire" 的关键词
      (b) 标签体系：标签类别中不得存在中文。
      (c) 文件匹配：图像和标签文件需要绝大部分匹配(文件名前缀一致)，不得存在图像文件和标签文件差异过大的情况。

  c. 检查 1 个任务小合集是否符合流程规范。符合则继续；不符合则报错，并以表格的形式打印给用户展示，再询问是否继续。
      任务小合集流程规范如下：

      (a) 标签体系：标签类别中不得存在中文，且警惕词义相近的类别，如 "qiche" 和 "car"。
      (b) 文件匹配：图像和标签文件需要绝大部分匹配(文件名前缀一致)，stem 对齐率≥95%，不得存在图像文件和标签文件差异过大的情况。

2. 与用户确认工作流：
  a. 提取分析根目录下的 `*基类M.yaml` 或者 `*基类M.txt` 基本类别概述文件，确认 M 个基础类别名, 某一类为 C_i。
  b. 分析 N+1 个子集的全部标签（⭐需要可新建：/home/yulin/1-project/1-PROCESS/tools/check_label.py）。强约束：至少 [collection] 须覆盖全部 M 个基础类别名；N 个任务子集只需登记各自类别（用于构建 pos/neg 表），不要求单个子集含全部 M 类。若 collection 未覆盖全部 M，报错并与用户确认。
  c. 保存数据集的基本信息

    (a) 以表格的形式，保存原始信息 》 | 序号 | N+1 任务子集 | 图像数据量 | 标签数据量 | 全部类别 |
    (b) 以表格的形式，保存类别_数据集信息 》 | 序号 | 类别 C_i(i∈M) | 样本个数(以标签个数为主) | pos 任务子集(含C_i类) | neg 任务子集(不含C_i类) |

  d. 基于 M 个类别，循环构建训练配置，并训练 M 个子模型，操作如下

    (a) 基于 C_i (i∈M) 类别，比对 类别_数据集 表格，获取 pos 任务子集 Tpos，并做训练配置
        如 "car" 类，有 [car] [person_boat_car] 以及 [collection] 三个 Tpos 数据集，则此轮只对这三数据集进行训练数据读取配置
        注：Tpos（含 collection 与其它 pos 子集）训练用标签不得永久破坏源标注，按下列顺序操作：
            - 首轮：若尚无 `labels-cache/`，将当前 `labels/` 完整缓存为 `labels-cache/`
            - 每个 C_i 开训前：从 `labels-cache/` 恢复到 `labels/`，再滤成仅含 C_i（类别 id remap 为 0）后训练
            - M 轮训练全部结束后：从 `labels-cache/` 恢复全量 `labels/`
            - 也可在工作区建训练副本、不改源目录的 `labels/`（二选一，优先不污染源标注）
    (b) 对 Tpos 数据集按照 YOLO 格式规范进行数据整理，具体规范和工具可参考 `.cursor/skills/standard-dataset_merge/SKILL.md`。注：训练读取的标签仅保留 C_i，须遵守上面的 cache→滤→恢复规则。
    (c) 训练配置，工作配置文件在工作路径下 /home/yulin/1-project/2-YOLO/yolo26/4-Agent-automerge，不污染源项目。结构参考如下

          ```markdown
              ├── 4-Agent-automerge/       
              │   ├── 0-QuickStart/             # 快速启动
              │   ├── config-C_i
              │   │   ├── 0-C_i.yaml            # 数据集读取文件
              │   │   └── default-person.yaml   # 训练配置文件
              │   ├── utils/                    # 工具脚本文件，Agent 可在此处生成工具脚本
              │   └── runs/                     # 存放训练 C_i 模型
          ```
      (d) 基于 C_i (i∈M) 类别，训练 Model-C_i

  e. 基于 M 个类别，循环构建推理和预标注配置。Model-C_i 推理全部 Tneg 任务子集

    (a) 基于 Model-C_i 模型，逐个推理 Tneg 任务子集，并把推理标签写入 `labels-pre-C_i` 中，仅保留 conf>0.2 的推理框

        (i) 将 conf > 0.6 ，保留标签
        (ii) 将  conf > 0.2 and conf < 0.6，送入裁图

    (b) 调用裁图工具(可参考 4-Agent-automerge/utils/BoxCrop_cls.py)，用其crop功能，读取伪标签，外扩 2 倍，保存目标截图到 `crops-pre-C_i`
    (c) 调用 qwen 工具 (⭐需要可新建：4-Agent-automerge/utils/qwen_filter.py)，对目标截图逐个读图，并输出 C_i 的得分。vllm 服务可参考 /home/yulin/1-project/0-VLM/z-OpenAI/2-vllm。如判断模型推理的 "car" 的截图是否真的为 "car"，并给出 qwen 的打分。
    (d) 用截图工具 4-Agent-automerge/utils/BoxCrop_cls.py，使用其update功能，更新标签
        
        (i) qwen_conf < 0.3，舍弃：删除 `crops-pre-C_i` 中的图像，并更新`labels-pre-C_i`。
        (ii) qwen_conf >= 0.6，保留: 删除 `crops-pre-C_i` 中的图像，无需更新`labels-pre-C_i`
        (iii) qwen_conf >= 0.3 and qwen_conf < 0.6，将进入人工核查：保留`crops-pre-C_i` 中的图像，并记录每个Tneg中需要人工核查的数量

  f. 数据最后检查，全套工作流程做完，进入人工核查之前，最后的数据结构应如下：

    ```markdown
      ├── T_1/
      │   ├── images/                # 图像[.jpg]/[.png]
      │   ├── pre                    # 多对 labels** 和 crops**
      │   │   ├── labels-pre-C_i/    # ⭐ 本流程产物：推理的伪标签
      │   │   └── crops-pre-C_i/     # ⭐ 本流程产物：目标×2外扩截图
      │   ├── labels                 
      │   ├── trian.txt
      │   └── val.txt
      ├── T_2/
      ├── ...
      ├── T_N/
      └── collection/                # 已人工校验、含全部 M 类、本流程不更新
    ```

3. 最后整理数据集信息，打印或保存



