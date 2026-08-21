# 📖 目标描述短语规则（外观 + 穷尽检查）

- **概述**: 只对目标**外观**做 1–3 条描述性短语，并结合图内同类标签做穷尽补查。
- **日期**: 2026-08-20

---

## 1 目标描述-规则要求

### 1.1 通用要求

|要求|说明|
|---|---|
|目标描述|为单个裁剪目标生成简短英文外观短语|
|类别锁定|给定 class label 为真值；每条短语必须带上该类中心词|
|禁止源标签|禁止单独输出 `car` / `person` 等源标签，必须与外观组合|
|短语条数|每个目标 **1–3** 条，不足不注水|
|短语形式|短名词短语（2–8 个英文词），不要完整句子|
|描述语言|短语正文仅用英文|
|禁止内容|不要提及裁剪边框、绿色框或标注痕迹|

### 1.2 外观原则（只写外观）

|要求|说明|
|---|---|
|允许|颜色、服装、配饰、车身涂装、口罩、可见表面材质|
|禁止|属性/子类（sedan / SUV / student）、方位（on the left / in the background）、动作姿态（walking / parked）|

### 1.3 结合基础类别

|类别|做法|正例|反例|
|---|---|---|---|
|car 等车辆|颜色 + 类别中心词|white car, black car, gray car|white sedan, black SUV, car|
|person|可略丰富：穿着/可见配饰|person wearing black jacket, person wearing blue jeans, person wearing mask|person, walking person, person on the left|

## 2 穷尽原则

每张图全部目标描述完成后：

1. 统计该图**同类**全部描述短语，作为候选池
2. 对每个目标，取出它还没有的同类短语
3. 用裁剪图再问模型：这些剩余短语是否也适用于该目标
4. 命中则补上，总数仍不超过 3 条

示例：图中已有 `person wearing black jacket` / `person wearing red shirt` / `person wearing blue jeans` / `person wearing mask`

- 目标 A 已有 mask + red shirt → 检查其余两条，不符合则过
- 目标 B 已有 black jacket + blue jeans → 若也符合 mask，则补上（此时 3 条）

## 3 输出格式

只返回 JSON：

```json
{"phrases": ["white car", "black car"]}
```
