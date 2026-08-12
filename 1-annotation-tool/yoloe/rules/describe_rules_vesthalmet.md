# 📖 目标描述短语规则（工地 person · 安全帽 / 反光衣）

- **概述**: **工地人员 PPE 专用规则**。面向 `person` 类目标，重点描述是否佩戴安全帽、是否穿着反光衣/背心，以及可见的工地相关外观与动作；用于验证该类 grounding 数据生成。
- **日期**: 2026-08-11

---

## 1 目标描述-规则要求

### 1.1 通用要求

|要求|说明|
|---|---|
|目标描述|为单个裁剪目标生成简短的英文描述性短语|
|类别锁定|**给定 class label 为真值**（多为 person）；短语必须描述该类，不得改写成车辆/其它物体|
|短语特性|可在同类内写角色/PPE/动作，主名词类别不得漂移|
|短语形式|短名词短语（2–8 个英文词），不要完整句子|
|描述语言|短语正文仅用英文|
|视觉依据|优先具体可见线索；看不清的帽徽/logo/文字不要编造；帽/背心是否穿戴以可见证据为准，不确定则用中性短语；**外观不能推翻 label**|
|禁止内容|不要提及裁剪边框、绿色框或标注痕迹|

### 1.2 专用要求

|要求|说明|
|---|---|
|标签优先|先认 label，再补 PPE/颜色/动作；禁止串成其它类别|
|场景焦点|工地 / 施工区域人员；短语应能体现 PPE 或工地角色（worker、construction worker 等）|
|安全帽|可见时区分 wearing hard hat / helmet 与 without hard hat / no helmet；可带颜色（yellow/white/red hard hat）|
|反光衣|可见时区分 in reflective vest / orange vest / safety vest 与 without reflective vest / no safety vest|
|短语覆盖|同一目标宜产出多条互补短语：至少覆盖「帽相关」与「背心相关」中可见的一项，并辅以角色/动作|
|用词偏好|hard hat、helmet、reflective vest、safety vest、orange vest、hi-vis vest；避免生僻缩写堆砌|

## 2 目标描述-具体规则

### 2.1 规则一：工地 person / PPE

|类型|说明|示例|
|---|---|---|
|属性/角色|工地角色或性别感|worker；construction worker；male worker；woman worker|
|安全帽|佩戴 / 未佩戴；可加颜色|worker with yellow hard hat；person wearing white helmet；worker without hard hat；person with no helmet|
|反光衣|穿着 / 未穿；可加颜色|worker in orange reflective vest；person in yellow safety vest；worker without reflective vest；person not wearing safety vest|
|外观组合|帽 + 背心等同框可见时组合|worker in orange vest with hard hat；person wearing yellow helmet and reflective vest|
|动作/状态|可见姿态或行为|worker walking；person standing；worker bending；person holding a tool|

## 3 目标描述-描述生成风格

|要求|说明|
|---|---|
|多样性|各短语彼此有区分：勿多条几乎同义（如仅 hard hat / helmet 换词重复）|
|适用场景|工地 PPE 场景；优先帽/背心/角色/动作，少写与安监无关的空泛外貌|
|不确定|帽或背心被遮挡、过小看不清时，不要猜测有无；改写可见的其他线索或中性 worker/person|

## 4 输出格式（暂时不需要改动）

只返回 JSON：

```json
{"phrases": ["...", "...", "..."]}
```
