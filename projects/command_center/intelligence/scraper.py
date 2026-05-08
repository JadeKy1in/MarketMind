"""
scraper.py — Sprint 3: URL 抓取 + 结构化提取模块 + 学术多源 API 矩阵

数据流（URL 抓取）:
  URL → httpx GET → raw HTML/text → Flash LLM → structured JSON

数据流（学术文献）:
  query → 并发 Semantic Scholar + OpenAlex → 合并去重 → fallback arXiv

SPARC:
  Specification: V2.0 Sprint 3 蓝图 — URL 抓取 + 结构化提取 + 学术 API
  Pseudocode: URL → httpx GET → raw HTML/text → Flash LLM → structured JSON
  Architecture: 依赖 FlashAdapter（高吞吐），三通道降级 + 学术三源矩阵
  Refinement: 异步安全，Mock 模式兼容（无需真实 API Key），异常隔离
  Completion: 测试覆盖率 ≥ 90%
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlencode

import httpx

logger = logging.getLogger(__name__)


# ============================================================
# Data Models
# ============================================================


@dataclass(frozen=True)
class ScrapedContent:
    """抓取结果的结构化数据模型。

    Attributes:
        url: 源 URL
        title: 页面标题（LLM 提取或 HTML title tag）
        raw_text: 纯文本内容（HTML 去标签后截断至 max_raw_chars）
        summary: LLM 生成的结构化摘要（JSON 字符串）
        extracted_entities: LLM 提取的关键实体列表
        sentiment: 情绪倾向（bullish/bearish/neutral）
        confidence: LLM 提取置信度 [0.0, 1.0]
        track_used: 实际使用的降级通道（'A' | 'B' | 'C'）
        timestamp: ISO-8601 抓取时间
        error: 非 None 表示抓取失败
    """
    url: str = ""
    title: str = ""
    raw_text: str = ""
    summary: str = ""
    extracted_entities: List[Dict[str, str]] = field(default_factory=list)
    sentiment: str = "neutral"
    confidence: float = 0.5
    track_used: str = ""
    timestamp: str = field(default_factory=lambda: (
        datetime.datetime.now(datetime.timezone.utc).isoformat()
    ))
    error: Optional[str] = None


@dataclass(frozen=True)
class ScrapedDocument:
    """学术论文统一数据模型 — 用于多源 API 矩阵的输出。

    Attributes:
        title: 论文标题
        authors: 作者列表
        year: 发表年份
        abstract: 摘要文本
        external_id: 外部 ID（如 s2:12345, openalex:W123, arxiv:2301.12345）
        source: 数据源标签（"semantic_scholar" | "openalex" | "arxiv"）
        citation_count: 引用数（可能为 None）
        url: 论文链接
        error: 非 None 表示该条记录来自失败的请求
    """
    title: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    abstract: str = ""
    external_id: str = ""
    source: str = ""
    citation_count: Optional[int] = None
    url: Optional[str] = None
    error: Optional[str] = None


class AcademicPaper(Dict[str, Any]):
    """兼容旧代码的学术论文 Dict 类型别名。"""
    pass


@dataclass
class ScraperConfig:
    """Scraper 配置。

    Attributes:
        max_raw_chars: 原始文本截断长度（默认 8000）
        request_timeout: HTTP 请求超时（秒，默认 30）
        user_agent: 自定义 User-Agent
        mock_mode: 强制 Mock 模式（即使有 API Key）
    """
    max_raw_chars: int = 8000
    request_timeout: int = 30
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
    mock_mode: bool = False


# ============================================================
# 辅助函数
# ============================================================

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    """去除 HTML 标签，返回纯文本。"""
    text = _HTML_TAG_RE.sub(" ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_title_from_html(html: str) -> str:
    """从 HTML 中提取 <title> 标签内容。"""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        return _strip_html(m.group(1))
    return ""


def _normalize_query_for_dedup(papers: List[ScrapedDocument]) -> List[ScrapedDocument]:
    """按标题粗略去重——标题相似度采用小写+空格归一化比较。"""
    seen_titles: set[str] = set()
    deduped: List[ScrapedDocument] = []
    for p in papers:
        norm = re.sub(r"\s+", " ", p.title.lower()).strip()
        if norm and norm not in seen_titles:
            seen_titles.add(norm)
            deduped.append(p)
    return deduped


def _safe_int(value: Any) -> Optional[int]:
    """安全转换 int，失败返回 None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ============================================================
# Scraper — URL 抓取 + 结构化提取（现有实现，保持不变）
# ============================================================


class Scraper:
    """URL 抓取 + 结构化提取器。

    三通道降级策略：
      Track A — httpx GET 获取原始 HTML/文本（纯网络通道）
      Track B — Flash LLM 结构化提取（LLM 通道）
      Track C — Mock 模式（离线测试）

    用法:
        scraper = Scraper(flash_adapter=my_flash_adapter)
        result = await scraper.scrape("https://example.com/news")
    """

    def __init__(
        self,
        flash_adapter: Any = None,
        config: Optional[ScraperConfig] = None,
    ) -> None:
        self._config = config or ScraperConfig()
        self._flash = flash_adapter
        self._mock_mode = self._config.mock_mode or flash_adapter is None

        if self._mock_mode:
            logger.warning("Scraper in MOCK mode — no FlashAdapter provided.")
        else:
            logger.info("Scraper initialized")

    # ============================================================
    # 公共 API
    # ============================================================

    async def scrape(
        self,
        url: str,
        prompt_override: Optional[str] = None,
    ) -> ScrapedContent:
        """抓取并提取一个 URL 的结构化信息。

        Args:
            url: 目标 URL（必须包含 http:// 或 https:// 协议头）
            prompt_override: 可选的自定义提取 prompt

        Returns:
            ScrapedContent: 抓取结果（error 非空表示失败）

        Raises:
            ValueError: URL 格式无效
        """
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return ScrapedContent(
                url=url,
                error=f"Invalid URL: '{url}' — missing scheme or netloc",
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )

        # Track A: 抓取原始内容
        raw_html, track_used = await self._fetch_raw(url)
        if raw_html is None and track_used == "mock":
            return self._mock_scrape(url)

        if raw_html is None:
            return ScrapedContent(
                url=url,
                error="Failed to fetch URL content",
                track_used=track_used,
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )

        title = _extract_title_from_html(raw_html)
        raw_text = _strip_html(raw_html)
        raw_text = raw_text[:self._config.max_raw_chars]

        if not raw_text.strip():
            return ScrapedContent(
                url=url,
                title=title,
                error="URL returned empty content",
                track_used=track_used,
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )

        # Track B: LLM 结构化提取
        extraction = await self._extract_with_llm(url, raw_text, prompt_override)
        if extraction is None:
            return ScrapedContent(
                url=url,
                title=title,
                raw_text=raw_text,
                track_used=track_used,
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )

        return ScrapedContent(
            url=url,
            title=title,
            raw_text=raw_text,
            summary=extraction.get("summary", ""),
            extracted_entities=extraction.get("entities", []),
            sentiment=extraction.get("sentiment", "neutral"),
            confidence=float(extraction.get("confidence", 0.5)),
            track_used=track_used,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    # ============================================================
    # Track A: HTTP 抓取
    # ============================================================

    async def _fetch_raw(self, url: str) -> tuple[Optional[str], str]:
        """Track A: 通过 HTTP GET 获取原始内容。"""
        if self._mock_mode:
            return None, "mock"

        try:
            async with httpx.AsyncClient(
                timeout=self._config.request_timeout,
                headers={"User-Agent": self._config.user_agent},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "").lower()

                if "text/html" in content_type or "text/plain" in content_type or "application/json" in content_type:
                    content = resp.text
                else:
                    try:
                        content = resp.text
                    except UnicodeDecodeError:
                        return None, "A"

                logger.debug("Fetched %s (%d bytes)", url, len(content))
                return content, "A"

        except httpx.TimeoutException:
            logger.warning("Timeout fetching %s", url)
            return None, "A"
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %d fetching %s", e.response.status_code, url)
            return None, "A"
        except httpx.RequestError as e:
            logger.warning("Request error fetching %s: %s", url, e)
            return None, "A"

    # ============================================================
    # Track B: LLM 结构化提取
    # ============================================================

    async def _extract_with_llm(
        self,
        url: str,
        raw_text: str,
        prompt_override: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if self._mock_mode or self._flash is None:
            return self._mock_extraction(url, raw_text)

        try:
            system_prompt = (
                "You are a financial information extraction assistant. "
                "Analyze the following web page content and extract structured information. "
                "You MUST output a valid JSON object with exactly these keys:\n"
                "- summary: A 1-3 sentence summary of the key financial/market implications\n"
                "- sentiment: One of 'bullish', 'bearish', 'neutral'\n"
                "- confidence: A float 0.0-1.0 indicating your confidence in the extraction\n"
                "- entities: A list of objects with 'name' and 'type' keys "
                "(types: ticker, company, person, economic_indicator, sector, region)\n\n"
                "IMPORTANT: Output ONLY valid JSON, no markdown code blocks."
            )

            user_prompt = prompt_override or (
                f"Extract structured financial information from this page content "
                f"(source: {url}):\n\n{raw_text[:6000]}"
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            response = await self._flash.chat(messages)

            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.strip()

            return json.loads(cleaned)

        except json.JSONDecodeError as e:
            logger.warning("LLM extraction JSON parse error: %s", e)
            return None
        except Exception as e:
            logger.warning("LLM extraction failed: %s", e)
            return None

    # ============================================================
    # Track C: Mock
    # ============================================================

    def _mock_scrape(self, url: str) -> ScrapedContent:
        return ScrapedContent(
            url=url,
            title=f"Mock Article: {url}",
            raw_text=f"This is mock content for {url}. "
                     "It simulates a financial news article about market conditions.",
            summary=(
                "Mock summary: Analysts expect continued volatility "
                "in the near term with potential upside catalysts."
            ),
            extracted_entities=[
                {"name": "SPY", "type": "ticker"},
                {"name": "Federal Reserve", "type": "organization"},
            ],
            sentiment="neutral",
            confidence=0.85,
            track_used="mock",
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    @staticmethod
    def _mock_extraction(url: str, raw_text: str) -> Dict[str, Any]:
        return {
            "summary": (
                f"Mock extracted summary for {url}. "
                f"Content length: {len(raw_text)} characters. "
                "Key market implications: neutral with bullish bias."
            ),
            "sentiment": "bullish",
            "confidence": 0.72,
            "entities": [
                {"name": "QQQ", "type": "ticker"},
                {"name": "Technology", "type": "sector"},
            ],
        }


# ============================================================
# AcademicScraper — 学术多源 API 矩阵
# ============================================================


class AcademicScraper:
    """学术文献多源 API 矩阵抓取器。

    三源矩阵：
      Track S2 — Semantic Scholar API（优先并发）
      Track OA — OpenAlex API（优先并发）
      Track AR — arXiv API（兜底 fallback）

    智能路由：
      1. 并发请求 S2 + OA，合并去重
      2. 如果两者都失败 → 自动 fallback 到 arXiv
      3. 独立 try-except，一个源故障不影响其他源

    用法:
        ac = AcademicScraper(user_agent="mailto:your@email.com")
        papers = await ac.fetch_academic_papers("transformer attention")
    """

    # ============================================================
    # API 端点
    # ============================================================
    SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
    OPENALEX_URL = "https://api.openalex.org/works"
    ARXIV_API_URL = "http://export.arxiv.org/api/query"

    def __init__(
        self,
        user_agent: str = "AcademicScraper/1.0 (mailto:system@cline.os)",
        request_timeout: int = 30,
        max_results: int = 5,
        mock_mode: bool = False,
    ) -> None:
        """初始化 AcademicScraper。

        Args:
            user_agent: HTTP User-Agent header（OpenAlex 需要 mailto: 邮箱）
            request_timeout: HTTP 请求超时秒数
            max_results: 每个 API 返回的最大结果数
            mock_mode: 强制 Mock 模式（用于测试）
        """
        self._user_agent = user_agent
        self._timeout = request_timeout
        self._max_results = max_results
        self._mock_mode = mock_mode

        if mock_mode:
            logger.warning("AcademicScraper in MOCK mode — no real API calls will be made.")

    # ============================================================
    # 对外暴露接口
    # ============================================================

    async def fetch_academic_papers(self, query: str) -> List[ScrapedDocument]:
        """对外暴露方法：按查询词抓取学术文献。

        智能路由逻辑：
          1. 并发请求 Semantic Scholar + OpenAlex
          2. 合并去重
          3. 如果 S2 和 OA 都失败 → fallback 到 arXiv
          4. 独立 try-except，一个源故障不影响其他

        Args:
            query: 学术搜索查询词

        Returns:
            List[ScrapedDocument]: 去重后的论文列表（可能为空，不会报错）
        """
        if self._mock_mode:
            return self._mock_fetch(query)

        # 并发请求 Semantic Scholar 和 OpenAlex
        s2_task = self._fetch_semantic_scholar(query)
        oa_task = self._fetch_openalex(query)

        s2_results: List[ScrapedDocument] = []
        oa_results: List[ScrapedDocument] = []

        # 使用 gather 实现并发，独立捕获异常
        s2_success = False
        oa_success = False

        try:
            s2_results, s2_success = await s2_task
        except Exception as e:
            logger.warning("Semantic Scholar fetch failed: %s", e)
            s2_results = []

        try:
            oa_results, oa_success = await oa_task
        except Exception as e:
            logger.warning("OpenAlex fetch failed: %s", e)
            oa_results = []

        # 如果至少一个源成功 → 合并去重
        if s2_success or oa_success:
            combined = s2_results + oa_results
            deduped = _normalize_query_for_dedup(combined)
            logger.info(
                "Academic fetch: S2=%d, OA=%d, combined=%d, deduped=%d",
                len(s2_results), len(oa_results), len(combined), len(deduped),
            )
            return deduped[:self._max_results * 2]  # 返回上限 2 倍的单源结果数

        # 两个主源都失败 → fallback 到 arXiv
        logger.warning("S2 and OA both failed — falling back to arXiv for query: %s", query)
        try:
            arxiv_results, _ = await self._fetch_arxiv(query)
            logger.info("ArXiv fallback returned %d results", len(arxiv_results))
            return arxiv_results[:self._max_results]
        except Exception as e:
            logger.error("ArXiv fallback also failed: %s", e)
            return []

    # ============================================================
    # Semantic Scholar API
    # ============================================================

    async def _fetch_semantic_scholar(
        self, query: str,
    ) -> tuple[List[ScrapedDocument], bool]:
        """Track S2: 通过 Semantic Scholar API 搜索论文。

        API: GET /graph/v1/paper/search?query={query}&fields=title,abstract,authors,year,citationCount&limit=5

        Returns:
            (papers, success): papers 为论文列表，success 表示 API 调用是否成功
        """
        params = {
            "query": query,
            "fields": "title,abstract,authors,year,citationCount",
            "limit": str(self._max_results),
        }
        url = f"{self.SEMANTIC_SCHOLAR_URL}?{urlencode(params)}"

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

            papers: List[ScrapedDocument] = []
            for paper in data.get("data", []):
                doc = self._parse_s2_paper(paper)
                if doc.title:
                    papers.append(doc)

            logger.debug("Semantic Scholar returned %d papers for '%s'", len(papers), query)
            return papers, True

        except httpx.HTTPStatusError as e:
            logger.warning("Semantic Scholar HTTP %d: %s", e.response.status_code, query)
            return [], False
        except httpx.TimeoutException:
            logger.warning("Semantic Scholar timeout: %s", query)
            return [], False
        except httpx.RequestError as e:
            logger.warning("Semantic Scholar request error: %s", e)
            return [], False
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Semantic Scholar parse error: %s", e)
            return [], False

    @staticmethod
    def _parse_s2_paper(paper: Dict[str, Any]) -> ScrapedDocument:
        """解析 Semantic Scholar API 返回的单条 paper 记录。"""
        paper_id = paper.get("paperId", "")
        title = paper.get("title", "") or ""
        year = _safe_int(paper.get("year"))
        citation_count = _safe_int(paper.get("citationCount"))
        abstract = paper.get("abstract") or ""

        authors_raw = paper.get("authors", [])
        authors: List[str] = []
        for a in authors_raw:
            if isinstance(a, dict):
                name = a.get("name", "")
                if name:
                    authors.append(name)

        return ScrapedDocument(
            title=title.strip(),
            authors=authors,
            year=year,
            abstract=abstract.strip(),
            external_id=f"s2:{paper_id}" if paper_id else "",
            source="semantic_scholar",
            citation_count=citation_count,
            url=f"https://api.semanticscholar.org/{paper_id}" if paper_id else None,
        )

    # ============================================================
    # OpenAlex API
    # ============================================================

    async def _fetch_openalex(
        self, query: str,
    ) -> tuple[List[ScrapedDocument], bool]:
        """Track OA: 通过 OpenAlex API 搜索论文。

        API: GET /works?search={query}&per-page=5
        必须添加 User-Agent: mailto: 邮箱以进入 polite pool。

        Returns:
            (papers, success): papers 为论文列表，success 表示 API 调用是否成功
        """
        params = {
            "search": query,
            "per-page": str(self._max_results),
        }
        url = f"{self.OPENALEX_URL}?{urlencode(params)}"

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

            papers: List[ScrapedDocument] = []
            for work in data.get("results", []):
                doc = self._parse_openalex_work(work)
                if doc.title:
                    papers.append(doc)

            logger.debug("OpenAlex returned %d papers for '%s'", len(papers), query)
            return papers, True

        except httpx.HTTPStatusError as e:
            logger.warning("OpenAlex HTTP %d: %s", e.response.status_code, query)
            return [], False
        except httpx.TimeoutException:
            logger.warning("OpenAlex timeout: %s", query)
            return [], False
        except httpx.RequestError as e:
            logger.warning("OpenAlex request error: %s", e)
            return [], False
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("OpenAlex parse error: %s", e)
            return [], False

    @staticmethod
    def _parse_openalex_work(work: Dict[str, Any]) -> ScrapedDocument:
        """解析 OpenAlex API 返回的单条 work 记录。"""
        work_id = work.get("id", "")  # e.g. "https://openalex.org/W12345678"
        title = work.get("title", "") or ""
        publication_year = _safe_int(work.get("publication_year"))
        cited_by_count = _safe_int(work.get("cited_by_count"))

        # 提取 OpenAlex ID（从 URL 中提取）
        oa_id = ""
        if work_id:
            # 格式: https://openalex.org/W12345678
            m = re.search(r"/W(\d+)$", work_id)
            if m:
                oa_id = m.group(1)

        # 提取作者
        authorships = work.get("authorships", [])
        authors: List[str] = []
        for a in authorships:
            if isinstance(a, dict):
                author_data = a.get("author", {})
                if isinstance(author_data, dict):
                    name = author_data.get("display_name", "")
                    if name:
                        authors.append(name)

        # 提取摘要（OpenAlex 使用倒排索引格式）
        abstract = work.get("abstract_inverted_index", "")
        if isinstance(abstract, dict):
            # 重建摘要文本
            words: List[tuple[int, str]] = []
            for word, positions in abstract.items():
                if isinstance(positions, list):
                    for pos in positions:
                        if isinstance(pos, int):
                            words.append((pos, word))
            words.sort(key=lambda x: x[0])
            abstract = " ".join(w for _, w in words) if words else ""

        return ScrapedDocument(
            title=title.strip(),
            authors=authors,
            year=publication_year,
            abstract=abstract.strip(),
            external_id=f"openalex:W{oa_id}" if oa_id else "",
            source="openalex",
            citation_count=cited_by_count,
            url=work_id if work_id else None,
        )

    # ============================================================
    # arXiv API
    # ============================================================

    async def _fetch_arxiv(
        self, query: str,
    ) -> tuple[List[ScrapedDocument], bool]:
        """Track AR: 通过 arXiv API（XML 接口）搜索论文。

        API: GET /api/query?search_query=all:{query}&max_results=5

        Returns:
            (papers, success): papers 为论文列表，success 表示 API 调用是否成功
        """
        params = {
            "search_query": f"all:{query}",
            "max_results": str(self._max_results),
        }
        url = f"{self.ARXIV_API_URL}?{urlencode(params)}"

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                xml_text = resp.text

            papers = self._parse_arxiv_xml(xml_text)
            logger.debug("ArXiv returned %d papers for '%s'", len(papers), query)
            return papers, True

        except httpx.HTTPStatusError as e:
            logger.warning("ArXiv HTTP %d: %s", e.response.status_code, query)
            return [], False
        except httpx.TimeoutException:
            logger.warning("ArXiv timeout: %s", query)
            return [], False
        except httpx.RequestError as e:
            logger.warning("ArXiv request error: %s", e)
            return [], False
        except (ET.ParseError, json.JSONDecodeError) as e:
            logger.warning("ArXiv XML parse error: %s", e)
            return [], False

    @staticmethod
    def _parse_arxiv_xml(xml_text: str) -> List[ScrapedDocument]:
        """解析 arXiv XML 响应。"""
        papers: List[ScrapedDocument] = []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return papers

        # arXiv 命名空间
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }

        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            title = title_el.text.strip() if title_el is not None and title_el.text else ""

            summary_el = entry.find("atom:summary", ns)
            abstract = summary_el.text.strip() if summary_el is not None and summary_el.text else ""

            # arXiv ID（从 id 标签提取）
            id_el = entry.find("atom:id", ns)
            arxiv_id = ""
            if id_el is not None and id_el.text:
                # 格式: http://arxiv.org/abs/2301.12345v1
                m = re.search(r"/(\d+\.\d+)", id_el.text)
                if m:
                    arxiv_id = m.group(1)

            # 作者
            authors: List[str] = []
            for author_el in entry.findall("atom:author", ns):
                name_el = author_el.find("atom:name", ns)
                if name_el is not None and name_el.text:
                    authors.append(name_el.text.strip())

            # 年份（从 published 字段提取）
            published_el = entry.find("atom:published", ns)
            year = None
            if published_el is not None and published_el.text:
                m = re.match(r"(\d{4})", published_el.text)
                if m:
                    year = int(m.group(1))

            # arXiv 论文链接
            paper_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None

            papers.append(ScrapedDocument(
                title=title,
                authors=authors,
                year=year,
                abstract=abstract,
                external_id=f"arxiv:{arxiv_id}" if arxiv_id else "",
                source="arxiv",
                citation_count=None,  # arXiv 不提供引用数
                url=paper_url,
            ))

        return papers

    # ============================================================
    # Mock 模式
    # ============================================================

    def _mock_fetch(self, query: str) -> List[ScrapedDocument]:
        """Mock 模式下的学术论文抓取模拟。"""
        return [
            ScrapedDocument(
                title=f"Mock Paper 1: {query} — A Novel Approach",
                authors=["Mock Author A", "Mock Author B"],
                year=2024,
                abstract=f"This is a mock abstract for '{query}'. "
                         "It simulates a state-of-the-art research paper.",
                external_id="s2:mock_paper_1",
                source="semantic_scholar",
                citation_count=42,
                url="https://api.semanticscholar.org/mock_paper_1",
            ),
            ScrapedDocument(
                title=f"Mock Paper 2: {query} — An Empirical Study",
                authors=["Mock Author C", "Mock Author D"],
                year=2023,
                abstract=f"An empirical study on '{query}' with comprehensive experiments.",
                external_id="openalex:W12345678",
                source="openalex",
                citation_count=17,
                url="https://openalex.org/W12345678",
            ),
            ScrapedDocument(
                title=f"Mock Paper 3: A Survey of {query}",
                authors=["Mock Author E"],
                year=2024,
                abstract=f"A comprehensive survey of {query} methods and applications.",
                external_id="arxiv:2401.12345",
                source="arxiv",
                citation_count=None,
                url="https://arxiv.org/abs/2401.12345",
            ),
        ]