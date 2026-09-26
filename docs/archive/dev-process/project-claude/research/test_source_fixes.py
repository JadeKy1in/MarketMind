"""Test all candidate fix URLs for 20 failed/empty MarketMind sources."""
import asyncio, json, sys, io, httpx, feedparser

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CANDIDATES = [
    # === China alternatives ===
    {'id': '01-Caixin-Global', 'orig': 'Caixin Global (RSSHub)', 'url': 'https://rsshub.rssforever.com/caixinglobal/latest', 'type': 'rss', 'region': 'CN', 'domain': 'China Financial News', 'method': 'alt-rsshub'},
    # 2. Caixin Finance - Google News proxy
    {'id': '02-Caixin-Finance', 'orig': 'Caixin Finance (RSSHub)', 'url': 'https://news.google.com/rss/search?q=Caixin+China+finance+banking&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'CN', 'domain': 'China Finance/Banking', 'method': 'google-news'},
    # 3. PBOC - Google News proxy
    {'id': '03-PBOC', 'orig': 'PBOC RSS (RSSHub)', 'url': 'https://news.google.com/rss/search?q=PBOC+People+Bank+China+monetary+policy+interest+rate&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'CN', 'domain': 'China Monetary Policy', 'method': 'google-news'},
    # 4. ECNS Business - Google News proxy
    {'id': '04-ECNS-Business', 'orig': 'ECNS Business', 'url': 'https://news.google.com/rss/search?q=China+business+economy+stock+market&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'CN', 'domain': 'China Business/Economy', 'method': 'google-news'},
    # 5. Yicai Global - Google News proxy
    {'id': '05-Yicai-Global', 'orig': 'Yicai Global (RSSHub)', 'url': 'https://news.google.com/rss/search?q=Yicai+Global+China+financial+policy&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'CN', 'domain': 'China Financial Policy', 'method': 'google-news'},
    # 6. China Economic Net - Google News proxy
    {'id': '06-ChinaEcoNet', 'orig': 'China Economic Net', 'url': 'https://news.google.com/rss/search?q=China+economic+data+GDP+CPI+PMI+trade&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'CN', 'domain': 'China Macro Data', 'method': 'google-news'},
    # 7. Xinhua Finance - try English Xinhua RSS + Google News
    {'id': '07a-Xinhua-Eng', 'orig': 'Xinhua Finance (RSSHub)', 'url': 'http://www.xinhuanet.com/english/rss/worldrss.xml', 'type': 'rss', 'region': 'CN', 'domain': 'China State Media', 'method': 'fix-url'},
    {'id': '07b-Xinhua-GN', 'orig': 'Xinhua Finance (RSSHub)', 'url': 'https://news.google.com/rss/search?q=Xinhua+China+economy+finance+policy&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'CN', 'domain': 'China State Media', 'method': 'google-news'},
    # 8. Caixin Original RSS - Google News proxy (official feed returned 406)
    {'id': '08-Caixin-Orig', 'orig': 'Caixin Original RSS', 'url': 'https://news.google.com/rss/search?q=Caixin+PMI+China+manufacturing+services&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'CN', 'domain': 'China PMI/Manufacturing', 'method': 'google-news'},

    # === EU alternatives ===
    # 9. DG Competition - use EC Press Corner (already working, confirmed)
    {'id': '09-EC-DG-COMP', 'orig': 'DG Competition Antitrust', 'url': 'https://ec.europa.eu/commission/presscorner/api/rss', 'type': 'rss', 'region': 'EU', 'domain': 'EU Antitrust/Regulation', 'method': 'alt-source'},
    # 10. Euronews Business - correct URL pattern
    {'id': '10a-Euronews', 'orig': 'Euronews Business', 'url': 'https://www.euronews.com/rss?format=mrss&level=theme&name=business', 'type': 'rss', 'region': 'EU', 'domain': 'EU Business News', 'method': 'fix-url'},
    {'id': '10b-Euronews-GN', 'orig': 'Euronews Business', 'url': 'https://news.google.com/rss/search?q=Euronews+EU+business+economy+eurozone&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'EU', 'domain': 'EU Business News', 'method': 'google-news'},
    # 11. Eurostat RSS - cache URL + Google News
    {'id': '11a-Eurostat', 'orig': 'Eurostat RSS', 'url': 'https://ec.europa.eu/eurostat/cache/RSS/rss_estat_news.xml', 'type': 'rss', 'region': 'EU', 'domain': 'EU Economic Data', 'method': 'fix-url'},
    {'id': '11b-Eurostat-GN', 'orig': 'Eurostat RSS', 'url': 'https://news.google.com/rss/search?q=Eurostat+EU+eurozone+GDP+inflation+CPI+economic+data&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'EU', 'domain': 'EU Economic Data', 'method': 'google-news'},

    # === EM alternatives ===
    # 12. Brazil BCB - specific feeds
    {'id': '12a-BCB-Copom', 'orig': 'Brazil BCB RSS', 'url': 'https://www.bcb.gov.br/api/feed/sitebcb/sitefeedsen/copomstatements', 'type': 'rss', 'region': 'EM', 'domain': 'Brazil Monetary Policy', 'method': 'fix-url'},
    {'id': '12b-BCB-Infl', 'orig': 'Brazil BCB RSS', 'url': 'https://www.bcb.gov.br/api/feed/sitebcb/sitefeedsen/inflationreport', 'type': 'rss', 'region': 'EM', 'domain': 'Brazil Economy', 'method': 'fix-url'},
    # 13. South Africa SARB
    {'id': '13-SARB-GN', 'orig': 'South Africa SARB RSS', 'url': 'https://news.google.com/rss/search?q=South+Africa+Reserve+Bank+SARB+monetary+policy+repo+rate&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'EM', 'domain': 'S.Africa Monetary Policy', 'method': 'google-news'},
    # 14. World Bank - API + Google News
    {'id': '14-WB-GN', 'orig': 'World Bank News RSS', 'url': 'https://news.google.com/rss/search?q=World+Bank+development+emerging+markets+economy&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'EM', 'domain': 'Global Development', 'method': 'google-news'},
    # 15. Trading Economics - Google News
    {'id': '15-TradingEcon', 'orig': 'Trading Economics RSS', 'url': 'https://news.google.com/rss/search?q=economic+indicators+emerging+markets+GDP+inflation+central+bank&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'EM', 'domain': 'EM Economic Data', 'method': 'google-news'},
    # 16. OPEC - official RSS + Google News
    {'id': '16a-OPEC', 'orig': 'OPEC Monthly Report', 'url': 'https://www.opec.org/opec_web/en/feeds.htm', 'type': 'rss', 'region': 'EM', 'domain': 'Oil/Energy', 'method': 'fix-url'},
    {'id': '16b-OPEC-GN', 'orig': 'OPEC Monthly Report', 'url': 'https://news.google.com/rss/search?q=OPEC+oil+production+crude+Saudi+monthly+report&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'EM', 'domain': 'Oil/Energy', 'method': 'google-news'},

    # === Empty source alternatives ===
    # 17. SCMP - specific category IDs
    {'id': '17a-SCMP-Biz', 'orig': 'SCMP RSS', 'url': 'https://www.scmp.com/rss/4/feed', 'type': 'rss', 'region': 'CN', 'domain': 'China/HK Business', 'method': 'fix-url'},
    {'id': '17b-SCMP-News', 'orig': 'SCMP RSS', 'url': 'https://www.scmp.com/rss/91/feed', 'type': 'rss', 'region': 'CN', 'domain': 'China/HK News', 'method': 'fix-url'},
    # 18. EUobserver - WordPress default feed
    {'id': '18-EUobserver', 'orig': 'EUobserver Business', 'url': 'https://euobserver.com/feed/', 'type': 'rss', 'region': 'EU', 'domain': 'EU Politics/Policy', 'method': 'fix-url'},
    # 19. India RBI - Liferay RSS + Google News
    {'id': '19a-RBI-Life', 'orig': 'India RBI RSS', 'url': 'https://website.rbi.org.in/web/rbi/press-releases/-/asset_publisher/0uAO/rss', 'type': 'rss', 'region': 'EM', 'domain': 'India Monetary Policy', 'method': 'fix-url'},
    {'id': '19b-RBI-GN', 'orig': 'India RBI RSS', 'url': 'https://news.google.com/rss/search?q=Reserve+Bank+India+RBI+repo+rate+monetary+policy+MPC&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'EM', 'domain': 'India Monetary Policy', 'method': 'google-news'},
    # 20. IMF News - try direct + Google News
    {'id': '20a-IMF-RSS', 'orig': 'IMF News RSS', 'url': 'https://www.imf.org/en/News/RSS', 'type': 'rss', 'region': 'EM', 'domain': 'Global Macro/IMF', 'method': 'fix-url'},
    {'id': '20b-IMF-GN', 'orig': 'IMF News RSS', 'url': 'https://news.google.com/rss/search?q=IMF+International+Monetary+Fund+global+economy+WEO+World+Economic+Outlook&hl=en-US&gl=US&ceid=US:en', 'type': 'rss', 'region': 'EM', 'domain': 'Global Macro/IMF', 'method': 'google-news'},
]

async def test_source(c):
    """Test a single source. Return result dict."""
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(c['url'], headers={'User-Agent': 'MarketMind/0.1 (contact@marketmind.dev)'})
            if resp.status_code >= 400:
                return {'status': 'FAILED', 'articles': 0, 'detail': f'HTTP {resp.status_code}', 'http_code': resp.status_code}
            text = resp.text
            f = feedparser.parse(text)
            entries = f.entries
            n = len(entries)
            if n == 0:
                return {'status': 'EMPTY', 'articles': 0, 'detail': f'Parsed 0 entries ({len(text)} bytes)', 'http_code': resp.status_code}
            title = entries[0].get('title', '?')[:100]
            return {'status': 'WORKING', 'articles': n, 'detail': title, 'http_code': resp.status_code}
    except httpx.ConnectError:
        return {'status': 'FAILED', 'articles': 0, 'detail': 'Connection refused / DNS failed', 'http_code': -1}
    except httpx.TimeoutException:
        return {'status': 'FAILED', 'articles': 0, 'detail': 'Timeout (20s)', 'http_code': -1}
    except Exception as e:
        return {'status': 'FAILED', 'articles': 0, 'detail': str(e)[:150], 'http_code': -1}

async def main():
    print(f'Testing {len(CANDIDATES)} candidate fix URLs...\n')
    results = []
    for c in CANDIDATES:
        r = await test_source(c)
        entry = {**c, **r}
        results.append(entry)
        marker = { 'WORKING': '✅', 'FAILED': '❌', 'EMPTY': '⚠️' }.get(r['status'], '?')
        print(f'{marker} {c["id"]:22s} [{c["region"]}] HTTP{r["http_code"]:4d}  {r["articles"]:3d} arts  {r["detail"][:80]}')

    print(f'\n{"="*70}')
    print(f'  RESULTS: {sum(1 for r in results if r["status"]=="WORKING")} working | '
          f'{sum(1 for r in results if r["status"]=="EMPTY")} empty | '
          f'{sum(1 for r in results if r["status"]=="FAILED")} failed')
    print(f'{"="*70}\n')

    working = [r for r in results if r['status'] == 'WORKING']
    for r in working:
        print(f'  ✅ {r["id"]:22s} [{r["region"]}] {r["articles"]:3d} articles — '
              f'{r["domain"]:30s} ({r["orig"]})')

    # Save JSON results
    with open('E:/AI_Studio_Workspace/.claude/research/source-fix-results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f'\nJSON results saved.')

asyncio.run(main())
