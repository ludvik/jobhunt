# Ashby React Input Fix — Design Document

## Problem

Ashby ATS 使用 React controlled inputs。Agent 用 `fill`（Playwright fill）设置值时，直接操作 DOM `.value` 属性，绕过了 React 的 synthetic event system。结果：

- DOM 上显示值 ✅
- React internal state 没更新 ❌
- 提交时 React 读自己的 state → 字段为空 → 校验失败

**影响范围**：所有 Ashby 平台的文本输入字段（textbox）。Checkbox、radio、button（Yes/No toggle）不受影响。

## 已验证的事实

### 失败案例（3 个）

| Job ID | Company | 症状 |
|--------|---------|------|
| 272 | Whatnot | fill → 值显示 → submit → "Your form needs corrections"，所有文本字段报空 |
| 457 | Whatnot | fill + DOM evaluate fallback → 同样结果 |
| 491 | OpenAI | fill → 值不持久 → 重试 fill → 仍然失败 |

### Agent 尝试过的方法（均失败）

1. **`kind: "fill"`** — Playwright fill，直接设 `.value`。React 不感知。
2. **DOM evaluate（`.value` + `dispatchEvent(new Event('input'))`）** — React 17+ 的合成事件系统不监听原生 `input` 事件。
3. **DOM evaluate（`nativeInputValueSetter`）** — 日志显示 agent 尝试了但 React state 仍未更新。

### 手动验证（2026-03-11 21:20 PDT）

**`kind: "type"` 直接可用**，在 Whatnot Ashby 表单上实测：

```
1. browser(action="act", kind="type", ref="e15", text="Haomin Liu")
2. browser(action="act", kind="type", ref="e16", text="haomin.liu@gmail.com")
3. snapshot → 两个字段值正确显示
```

`type` 模拟键盘逐字输入 → 触发 React 的 `onChange` → state 同步。

## 根因分析

| 方法 | 原理 | React 感知 |
|------|------|-----------|
| `fill` | 直接设 `element.value` | ❌ 不触发 React 事件 |
| `evaluate(.value=)` | JS 设 value + 原生事件 | ❌ React 不监听原生 input 事件 |
| `type` | 逐字键盘事件 (keydown/keypress/input/keyup) | ✅ React 的 onChange 被触发 |

## 修复方案

### 方案：更新 Ashby platform knowledge + apply prompt

**不改代码**，只改 agent 的指令：

1. **更新 `references/platforms/ashby.md`**
   - 明确标注：**所有 Ashby 文本字段必须用 `type`，禁止用 `fill`**
   - 添加操作序列：`click ref → press Meta+a → type text`（Meta+a 清除已有内容）
   - 添加验证步骤：type 后 snapshot 一次确认值可见

2. **更新 `agents/apply/task_prompt.md`**
   - 在 "Fill form" 部分加 Ashby 特殊处理规则
   - 明确 `fill` vs `type` 的区别和适用场景

### 为什么不做代码层面的 fix

- Apply agent 是通过 `openclaw agent` 调用的 LLM agent，不是代码
- 它通过 browser tool 与表单交互，tool 本身支持 `type` 和 `fill` 两种 kind
- 问题是 agent 选择了错误的 kind（`fill` 而不是 `type`）
- 正确的 fix 是让 agent 知道在 Ashby 上用 `type`

### 风险

1. **`type` 比 `fill` 慢**：逐字输入，长文本（如 URL）需要更多时间。对于 Ashby 表单的字段长度（名字、邮箱、电话），影响可忽略。
2. **已有内容冲突**：如果 autofill 已经填了部分内容，`type` 会追加而不是替换。需要先 `Meta+a`（全选）再 type。
3. **reCAPTCHA 触发**：Whatnot Ashby 页面有 reCAPTCHA，但通常在 submit 后触发，不影响表单填写。

### 不解决的问题

- **494 Perplexity**：blocked 是因为有 required open-ended questions 需要 human input，不是 React 输入问题
- **498 Abridge**：blocked 是因为 LinkedIn 外链导到 Ashby 通用 board 而不是具体职位页面，不是输入问题
- **reCAPTCHA**：部分 Ashby 站点有 reCAPTCHA，目前无法自动化

## 实施步骤

1. 更新 `references/platforms/ashby.md`
2. 更新 `agents/apply/task_prompt.md`（如果 Ashby 规则需要在 prompt 中强调）
3. 重置 272、457、491 为 `tailored`，重新跑 apply
4. 验证 submit 成功

## 预期结果

- 3 个 Ashby apply_failed（272, 457, 491）应变为 applied 或 blocked（取决于 reCAPTCHA）
- 未来 Ashby 平台的文本输入不再失败
