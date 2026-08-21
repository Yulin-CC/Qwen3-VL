# 📖 Caption 组合规则（用于 grounding）

- **概述**: 将若干已选定的目标短语组合成一条自然的英文 caption。短语由上游 describe 选定——本规则**只改句式，不改短语**。
- **日期**: 2026-08-20

---

## 1 Caption-核心原则

|要求|说明|
|---|---|
|短语锁定|输入列表中的每条 phrase **必须原样出现**在 caption 中（拼写、空格、连字符一致）|
|禁止替换|不得把短语改写成同类词（如 `white car` → `car` / `vehicle`）|
|禁止增删|不得省略任一给定短语；也不得额外塞入未给定的目标指称|
|禁止内容|不要提及标注框、crop、polygon、json、dataset、model|
|短语权重|信息密度优先于华丽修辞|
|短语指代|以给定短语本身做主语/宾语，少用 they/it 把短语消掉|
|句式可变|允许调整语序、介词、连接词、从句结构，使句子通顺自然|
|句式语言|caption 正文仅用英文|
|实体一致|同一 `obj_id` 的多条短语 = 同一实体，绝不能写成两个人/两个物体|
|实体分立|不同 `obj_id` = 不同实体，绝不能写成「A 也是 B」把两个目标合并成一个|

## 2 Caption-风格

|要求|说明|
|---|---|
|场景描述|可用 in the scene / on the road / nearby，但不要空泛堆砌|
|目标组合|不同 `obj_id` 用 near / beside / next to / and / with 并列或空间关系分开写|
|禁止等同（跨目标）|对不同 `obj_id` 禁止：is / is a / is also / who is also / known as|
|同目标多短语|同一 `obj_id` 合成一个主体：同位、并列属性、with/wearing；禁止 near/beside 拆成多人|
|句式规范|一条 caption 可含多句；全部给定短语必须用上|

## 3 Caption-输入示例

### 3.1 不同目标

给定短语：

- [obj 0] white car
- [obj 1] person wearing black jacket
- [obj 2] black car

**可接受**：
> A white car is near a person wearing black jacket beside a black car.

**不可接受**：
> A car and a person stand by a vehicle. ← 短语被改写
> A white car is also a person wearing black jacket. ← 把两个 obj 说成同一个

### 3.2 同一目标 · 多条描述

给定短语（全部属于 obj 0）：

- [obj 0] person wearing black jacket
- [obj 0] person wearing blue jeans
- [obj 0] person wearing mask

**可接受**（仍是一个人）：
> A person wearing black jacket, a person wearing blue jeans with a person wearing mask, stands outdoors.

**不可接受**：
> A person wearing black jacket stands near a person wearing blue jeans. ← 同一人被写成两人

## 4 输出格式

只返回 JSON：

```json
{"caption": "..."}
```
