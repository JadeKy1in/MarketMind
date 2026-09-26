#!/usr/bin/env python3
"""
Phase 8.3 — Real Reconnaissance Fetch
Scrapes arxiv.org and GitHub for real-world parameters for cognitive trading architectures.
"""

import requests
import re
import json
import time
import sys
from html.parser import HTMLParser

PROXIES = {
    "http": "http://127.0.0.1:10808",
    "https": "http://127.0.0.1:10808",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = 30


class ArxivResultParser(HTMLParser):
    """Minimal parser to extract paper titles, authors, and abstracts from arxiv search results."""
    def __init__(self):
        super().__init__()
        self.results = []
        self._current = {}
        self._in_title = False
        self._in_abstract = False
        self._in_p = False
        self._skip_p = 0
        self._p_count = 0
        self._abstract_p_count = 0
        self._title_text = ""
        self._abstract_text = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "p" and "class" in attrs_dict and "title" in attrs_dict.get("class", ""):
            self._in_title = True
            self._title_text = ""
        if tag == "span" and "class" in attrs_dict:
            cls = attrs_dict.get("class", "")
            if "abstract-full" in cls:
                self._in_abstract = True
                self._abstract_text = ""
        if tag == "div" and "class" in attrs_dict and "list-title" in attrs_dict.get("class", ""):
            self._in_title = True
            self._title_text = ""

    def handle_data(self, data):
        if self._in_title:
            self._title_text += data
        if self._in_abstract:
            self._abstract_text += data

    def handle_endtag(self, tag):
        if tag == "p" and self._in_title:
            self._in_title = False
            title = self._title_text.strip()
            if title:
                # Clean arxiv prefix
                title = re.sub(r'^Title:\s*', '', title, flags=re.IGNORECASE).strip()
                self._current["title"] = title
        if tag == "span" and self._in_abstract:
            self._in_abstract = False
            abstract = self._abstract_text.strip()
            if abstract:
                self._current["abstract"] = abstract
        # When both title and abstract found, push result and reset
        if "title" in self._current and "abstract" in self._current:
            self.results.append(self._current)
            self._current = {}


def fetch_url(url, label="url"):
    """Fetch a URL with proxy, return text."""
    print(f"[FETCH] {label}: {url[:80]}...")
    try:
        r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=TIMEOUT)
        r.raise_for_status()
        print(f"[OK] {label}: HTTP {r.status_code}, {len(r.text)} bytes")
        return r.text
    except requests.exceptions.ConnectTimeout:
        print(f"[NETWORK_BLOCK_ALERT] {label}: Connection timed out (proxy unreachable?)")
        return None
    except requests.exceptions.ProxyError as e:
        print(f"[NETWORK_BLOCK_ALERT] {label}: Proxy error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] {label}: {e}")
        return None


def search_arxiv(query, max_results=10):
    """Search arxiv and extract paper metadata."""
    url = f"https://arxiv.org/search/?query={requests.utils.quote(query)}&searchtype=all&start=0"
    html = fetch_url(url, f"arxiv: {query[:50]}")
    if not html:
        return []

    # Try parsing via arxiv API as fallback
    api_url = f"http://export.arxiv.org/api/query?search_query=all:{requests.utils.quote(query)}&max_results={max_results}&sortBy=relevance"
    print(f"[FETCH] arxiv API: {api_url[:80]}...")
    try:
        api_r = requests.get(api_url, headers=HEADERS, proxies=PROXIES, timeout=TIMEOUT)
        api_r.raise_for_status()
        xml_text = api_r.text
        print(f"[OK] arxiv API: {len(xml_text)} bytes")

        # Simple XML parse via regex (avoid heavy deps)
        entries = re.findall(r'<entry>(.*?)</entry>', xml_text, re.DOTALL)
        results = []
        for entry in entries[:max_results]:
            title = re.search(r'<title>(.*?)</title>', entry, re.DOTALL)
            abstract = re.search(r'<summary>(.*?)</summary>', entry, re.DOTALL)
            published = re.search(r'<published>(.*?)</published>', entry)
            authors = re.findall(r'<name>(.*?)</name>', entry)
            arxiv_id = re.search(r'<id>(.*?)</id>', entry)
            categories = re.findall(r'<category term="([^"]+)"', entry)
            doi = re.search(r'<arxiv:doi[^>]*>(.*?)</arxiv:doi>', entry)

            result = {
                "title": title.group(1).strip() if title else "N/A",
                "abstract": abstract.group(1).strip().replace('\n', ' ') if abstract else "N/A",
                "published": published.group(1).strip() if published else "N/A",
                "authors": authors[:5] if authors else [],
                "arxiv_id": arxiv_id.group(1).split('/')[-1] if arxiv_id else "N/A",
                "categories": categories,
                "doi": doi.group(1).strip() if doi else None,
            }
            results.append(result)

        return results

    except Exception as e:
        print(f"[ERROR] arxiv API failed: {e}")
        return []


def search_github_repos(query, max_repos=10):
    """Search GitHub for high-star repos."""
    url = f"https://api.github.com/search/repositories?q={requests.utils.quote(query)}+stars:>50&sort=stars&order=desc&per_page={max_repos}"
    html = fetch_url(url, f"github: {query}")
    if not html:
        return []
    
    try:
        data = json.loads(html)
        repos = []
        for item in data.get("items", [])[:max_repos]:
            repos.append({
                "name": item.get("full_name"),
                "stars": item.get("stargazers_count"),
                "description": item.get("description"),
                "url": item.get("html_url"),
                "topics": item.get("topics", []),
                "language": item.get("language"),
                "updated_at": item.get("updated_at"),
                "forks": item.get("forks_count"),
            })
        print(f"[OK] GitHub: found {len(repos)} repos for '{query}'")
        return repos
    except json.JSONDecodeError as e:
        print(f"[ERROR] GitHub API JSON decode: {e}")
        print(f"[DEBUG] Response snippet: {html[:500]}")
        return []


def main():
    results = {}

    # --- arXiv Searches ---
    arxiv_queries = [
        "hierarchical self-reflection reinforcement learning trading agent",
        "multi-agent trading system transformer market",
        "SHAP attribution quantitative finance feature importance",
        "experience replay buffer trading deep reinforcement learning",
        "meta-learning portfolio optimization reinforcement learning",
        "transformer time series financial forecasting attention",
        "hierarchical reinforcement learning option discovery trading",
        "curriculum learning reinforcement learning trading",
    ]
    results["arxiv"] = {}
    for q in arxiv_queries:
        papers = search_arxiv(q, max_results=5)
        results["arxiv"][q] = papers
        time.sleep(1.5)  # Rate limiting

    # --- GitHub Searches ---
    github_queries = [
        "reinforcement-learning trading",
        "quantitative-finance machine-learning",
        "deep-reinforcement-learning portfolio",
        "transformer time-series forecasting",
        "SHAP feature importance trading",
    ]
    results["github"] = {}
    for q in github_queries:
        repos = search_github_repos(q, max_repos=8)
        results["github"][q] = repos
        time.sleep(0.5)

    # --- Summary Output ---
    print("\n" + "=" * 80)
    print("PHASE 8.3 RECONNAISSANCE SUMMARY")
    print("=" * 80)

    # Aggregate papers
    all_papers = []
    for q, papers in results["arxiv"].items():
        all_papers.extend(papers)
    print(f"\n[ARXIV] Total papers retrieved: {len(all_papers)}")

    # Show top papers by relevance
    print("\n--- TOP ARXIV PAPERS ---")
    for i, paper in enumerate(all_papers[:15]):
        print(f"\n[{i+1}] {paper['title']}")
        print(f"    Published: {paper['published']} | Categories: {', '.join(paper['categories'][:4])}")
        abstract_preview = paper['abstract'][:200].replace('\n', ' ')
        print(f"    Abstract: {abstract_preview}...")
        print(f"    URL: https://arxiv.org/abs/{paper['arxiv_id']}")

    # Aggregate repos
    all_repos = []
    for q, repos in results["github"].items():
        all_repos.extend(repos)
    # Deduplicate by name
    seen = set()
    unique_repos = []
    for r in all_repos:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique_repos.append(r)
    all_repos = unique_repos
    print(f"\n[GITHUB] Total unique repos retrieved: {len(all_repos)}")

    print("\n--- TOP GITHUB REPOS ---")
    for i, repo in enumerate(all_repos[:10]):
        print(f"\n[{i+1}] {repo['name']}")
        print(f"    Stars: {repo['stars']} | Forks: {repo['forks']} | Lang: {repo['language']}")
        print(f"    Description: {repo['description']}")
        print(f"    URL: {repo['url']}")
        if repo['topics']:
            print(f"    Topics: {', '.join(repo['topics'][:6])}")

    # Save full results
    output_path = "data/recon/phase8_3_recon_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[SAVED] Full results to {output_path}")


if __name__ == "__main__":
    main()