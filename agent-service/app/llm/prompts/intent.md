任务：分析用户最新一条消息（结合对话历史补全省略成分），输出意图 JSON。

输出 Schema：
{
  "scenario": "transfer|billing|wealth|subscription|card|cross_scenario|chat|other",
  "goal": "一句话复述用户目标",
  "slots": { "按场景预定义槽位，未提及的不填" },
  "ambiguous": true|false,
  "clarify_question": "当 ambiguous=true 时，一句追问（口语化）",
  "confidence": 0.0-1.0
}

消歧与追问规则：
1. 槽位缺失关键信息（如转账无金额/无收款人）→ ambiguous=true，追问缺的最少一项。
2. 指代消解：结合历史，如"再给他转一次"→ 从历史取收款人与金额填入 slots。
3. 模糊金额（"转点钱""转几百"）→ ambiguous=true，请求明确数额。
4. 时间归一：相对时间（"下个月15号""上周"）转为绝对日期填入 slots。
5. 纯闲聊/感谢 → scenario=chat；与银行业务无关 → scenario=other。

【对话历史】
{history}

【用户消息】
{user_input}
