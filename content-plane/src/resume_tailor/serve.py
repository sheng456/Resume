"""P0 本地服务：把内容面暴露为 loopback HTTP + 服务令牌，正文不出进程。

跨边界只回 **id / hash / 标签 / 枚举 / 计数**；简历正文、JD 正文、改写候选永远
只在本进程内存与内容寻址工件里。评审 diff 走 ``/review/<plan_id>`` 本地页，文本
不进任何工具响应。

协议：``POST /`` 收 ``{"method", "params", "token"}``，回
``{"ok": true, "result": ...}`` 或 ``{"ok": false, "error": "code"}``。
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import threading
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .diagnose.gap import analyze_gaps
from .domain.contracts import JdRequirement, ResumeBlock, RewrittenBlock
from .extract.blocks import extract_blocks
from .extract.loader import extract_text
from .plan.plan import build_plan
from .render.markdown import render_markdown
from .rewrite.pipeline import rewrite_resume
from .store.identity import sha256_hex
from .store.version import commit_resume
from .store.version_store import ResumeVersionStore

__all__ = ["TailorService", "make_server", "run"]

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _cjk_count(text: str) -> int:
    return len(_CJK.findall(text))


def _reordered_block_ids(blocks, final) -> tuple[str, ...]:
    """返回位置发生变化的块 id（重排可见性：文本没变但顺序变了）。"""
    original = {block.block_id: index for index, block in enumerate(blocks)}
    return tuple(item.block_id for index, item in enumerate(final) if original.get(item.block_id) != index)


def _error_code(exc: Exception) -> str:
    """把异常映射为稳定错误码（不回正文/堆栈/裸异常名）。"""
    msg = str(exc)
    if isinstance(exc, FileNotFoundError):
        return "file_not_found"
    if isinstance(exc, IsADirectoryError):
        return "not_a_file"
    if isinstance(exc, KeyError):
        return "unknown_reference"
    if msg == "tailor_supersedes_not_found":
        return "supersedes_not_found"
    if msg == "docx_invalid":
        return "invalid_docx"
    if isinstance(exc, RuntimeError):
        return "store_unavailable"
    if isinstance(exc, ValueError):
        return "invalid_request"
    return type(exc).__name__


def _jd_requirements(text: str) -> tuple[JdRequirement, ...]:
    """把 JD 纯文本切成要求项。

    BOSS 抓的 JD 常是**无换行的一段纯文本**；若只按行切，整段会塌缩成 1 条。
    因此：先按非空行切；单行过长（>60 字）再按 ``。；;`` 句切，最后兜底按编号
    ``1. 2. 3.`` 切。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    reqs: list[str] = []
    for ln in lines:
        reqs.extend(_split_long_line(ln))
    return tuple(JdRequirement(f"req:{i}", ln) for i, ln in enumerate(reqs))


def _split_long_line(line: str) -> list[str]:
    """把一条过长的 JD 行按句/编号切分。

    触发条件：行长 > 60 字，或含 ≥2 个句末标点（``。；;``，即 3 句及以上）——
    后者覆盖"多条短句挤在一行"的 JD。
    """
    marks = line.count("。") + line.count("；") + line.count(";")
    if len(line) <= 60 and marks < 2:
        return [line]
    by_sentence = [p.strip() for p in re.split(r"[。；;]\s*", line) if p.strip()]
    if len(by_sentence) >= 2:
        return by_sentence
    by_number = [p.strip() for p in re.split(r"(?=\d+[.、)])", line) if p.strip()]
    return by_number or [line]


class TailorService:
    """内容面核心服务（无 HTTP，可单测）。

    持有 in-memory 状态：doc 文本/块、计划、最终块。正文永不进返回值。
    """

    def __init__(self, token: str, store: ResumeVersionStore | None = None) -> None:
        self._token = token
        self._store = store
        self._texts: dict[str, str] = {}
        self._blocks: dict[str, tuple[ResumeBlock, ...]] = {}
        self._plans: dict[str, object] = {}
        self._ctx: dict[str, tuple[tuple[ResumeBlock, ...], str]] = {}
        self._finals: dict[str, tuple[RewrittenBlock, ...]] = {}
        self._review_tokens: dict[str, str] = {}
        self._lock = threading.Lock()

    def authorized(self, token: str) -> bool:
        return secrets.compare_digest(self._token, token or "")

    def authorized_review(self, plan_id: str, token: str) -> bool:
        """评审页令牌：按 plan 绑定、进程内短命（重启即失效），避免服务令牌进 URL。"""
        stored = self._review_tokens.get(plan_id)
        return stored is not None and secrets.compare_digest(stored, token or "")

    # ------------------------------------------------------------------ #
    # 核心方法（干净入参，直接单测）
    # ------------------------------------------------------------------ #

    def extract(self, filename: str, data: bytes) -> dict:
        ext = extract_text(data, source_name=filename, expected_cjk=True)
        doc_id = "doc:" + sha256_hex(data)
        with self._lock:
            self._texts[doc_id] = ext.text
            self._blocks[doc_id] = extract_blocks(ext.text)
        return {
            "doc_id": doc_id,
            "media_type": ext.media_type,
            "extractor": ext.extractor,
            "confidence": ext.confidence.confidence,
            "signals": [{"name": s.name, "detail": s.detail} for s in ext.confidence.signals],
            "char_count": len(ext.text),
            "cjk_count": _cjk_count(ext.text),
            "usable": ext.usable,
        }

    def gap(self, jd_doc_id: str, resume_doc_id: str) -> dict:
        jd_text = self._texts[jd_doc_id]
        blocks = self._blocks[resume_doc_id]
        gaps = analyze_gaps(requirements=_jd_requirements(jd_text), blocks=blocks)
        return {
            "requirement_count": len(gaps),
            "gaps": [
                {
                    "requirement_id": g.requirement_id,
                    "coverage": g.coverage.value,
                    "requirement_terms": list(g.requirement_terms),
                    "best_block_ids": list(g.best_block_ids),
                }
                for g in gaps
            ],
        }

    def plan(self, jd_doc_id: str, resume_doc_id: str, instruction: str | None = None) -> dict:
        jd_text = self._texts[jd_doc_id]
        resume_text = self._texts[resume_doc_id]
        blocks = self._blocks[resume_doc_id]
        result = build_plan(
            requirements=_jd_requirements(jd_text),
            blocks=blocks,
            instruction=instruction,
            resume_content_hash=sha256_hex(resume_text),
            jd_content_hash=sha256_hex(jd_text),
            strategy_version="resume-tailor-plan-v1",
        )
        if not result.ok:
            return {
                "ok": False,
                "clarification_options": list(result.clarification_options),
                "conflicts": [
                    {
                        "requirement_id": c.requirement_id,
                        "gap_direction": c.gap_direction,
                        "instruction_direction": c.instruction_direction,
                    }
                    for c in result.conflicts
                ],
            }
        plan = result.plan
        with self._lock:
            self._plans[plan.plan_id] = plan
            self._ctx[plan.plan_id] = (blocks, jd_text)
        return {
            "ok": True,
            "plan_id": plan.plan_id,
            "driver": plan.driver,
            "intent_id": plan.intent_id,
            "instruction_hash": plan.instruction_hash,
            "step_count": len(plan.steps),
            "forbidden_terms": list(plan.forbidden_terms),
            "bullet_order": list(plan.bullet_order),
        }

    def run(self, plan_id: str) -> dict:
        plan = self._plans[plan_id]
        blocks, jd_text = self._ctx[plan_id]
        # P0 确定性（对齐 + 重排）；模型由环境变量插入（未来接 Ollama/DeepSeek）
        final = rewrite_resume(blocks=blocks, plan=plan, model=None, jd_text=jd_text)
        with self._lock:
            self._finals[plan_id] = final
        changed = [f.block_id for f in final if f.changed]
        reordered = _reordered_block_ids(blocks, final)
        return {
            "plan_id": plan_id,
            "changed_count": len(changed),
            "changed_block_ids": changed,
            "reordered_count": len(reordered),
            "reordered_block_ids": reordered,
            "total_blocks": len(final),
        }

    def commit(self, plan_id: str, base_resume_version_id: str | None = None) -> dict:
        if self._store is None:
            raise RuntimeError("store_unavailable")
        plan = self._plans[plan_id]
        blocks, jd_text = self._ctx[plan_id]
        final = self._finals[plan_id]
        result = commit_resume(
            store=self._store,
            final=final,
            blocks=blocks,
            base_resume_version_id=base_resume_version_id,
            plan_id=plan.plan_id,
            jd_content_hash=sha256_hex(jd_text),
            strategy_version="resume-tailor-plan-v1",
            mode="local",
            model_ref="none",
        )
        return {
            "resume_version_id": result.resume_version.resume_version_id,
            "content_hash": result.resume_version.content_hash,
            "local_artifact_ref": result.resume_version.local_artifact_ref,
            "lineage_id": result.lineage.lineage_id,
            "reused": result.reused,
        }

    def export(self, plan_id: str, resume_dir: str | None = None, display_name: str | None = None) -> dict:
        """把改写结果渲染成 markdown 写到目标目录（供 boss-watch import）。

        身份与 boss-watch 对齐：``contentHash = sha256(markdown 字节)``，
        ``resume-version:sha256`` 可与 ``boss_watch_resume_import_apply`` 直接对上。
        目标目录缺省取 ``BOSS_WATCH_RESUME_DIR``（boss-watch 的 resumeRoot），
        这样 boss-watch 的导入工具能直接读到该文件。
        """
        blocks, _ = self._ctx[plan_id]
        final = self._finals[plan_id]
        md = render_markdown(final, blocks)
        content_hash = sha256_hex(md)

        target = Path(resume_dir) if resume_dir else Path(
            os.environ.get("BOSS_WATCH_RESUME_DIR", "~/.resume-tailor/export")
        ).expanduser()
        target.mkdir(parents=True, exist_ok=True)

        safe_name = (display_name or f"tailored-{content_hash[:8]}").replace("/", "_").replace("\\", "_")
        file_name = f"{safe_name}.md"
        (target / file_name).write_text(md, encoding="utf-8")

        return {
            "file_name": file_name,
            "file_path": str(target / file_name),
            "content_hash": content_hash,
            "resume_version_id": "resume-version:" + content_hash,
            "media_type": "text/markdown",
            "byte_size": len(md.encode("utf-8")),
        }

    def review(self, plan_id: str) -> dict:
        """签发按 plan 绑定的短命评审令牌，返回本地评审页 URL（URL 带令牌，不含服务令牌）。"""
        review_token = secrets.token_urlsafe(24)
        with self._lock:
            self._review_tokens[plan_id] = review_token
        return {"review_url": f"/review/{plan_id}?token={review_token}"}

    def review_html(self, plan_id: str) -> str:
        """渲染本地评审页（diff 文本只在这一页，不进入任何工具响应）。"""
        final = self._finals[plan_id]
        blocks = self._ctx[plan_id][0]

        text_rows = []
        for f in final:
            if f.changed:
                text_rows.append(
                    "<tr><td><code>{bid}</code></td><td><del>{old}</del></td>"
                    "<td><ins>{new}</ins></td></tr>".format(
                        bid=_html(f.block_id), old=_html(f.original_text), new=_html(f.rewritten_text)
                    )
                )
        text_body = "".join(text_rows) or "<tr><td colspan='3'>无文本改动</td></tr>"

        old_pos = {block.block_id: i for i, block in enumerate(blocks)}
        text_by_id = {block.block_id: block.text for block in blocks}
        reorder_rows = []
        for i, f in enumerate(final):
            if old_pos.get(f.block_id) == i:
                continue
            reorder_rows.append(
                "<tr><td><code>{bid}</code></td><td>{old}</td><td>{new}</td>"
                "<td>{text}</td></tr>".format(
                    bid=_html(f.block_id),
                    old=old_pos[f.block_id] + 1,
                    new=i + 1,
                    text=_html(text_by_id.get(f.block_id, "")[:60]),
                )
            )
        reorder_body = "".join(reorder_rows) or "<tr><td colspan='4'>无顺序调整</td></tr>"

        return (
            "<!doctype html><meta charset='utf-8'><title>简历改写评审</title>"
            "<h1>简历改写评审（本地）</h1>"
            "<h2>文本改动</h2><table border='1' cellspacing='0' cellpadding='6'>"
            "<tr><th>块</th><th>原文</th><th>改写后</th></tr>" + text_body + "</table>"
            "<h2>顺序调整</h2><table border='1' cellspacing='0' cellpadding='6'>"
            "<tr><th>块</th><th>原位置</th><th>新位置</th><th>内容</th></tr>" + reorder_body + "</table>"
        )


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------- #
# HTTP 层
# ---------------------------------------------------------------------- #


def make_server(service: TailorService, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length)
            try:
                req = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._reply(400, {"ok": False, "error": "bad_json"})
                return
            if not service.authorized(req.get("token", "")):
                self._reply(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                result = self._dispatch(req.get("method", ""), req.get("params") or {})
                self._reply(200, {"ok": True, "result": result})
            except KeyError:
                self._reply(404, {"ok": False, "error": "unknown_method"})
            except Exception as exc:  # 结构化错误码，不回正文/堆栈/裸异常名
                self._reply(500, {"ok": False, "error": _error_code(exc)})

        def do_GET(self) -> None:  # noqa: N802
            # 本地评审页：正文最敏感的端点，必须校验一次性评审令牌。
            parsed = urllib.parse.urlparse(self.path)
            plan_id = parsed.path.strip("/").removeprefix("review/")
            token = (urllib.parse.parse_qs(parsed.query).get("token") or [""])[0]
            if not service.authorized_review(plan_id, token):
                self._reply(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                html = service.review_html(plan_id)
            except Exception:
                self._reply(404, {"ok": False, "error": "not_found"})
                return
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, method: str, params: dict) -> dict:
            if method == "extract":
                data = base64.b64decode(params.get("data_b64", ""))
                return service.extract(params.get("filename", "resume.txt"), data)
            if method == "gap":
                return service.gap(params["jd_doc_id"], params["resume_doc_id"])
            if method == "plan":
                return service.plan(
                    params["jd_doc_id"], params["resume_doc_id"], params.get("instruction")
                )
            if method == "run":
                return service.run(params["plan_id"])
            if method == "commit":
                return service.commit(params["plan_id"], params.get("base_resume_version_id"))
            if method == "export":
                return service.export(params["plan_id"], params.get("resume_dir"), params.get("display_name"))
            if method == "review":
                return service.review(params["plan_id"])
            raise KeyError(method)

        def _reply(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:  # 静默，避免正文进 stderr
            pass

    return ThreadingHTTPServer((host, port), Handler)


def run(host: str = "127.0.0.1", port: int = 4319) -> None:
    """启动本地服务（阻塞）。配置走环境变量，不写死。"""
    token = os.environ.get("RESUME_TAILOR_TOKEN") or secrets.token_urlsafe(24)
    home = Path(os.environ.get("RESUME_TAILOR_HOME", Path.home() / ".resume-tailor"))
    db_path = os.environ.get("RESUME_TAILOR_DB_PATH", str(home / "versions.sqlite3"))
    artifact_root = os.environ.get("RESUME_TAILOR_ARTIFACT_ROOT", str(home / "artifacts"))
    store = ResumeVersionStore(db_path=db_path, artifact_root=artifact_root)
    service = TailorService(token=token, store=store)
    server = make_server(service, host, port)
    actual = server.server_address[1]
    print(f"resume-tailor 服务已启动：http://{host}:{actual}  token={token[:8]}…（正文不出本机）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
