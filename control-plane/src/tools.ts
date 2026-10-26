/** Host tools：把内容面 loopback 契约暴露成 DSH 工具（只回 id/hash/标签/枚举/计数）。 */
import type { Context } from '@deepseek-ai/cordis'
import type { ContentBlock } from '@deepseek-ai/dsh-llm'
import {
  defineTool as dshDefineTool,
  type DefineToolOptions,
  type ParameterSchemaSpec,
  type ToolDefinition,
  type ValueSchemaSpec,
} from '@deepseek-ai/dsh-tools'
import { TailorHttpClient } from './http-client.js'

const unsafeDefineTool = dshDefineTool as unknown as (
  options: DefineToolOptions<ParameterSchemaSpec, ValueSchemaSpec>,
) => ToolDefinition

// 与 boss-watch 相同的兼容修复：确保 required 为数组，兼容 OpenAI 网关校验。
function defineTool<const S extends ParameterSchemaSpec, const O extends ValueSchemaSpec>(
  options: DefineToolOptions<S, O>,
): ToolDefinition {
  const tool = unsafeDefineTool(options as never)
  const parameters = tool.parameters as Record<string, unknown>
  return {
    ...tool,
    parameters: { ...parameters, ...(Array.isArray(parameters.required) ? {} : { required: [] }) },
  }
}

function renderJson(_args: unknown, value: unknown): ContentBlock[] {
  return [{ type: 'text', text: JSON.stringify(value) }]
}

const OBJECT = { type: 'object' } as const

export function registerResumeTailorTools(ctx: Context, client: TailorHttpClient): () => void {
  const disposers = [
    ctx.tools.register(
      defineTool({
        name: 'resume_tailor_extract',
        description:
          'Upload a resume or JD file to the local content plane; returns a content-addressed doc id, extractor, confidence and counts, never the text.',
        parameters: {
          filePath: { type: 'string', required: true, description: 'Absolute path to a PDF/DOCX/Markdown/TXT file.' },
        },
        output: { schema: OBJECT, render: renderJson },
        async execute(args) {
          const fs = await import('node:fs/promises')
          const data = await fs.readFile(args.filePath)
          const b64 = Buffer.from(data).toString('base64')
          const name = args.filePath.split(/[\\/]/).pop() ?? 'resume.txt'
          return client.call('extract', { filename: name, data_b64: b64 })
        },
      }),
    ),
    ctx.tools.register(
      defineTool({
        name: 'resume_tailor_gap',
        description:
          'Diagnose which JD requirements are missing/partial in a resume; returns labels and coverage only, never JD text.',
        parameters: {
          jdDocId: { type: 'string', required: true, description: 'doc id from resume_tailor_extract for the JD.' },
          resumeDocId: { type: 'string', required: true, description: 'doc id from resume_tailor_extract for the resume.' },
        },
        output: { schema: OBJECT, render: renderJson },
        async execute(args) {
          return client.call('gap', { jd_doc_id: args.jdDocId, resume_doc_id: args.resumeDocId })
        },
      }),
    ),
    ctx.tools.register(
      defineTool({
        name: 'resume_tailor_plan',
        description:
          'Build a rewrite plan (instruction-driven if an instruction is given, else JD-gap rules). Returns plan id, driver, intent/hash, step counts; never target text.',
        parameters: {
          jdDocId: { type: 'string', required: true },
          resumeDocId: { type: 'string', required: true },
          instruction: { type: 'string', description: 'Optional user instruction in natural language.' },
        },
        output: { schema: OBJECT, render: renderJson },
        async execute(args) {
          return client.call('plan', {
            jd_doc_id: args.jdDocId,
            resume_doc_id: args.resumeDocId,
            instruction: args.instruction,
          })
        },
      }),
    ),
    ctx.tools.register(
      defineTool({
        name: 'resume_tailor_run',
        description:
          'Run the deterministic rewrite (terminology alignment + reorder). Returns changed block ids and counts; never rewritten text.',
        parameters: {
          planId: { type: 'string', required: true, description: 'plan id from resume_tailor_plan.' },
        },
        output: { schema: OBJECT, render: renderJson },
        async execute(args) {
          return client.call('run', { plan_id: args.planId })
        },
      }),
    ),
    ctx.tools.register(
      defineTool({
        name: 'resume_tailor_review',
        description:
          'Return the local review page URL for a rewritten plan. The diff text lives only on that local page, never in this tool result.',
        parameters: {
          planId: { type: 'string', required: true },
        },
        output: { schema: OBJECT, render: renderJson },
        async execute(args) {
          return client.call('review', { plan_id: args.planId })
        },
      }),
    ),
    ctx.tools.register(
      defineTool({
        name: 'resume_tailor_commit',
        description:
          'Content-addressed commit of a reviewed plan (Gate W). Returns the new resume version hash and lineage id; idempotent on same content.',
        parameters: {
          planId: { type: 'string', required: true },
          baseResumeVersionId: { type: 'string', description: 'Optional existing resume version this supersedes.' },
        },
        output: { schema: OBJECT, render: renderJson },
        async execute(args) {
          return client.call('commit', { plan_id: args.planId, base_resume_version_id: args.baseResumeVersionId })
        },
      }),
    ),
  ]
  return () => {
    for (const dispose of disposers) dispose()
  }
}
