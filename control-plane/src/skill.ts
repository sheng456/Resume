/** resume-tailor Skill：告诉模型何时调哪个工具、停在哪个审批边界。 */
import type { Context } from '@deepseek-ai/cordis'
import type { SkillRegistration } from '@deepseek-ai/dsh-skill'

export const RESUME_TAILOR_SKILL = {
  name: 'resume-tailor',
  description:
    'Tailor a resume to a captured JD safely: analyze gaps, plan, rewrite, review, and commit — without fabricating facts.',
  source: 'runtime' as const,
  content: `# 简历改写（resume-tailor）

## 工作边界

- 简历正文永不进 DSH Transcript、工具响应或日志；本插件只经 loopback 调用本机 Python 内容面，
  跨边界只回 id / hash / 标签 / 枚举 / 计数。
- 改写**不臆造、不夸大**：JD 词进简历只有三条通道——简历本来就有 / 人工认定的同义短语
  （synonyms.json）/ 用户声明事实（DeclaredFact）。证据锚定是硬门禁，不是提示词约束。
- 登录、验证码、投递、发消息、最终提交始终由人工完成；本插件只做"分析 → 计划 → 改写 → 评审 → 落盘"。

## 建议流程

1. 用户提供简历文件路径时，调用 \`resume_tailor_extract\` 上传字节，拿到 \`doc_id\` 与
   \`confidence\`。若 \`confidence=low\`，把 \`signals\` 原样报告给用户（0% 中文 / 表格布局 /
   技术词粘连 / 无 PDF 提取器），不要硬继续块级编辑。
2. 用户提供 JD 时，同样 \`resume_tailor_extract\` 得到 \`jd_doc_id\`。
3. 调用 \`resume_tailor_gap\`（jd_doc_id + resume_doc_id）看缺口；只回 coverage 与标签，不回 JD 原文。
4. 调用 \`resume_tailor_plan\` 生成计划；有指令时传 \`instruction\`，驱动走指令意图。
   计划返回 \`ok:false\` 时，把 \`clarification_options\` / \`conflicts\` 交给用户裁决，不自行猜计划。
5. \`resume_tailor_run\` 触发确定性改写（对齐 + 重排），回 changed 块计数与 id，不回正文。
6. \`resume_tailor_review\` 返回本地评审页 URL；diff 文本只在该页，不进 Transcript。
7. 用户确认后 \`resume_tailor_commit\` 内容寻址落盘（Gate W），回版本哈希与血缘 id。
   supersedes 指向不存在版本时拒绝；同内容重复落盘 \`reused=true\`。

## 安全边界

- 看到 \`confidence=low\`、\`ok:false\`、\`unauthorized\`、\`store_unavailable\` 时报告稳定错误码，
  不自动重试、不绕过。
- 任何工具结果都不含简历/JD/改写候选正文；若某一步需要看 diff，只用 \`resume_tailor_review\`
  返回的本地页。
- 云端模型（DeepSeek）必须逐次授权（Gate E）；默认只走本地 Ollama。
`,
} as const satisfies SkillRegistration

export function registerResumeTailorSkill(ctx: Context): () => void {
  return ctx.skills.register(RESUME_TAILOR_SKILL)
}
