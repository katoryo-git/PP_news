"""
DeepL 用語集(glossary)作成ヘルパー — 一度だけ実行するスクリプト

fetch_news.py の KEEP_ENGLISH_KEYWORDS を「英語→同じ英語」の対応として
DeepL に登録し、glossary_id を出力する。
出力された ID を GitHub Secrets の DEEPL_GLOSSARY_ID に登録して使う。

使い方 (Windows PowerShell):
    $env:DEEPL_API_KEY = "あなたのキー:fx"
    python create_glossary.py

KEEP_ENGLISH_KEYWORDS を更新したら本スクリプトを再実行し、
新しい glossary_id を DEEPL_GLOSSARY_ID に差し替えること
(DeepL の glossary は不変。古いものは残るので、必要なら手動削除)。

注意:
    DeepL の glossary は言語ペアによって対応可否がある。
    本スクリプトは作成前に EN→JA が対応しているか API で検証する。
    非対応の場合は glossary を使わず、fetch_news.py 側で DEEPL_GLOSSARY_ID を
    空のままにすれば DeepL 素の翻訳で動作する
    (製品名を英語で保持したい場合は tag_handling 方式への切り替えを検討)。
"""

import json
import os
import sys
import urllib.error
import urllib.request

from fetch_news import KEEP_ENGLISH_KEYWORDS

DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "").strip()
IS_FREE = DEEPL_API_KEY.endswith(":fx")
BASE = "https://api-free.deepl.com" if IS_FREE else "https://api.deepl.com"

GLOSSARY_NAME = "pp-news-en-ja"
SOURCE_LANG = "en"
TARGET_LANG = "ja"


def _request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={
            "Authorization": f"DeepL-Auth-Key {DEEPL_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "PPNewsDigest-glossary/1.0",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def check_language_pair_supported() -> bool:
    """EN→JA が glossary 対応ペアか確認"""
    try:
        data = _request("GET", "/v2/glossary-language-pairs")
    except Exception as e:
        print(f"言語ペアの確認に失敗: {e}", file=sys.stderr)
        return False
    pairs = data.get("supported_languages", [])
    for p in pairs:
        if (p.get("source_lang", "").lower() == SOURCE_LANG
                and p.get("target_lang", "").lower() == TARGET_LANG):
            return True
    return False


def build_entries_tsv() -> str:
    """KEEP_ENGLISH_KEYWORDS を「英語 <TAB> 同じ英語」の TSV にする (重複除去)"""
    seen = set()
    lines = []
    for kw in KEEP_ENGLISH_KEYWORDS:
        kw = kw.strip()
        # source term は一意でなければならない (大文字小文字も区別される)
        if not kw or kw in seen or "\t" in kw or "\n" in kw:
            continue
        seen.add(kw)
        lines.append(f"{kw}\t{kw}")
    return "\n".join(lines)


def main():
    if not DEEPL_API_KEY:
        print("DEEPL_API_KEY が未設定です。環境変数に設定してから実行してください。",
              file=sys.stderr)
        sys.exit(1)

    print(f"エンドポイント: {BASE} ({'Free' if IS_FREE else 'Pro'})")

    if not check_language_pair_supported():
        print("\n⚠️ EN→JA は現在この DeepL アカウントの glossary 対応ペアに含まれていません。")
        print("   glossary は使えません。以下いずれかで対応してください:")
        print("   1) DEEPL_GLOSSARY_ID を空のままにして DeepL 素の翻訳で運用")
        print("      (DeepL は素でも製品名を英語で残す精度が高い)")
        print("   2) fetch_news.py を tag_handling + ignore_tags 方式に切り替える")
        sys.exit(2)

    entries = build_entries_tsv()
    count = len(entries.splitlines())
    print(f"用語集エントリ数: {count}")

    try:
        result = _request("POST", "/v2/glossaries", {
            "name": GLOSSARY_NAME,
            "source_lang": SOURCE_LANG,
            "target_lang": TARGET_LANG,
            "entries": entries,
            "entries_format": "tsv",
        })
    except urllib.error.HTTPError as e:
        print(f"作成に失敗 HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}",
              file=sys.stderr)
        sys.exit(1)

    glossary_id = result.get("glossary_id", "")
    print("\n✅ glossary を作成しました")
    print(f"   name        : {result.get('name')}")
    print(f"   entry_count : {result.get('entry_count')}")
    print(f"   glossary_id : {glossary_id}")
    print("\n次の手順:")
    print("   GitHub → Settings → Secrets and variables → Actions に")
    print(f"   DEEPL_GLOSSARY_ID = {glossary_id}")
    print("   を登録してください。")


if __name__ == "__main__":
    main()
