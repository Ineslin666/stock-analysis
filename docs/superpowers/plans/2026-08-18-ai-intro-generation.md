# AI 自动补写公司介绍 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每日筛选出 3 只股票后，缺知识库条目时自动调 DeepSeek API（deepseek-v4-flash）生成公司介绍并入库，失败回退终端提醒。

**Architecture:** 新增 `intro_gen.py`（API 调用 + prompt + JSON 校验 + 编排），`knowledge.py` 增加写入函数（只补缺、不覆盖），`scripts/daily_run.py` 覆盖检查升级为"先 AI 补写、仍缺才提醒"，另加 `scripts/gen_intro.py` 手动补写入口。API 为 Anthropic Messages 兼容格式（已实测可用），响应含 thinking 块，解析时仅取 text 块。

**Tech Stack:** Python 3.9（venv）、requests 2.32.5（已有，无新依赖）、DeepSeek API（POST https://api.deepseek.com/anthropic/v1/messages）

**Spec:**
- `文档/01-需求说明.md`（F8 v1.2：内容来源与验收标准）
- `文档/02-技术方案.md`（v1.3：技术选型、目录、数据流、AI 兜底）
- `文档/05-开发计划与执行步骤.md`（§10 阶段 7 执行步骤）

## Global Constraints

- 运行一律用 `.venv/bin/python`（仅 `scripts/devlog.py` 用系统 python3）
- 知识库 JSON schema 与现有条目完全一致：个股 `code/name/what/life/products/upstream[{name,role}]/downstream[{name,role}]`；行业 `industry/what/money/products/upstream[str]/downstream[str]`（参照 `knowledge/stocks/001337.json`、`knowledge/industries/有色金属矿采选业.json`）
- 只补缺、不覆盖：目标文件已存在一律跳过，且跳过时不调 API
- DeepSeek：`POST https://api.deepseek.com/anthropic/v1/messages`；`model=deepseek-v4-flash`；请求头 `x-api-key`（读项目根 `.deepseek_key`，已创建、git 忽略）+ `anthropic-version: 2023-06-01`；单次超时 60 秒；不合法结果重试 1 次；每天最多 6 次调用（3 个股条目 + 最多 3 张行业卡）
- 失败回退：无密钥/断网/返回不合法 → 该条目跳过，不阻塞 daily_run，走现有终端缺条目提醒
- 项目无 pytest：验收脚本 `scripts/verify_intro_gen.py`（断言 + 失败计数，非零退出码）
- git 提交信息沿用项目格式「feat: …（阶段 7.x）」
- 终端输出中文；生成的 JSON 文件 `ensure_ascii=False`、缩进 2、末尾换行（与现有条目格式一致）

---

### Task 1: 7.0 阶段 6 收尾验收（实跑）

**Files:**
- Modify: `文档/05-开发计划与执行步骤.md`（阶段 6 路线图状态行）

**Interfaces:**
- Consumes: 无
- Produces: 阶段 6 正式完成，05 文档阶段 6 状态 ✅

- [ ] **Step 1: 实跑每日脚本，核对终端覆盖提醒**

Run: `.venv/bin/python scripts/daily_run.py`（联网约 3~5 分钟）
Expected: 1/3→2/3→3/3 正常走完，输出今日 3 只；末尾出现 `知识库覆盖完整，公司介绍模块将完整展示。`（今日 3 只已有条目）。若出现 ⚠️ 缺条目提醒，记录缺什么。

- [ ] **Step 2: 用户核对详情页三段与移动端（人工确认点）**

Run: `./start.sh` 后浏览器核对任意一只今日推荐：
- 详情页"这家公司是做什么的？"三段齐全（行业科普卡 / 公司介绍 / 行业里的位置）
- 手机宽度（或浏览器窄窗口）排版正常
- 龙头排名与事实一致（人工抽查：本股排名 + 前三龙头与公开常识对照）
- 免责声明可见
（缺条目优雅隐藏已在 6.4 三场景验证过，此处记录即可）

- [ ] **Step 3: 05 文档阶段 6 状态置完成**

把路线图阶段 6 行 `🟡 实施完成，6.6 验收实跑合并至阶段 7 第一步（2026-08-18）` 改为 `✅ 已完成（2026-08-18，6.6 验收实跑通过见开发日志）`，并把 §9 第 6 条 `⬜ 6.6 验收…` 改为 `✅ 6.6 验收：实跑通过（2026-08-18，见开发日志）`。

- [ ] **Step 4: 提交**

```bash
git add 文档/05-开发计划与执行步骤.md
git commit -m "docs: 阶段 6 验收实跑通过（6.6，阶段 6 完成）"
```

---

### Task 2: knowledge.py 写入函数（save_stock / save_industry）

**Files:**
- Modify: `knowledge.py`（文件末尾追加写入函数）
- Create: `scripts/verify_intro_gen.py`（本任务仅含知识库写入测试）

**Interfaces:**
- Consumes: 无
- Produces:
  - `knowledge.save_stock(entry: dict) -> bool` — entry 含 `code`；文件已存在返回 False（不覆盖）；写入成功返回 True；缺 code 或 IO 失败返回 False
  - `knowledge.save_industry(card: dict) -> bool` — card 含 `industry`；语义同上
  - `knowledge._write(path: Path, data: dict) -> bool` — JSON 落盘（ensure_ascii=False、indent=2、末尾换行）

- [ ] **Step 1: 写失败测试**

创建 `scripts/verify_intro_gen.py`（本任务版本只测 knowledge 写入）：

```python
#!/usr/bin/env python3
"""阶段 7 离线验收脚本（不调真实 API，不产生费用）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


def main() -> int:
    _test_knowledge_save()
    if FAILED:
        print(f"\n{len(FAILED)} 项失败：")
        for name in FAILED:
            print("  -", name)
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python scripts/verify_intro_gen.py`
Expected: FAIL——`AttributeError: module 'knowledge' has no attribute 'save_stock'`

- [ ] **Step 3: 实现**

`knowledge.py` 文件末尾追加（注意：顶部已 import json 与 Path，无需新增 import）：

```python
def save_stock(entry: dict) -> bool:
    """写入个股条目；文件已存在则跳过（不覆盖，人工条目优先）。返回是否写入。"""
    code = entry.get("code")
    if not code:
        return False
    path = STOCK_DIR / f"{code}.json"
    if path.exists():
        return False
    return _write(path, entry)


def save_industry(card: dict) -> bool:
    """写入行业科普卡；文件已存在则跳过（不覆盖）。返回是否写入。"""
    industry = card.get("industry")
    if not industry:
        return False
    path = INDUSTRY_DIR / f"{_safe_name(industry)}.json"
    if path.exists():
        return False
    return _write(path, card)


def _write(path: Path, data: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python scripts/verify_intro_gen.py`
Expected: 全部通过，退出码 0

- [ ] **Step 5: 提交**

```bash
git add knowledge.py scripts/verify_intro_gen.py
git commit -m "feat: knowledge.py 写入函数 save_stock/save_industry（阶段 7.2）"
```

---

### Task 3: intro_gen.py 基础设施（密钥 / 请求 / 解析）

**Files:**
- Create: `intro_gen.py`（本任务先写常量 + api_key + _parse_text_blocks + _call_once + _extract_json）
- Modify: `scripts/verify_intro_gen.py`（追加解析与请求测试）

**Interfaces:**
- Consumes: `knowledge`（不依赖；本任务暂不 import）
- Produces:
  - `intro_gen.API_URL = "https://api.deepseek.com/anthropic/v1/messages"`、`MODEL = "deepseek-v4-flash"`、`TIMEOUT = 60`、`MAX_TOKENS = 3000`、`KEY_PATH = ROOT / ".deepseek_key"`（模块级常量，测试可替换）
  - `intro_gen.api_key() -> Optional[str]` — 读 .deepseek_key 去空白；缺失/IO 错返回 None
  - `intro_gen._parse_text_blocks(resp: dict) -> Optional[str]` — 拼 content 中所有 text 块，跳过 thinking 块
  - `intro_gen._call_once(system: str, user: str) -> Optional[str]` — 单次 POST，无密钥直接 None；网络/HTTP/JSON 异常返回 None
  - `intro_gen._extract_json(text: str) -> Optional[dict]` — 剥 ``` 围栏 → json.loads → 兜底取首个 {…} 段

- [ ] **Step 1: 写失败测试**

`scripts/verify_intro_gen.py` 顶部 import 处（`import knowledge` 之后）加：

```python
import json

import intro_gen
```

并在 `main()` 里 `_test_knowledge_save()` 之后加调用、文件末尾（`main` 之前）加测试函数：

```python
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
```

main() 改为：

```python
def main() -> int:
    _test_knowledge_save()
    _test_parse_and_extract()
    _test_api_key_and_call()
    ...
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python scripts/verify_intro_gen.py`
Expected: FAIL——`ModuleNotFoundError: No module named 'intro_gen'`

- [ ] **Step 3: 实现**

创建 `intro_gen.py`（本任务版本）：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python scripts/verify_intro_gen.py`
Expected: 全部通过，退出码 0

- [ ] **Step 5: 提交**

```bash
git add intro_gen.py scripts/verify_intro_gen.py
git commit -m "feat: intro_gen.py 请求层（密钥/调用/JSON 提取）（阶段 7.1）"
```

---

### Task 4: intro_gen.py 生成与校验（prompt / gen_stock / gen_industry）

**Files:**
- Modify: `intro_gen.py`（追加 prompt 常量、校验函数、生成函数、_with_snapshot）
- Modify: `scripts/verify_intro_gen.py`（追加校验与重试测试）

**Interfaces:**
- Consumes: Task 3 的 `_call_once` / `_extract_json`；`db.get_snapshot_row(code) -> Optional[sqlite3.Row]`、`db.get_finance(code) -> Optional[sqlite3.Row]`（db.py 已有）
- Produces:
  - `intro_gen.gen_stock(stock: dict) -> Optional[dict]` — stock 含 `code`/`name`（industry 可选）；不合法结果重试 1 次（共 2 次调用），仍不合法返回 None；返回条目含规范化后的 code/name（覆盖模型自报值）
  - `intro_gen.gen_industry(industry: str) -> Optional[dict]` — 语义同上
  - `intro_gen._validate_stock(data: dict, code: str, name: str) -> Optional[dict]`
  - `intro_gen._validate_industry(data: dict, industry: str) -> Optional[dict]`
  - `intro_gen._with_snapshot(stock: dict) -> dict` — 用 db 快照/财务字段充实 stock（None 不覆盖已有值）

- [ ] **Step 1: 写失败测试**

`scripts/verify_intro_gen.py` 中追加（`main()` 里加 `_test_validate()` 与 `_test_gen_retry()`）：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python scripts/verify_intro_gen.py`
Expected: FAIL——`AttributeError: module 'intro_gen' has no attribute '_validate_stock'`

- [ ] **Step 3: 实现**

`intro_gen.py` 末尾追加（文件顶部 import 增加 `import db`）：

```python
STOCK_SYSTEM = (
    "你是一位财经科普写手，为完全不懂股票的初学者写 A 股公司介绍。\n"
    "写作要求：\n"
    "1. 语气通俗、生活化，像朋友聊天；出现术语时必须用大白话解释\n"
    "2. 事实部分只使用我提供的数据，禁止编造任何具体数字\n"
    "3. 上下游企业：确定真实存在的才写具体企业名，没把握就写「类别 + 角色」\n"
    "4. 只输出一个 JSON 对象，不要输出任何解释、前后缀文字或代码围栏\n"
    "5. 全部用简体中文，字符串内不要出现换行"
)

INDUSTRY_SYSTEM = (
    "你是一位财经科普写手，为完全不懂股票的初学者写 A 股行业科普卡。\n"
    "写作要求：\n"
    "1. 语气通俗、生活化，像朋友聊天；出现术语时必须用大白话解释\n"
    "2. 只输出一个 JSON 对象，不要输出任何解释、前后缀文字或代码围栏\n"
    "3. 全部用简体中文，字符串内不要出现换行"
)


def _stock_user_prompt(stock: dict) -> str:
    """把库内真实数据拼成事实清单，作为生成的唯一事实依据。"""
    lines = [f"公司名称：{stock.get('name')}", f"股票代码：{stock.get('code')}"]
    if stock.get("industry"):
        lines.append(f"所属行业：{stock['industry']}")
    if stock.get("total_mv"):
        lines.append(f"总市值：{round(stock['total_mv'] / 1e8, 1)} 亿元")
    if stock.get("price"):
        lines.append(f"最新价：{stock['price']} 元")
    if stock.get("pe_ttm"):
        lines.append(f"市盈率 PE(TTM)：{round(stock['pe_ttm'], 1)}")
    if stock.get("pb"):
        lines.append(f"市净率 PB：{round(stock['pb'], 2)}")
    if stock.get("roe_latest") is not None:
        lines.append(f"最新年报 ROE：{round(stock['roe_latest'], 1)}%")
    if stock.get("revenue_cagr3") is not None:
        lines.append(f"近 3 年营收复合增速：{round(stock['revenue_cagr3'], 1)}%")
    if stock.get("profit_cagr3") is not None:
        lines.append(f"近 3 年净利润复合增速：{round(stock['profit_cagr3'], 1)}%")
    if stock.get("gross_margin") is not None:
        lines.append(f"毛利率：{round(stock['gross_margin'], 1)}%")
    if stock.get("net_margin") is not None:
        lines.append(f"净利率：{round(stock['net_margin'], 1)}%")
    if stock.get("dividend_yield") is not None:
        lines.append(f"股息率：{round(stock['dividend_yield'], 2)}%")
    if stock.get("list_date"):
        lines.append(f"上市日期：{stock['list_date']}")
    facts = "\n".join(lines)
    return (
        f"请为这家公司写一条介绍条目，严格按下面的 JSON schema 输出（键名必须完全一致）：\n\n"
        f"【真实数据】\n{facts}\n\n"
        "【JSON schema】\n"
        "{\n"
        '  "what": "一句话通俗介绍这家公司是做什么的（不超过 60 字）",\n'
        '  "life": "生活实感钩子：普通人可能在什么场景接触过它或它的产品，一句话（不超过 50 字）",\n'
        '  "products": ["代表产品或服务 2~4 个"],\n'
        '  "upstream": [{"name": "上游企业名或类别", "role": "它给这家公司提供什么，一句话"}],  // 2~3 个\n'
        '  "downstream": [{"name": "下游企业名或类别", "role": "它买走这家公司的什么、用来做什么，一句话"}]  // 2~3 个\n'
        "}\n\n"
        "【风格示例】（另一只股票的条目）\n"
        "{\n"
        '  "what": "一家在四川木里县山里挖黄金的公司。它把矿山里的矿石挖出来，挑选、富集成含金量更高的金精矿和合质金，再卖给下游的冶炼厂。",\n'
        '  "life": "你可能没机会直接看到它——它不卖金条也不开金店。但你买的金首饰、金条，原材料链条的起点可能就有它挖出来的黄金。",\n'
        '  "products": ["金精矿（初步筛选富集的含金矿石）", "合质金（初步提炼出的黄金半成品）"],\n'
        '  "upstream": [{"name": "采矿设备供应商", "role": "提供挖掘、运输、破碎和选矿设备"}],\n'
        '  "downstream": [{"name": "甘肃招金贵金属冶炼有限公司", "role": "主要客户之一，买走金精矿和合质金进行冶炼提纯"}]\n'
        "}\n\n"
        "只输出 JSON，不要输出其他内容。"
    )


def _industry_user_prompt(industry: str) -> str:
    return (
        f"请为「{industry}」行业写一张科普卡，严格按下面的 JSON schema 输出（键名必须完全一致）：\n\n"
        "【JSON schema】\n"
        "{\n"
        '  "what": "这个行业是做什么的，通俗一句话（不超过 80 字）",\n'
        '  "money": "这个行业靠什么赚钱（不超过 80 字）",\n'
        '  "products": "代表产品，通俗说清是什么（不超过 80 字）",\n'
        '  "upstream": ["上游环节 2~4 个，如「采矿设备与工程服务（挖掘机、选矿设备等）」"],\n'
        '  "downstream": ["下游环节 2~4 个，如「冶炼与精炼企业（把精矿提炼成纯金属）」"]\n'
        "}\n\n"
        "【风格示例】（另一个行业的卡）\n"
        "{\n"
        '  "what": "把埋在地下的金属矿石挖出来、初步挑选富集的行业。黄金、铜、铅锌、稀土这些金属，都要先靠这个行业把矿石从矿山里采出来、做初步加工。",\n'
        '  "money": "主要靠把采选出的精矿卖给下游冶炼企业赚钱。矿产品价格跟着全球金属行情走，矿山的资源储量和开采成本决定了赚多赚少。",\n'
        '  "products": "代表产品有金精矿、铜精矿、铅锌精矿等——通俗说，就是把矿石挑选富集后得到的「半成品金属矿石」。",\n'
        '  "upstream": ["采矿设备与工程服务（挖掘机、选矿设备等）", "电力能源（选矿提纯都要大量用电）"],\n'
        '  "downstream": ["冶炼与精炼企业（把精矿提炼成纯金属）", "金属交易所（如上海黄金交易所）"]\n'
        "}\n\n"
        "只输出 JSON，不要输出其他内容。"
    )


def _validate_stock(data: dict, code: str, name: str) -> Optional[dict]:
    """校验并规范化个股条目；不合法返回 None。code/name 以真实值为准。"""
    if not isinstance(data, dict):
        return None
    what, life = data.get("what"), data.get("life")
    if not (isinstance(what, str) and what.strip() and isinstance(life, str) and life.strip()):
        return None
    products = data.get("products")
    if not (isinstance(products, list) and 1 <= len(products) <= 5
            and all(isinstance(p, str) and p.strip() for p in products)):
        return None
    upstream, downstream = data.get("upstream"), data.get("downstream")
    for chain in (upstream, downstream):
        if not (isinstance(chain, list) and 1 <= len(chain) <= 6
                and all(isinstance(c, dict)
                        and isinstance(c.get("name"), str) and c["name"].strip()
                        and isinstance(c.get("role"), str) and c["role"].strip()
                        for c in chain)):
            return None
    return {
        "code": code, "name": name, "what": what.strip(), "life": life.strip(),
        "products": [p.strip() for p in products],
        "upstream": [{"name": c["name"].strip(), "role": c["role"].strip()} for c in upstream],
        "downstream": [{"name": c["name"].strip(), "role": c["role"].strip()} for c in downstream],
    }


def _validate_industry(data: dict, industry: str) -> Optional[dict]:
    """校验并规范化行业卡；不合法返回 None。行业名以真实值为准。"""
    if not isinstance(data, dict):
        return None
    for key in ("what", "money", "products"):
        v = data.get(key)
        if not (isinstance(v, str) and v.strip()):
            return None
    upstream, downstream = data.get("upstream"), data.get("downstream")
    for chain in (upstream, downstream):
        if not (isinstance(chain, list) and 1 <= len(chain) <= 8
                and all(isinstance(x, str) and x.strip() for x in chain)):
            return None
    return {
        "industry": industry,
        "what": data["what"].strip(), "money": data["money"].strip(),
        "products": data["products"].strip(),
        "upstream": [x.strip() for x in upstream],
        "downstream": [x.strip() for x in downstream],
    }


def gen_stock(stock: dict) -> Optional[dict]:
    """生成个股条目；不合法结果重试 1 次，仍不合法返回 None。"""
    for _ in range(2):
        text = _call_once(STOCK_SYSTEM, _stock_user_prompt(stock))
        if text is None:
            return None
        entry = _validate_stock(_extract_json(text) or {}, stock["code"], stock["name"])
        if entry is not None:
            return entry
    return None


def gen_industry(industry: str) -> Optional[dict]:
    """生成行业科普卡；不合法结果重试 1 次，仍不合法返回 None。"""
    for _ in range(2):
        text = _call_once(INDUSTRY_SYSTEM, _industry_user_prompt(industry))
        if text is None:
            return None
        card = _validate_industry(_extract_json(text) or {}, industry)
        if card is not None:
            return card
    return None


def _with_snapshot(stock: dict) -> dict:
    """用库内快照与财务字段充实事实依据（生成 prompt 用）；库内无该股则原样返回。"""
    out = dict(stock)
    row = db.get_snapshot_row(stock.get("code", ""))
    if row:
        for k in ("name", "industry", "price", "pe_ttm", "pb", "total_mv", "dividend_yield", "list_date"):
            if row[k] is not None and out.get(k) is None:
                out[k] = row[k]
    fin = db.get_finance(stock.get("code", ""))
    if fin:
        for k in ("roe_latest", "revenue_cagr3", "profit_cagr3", "gross_margin", "net_margin"):
            if fin[k] is not None:
                out.setdefault(k, fin[k])
    return out
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python scripts/verify_intro_gen.py`
Expected: 全部通过，退出码 0（`_test_gen_retry` 中 `_with_snapshot` 未被调用；`_test_validate` 纯函数，无需数据库）

- [ ] **Step 5: 提交**

```bash
git add intro_gen.py scripts/verify_intro_gen.py
git commit -m "feat: intro_gen.py 生成与校验层（prompt/gen_stock/gen_industry）（阶段 7.1）"
```

---

### Task 5: intro_gen.py 编排（ensure_coverage / 打印报告）

**Files:**
- Modify: `intro_gen.py`（追加 ensure_coverage、print_entry、print_report；import knowledge）
- Modify: `scripts/verify_intro_gen.py`（追加编排测试）

**Interfaces:**
- Consumes: Task 4 的 `gen_stock`/`gen_industry`；Task 2 的 `knowledge.save_stock`/`save_industry`/`missing_coverage`
- Produces:
  - `intro_gen.ensure_coverage(picked: list) -> dict` — picked 每项含 code/name/industry；返回 `{"generated": [{"type": "stock", "code", "name"} | {"type": "industry", "industry"}], "entries": {code 或行业名: 条目 dict}, "missing": {"stocks": [...], "industries": [...]}, "skipped_no_key": bool}`
  - `intro_gen.print_entry(entry: dict) -> None` — 按个股/行业两种 schema 打印全文
  - `intro_gen.print_report(report: dict, picked: list) -> None` — 终端打印补写报告

- [ ] **Step 1: 写失败测试**

`scripts/verify_intro_gen.py` 顶部 import 区加 `import db`，并追加以下测试函数（`main()` 里在 `_test_validate()` 等之后加 `db.init_db()` 与 `_test_ensure()`）：

```python
def _test_ensure() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="verify_ensure_"))
    knowledge.STOCK_DIR = tmp / "stocks"
    knowledge.INDUSTRY_DIR = tmp / "industries"
    stock_json = json.dumps({"what": "w", "life": "l", "products": ["p"],
                             "upstream": [{"name": "a", "role": "r"}],
                             "downstream": [{"name": "b", "role": "r"}]}, ensure_ascii=False)
    industry_json = json.dumps({"what": "w", "money": "m", "products": "p",
                                "upstream": ["a"], "downstream": ["b"]}, ensure_ascii=False)
    replies = iter([
        {"content": [{"type": "text", "text": stock_json}]},
        {"content": [{"type": "text", "text": industry_json}]},
    ])
    fake, restore = _setup_requests(None)
    fake.post = lambda url, **kw: _FakeResp(next(replies))
    picked = [{"code": "600100", "name": "测试股", "industry": "测试行业"}]
    try:
        r1 = intro_gen.ensure_coverage(picked)
        check("ensure_coverage 补上缺的个股与行业",
              len(r1["generated"]) == 2 and not r1["missing"]["stocks"] and not r1["missing"]["industries"])
        check("ensure_coverage 文件已写入知识库", knowledge.load_stock("600100") is not None)
        r2 = intro_gen.ensure_coverage(picked)
        check("ensure_coverage 幂等（已有条目不再生成、不再请求）",
              r2["generated"] == [] and len(fake.calls) == 2)
    finally:
        restore()
    orig_key = intro_gen.api_key
    intro_gen.api_key = lambda: None
    try:
        r3 = intro_gen.ensure_coverage([{"code": "600200", "name": "乙", "industry": "行业乙"}])
        check("ensure_coverage 无密钥回退为缺失报告",
              r3["skipped_no_key"] is True and r3["missing"]["stocks"] == ["600200"]
              and r3["missing"]["industries"] == ["行业乙"] and r3["generated"] == [])
    finally:
        intro_gen.api_key = orig_key
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python scripts/verify_intro_gen.py`
Expected: FAIL——`AttributeError: module 'intro_gen' has no attribute 'ensure_coverage'`

- [ ] **Step 3: 实现**

`intro_gen.py` 末尾追加（文件顶部 import 增加 `import knowledge`）：

```python
def ensure_coverage(picked: list) -> dict:
    """对当日推荐补写知识库缺条目（只补缺、不覆盖已有文件）。

    返回报告：
    {"generated": [{type, code/industry, name?}], "entries": {key: dict},
     "missing": {"stocks": [...], "industries": [...]}, "skipped_no_key": bool}
    """
    report = {"generated": [], "entries": {},
              "missing": {"stocks": [], "industries": []}, "skipped_no_key": False}
    codes = [x["code"] for x in picked]
    industries = [x.get("industry") for x in picked if x.get("industry")]
    miss = knowledge.missing_coverage(codes, industries)
    if not (miss["stocks"] or miss["industries"]):
        return report
    if api_key() is None:
        report["missing"] = miss
        report["skipped_no_key"] = True
        return report
    by_code = {x["code"]: x for x in picked}
    for code in miss["stocks"]:
        stock = _with_snapshot(by_code.get(code) or {"code": code, "name": code})
        entry = gen_stock(stock)
        if entry is not None and knowledge.save_stock(entry):
            report["generated"].append({"type": "stock", "code": code, "name": entry["name"]})
            report["entries"][code] = entry
        else:
            report["missing"]["stocks"].append(code)
    for ind in miss["industries"]:
        card = gen_industry(ind)
        if card is not None and knowledge.save_industry(card):
            report["generated"].append({"type": "industry", "industry": ind})
            report["entries"][ind] = card
        else:
            report["missing"]["industries"].append(ind)
    return report


def print_entry(entry: dict) -> None:
    """终端打印条目全文（供人工扫一眼；按有无 code 区分个股/行业卡）。"""
    if "code" in entry:
        print(f"    what: {entry['what']}")
        print(f"    life: {entry['life']}")
        print(f"    产品: {'、'.join(entry['products'])}")
        print(f"    上游: {'、'.join(f\"{c['name']}（{c['role']}）\" for c in entry['upstream'])}")
        print(f"    下游: {'、'.join(f\"{c['name']}（{c['role']}）\" for c in entry['downstream'])}")
    else:
        print(f"    what: {entry['what']}")
        print(f"    赚钱: {entry['money']}")
        print(f"    产品: {entry['products']}")
        print(f"    上游: {'、'.join(entry['upstream'])}")
        print(f"    下游: {'、'.join(entry['downstream'])}")


def print_report(report: dict, picked: list) -> None:
    """终端打印 AI 补写报告（daily_run 与 gen_intro.py 共用）。"""
    for g in report["generated"]:
        entry = report["entries"].get(g.get("code") or g.get("industry"))
        if g["type"] == "stock":
            print(f"  ✓ {g['name']} {g['code']} 条目已由 AI 生成并入库：")
        else:
            print(f"  ✓ 行业卡「{g['industry']}」已由 AI 生成并入库：")
        if entry:
            print_entry(entry)
    if report["skipped_no_key"]:
        print("  ℹ️ 未配置 .deepseek_key（项目根目录），AI 补写已跳过")
    miss = report["missing"]
    if not (miss["stocks"] or miss["industries"]):
        print("知识库覆盖完整，公司介绍模块将完整展示。")
        return
    print("⚠️ 知识库仍缺条目（公司介绍模块将降级显示）：")
    if miss["stocks"]:
        names = {x["code"]: x["name"] for x in picked}
        items = [f"{c} {names.get(c, '')}".strip() for c in miss["stocks"]]
        print(f"  · 缺个股条目：{'、'.join(items)}（可运行 scripts/gen_intro.py <代码> 重试）")
    if miss["industries"]:
        print(f"  · 缺行业卡：{'、'.join(miss['industries'])}")
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python scripts/verify_intro_gen.py`
Expected: 全部通过，退出码 0（`_test_ensure` 用临时知识库目录，不触碰真实 knowledge/）

- [ ] **Step 5: 提交**

```bash
git add intro_gen.py scripts/verify_intro_gen.py
git commit -m "feat: intro_gen.py 编排层 ensure_coverage + 终端报告（阶段 7.1）"
```

---

### Task 6: daily_run.py 集成（4/4 步骤）

**Files:**
- Modify: `scripts/daily_run.py`

**Interfaces:**
- Consumes: `intro_gen.ensure_coverage(picked)`、`intro_gen.print_report(report, picked)`
- Produces: 每日流程第 4 步"补全公司介绍（AI 自动补写缺条目）"

- [ ] **Step 1: 修改代码**

`scripts/daily_run.py`：

1. 顶部 import 区（`import knowledge` 之后）加 `import intro_gen`，并删除 `import knowledge`（不再使用，intro_gen 内部已引）——若删除后无其他使用则删，否则保留。
2. 删除整个 `_print_coverage` 函数（第 22~40 行）。
3. 模块 docstring 第一行改为 `"""每日一键运行：刷新快照 → 筛选 3 只 → 生成结论 → AI 补写公司介绍缺条目（幂等，可重复运行）。`
4. main() 末尾改为：

```python
    print("3/3 生成买入结论与参考价位…", flush=True)
    picked = analyzer.run()
    print("=" * 46)
    print("完成！今日 3 只（仅供学习参考，不构成投资建议）：")
    for x in picked:
        print(f"  {x['rank']}. {x['name']} {x['code']} — {VERDICT_TXT[x['verdict']]}")
    print("=" * 46)
    if picked:
        print("4/4 补全公司介绍（缺条目由 AI 自动补写）…", flush=True)
        intro_gen.print_report(intro_gen.ensure_coverage(picked), picked)
    return 0
```

- [ ] **Step 2: 导入自检**

Run: `.venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); sys.path.insert(0, '.'); import daily_run; print('import ok')"`
Expected: `import ok`，无报错

- [ ] **Step 3: 离线验证**

Run: `.venv/bin/python scripts/verify_intro_gen.py`
Expected: 全部通过（确认无回归）

- [ ] **Step 4: 提交**

```bash
git add scripts/daily_run.py
git commit -m "feat: daily_run 集成 AI 补写公司介绍第 4 步（阶段 7.3）"
```

---

### Task 7: scripts/gen_intro.py 手动补写入口

**Files:**
- Create: `scripts/gen_intro.py`

**Interfaces:**
- Consumes: `intro_gen._with_snapshot` / `gen_stock` / `ensure_coverage` / `print_entry` / `print_report`；`knowledge.load_stock` / `save_stock`；`db.init_db` / `get_recommendations`
- Produces: CLI 入口：无参数 = 补写最近一次推荐的缺条目；`<代码>` = 单独补写个股条目（已有条目先跳过，不调 API）

- [ ] **Step 1: 实现**

创建 `scripts/gen_intro.py`：

```python
#!/usr/bin/env python3
"""公司介绍手动补写入口（05 §10 7.3）。

用法：
    .venv/bin/python scripts/gen_intro.py              # 补写最近一次推荐的知识库缺条目
    .venv/bin/python scripts/gen_intro.py 600519       # 指定股票代码，单独补写个股条目
已有条目一律跳过（不覆盖）；生成失败返回非零退出码。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
import intro_gen
import knowledge


def _gen_one(code: str) -> int:
    if knowledge.load_stock(code) is not None:
        print(f"· {code} 已有条目，跳过（不覆盖）")
        return 0
    stock = intro_gen._with_snapshot({"code": code})
    entry = intro_gen.gen_stock(stock)
    if entry is None:
        print(f"✗ {code} 生成失败（检查 .deepseek_key 与网络，可稍后重试）")
        return 1
    if not knowledge.save_stock(entry):
        print(f"✗ {code} 入库失败")
        return 1
    print(f"✓ {entry['name']} {entry['code']} 条目已由 AI 生成并入库：")
    intro_gen.print_entry(entry)
    return 0


def main() -> int:
    db.init_db()
    codes = sys.argv[1:]
    if codes:
        return max(_gen_one(c) for c in codes)
    recs = db.get_recommendations()
    if recs.empty:
        print("暂无推荐记录。用法：scripts/gen_intro.py <股票代码> [<代码> …]")
        return 1
    date = recs["rec_date"].max()
    picked = [{"code": r["code"], "name": r["name"], "industry": r["industry"]}
              for _, r in db.get_recommendations(date).iterrows()]
    intro_gen.print_report(intro_gen.ensure_coverage(picked), picked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 不触发 API 的冒烟测试**

Run: `.venv/bin/python scripts/gen_intro.py 001337`（已有条目）
Expected: `· 001337 已有条目，跳过（不覆盖）`，退出码 0，无 API 调用

Run: `.venv/bin/python scripts/gen_intro.py`（今日 3 只均已覆盖）
Expected: `知识库覆盖完整，公司介绍模块将完整展示。`，无 API 调用

- [ ] **Step 3: 提交**

```bash
git add scripts/gen_intro.py
git commit -m "feat: gen_intro.py 手动补写入口（阶段 7.3）"
```

---

### Task 8: 端到端验收（真实 API 调用 + 实跑）

**Files:**
- Create（验收产物）: `knowledge/stocks/600519.json`（贵州茅台，08-14 曾推荐但无条目，真实补缺）

**Interfaces:**
- Consumes: Task 7 的 CLI
- Produces: 真实生成内容经用户审阅后留用

- [ ] **Step 1: 真实调用生成（花费约几分钱）**

Run: `.venv/bin/python scripts/gen_intro.py 600519`
Expected: 终端打印 `✓ 贵州茅台 600519 条目已由 AI 生成并入库：` + 全文；文件 `knowledge/stocks/600519.json` 生成且 schema 与现有条目一致（code/name/what/life/products/upstream/downstream）。

- [ ] **Step 2: 用户审阅内容质量（人工确认点）**

用户通读生成内容：通俗性、事实准确性（重点查上下游企业名）、生活钩子是否自然。
- 满意 → 进入 Step 3
- 不满意 → 删除 `knowledge/stocks/600519.json`，调整 `intro_gen.py` 中 STOCK_SYSTEM/_stock_user_prompt 后回到 Step 1 重试（最多 2 轮，仍不满意记录到开发日志备查）

- [ ] **Step 3: 实跑每日流程确认集成无回归**

Run: `.venv/bin/python scripts/daily_run.py`
Expected: 4 步走完；今日覆盖完整 → 第 4 步输出 `知识库覆盖完整，公司介绍模块将完整展示。`（不调 API）

- [ ] **Step 4: 提交茅台条目**

```bash
git add knowledge/stocks/600519.json
git commit -m "feat: 公司介绍知识库新增 600519 贵州茅台（阶段 7.4 真实生成验收）"
```

---

### Task 9: 收尾（开发日志 / 05 文档状态 / git）

**Files:**
- Modify: `开发日志/2026-08-18.md`
- Modify: `文档/05-开发计划与执行步骤.md`

**Interfaces:**
- Consumes: 无
- Produces: 阶段 7 正式完成

- [ ] **Step 1: 更新开发日志**

`开发日志/2026-08-18.md`：
- "今日完成"追加：7.1 intro_gen.py（请求/解析/校验/生成/编排）、7.2 knowledge.py 写入函数、7.3 daily_run 集成 + gen_intro.py、7.4 离线验收脚本 + 600519 真实生成（用户审阅通过）
- "待办事项"勾掉阶段 7 相关项
- "明日计划"更新：观察次日晨间 ./start.sh 首次真实 AI 补写场景（若当日筛选出无条目股票）+ 既有观察项

- [ ] **Step 2: 05 文档阶段 7 状态置完成**

路线图阶段 7 行 `⬜ 待实施（2026-08-18 立项）` 改为 `✅ 已完成（2026-08-18，验收见开发日志）`；§10 各步骤加 ✅ 与日期。

- [ ] **Step 3: 与用户确认 requirements.txt 遗留问题**

CLAUDE.md 与 02 规范引用 requirements.txt 但文件不存在。二选一（用户拍板）：
- 补文件：`.venv/bin/pip freeze > requirements.txt` 后人工精简为直接依赖（akshare/fastapi/uvicorn/jinja2/pandas/requests）
- 删引用：从 CLAUDE.md 与 02 规范中删掉 requirements.txt 相关行

- [ ] **Step 4: 提交收尾**

```bash
git add 开发日志/2026-08-18.md 文档/05-开发计划与执行步骤.md
git commit -m "docs: 阶段 7 完成收尾（AI 自动补写公司介绍）"
```

---

## Self-Review 记录

- **Spec coverage**：01 F8 v1.2 验收两场景 → Task 8（补写成功）+ Task 3/5 兜底（无密钥/失败回退）；02 v1.3 各要点 → 常量/请求头（Task 3）、只补缺不覆盖（Task 2/5）、兜底（Task 5）、每天≤6 次（每缺一项一次调用，Task 5 结构保证）；05 §10 7.0~7.5 → Task 1/2/3/4/5/6/7/8/9
- **Placeholder scan**：无 TBD/TODO，所有代码步骤含完整代码
- **Type consistency**：`ensure_coverage` 返回结构在 Task 5 定义、Task 6/7 消费字段一致；`_setup_requests` 返回 `(fake, restore)` 在 Task 3 定义、Task 4/5 复用一致
