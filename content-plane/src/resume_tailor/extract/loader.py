"""L1 字节→文本提取：PDF/DOCX/Markdown/TXT 字节 → 文本，并接置信度门禁。

零第三方依赖：

- Markdown/TXT：UTF-8 / GB18030 / UTF-16 依次尝试解码；
- DOCX：stdlib ``zipfile`` + ``ElementTree`` 读 ``word/document.xml``，段落与表格
  分开处理——表格按行输出为 ``单元格\\t单元格``（**不再逐行交错**，那正是实测里
  章节被静默打乱的原因）；
- PDF：尽力而为——优先可选 ``pypdf``，其次 ``pdftotext`` 子进程；两者都没有时
  如实标记 ``pdf_extractor_unavailable``，**绝不静默返回空串**。

每种结果都过 ``assess_extraction``：低置信度不意味着不能用，而是强制走重生模式
（表格/多栏布局需要表格感知解析，而不是把它当块级文本去编辑）。
"""

from __future__ import annotations

import io
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .confidence import ConfidenceSignal, ExtractionConfidence, assess_extraction

__all__ = ["ExtractedText", "extract_text", "extract_text_from_path"]

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class ExtractedText:
    """字节提取结果：文本 + 提取器 + 置信度门禁结论。"""

    text: str
    media_type: str
    source_name: str
    extractor: str
    confidence: ExtractionConfidence

    @property
    def usable(self) -> bool:
        """是否可作为块级编辑的输入（高置信度且非空）。"""
        return self.confidence.confidence == "high" and bool(self.text.strip())


def extract_text(
    data: bytes,
    *,
    source_name: str,
    expected_cjk: bool = True,
) -> ExtractedText:
    """按文件名后缀分派提取器，并对结果跑置信度门禁。

    Args:
        data: 源文件字节。
        source_name: 文件名（用后缀决定提取器）。
        expected_cjk: 是否预期中文（中文简历应传 True）。

    Returns:
        ExtractedText；提取器不可用/损坏时 confidence 为 low 并带信号。

    Raises:
        ValueError: DOCX 字节损坏（``docx_invalid``）。
    """
    name = (source_name or "").lower()

    if name.endswith((".md", ".markdown", ".txt", ".text")):
        media = "text/markdown" if name.endswith((".md", ".markdown")) else "text/plain"
        return _gated(_decode_text(data), media, source_name, "utf8", expected_cjk)

    if name.endswith(".docx"):
        return _gated(
            _docx_text(data),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            source_name,
            "docx-zip",
            expected_cjk,
        )

    if name.endswith(".pdf"):
        return _extract_pdf(data, source_name, expected_cjk)

    # 未知类型：当文本尽力解码
    return _gated(_decode_text(data), "application/octet-stream", source_name, "utf8", expected_cjk)


def extract_text_from_path(path: str | Path, *, expected_cjk: bool = True) -> ExtractedText:
    """读取本地文件并提取文本。"""
    p = Path(path)
    return extract_text(p.read_bytes(), source_name=p.name, expected_cjk=expected_cjk)


# --------------------------------------------------------------------------- #
# 内部实现
# --------------------------------------------------------------------------- #


def _gated(text: str, media_type: str, source_name: str, extractor: str, expected_cjk: bool) -> ExtractedText:
    return ExtractedText(text, media_type, source_name, extractor, assess_extraction(text=text, expected_cjk=expected_cjk))


def _decode_text(data: bytes) -> str:
    """按 UTF-8 → GB18030 → UTF-16 顺序解码，最后兜底 replace。"""
    for encoding in ("utf-8", "gb18030", "utf-16"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _docx_text(data: bytes) -> str:
    """从 DOCX 提取文本（段落 + 表格，保持 body 内顺序）。

    - ``<w:p>`` 段落 -> 单行；
    - ``<w:tbl>`` 表格 -> 每行输出为 ``cell1\\tcell2\\t...``（列结构不丢）。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("docx_invalid") from exc

    root = ET.fromstring(xml)
    body = root.find(f"{_W_NS}body")
    if body is None:
        return ""

    lines: list[str] = []
    for child in body:
        tag = child.tag[len(_W_NS):] if child.tag.startswith(_W_NS) else child.tag
        if tag == "p":
            text = _paragraph_text(child).strip()
            if text:
                lines.append(text)
        elif tag == "tbl":
            for row in child.findall(f"{_W_NS}tr"):
                cells = [_cell_text(tc).strip() for tc in row.findall(f"{_W_NS}tc")]
                lines.append("\t".join(cells))
    return "\n".join(lines)


def _paragraph_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.iter(f"{_W_NS}t"))


def _cell_text(tc: ET.Element) -> str:
    return "\n".join(t for t in (_paragraph_text(p).strip() for p in tc.findall(f"{_W_NS}p")) if t)


def _extract_pdf(data: bytes, source_name: str, expected_cjk: bool) -> ExtractedText:
    text = _pdf_via_pypdf(data)
    if text is not None:
        return _gated(text, "application/pdf", source_name, "pypdf", expected_cjk)
    text = _pdf_via_pdftotext(data)
    if text is not None:
        return _gated(text, "application/pdf", source_name, "pdftotext", expected_cjk)
    return ExtractedText(
        "",
        "application/pdf",
        source_name,
        "unavailable",
        ExtractionConfidence(
            "low",
            (ConfidenceSignal("pdf_extractor_unavailable", "没有可用的 PDF 提取器（缺 pdftotext / pypdf）"),),
        ),
    )


def _pdf_via_pypdf(data: bytes) -> str | None:
    try:
        from pypdf import PdfReader  # 可选依赖
    except ImportError:
        return None
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return None


def _pdf_via_pdftotext(data: bytes) -> str | None:
    """pdftotext 子进程提取；二进制不可用时返回 None。"""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        dst = Path(tmp) / "out.txt"
        src.write_bytes(data)
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", str(src), str(dst)],
                capture_output=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0 or not dst.exists():
            return None
        return dst.read_text(encoding="utf-8", errors="replace")
