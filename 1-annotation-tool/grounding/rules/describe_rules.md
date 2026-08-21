# 📖 目标描述短语规则（用于 grounding）

- **概述**: **通用性试验性的规则**，没有特殊的项目特点，只是为了验证多模态数据的生成流程和训练有效性。
- **日期**: 2026-08-14

---

## 1 目标描述-规则要求

### 1.1 通用要求

|要求|说明|
|---|---|
|目标描述|为单个裁剪目标生成简短的英文描述性短语|
|类别锁定|**给定 class label 为真值**；每条短语必须描述该类物体，不得改写成其它类别|
|短语特性|可在「同类家族」内写子类/属性（car→sedan/SUV/taxi），但主名词类别不得漂移|
|短语形式|短名词短语（2–8 个英文词），不要完整句子|
|描述语言|短语正文仅用英文|
|视觉依据|优先具体可见线索；看不清的文字/logo 不要编造；**外观再像也不能推翻 label**|
|禁止内容|不要提及裁剪边框、绿色框或标注痕迹|

### 1.2 专用要求

|要求|说明|
|---|---|
|标签优先|先认 label，再看图补颜色/状态/子类；禁止「按图猜成另一类」|
|粘连标签|`specialvehicle` / `hard_hat` 等按语义拆读（special vehicle、hard hat），短语围绕该语义|
|禁止串类|车辆类尤易错：car 禁止写成 motorcycle/bike/scooter；motorcycle 禁止写成 car；truck≠car；specialvehicle 按特种/工程/作业车辆写，禁止写成私家车或摩托车|
|外观轴|颜色、服装/配饰、车身涂装、反光/高亮部位、明显图案或装备外形；多条短语尽量换不同外观侧面，避免近重复|
|弱化项|纯角色词（worker/student）或纯动作（walking/parked）可作少数补充，**不宜占满全部短语**|
|推荐落地|短语中宜出现与 label 同族的中心词，并尽量带外观修饰（red sedan；person in yellow vest）|
|条数上限|每个目标最多 **8** 条候选短语；不足时按实有条数即可，勿注水|
|同组维度|同一 phrases 列表内应拉开维度（如 `helmet` / `shirt` / `standing`），勿堆同义侧面|
|近义禁止|同组候选禁止重复：①仅改介词/分词（~~person in red helmet~~ ≈ ~~person wearing red helmet~~）；②同义名词（~~helmet~~ ≈ ~~hard hat~~）。审阅侧：未选的精确他用隐藏；已选他用虚线提示点灭（近义他用后续）|
|刷新换维|点刷新时读取已有/已锁短语并去重；**已锁特征维不得换皮**（已选 `red sedan` → 禁止 `red car` / `red private car`）。应改用其余可见维：`parked car`、`car with sunroof`、其它子类等|

## 2 目标描述-具体规则

### 2.1 规则一：通用性规则

|类型|说明|示例|
|---|---|---|
|属性|子类/角色等，须留在 label 同类内|person → student, worker；car → sedan, taxi, SUV；specialvehicle → special vehicle, utility truck|
|外观|颜色、服装、配饰、车身涂装等|person in white jacket；green car；yellow special vehicle|
|动作/状态|可见姿态或行为；看不清则用平稳状态|person walking；car parked；special vehicle moving|
|方位|可见所在位置或场景关系|car on the road；boat on the river|
|部分特征|局部可见物、手持物或配件|person holding a phone；car with sunroof|

## 3 目标描述-描述生成风格

|要求|说明|
|---|---|
|多样性|各短语彼此有区分；同组优先换属性轴（外观/动作/方位等），不要同内容换皮或同义堆叠。刷新已选时换维，不要在已锁颜色/配件上打转|
|适用场景|偏普适认知的描述，避免特殊行业或生僻用语|
|冲突处理|图与 label 冲突时**以 label 为准**；只补该类下可见的颜色/状态，不改换物体种类|
|串类反例|即使裁剪看起来像其它类也禁止改写。例：label=`car` → ~~green motorcycle~~ / ~~scooter~~；label=`specialvehicle` → ~~private car~~ / ~~motorbike~~|
|描述组合|优先从属性/外观/方位/部分特征中取 **1–2 维**组合（如 `red car`；`car on the road`；`car with sunroof`）；避免三元以上堆叠（如 ~~red car on the road with sunroof~~）|
|近义反例|重复：~~person in red helmet~~ + ~~person wearing red helmet~~；~~yellow helmet~~ + ~~yellow hard hat~~。宜换维度，如已用 helmet → 再给 `person in yellow vest` / `person standing`，不要再给 hard hat。刷新：已锁 `red sedan` → ~~red car~~ / ~~red private car~~；宜 `parked car` / `car with sunroof`|

## 4 输出格式（暂时不需要改动）

只返回 JSON：

```json
{"phrases": ["...", "...", "..."]}
```
