# 📖 Caption 组合规则（工地 person · 安全帽 / 反光衣）

- **概述**: 将**若干已选定的目标短语**组合成一条自然的英文 caption。短语本身由人工或上游 describe 选定——本规则**只改句式，不改短语**。场景偏工地人员 PPE（安全帽 / 反光衣）。
- **日期**: 2026-08-07

---

## 1 Caption-核心原则（刷新 / 重组时）

|要求|说明|
|---|---|
|短语锁定|输入列表中的每条 phrase **必须原样出现**在 caption 中（拼写、空格、连字符一致）|
|禁止替换|不得把短语改写成同类词（如 `worker with yellow hard hat` → `person` / `worker`）|
|禁止增删|不得省略任一给定短语；也不得额外塞入未给定的目标指称|
|禁止内容|不要提及标注框、crop、polygon、json、dataset、model|
|短语权重|信息密度优先于华丽修辞；PPE 短语（hard hat / reflective vest）不要被虚词冲淡|
|短语指代|以给定短语本身做主语/宾语，少用 they/it 把短语消掉|
|句式可变|允许调整语序、介词、连接词、从句结构，使句子通顺自然|
|句式语言|caption 正文仅用英文|

## 2 Caption-风格

|要求|说明|
|---|---|
|场景描述|工地/施工区可用 on the construction site / at the worksite / near scaffolding 等，但不要空泛堆砌|
|目标组合|同一目标可有多条描述短语（如帽 + 背心）；组合进 **一条** caption 时，不必塞进单句，可用多句分别装填|
|句式规范|一条 caption 可含多句完整英文；全部给定短语必须用上，句间逻辑通顺即可|

## 3 Caption-输入示例

### 3.1 示例1（单句）

给定短语：

- worker with yellow hard hat
- orange reflective vest
- traffic cone

**可接受**：
> A worker with yellow hard hat in an orange reflective vest stands beside a traffic cone.

**不可接受**：
> A worker stands by a cone. ← PPE 短语被改写/省略

### 3.2 示例2（一条 caption 内多句）

给定短语：

- worker with yellow hard hat
- person in orange reflective vest
- worker without hard hat
- person not wearing safety vest

**可接受**（仍是一条 caption，内部多句；短语均原样出现）：
> A worker with yellow hard hat walks near the scaffolding. A person in orange reflective vest stands by the materials. Nearby, a worker without hard hat talks with a person not wearing safety vest.

**不可接受**：硬把全部短语揉进一句导致不通顺，或漏用/改写任一短语。

## 4 输出格式（暂时不需要改动）

只返回 JSON（多句写在同一个字符串里）：

```json
{"caption": "..."}
```
