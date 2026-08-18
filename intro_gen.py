"""公司介绍生成器（01 规范 F8 v1.2 / 02 规范 v1.3 / 05 规范 §10）

调 DeepSeek API（Anthropic Messages 兼容接口）生成公司介绍 JSON：
- 个股条目 schema 与知识库人工条目一致（knowledge/stocks/<code>.json）
- 行业卡 schema 与人工行业卡一致（knowledge/industries/<行业>.json）
失败（无密钥/断网/返回不合法）一律返回 None，由调用方回退。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent
KEY_PATH = ROOT / ".deepseek_key"
API_URL = "https://api.deepseek.com/anthropic/v1/messages"
MODEL = "deepseek-v4-flash"
TIMEOUT = 60
MAX_TOKENS = 3000


def api_key() -> Optional[str]:
    """读取 DeepSeek 密钥（.deepseek_key，git 忽略）；缺失返回 None。"""
    try:
        key = KEY_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return key or None


def _parse_text_blocks(resp: dict) -> Optional[str]:
    """从 Anthropic Messages 响应中拼出文本（跳过 thinking 块）。"""
    try:
        text = "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text")
    except (KeyError, TypeError):
        return None
    return text or None


def _call_once(system: str, user: str) -> Optional[str]:
    """单次 API 调用，返回纯文本；无密钥或请求失败返回 None。"""
    key = api_key()
    if not key:
        return None
    try:
        r = requests.post(
            API_URL,
            headers={
                "content-type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return _parse_text_blocks(r.json())
    except (requests.RequestException, ValueError):
        return None


def _extract_json(text: str) -> Optional[dict]:
    """从模型输出中提取 JSON：剥 ``` 围栏 → json.loads → 兜底取首个 {…} 段。"""
    t = text.strip()
    if t.startswith("```"):
        t = "\n".join(ln for ln in t.splitlines() if not ln.strip().startswith("```")).strip()
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else None
    except ValueError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(t[start:end + 1])
            return data if isinstance(data, dict) else None
        except ValueError:
            return None
    return None
