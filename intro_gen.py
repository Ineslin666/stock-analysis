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

import db
import knowledge

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
        up = "、".join(f"{c['name']}（{c['role']}）" for c in entry["upstream"])
        down = "、".join(f"{c['name']}（{c['role']}）" for c in entry["downstream"])
        print(f"    what: {entry['what']}")
        print(f"    life: {entry['life']}")
        print(f"    产品: {'、'.join(entry['products'])}")
        print(f"    上游: {up}")
        print(f"    下游: {down}")
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
