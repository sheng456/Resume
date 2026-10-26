/** loopback HTTP 客户端：调用 Python 内容面服务（正文不出本机）。 */
export class TailorHttpClient {
  constructor(
    readonly baseUrl: string,
    readonly token: string,
  ) {}

  async call<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    const res = await fetch(`${this.baseUrl}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ method, params, token: this.token }),
    })
    const body = (await res.json()) as { ok: boolean; result?: T; error?: string }
    if (!body.ok) throw new Error(body.error ?? `tailor_http_${res.status}`)
    return body.result as T
  }
}
