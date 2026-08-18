#!/usr/bin/env python3
"""阶段 7 离线验收脚本（不调真实 API，不产生费用）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

import intro_gen
import knowledge

FAILED = []


def check(name: str, cond: bool) -> None:
    print(("  ✓ " if cond else "  ✗ ") + name)
    if not cond:
        FAILED.append(name)


def _test_knowledge_save() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="verify_intro_"))
    knowledge.STOCK_DIR = tmp / "stocks"
    knowledge.INDUSTRY_DIR = tmp / "industries"
    entry = {"code": "600000", "name": "测试银行", "what": "一家银行。", "life": "你可能在街边见过它。",
             "products": ["存款", "贷款"],
             "upstream": [{"name": "储户", "role": "提供资金"}],
             "downstream": [{"name": "借款人", "role": "使用贷款"}]}
    check("save_stock 新条目写入成功", knowledge.save_stock(entry) is True)
    check("save_stock 已存在跳过（不覆盖）", knowledge.save_stock(entry) is False)
    loaded = knowledge.load_stock("600000")
    check("load_stock 读回内容一致", loaded == entry)
    check("save_stock 不覆盖原内容", loaded["what"] == "一家银行。")
    card = {"industry": "测试行业", "what": "x", "money": "y", "products": "z",
            "upstream": ["甲"], "downstream": ["乙"]}
    check("save_industry 写入成功", knowledge.save_industry(card) is True)
    check("save_industry 已存在跳过", knowledge.save_industry(card) is False)
    check("save_industry 中文文件名可读回", knowledge.load_industry("测试行业") == card)
    check("save_stock 缺 code 拒绝", knowledge.save_stock({"name": "x"}) is False)
    check("save_industry 缺 industry 拒绝", knowledge.save_industry({"what": "x"}) is False)


class _FakeRequests:
    """替代 intro_gen.requests：记录调用、返回预设响应。"""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResp(self.payload)


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _setup_requests(payload):
    """临时替换 intro_gen.requests 与 api_key，返回 (fake, restore)。"""
    orig_requests, orig_key = intro_gen.requests, intro_gen.api_key
    fake = _FakeRequests(payload)
    intro_gen.requests = fake
    intro_gen.api_key = lambda: "sk-test"

    def restore():
        intro_gen.requests = orig_requests
        intro_gen.api_key = orig_key

    return fake, restore


def _test_parse_and_extract() -> None:
    resp = {"content": [
        {"type": "thinking", "thinking": "思考中…"},
        {"type": "text", "text": "{"},
        {"type": "text", "text": '"a": 1}'},
    ]}
    check("_parse_text_blocks 跳过 thinking 并拼接", intro_gen._parse_text_blocks(resp) == '{"a": 1}')
    check("_parse_text_blocks 坏结构返回 None", intro_gen._parse_text_blocks({}) is None)
    check("_extract_json 纯 JSON", intro_gen._extract_json('{"a": 1}') == {"a": 1})
    check("_extract_json 代码围栏", intro_gen._extract_json('```json\n{"b": 2}\n```') == {"b": 2})
    check("_extract_json 前后杂文", intro_gen._extract_json('好的，以下是内容：\n{"c": 3}') == {"c": 3})
    check("_extract_json 非法返回 None", intro_gen._extract_json("不是 JSON") is None)
    check("_extract_json 数组返回 None", intro_gen._extract_json("[1,2]") is None)


def _test_api_key_and_call() -> None:
    orig_path = intro_gen.KEY_PATH
    tmp = Path(tempfile.mkdtemp(prefix="verify_key_"))
    intro_gen.KEY_PATH = tmp / "key"
    try:
        check("api_key 无文件返回 None", intro_gen.api_key() is None)
        (tmp / "key").write_text("  sk-abc123 \n", encoding="utf-8")
        check("api_key 读取并去空白", intro_gen.api_key() == "sk-abc123")
    finally:
        intro_gen.KEY_PATH = orig_path
    fake, restore = _setup_requests({"content": [
        {"type": "thinking", "thinking": "x"},
        {"type": "text", "text": "回复文本"},
    ]})
    try:
        check("_call_once 成功返回文本", intro_gen._call_once("sys", "u") == "回复文本")
        url, kw = fake.calls[0]
        check("_call_once 请求 URL 正确", url == intro_gen.API_URL)
        check("_call_once 模型与请求头正确",
              kw["json"]["model"] == intro_gen.MODEL
              and kw["headers"]["x-api-key"] == "sk-test"
              and kw["headers"]["anthropic-version"] == "2023-06-01")
        check("_call_once 带 system 与 user 消息",
              kw["json"]["system"] == "sys" and kw["json"]["messages"] == [{"role": "user", "content": "u"}])
        intro_gen.api_key = lambda: None
        check("_call_once 无密钥不发请求", intro_gen._call_once("s", "u") is None and len(fake.calls) == 1)
    finally:
        restore()


def _test_validate() -> None:
    good = {"what": "一句话", "life": "钩子", "products": ["A", "B"],
            "upstream": [{"name": "甲", "role": "r"}],
            "downstream": [{"name": "乙", "role": "r"}]}
    out = intro_gen._validate_stock(good, "600001", "测试股")
    check("_validate_stock 合法通过且带真实 code/name",
          out is not None and out["code"] == "600001" and out["name"] == "测试股")
    check("_validate_stock 覆盖模型自报 code/name",
          intro_gen._validate_stock({**good, "code": "X", "name": "Y"}, "600001", "测试股")["code"] == "600001")
    check("_validate_stock 缺 life 拒绝", intro_gen._validate_stock({**good, "life": ""}, "600001", "测试股") is None)
    check("_validate_stock products 非列表拒绝", intro_gen._validate_stock({**good, "products": "AB"}, "600001", "测试股") is None)
    check("_validate_stock upstream 缺 role 拒绝",
          intro_gen._validate_stock({**good, "upstream": [{"name": "甲"}]}, "600001", "测试股") is None)
    good_ind = {"what": "w", "money": "m", "products": "p", "upstream": ["a"], "downstream": ["b"]}
    check("_validate_industry 合法通过且带真实行业名",
          intro_gen._validate_industry(good_ind, "测试行业")["industry"] == "测试行业")
    check("_validate_industry 缺 money 拒绝", intro_gen._validate_industry({**good_ind, "money": ""}, "测试行业") is None)


def _test_gen_retry() -> None:
    good = json.dumps({"what": "w", "life": "l", "products": ["p"],
                       "upstream": [{"name": "a", "role": "r"}],
                       "downstream": [{"name": "b", "role": "r"}]}, ensure_ascii=False)
    replies = iter([
        {"content": [{"type": "text", "text": "不是 JSON"}]},
        {"content": [{"type": "text", "text": good}]},
    ])
    fake, restore = _setup_requests(None)
    fake.post = lambda url, **kw: _FakeResp(next(replies))
    try:
        entry = intro_gen.gen_stock({"code": "600001", "name": "测试股", "industry": "测试行业"})
        check("gen_stock 首次不合法后重试成功", entry is not None and entry["code"] == "600001")
    finally:
        restore()
    fake2, restore2 = _setup_requests({"content": [{"type": "text", "text": "垃圾"}]})
    try:
        check("gen_stock 两次不合法返回 None（只调 2 次）",
              intro_gen.gen_stock({"code": "1", "name": "x"}) is None and len(fake2.calls) == 2)
    finally:
        restore2()


def main() -> int:
    _test_knowledge_save()
    _test_parse_and_extract()
    _test_api_key_and_call()
    _test_validate()
    _test_gen_retry()
    if FAILED:
        print(f"\n{len(FAILED)} 项失败：")
        for name in FAILED:
            print("  -", name)
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
