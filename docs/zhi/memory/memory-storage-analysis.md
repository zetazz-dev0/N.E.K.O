# Memory Server 存储结构分析

## 当前现状

### 在运行的模块

| 模块 | 存储方式 | 内容 |
|------|----------|------|
| **CompressedRecentHistory** | JSON 文件 (`recent_*.json`) | 滑动窗口(10条)近期对话，旧消息由 LLM 压缩成摘要 |
| **TimeIndexedMemory** | SQLite (`time_indexed_original` + `time_indexed_compressed`) | 完整对话原文 + 对应摘要，带时间戳，支持时间范围查询 |

### 被禁用的模块

| 模块 | 状态 | 原因 |
|------|------|------|
| **ImportantSettingsManager** | 代码注释掉 | "Qwen与GPT等旗舰模型相比性能差距过大，实用性近乎于0" |
| **Semantic Memory** (向量搜索) | 接口占位，返回"语义记忆已下线" | 同上 |

### 关键代码位置

- `memory/recent.py` — CompressedRecentHistoryManager
- `memory/settings.py` — ImportantSettingsManager
- `memory/timeindex.py` — TimeIndexedMemory
- `memory_server.py` — FastAPI 服务端，端口 48912

## 问题分析

现在的存储结构本质上只记录了"发生过什么对话"，且粒度很粗。缺乏结构化的知识提取和多维度的记忆分层。

## 记忆类型分析

从认知科学角度，角色 AI 的记忆系统可以支持以下类型：

| 记忆类型 | 说明 | 当前状态 |
|----------|------|----------|
| **工作记忆** (Working) | 当前对话上下文 | recent history 覆盖 |
| **情节记忆** (Episodic) | 什么时候发生了什么事 | time_indexed 部分覆盖，但没有结构化提取 |
| **语义记忆** (Semantic) | 事实性知识（用户喜欢X，用户的猫叫Y） | settings 模块尝试做但已禁用 |
| **情感记忆** (Emotional) | 关系状态、好感度、情绪轨迹 | 完全没有 |
| **程序性记忆** (Procedural) | 行为模式、说话风格的习得 | 完全没有 |
| **世界状态** (World State) | 角色所处世界的持续状态 | 完全没有 |

## 初步结论

### 1. 语义记忆重做 — 优先级最高

Settings 模块的思路是对的（从对话中提取事实），但不应该依赖弱模型。可选方案：
- 用主对话模型顺带提取，不额外调用
- 对话结束后异步用强模型提取
- 设计更好的 prompt 降低对模型能力的要求

### 2. 情感记忆 — 差异化关键

好感度、亲密度、关系里程碑等如果能持久化，角色的"活"感会完全不同。需要设计：
- 情感状态的数据结构
- 情感变化的触发和更新机制
- 如何在对话中自然地体现情感记忆

### 3. 情节记忆需要结构化

现在 time_indexed 存的是原始对话文本，检索时很难用。应该提取成结构化的"事件"：
- 时间
- 参与者
- 事件摘要
- 情感标签
- 重要程度
