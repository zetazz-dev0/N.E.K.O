# GPT Realtime API：上下文机制与流程控制

## 1. 主API与辅助API的职责划分

N.E.K.O 中存在两类 API：

| | 主API (Core API) | 辅助API (Assist API) |
|---|---|---|
| 职责 | 实时语音/视频对话 | 语义文本处理（摘要、情绪、纠错、视觉、Agent） |
| 协议 | WebSocket | HTTP REST (OpenAI 兼容) |
| 客户端 | `OmniRealtimeClient` | `OmniOfflineClient` |

**重要结论**：语音模式下，回复内容的质量 **100% 取决于主API**。辅助API不参与回复生成，只做后处理（情绪分析驱动表情、记忆摘要等）。

## 2. GPT Realtime 的上下文机制

### 有状态的 WebSocket Session

与普通 Chat API 每次请求携带完整 `messages` 数组不同，GPT Realtime 是**有状态长连接**：

- 连接建立时通过 `session.update` 设置 `instructions`（系统提示）
- 之后每轮对话（用户音频输入 + 模型输出）自动追加到服务端维护的 `conversation` 对象
- 第 N+1 轮对话自动拥有前 N 轮的完整上下文，无需手动管理

### N.E.K.O 的 40 秒热切换机制

N.E.K.O 的 session 不是永久保持的。`core.py` 中的逻辑：

```
Session 1 (0~40秒)
  ├─ 服务端自动维护对话上下文
  ├─ 40秒到期 → 触发记忆归档（辅助API的摘要模型）
  ├─ 后台准备 Session 2：
  │   ├─ 调 Memory Server 获取记忆摘要
  │   ├─ 收集 Session 1 后续的对话缓存（_convert_cache_to_str）
  │   └─ 拼接为新的 initial_prompt
  └─ 当前轮结束 → 热切换到 Session 2

Session 2 (新 WebSocket)
  ├─ instructions = 角色设定 + 记忆摘要 + 最近对话缓存
  └─ 继续对话...
```

因此上下文来源取决于是否跨 session：
- **同 session 内**：服务端自动保留完整的前序音频/文本
- **跨热切换**：通过 instructions 注入记忆摘要 + 近期对话文本缓存

## 3. GPT Realtime 的运行时注入点

### 3.1 `conversation.item.create` — 插入对话消息

可在对话进行中往历史里注入一条消息：

```json
{
  "type": "conversation.item.create",
  "item": {
    "type": "message",
    "role": "user",
    "content": [
      { "type": "input_text", "text": "需要注入的文本" }
    ]
  }
}
```

N.E.K.O 中的使用场景：`create_response()` 方法（非 Qwen 模型路径）、图片描述注入。

### 3.2 `session.update` — 更新系统指令

```json
{
  "type": "session.update",
  "session": {
    "instructions": "更新后的系统提示..."
  }
}
```

N.E.K.O 中的使用场景：Qwen 模型的 `create_response()` 通过追加 instructions 实现。

### 3.3 `create_response: false` — 禁止自动回复（GPT 独有）

GPT Realtime 的 `semantic_vad` 支持 `create_response` 参数：

```json
{
  "type": "semantic_vad",
  "eagerness": "auto",
  "create_response": false,
  "interrupt_response": true
}
```

设为 `false` 后，用户说完话**不会自动触发回复**，需要手动发送 `response.create` 事件。这是实现"辅助AI引导→主API回复"方案的关键开关。

## 4. 各模型的流程控制能力对比

| 模型 | VAD 类型 | create_response 开关 | conversation.item.create | 手动 response.create |
|------|----------|---------------------|--------------------------|---------------------|
| GPT Realtime | `semantic_vad` | 支持 | 支持 | 支持 |
| Qwen Omni | `server_vad` | 不支持 | 不支持（通过 update_session 追加 instructions） | 支持 |
| GLM Realtime | `server_vad` | 不支持 | 未知 | 未知 |
| Step Audio | `server_vad` | 不支持 | 支持（同 GPT 格式） | 支持 |
| Free (lanlan.tech) | `server_vad` | 不支持 | 未知 | 未知 |
| Gemini Live | SDK 原生 | 不适用（SDK 模式） | 不适用 | 通过 `send_client_content` |

## 5. "辅助AI引导"方案的可行性分析

### 目标架构

```
用户说话 → 主API(create_response:false，不自动回复)
        → 等待 transcript 事件
        → transcript + 上下文 → 辅助API (如 DeepSeek Reasoner) 深度理解
        → 辅助API返回分析/引导
        → conversation.item.create 注入引导文本
        → 手动发送 response.create
        → 主API基于完整上下文 + 引导生成语音回复
```

### 可行性

| 条件 | 状态 |
|------|------|
| 禁止自动回复 | 仅 GPT Realtime 支持 (`create_response: false`) |
| 获取用户语音文本 | 支持（`input_audio_transcription.completed` 事件） |
| 注入引导文本 | 支持（`conversation.item.create`） |
| 手动触发回复 | 支持（`response.create` 事件） |

### 预期延迟影响

原始流程：用户说完 → ~200-500ms → 开始出声

引导方案：用户说完 → 等 transcript (~1-2s) → 辅助API推理 (~2-10s) → 主API生成 → 开始出声

**总延迟预计 5-15 秒**，取决于辅助API的响应速度。

### 需要改动的文件

| 文件 | 改动内容 |
|------|---------|
| `omni_realtime_client.py` | GPT 配置中 `create_response` 改为 `false`；新增 transcript 等待 + 手动触发逻辑 |
| `core.py` | 新增辅助API调用编排：收到 transcript → 调辅助API → 注入结果 → 触发回复 |
| 可能新增中间件 | 辅助语义理解的调用封装 |

### 局限性

- **仅限 GPT Realtime**，其他模型无法使用此方案
- 延迟显著增加，影响对话自然感
- 打断逻辑复杂化：辅助API处理期间用户又说话时需要取消/重排
- 辅助API的引导质量直接影响最终效果——如果引导过于详细，主API可能变成纯念稿；如果过于简略，则引导无意义

## 6. 替代方案：文本模式 + TTS

如果目标是"让语义理解更强的模型决定回复内容"，最简单的路径是使用现有的**文本模式**（`OmniOfflineClient`），将辅助API的 `CONVERSATION_MODEL` 设为强语义模型（如 DeepSeek Reasoner），配合高质量 TTS。这是零代码改动的方案。

## 7. 关键代码位置参考

| 位置 | 说明 |
|------|------|
| `omni_realtime_client.py:495-515` | GPT Realtime session 配置（含 semantic_vad） |
| `omni_realtime_client.py:915-959` | `create_response()` — 手动触发回复 |
| `omni_realtime_client.py:1071-1241` | `handle_messages()` — 事件处理循环 |
| `omni_realtime_client.py:1158-1175` | speech_started / speech_stopped 事件处理 |
| `omni_realtime_client.py:1198-1201` | transcript 完成事件 |
| `core.py:1272-1371` | `start_llm_session()` — session 创建与上下文注入 |
| `core.py:366-432` | `handle_response_complete()` — 热切换逻辑 |
| `core.py:1536-1541` | `_convert_cache_to_str()` — 对话缓存转文本 |
| `core.py:1543-1580` | `_build_initial_prompt()` — 系统提示构建 |
| `core.py:1677-1790` | `_background_prepare_pending_session()` — 热切换准备 |

## 8. 结论修正：更真实的最佳实践不是"辅助AI先写稿，主API照着念"

前面的"辅助AI引导"示例在机制上成立，但不够真实。对于如下目标：

- 本地保存最近 10 天对话记录
- 维护一份持续增长的用户画像文档
- 维护多份"交互重点 / 长期话题"文档
- 希望 `gpt-realtime` 保持自然、低延迟、像真人一样即时回应
- 希望 `deepseek-reasoner` 提供更深层的分析、纠错和补充

更合理的结论是：

1. `gpt-realtime` 只负责"当前这一轮该怎么自然地说出来"
2. `deepseek-reasoner` 不直接代替回复，而是负责"慢分析 + 事实补充 + 记忆提炼"
3. 长期记忆不能整包塞进 Realtime session，只能先检索、压缩，再生成一个小型 briefing 注入
4. 异步分析结果不应无条件插嘴，而应先进入 `pending_followups / pending_corrections` 队列，等待合适的话题时机

换句话说，推荐架构不是：

```text
用户输入 -> realtime
        -> deepseek
        -> deepseek 写好一段长答案
        -> realtime 念出来
```

而是：

```text
用户输入 -> realtime 快速回复
        -> deepseek 慢速分析
        -> 分析结果写回记忆 / 待补充事项
        -> 下一轮若相关，再由 realtime 自然吸收并表达
```

## 9. 长期记忆注入的推荐分层

如果本地存储的是"最近 10 天对话记录 + 用户画像 + 交互重点"，那么不应把它们作为一整段原文直接拼到 `instructions`。推荐拆成 4 层：

### 9.1 Working Memory（工作记忆）

- 当前 realtime session 内的实时对话上下文
- 最近几轮用户与 AI 的原始互动
- 由 Realtime 服务端 conversation 自动维护

### 9.2 Profile Memory（用户画像）

- 稳定偏好
- 交流风格偏好
- 关系边界
- 长期目标

示例：

- 用户更喜欢先结论后解释
- 不喜欢被生硬纠错
- 常在下午去游泳
- 正在准备新能源汽车供应链汇报

### 9.3 Focus Memory（交互重点）

- 当前持续中的主题
- 尚未完成的任务
- 最近几天反复提及的问题

示例：

- 周五要向老板汇报新能源汽车供应链
- 害怕被问到碳排问题
- 最近恢复规律游泳

### 9.4 Episodic Memory（情节记忆）

- 最近 10 天中的结构化事件
- 只保留和当前问题最相关的条目

示例：

- 3 月 18 日：用户说老板只看结论，不喜欢太学术
- 3 月 19 日：用户提过电池环节、钢铁环节和碳排问题
- 3 月 20 日：用户明确说不喜欢被当场指出错误

## 10. 推荐新增：Context Composer（上下文拼装层）

当前 N.E.K.O 的 `new_dialog` 更接近"recent history + settings"。如果要支持更真实的长期记忆 + 异步分析，建议在 Memory Server 与 Realtime Session 之间新增一层 `Context Composer`。

它至少做 3 件事：

### 10.1 会话启动时生成 `session_brief`

用于新 session 建立时注入，内容应尽量短：

- 角色设定
- 用户画像摘要（5~10 条）
- 当前 active focus（3~5 条）
- 最近 24~72 小时的重要摘要
- 待跟进事项（1~3 条）

### 10.2 每轮生成 `turn_brief`

用于每次用户说完后、模型回答前的轻量检索：

- 这一轮 transcript 提到了什么主题
- 命中了哪些 profile / focus / episodic 项
- 是否存在相关的 `pending_correction`
- 是否需要提醒模型采用某种回复风格

### 10.3 管理 `pending_followups`

将 DeepSeek 的异步分析结果先存起来，而不是立刻打断用户当前话题。

典型字段：

- `topic`
- `summary`
- `detail`
- `confidence`
- `urgency`
- `source_turn_id`
- `expires_at`
- `delivery_strategy`

## 11. Realtime + DeepSeek 的双通道推荐模式

推荐把系统分成"快通道"和"慢通道"。

### 11.1 快通道：面向自然对话

```text
用户说话
  -> ASR transcript
  -> 轻量检索 turn_brief
  -> gpt-realtime 快速回复
```

目标：

- 尽量保持 300~800ms 级别的自然响应
- 不等待 DeepSeek 完整推理
- 回答以"自然、连续、低延迟"为第一优先级

### 11.2 慢通道：面向深度理解

```text
同一条 transcript
  -> 发送给 DeepSeek Reasoner
  -> 输出结构化分析
  -> 写回 profile / focus / episodic / pending_correction
```

DeepSeek 更适合输出结构化结果，而不是直接输出给用户的话术：

```json
{
  "fact_corrections": [],
  "reasoning_summary": "",
  "profile_updates": [],
  "focus_updates": [],
  "followup_candidates": []
}
```

## 12. 异步补充能否实现？

**能实现，但不应默认"晚到就插嘴"。**

下面这个设想：

```text
用户：我觉得制作汽车是无需使用煤矿的
realtime：嗯，的确，你说的很对

...若干轮后...

deepseek 返回：煤矿其实也是汽车某个零件制作中的重要参与部分

用户：我下午去游泳了
realtime：游泳很健康。啊，对了，煤矿其实也参与汽车零件制作。
```

从技术上看可以实现，但从产品体验看通常不应无条件这样做。更好的规则是：

### 12.1 允许补充的情况

- 当前话题仍然和原问题强相关
- 之前回答存在明显事实风险
- 用户马上要拿这个结论去汇报、决策或执行
- 可以用 1~2 句自然补充完成

### 12.2 不宜插入的情况

- 用户已经切换到完全无关的话题
- 当前是情绪安抚、身体不适、关系沟通等敏感场景
- 补充内容太长，插入会破坏当前对话节奏
- 补充只是"更完整"，但不是"必须马上纠正"

### 12.3 更合理的话术

不要用：

- `啊，对了，你前面错了`

更推荐：

- `顺便把刚才那个制造链的点补稳一下：...`
- `我刚刚补查了一下，更稳妥的说法是：...`
- `如果你明天要拿去汇报，我建议改成这个表述：...`

## 13. 十轮真实示例

假设本地档案中已有：

### 用户画像

- 用户偏好简洁结论，不喜欢太学术
- 不喜欢被生硬纠错
- 最近在准备新能源汽车供应链汇报
- 常在下午去游泳

### 交互重点

- `focus-1`：周五要向老板汇报新能源汽车供应链
- `focus-2`：担心被问到碳排和原材料问题
- `focus-3`：最近恢复规律游泳

### 最近 10 天事件

- 3 月 18 日：用户说老板只看结论，不喜欢太长解释
- 3 月 19 日：用户提过电池环节、钢铁环节和碳排问题
- 3 月 20 日：用户说自己不喜欢被直接指出错误

### 第 1 轮

用户：`我明天要讲新能源汽车供应链，我还是觉得造车基本不用煤矿吧？`

系统动作：

- `turn_brief` 命中 `focus-1`
- 并行把该句发送给 `deepseek-reasoner` 做事实核验

realtime：

`如果你是说汽车不是直接靠煤来跑，可以这么理解；但如果是讲制造链，我不建议说得这么绝对。我先把这个点记成待核实，稍后给你一个更稳妥的讲法。`

### 第 2 轮

用户：`先不管这个，我下午想去游泳。`

系统动作：

- 命中画像中的"下午游泳"
- DeepSeek 仍在分析中

realtime：

`可以，游完再整理汇报也行。你之前不是也常去公司附近那个恒温池吗？`

### 第 3 轮

用户：`对，我一般去公司附近那个恒温泳池。`

系统动作：

- DeepSeek 返回：钢铁、焦炭、部分电力链条仍常涉及煤
- 系统判断 `focus-1` 仍是高优先级未完成话题，允许轻量补充

realtime：

`恒温池挺适合恢复节奏。顺便把刚才那个点补稳一下：如果看的是制造链而不是用车阶段，钢铁、焦炭和部分电力环节通常还是会涉及煤，所以明天别讲成“完全无关”。`

### 第 4 轮

用户：`嗯，但别说得太学术，我老板只看结论。`

系统动作：

- 更新 profile：`偏好先结论后解释`

realtime：

`明白，后面我都按“先结论、再一句解释”的格式给你。`

### 第 5 轮

用户：`我上周是不是还提过电池环节？`

系统动作：

- 检索到 3 月 19 日相关事件

realtime：

`提过。你当时主要担心两件事：电池原材料链条，以及别人追问碳排时你不好一句话说清。`

### 第 6 轮

用户：`对，我最怕别人追问碳排。`

系统动作：

- 更新 `focus-2`
- 并行让 DeepSeek 生成"老板追问时的简短答法"

realtime：

`那你主讲时不要主动展开碳排，只准备一个 10 秒备用答法就够了。`

### 第 7 轮

用户：`那你先给我一句20秒能讲完的话。`

系统动作：

- 使用 `focus-1 + focus-2 + profile` 生成主答法

realtime：

`可以这么说：新能源汽车本身不直接依赖煤，但如果看完整制造链，钢铁、材料加工和部分能源供给仍可能与煤相关，所以更准确的说法是“依赖程度下降，但没有完全脱离”。`

### 第 8 轮

用户：`还有，别把我之前说错的事讲得像在打我脸。`

系统动作：

- 更新 profile：`纠错要柔和，用“补充”“更稳妥的说法”`

realtime：

`记住了。以后我会用“补充一下”或者“更稳妥的表述是”这种方式。`

### 第 9 轮

用户：`我游完了，给我最终版。`

系统动作：

- 当前回到 `focus-1`
- 注入 DeepSeek 之前生成的追问备用答法

realtime：

`最终版我给你两句。第一句主讲：新能源汽车不直接以煤作为使用能源，但制造链中的钢铁、材料加工和部分能源环节仍可能涉及煤。第二句追问备用：所以更准确的表述不是“完全无关”，而是“相关性在下降，但尚未消失”。`

### 第 10 轮

用户：`行，把我今晚要做的三件事列出来。`

系统动作：

- 汇总 active focus

realtime：

`三件事：第一，记住主讲那一句；第二，背熟追问备用那一句；第三，把 PPT 里任何“完全不需要煤”这种绝对化表述删掉。`

## 14. 对当前 N.E.K.O 实现的直接结论

结合现有代码，当前系统已经有以下基础：

- 新 session 启动时会请求 Memory Server 的 `/new_dialog`
- 热切换时也会重新请求 `/new_dialog`
- GPT Realtime 已支持 `semantic_vad`
- 已能接收输入 transcript 事件

但距离本文推荐模式仍差三块：

1. `new_dialog` 目前更像"recent history + settings"，不是完整的 `Context Composer`
2. GPT 路径当前仍是 `create_response: true`，不利于"先检索再决定是否回复"
3. 缺少 `pending_correction / pending_followup` 的显式数据结构和投递策略

因此后续如果继续实现，建议优先顺序为：

1. 重做 Memory Server 的上下文输出，从"返回原始摘要"升级为"返回 session_brief"
2. 引入每轮 `turn_brief` 的轻量检索
3. 将 DeepSeek 的输出改为结构化结果，而不是直接给主模型一大段自然语言
4. 再决定是否把 GPT Realtime 改成 `create_response: false`

## 15. 最终结论

要让 `gpt-realtime + deepseek-reasoner` 组合出更有深度、又不牺牲自然感的结果，最佳实践是：

- `gpt-realtime` 做即时交互
- `deepseek-reasoner` 做异步深度分析
- 长期记忆按需检索，不整包注入
- 异步分析结果先进入记忆和待补充队列，不默认立刻插嘴
- 只有在话题相关、事实风险高、补充足够短时，才让 realtime 在后续轮次自然补充

这是一种"实时对话模型 + 后台分析系统"的架构，不是一种"主模型说一句，辅助模型改一句"的架构。
