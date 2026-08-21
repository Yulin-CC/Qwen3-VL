# 📖 Caption 组合规则（用于 grounding）

- **概述**: 将**若干已选定的目标短语**组合成一条自然的英文 caption。短语本身由人工或上游 describe 选定——本规则**只改句式，不改短语**。
- **日期**: 2026-08-14

---

## 1 Caption-核心原则（刷新 / 重组时）

|要求|说明|
|---|---|
|短语锁定|输入列表中的每条 phrase **必须原样出现**在 caption 中（拼写、空格、连字符一致）|
|禁止替换|不得把短语改写成同类词（如 `red sedan` → `car` / `vehicle`）|
|禁止增删|不得省略任一给定短语；也不得额外塞入未给定的目标指称|
|禁止内容|不要提及标注框、crop、polygon、json、dataset、model|
|短语权重|信息密度优先于华丽修辞|
|短语指代|以给定短语本身做主语/宾语，少用 they/it 把短语消掉|
|句式可变|允许调整语序、介词、连接词、从句结构，使句子通顺自然|
|句式语言|caption 正文仅用英文|
|实体一致|输入会按 `obj_id` 标注短语所属目标：**同一 obj_id 的多条短语 = 同一实体的不同说法**，绝不能写成两个人/两个物体|
|实体分立|**不同 obj_id = 不同实体**，绝不能写成「A 也是 B / A is B / A who is also B」把两个目标合并成一个|


## 2 Caption-风格

|要求|说明|
|---|---|
|场景描述|俯视/航拍场景可用 in the scene/ on the road/nearby 等，但不要空泛堆砌|
|目标组合|不同 `obj_id` 才是不同目标，可用 near / beside / next to / and / with 等**并列或空间关系**把它们分开写|
|禁止等同（跨目标）|对不同 `obj_id` **禁止**：is / is a / is also / who is also / known as / aka / the same as 等把 phrase_A 说成 phrase_B|
|同目标多短语|同一 `obj_id` 的多条短语必须合成**一个**主体：用同位、并列属性、with/holding/wearing、关系从句等；**禁止** near / beside / next to / stands near 把它们拆成多人|
|句式规范|一条 caption 可含多句完整英文；全部给定短语必须用上，句间逻辑通顺即可|


## 3 Caption-输入示例

### 3.1 示例1（单句 · 不同目标）

给定短语：

- [obj 0] white pickup truck
- [obj 1] worker in orange vest
- [obj 2] traffic cone

**可接受**：
> A white pickup truck is parked near a worker in orange vest beside a traffic cone.

**不可接受**：
> A truck and a person stand by a cone. ← 短语被改写/省略
> A white pickup truck is also a worker in orange vest. ← 错误：把两个不同 obj 说成同一个
> A white pickup truck who is also a worker in orange vest stands by a traffic cone. ← 错误：跨目标用 is also

### 3.2 示例2（一条 caption 内多句 · 不同目标）

给定短语：

- [obj 0] white pickup truck
- [obj 1] worker in orange vest
- [obj 2] traffic cone
- [obj 3] woman
- [obj 4] person holding a broom

**可接受**（仍是一条 caption，内部多句；短语均原样出现）：
> A white pickup truck is parked near a worker in orange vest beside a traffic cone. There is a woman on the street. A person holding a broom is cleaning the street.

**不可接受**：硬把全部短语揉进一句导致不通顺，或漏用/改写任一短语。

### 3.3 示例3（同一目标 · 多条描述短语）★ 易错

给定短语（**全部属于 obj 0，画面里只有这一个人**）：

- [obj 0] lady holding umbrella
- [obj 0] woman in floral swimsuit
- [obj 0] pink umbrella

**可接受**（仍是**一个人**；短语原样嵌入）：
> A lady holding umbrella, a woman in floral swimsuit with a pink umbrella, stands outdoors.
> A woman in floral swimsuit, a lady holding umbrella under a pink umbrella, stands outdoors.

**不可接受**（把同目标拆成两人/两实体）：
> A lady holding umbrella stands near a woman in floral swimsuit under a pink umbrella. ← 错误：near 暗示两人
> A lady holding umbrella stands next to a woman in floral swimsuit. ← 错误：同一人被写成两个女士

**组合提示**（同 `obj_id` 时优先）：

- 同位/并列：`A {phrase_a}, a {phrase_b}, ...`
- 属性附着：`A {phrase_a} with a {phrase_b}` / `wearing` / `holding`
- 关系从句（**仅同 obj_id**）：`A {phrase_a} who is also a {phrase_b}`
- **禁止**对同 `obj_id` 使用：near / beside / next to / stands near / next to another / 暗示多人的空间分置

### 3.4 示例4（不同目标 · 禁止「也是」合并）★ 易错

给定短语（两个不同目标）：

- [obj 0] blue special vehicle
- [obj 1] white sedan

**可接受**（两个实体，并列/空间关系）：
> A blue special vehicle is near a white sedan.
> There is a blue special vehicle and a white sedan in the scene.

**不可接受**（把两个目标说成同一个）：
> A blue special vehicle is also a white sedan. ← 错误
> A blue special vehicle is a white sedan. ← 错误
> A blue special vehicle who is also a white sedan. ← 错误


## 4 输出格式（暂时不需要改动）

只返回 JSON（多句写在同一个字符串里）：

```json
{"caption": "..."}
```
