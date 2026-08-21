
1. 目标格式

    a. 数据结构
        ```
        ├── path/to/dataset       # 数据集路径
        │   ├── images            # 图像文件夹 [.jpg/.png]
        │   ├── jsons-GD          # 标签文件夹-grounding [.json] ⭐新grounding标签
        │   ├── jsons             # 标签文件夹-检测 [.json]
        │   └── labels            # 标签文件夹-分割 [.txt]
        ```
    b. jsons-GD 的文件格式参考 `/home/yulin/0-data/2-DroneObject/grounding_sample/samples_Flickr30k/jsons` 中的标签文件

- 可以以 `/home/yulin/0-data/2-DroneObject/grounding_sample/rm` 为例做试验

2. 标签描述生成

    a. 对每张图的单个目标进行 1.5x 扩展 crop 并保存，可以参考 `1-annotation-tool/yoloe/tools/JsonCrop_cls.py`，但命名需要附上其类别名字
    b. 使用本地部署的 8081 的 vllm 服务端口的 qwen 多模态模型，对每张图像进行简单描述(需要关注其类别)，须至少三个描述及以上

        (a) 属性描述：如类别为 "person"，则做 "student", "boy", "child", "girl", "man", "woman" 等描述
        (b) 外观描述：如类别为 "person"，则做 "person in white jecket and blue jeans", "person wear a helmet"；如类别为 "car"，则做 "blue car", "black car" 等等
        (c) 行为描述：如类别为 "person"，则做 "person Squatting", "person swimming", "person running" 等；
    注：需要有个额外的规则文档，可以给 qwen 读取，也方便后续扩增更多场景，保持文档简洁清晰。

    c. 保存每个 crop 目标的描述（可以写个文档）

3. caption 生成，随机挑选 3-10 个相邻目标 (没有可适当减少)，组成一句话，如

    a. "A `girl in white jecket and blue jeans` is walking pass by a `black truck` and `orange car`"
    b. "A busy street intersection where multiple `scooter riders` and two vehicles—a `blue truck` and a `silver van—are` stopped at or near a crosswalk, with some riders carrying passengers or cargo."
    c. "A street corner beside a canal, where a `man in a red jacket` stands on the sidewalk near two food carts; meanwhile, two electric scooters cross the pedestrian crossing — one `rider wears no helmet` and carries a `child passenger`, while the other `rider wears a red helmet` and also carries a `child`."
    注：最少需要 5 条及以上 captions

4. 人工检查界面，需要仿照 `1-annotation-tool/qwen` 做一个界面端，供人工检查 qwen 生成的

    a. 目标描述是否正确（需要翻译成中文，后台以及标签保持英文就行）
    b. caption 是否合理（需要翻译成中文，后台以及标签保持英文就行）

5. 最终需要一个 `jsons-GD` 文件夹

    






