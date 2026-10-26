/** 薄控制面切片：注册 resume_tailor_* Host 工具 + resume-tailor Skill。 */
import type { Context } from '@deepseek-ai/cordis'
import { TailorHttpClient } from './http-client.js'
import { registerResumeTailorTools } from './tools.js'
import { registerResumeTailorSkill } from './skill.js'

export const name = 'resume-tailor-dsh-plugin'
export const inject = ['tools', 'skills']

export function apply(ctx: Context): void {
  const baseUrl = process.env.RESUME_TAILOR_URL ?? 'http://127.0.0.1:4319'
  const token = process.env.RESUME_TAILOR_TOKEN ?? ''
  const client = new TailorHttpClient(baseUrl, token)

  ctx.effect(() => {
    const disposeTools = registerResumeTailorTools(ctx, client)
    const disposeSkill = registerResumeTailorSkill(ctx)
    return () => {
      disposeSkill()
      disposeTools()
    }
  }, 'resume-tailor-dsh-plugin.lifecycle()')
}
