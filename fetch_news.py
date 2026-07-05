"""
Power Platform ニュース ダイジェスト - RSS フィード取得スクリプト

対象フィード:
  1. Power Platform Blog (powerapps.microsoft.com/en-us/blog/feed/)
  2. Power Platform Developer Blog (devblogs.microsoft.com/powerplatform/feed/)

機械翻訳: DeepL API (Free)
  - 製品名・固有名詞・技術用語は用語集(glossary)で英語のまま保持
  - 用語集は create_glossary.py で一度だけ作成し、glossary_id を環境変数で渡す
翻訳キャッシュ:
  - 既存 docs/news.json を読み込み、原文(titleOriginal)が一致する記事は既訳を再利用
出力: docs/news.json

必要な環境変数:
  DEEPL_API_KEY      : DeepL の認証キー (末尾 :fx が付くのが Free 版)
  DEEPL_GLOSSARY_ID  : (任意) create_glossary.py が出力した glossary_id
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape


# ========== DeepL 設定 ==========
DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "").strip()
DEEPL_GLOSSARY_ID = os.environ.get("DEEPL_GLOSSARY_ID", "").strip()
# Free 版はキー末尾が ":fx"。それに応じてエンドポイントを切り替える
DEEPL_ENDPOINT = (
    "https://api-free.deepl.com/v2/translate"
    if DEEPL_API_KEY.endswith(":fx")
    else "https://api.deepl.com/v2/translate"
)


FEEDS = [
    {
        "url": "https://powerapps.microsoft.com/en-us/blog/feed/",
        "source": "Blog",
    },
    {
        "url": "https://devblogs.microsoft.com/powerplatform/feed/",
        "source": "DevBlog",
    },
]

# 製品判定キーワード
PRODUCT_KEYWORDS = {
    "Power Apps": ["power apps", "powerapps", "canvas app", "model-driven", "model driven", "code apps"],
    "Power Automate": ["power automate", "process mining", "rpa", "desktop flow", "cloud flow"],
    "Copilot Studio": ["copilot studio", "copilot", "virtual agent", "pva"],
    "Power Pages": ["power pages", "portal"],
    "Dataverse": ["dataverse", "common data service", "cds"],
    "AI Builder": ["ai builder"],
    "管理・ガバナンス": ["admin", "governance", "dlp", "managed environment", "tenant", "ppac",
                         "admin center", "security", "compliance", "licensing"],
}

PRODUCT_PRIORITY = [
    "Power Apps", "Power Automate", "Copilot Studio", "Power Pages",
    "Dataverse", "AI Builder", "管理・ガバナンス",
]

# 英語のまま残すキーワード (約110ワード)
# create_glossary.py がこの一覧から DeepL の用語集(glossary)を作成する。
# 各語を「英語→同じ英語」の対応として登録することで、翻訳時に英語のまま保持される。
# ここを更新したら create_glossary.py を再実行し、新しい glossary_id を設定すること。
KEEP_ENGLISH_KEYWORDS = [
    # ========== Microsoft製品・プラットフォーム ==========
    "Microsoft Power Platform",
    "Microsoft 365 Copilot",
    "Microsoft Power Apps",
    "Microsoft Dataverse",
    "Microsoft Copilot Studio",
    "Microsoft Teams",
    "Microsoft Entra",
    "Microsoft Fabric",
    "Microsoft Learn",
    "Power Platform",
    "Power Apps",
    "Power Automate",
    "Power Automate for desktop",
    "Power Apps Studio",
    "Power Platform admin center",
    "Power Platform CLI",
    "Power Platform inventory",
    "Copilot Studio",
    "Power Pages",
    "Dataverse",
    "Dataverse SDK",
    "Dataverse Search",
    "Dataverse accelerator",
    "AI Builder",
    "Power BI",
    "Power Fx",
    "Dynamics 365",

    # ========== Azure関連 ==========
    "Azure OpenAI",
    "Azure AI Foundry",
    "Azure AI Services",
    "Azure Synapse Link",
    "Azure Synapse",
    "Azure Data Lake",
    "Azure App Insights",
    "Entra ID",

    # ========== 外部ツール・サービス ==========
    "GitHub Copilot CLI",
    "GitHub Copilot",
    "Claude Code",
    "Visual Studio Code",
    "VS Code extension",
    "VS Code",
    "vibe.powerapps.com",

    # ========== 機能・コンポーネント ==========
    "Agent Academy",
    "Agent Feed",
    "Agent Flows",
    "Agent API",
    "Plan Designer",
    "Plan designer",
    "Canvas Apps",
    "Canvas App",
    "Model-driven Apps",
    "Model-driven App",
    "Model-driven",
    "Managed Environments",
    "Managed Environment",
    "Admin Center",
    "Enhanced Component Properties",
    "Component Library",
    "Security Compliance",
    "Power Platform Advisor",
    "Code Apps",
    "Cloud Flow",
    "Desktop Flow",
    "Agent Flow",
    "Server Logic",
    "Process Mining",
    "Object-Centric Process Mining",
    "OCPM",
    "Process Intelligence",
    "Work IQ",
    "Generative Page",
    "generative pages",
    "modern controls",
    "Web API",
    "Web Template",
    "Web Application Firewall",
    "Content Security Policy",
    "Virtual Network",

    # ========== モダンコントロール名 ==========
    "Combo Box",
    "Date Picker",
    "Text Input",
    "Number Input",
    "Tab List",
    "Info Button",

    # ========== セキュリティ・ガバナンス ==========
    "Role-based access control",
    "Run-only user role",
    "Managed identities",

    # ========== 技術プロトコル・用語 ==========
    "Model Context Protocol",
    "MCP Server",
    "MCP",
    "FetchXML",
    "Dataflows",
    "Dataflow",
    "Connectors",
    "Connector",
    "Liquid",
    "REST API",
    "OAuth 2.0",
    "IntelliSense",
    "npm CLI",

    # ========== ステータス・リリース用語 ==========
    "General Availability",
    "Generally Available",
    "Public Preview",

    # ========== 略語・短い用語 ==========
    "Copilot",
    "Agents",
    "Agent",
    "Workflows",
    "Workflow",
    "DLP",
    "ALM",
    "SDK",
    "API",
    "RSS",
    "GA",
    "OAuth",
    "SSO",
    "MFA",
    "KPI",
    "DNA",
    "ERP",
    "React",
    "TypeScript",
    "JavaScript",
]


def fetch_feed(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PPNewsDigest/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def strip_html(text: str) -> str:
    text = unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    # WordPress RSS 定番の "The post ... appeared first on ..." 定型文を除去
    # (翻訳すると「投稿 ... 最初に表示されました」というゴミになるため翻訳前に落とす)
    text = re.sub(r"The post\s+.*?appeared first on.*$", "", text,
                  flags=re.IGNORECASE | re.DOTALL)
    # "Read more" / "Continue reading" などの末尾リンク文言も除去
    text = re.sub(r"(Read more|Continue reading)\b.*$", "", text,
                  flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def looks_translated(s: str) -> bool:
    """日本語(ひらがな/カタカナ/漢字)を含むかで翻訳済みかを判定する"""
    return bool(re.search(r"[぀-ヿ㐀-鿿]", s or ""))


def translate_batch(texts: list) -> list:
    """
    複数テキストをまとめて英語→日本語に翻訳する (DeepL API)。
    固有名詞は glossary (DEEPL_GLOSSARY_ID) で英語のまま保持される。
    失敗時は入力テキストをそのまま返す (英語のまま表示)。
    """
    # 空でない要素だけ翻訳対象にし、インデックスを保持
    indexed = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
    result = list(texts)
    if not indexed:
        return result
    if not DEEPL_API_KEY:
        print("  DEEPL_API_KEY 未設定のため翻訳をスキップします", file=sys.stderr)
        return result

    payload = {
        "text": [t for _, t in indexed],
        "source_lang": "EN",   # glossary 利用時は source_lang 必須
        "target_lang": "JA",
    }
    if DEEPL_GLOSSARY_ID:
        payload["glossary_id"] = DEEPL_GLOSSARY_ID

    try:
        req = urllib.request.Request(
            DEEPL_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"DeepL-Auth-Key {DEEPL_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "PPNewsDigest/2.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        translations = data.get("translations", [])
        for (orig_idx, _), tr in zip(indexed, translations):
            translated = (tr.get("text") or "").strip()
            if translated:
                result[orig_idx] = translated
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        print(f"  DeepL HTTP {e.code}: {body}", file=sys.stderr)
    except Exception as e:
        print(f"  Translation failed: {e}", file=sys.stderr)
    return result


def detect_products(title: str, summary: str) -> list:
    combined = (title + " " + summary).lower()
    matched = []
    for product in PRODUCT_PRIORITY:
        keywords = PRODUCT_KEYWORDS[product]
        for kw in keywords:
            if kw in combined:
                if product not in matched:
                    matched.append(product)
                break
    return matched


def parse_date(date_str: str) -> str:
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_rss(xml_bytes: bytes, source: str, cache: dict) -> list:
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  XML parse error for {source}: {e}", file=sys.stderr)
        return items

    for item_el in root.findall(".//item"):
        title_el = item_el.find("title")
        link_el = item_el.find("link")
        desc_el = item_el.find("description")
        pub_el = item_el.find("pubDate")

        title_en = title_el.text.strip() if title_el is not None and title_el.text else ""
        link = link_el.text.strip() if link_el is not None and link_el.text else ""
        desc_en = strip_html(desc_el.text) if desc_el is not None and desc_el.text else ""
        date = parse_date(pub_el.text) if pub_el is not None and pub_el.text else ""

        if not title_en:
            continue

        products = detect_products(title_en, desc_en)
        primary_product = products[0] if products else "Power Platform"

        summary_en = desc_en[:300] + "..." if len(desc_en) > 300 else desc_en

        # --- 翻訳キャッシュ: 原文が前回と一致し、かつ実際に翻訳済みなら再利用 ---
        # 翻訳失敗で英語のまま保存された項目 (looks_translated が False) は
        # キャッシュ扱いにせず再翻訳する。これによりキー未設定で汚れたキャッシュが自己修復する。
        prev = cache.get(link)
        if (prev and prev.get("titleOriginal") == title_en
                and prev.get("summaryOriginal") == summary_en
                and prev.get("title") and prev.get("summary")
                and (looks_translated(prev.get("title")) or looks_translated(prev.get("summary")))):
            title_ja = prev["title"]
            summary_ja = prev["summary"]
            print(f"  Cached:      {title_en[:60]}...")
        else:
            print(f"  Translating: {title_en[:60]}...")
            title_ja, summary_ja = translate_batch([title_en, summary_en])
            time.sleep(0.3)

        items.append({
            "date": date,
            "title": title_ja,
            "titleOriginal": title_en,
            "summary": summary_ja,
            "summaryOriginal": summary_en,
            "product": primary_product,
            "tags": products,
            "url": link,
            "source": source,
        })

    return items


def load_cache(path: str) -> dict:
    """既存 news.json を url -> item の辞書として読み込む (翻訳キャッシュ用)"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {it["url"]: it for it in data.get("items", []) if it.get("url")}
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {}


def main():
    output_path = "docs/news.json"
    cache = load_cache(output_path)
    if cache:
        print(f"Cache: {len(cache)} previously translated items loaded")

    all_items = []

    for feed in FEEDS:
        print(f"Fetching: {feed['url']}")
        try:
            xml_bytes = fetch_feed(feed["url"])
            items = parse_rss(xml_bytes, feed["source"], cache)
            print(f"  Found {len(items)} items")
            all_items.extend(items)
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)

    all_items.sort(key=lambda x: x["date"], reverse=True)

    seen_urls = set()
    unique_items = []
    for item in all_items:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            unique_items.append(item)

    output = {
        "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "totalCount": len(unique_items),
        "translationNote": "タイトル・要約はDeepLによる機械翻訳です (固有名詞は英語のまま保持)",
        "items": unique_items,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nOutput: {output_path} ({len(unique_items)} items)")


if __name__ == "__main__":
    main()
