from __future__ import annotations

import re


INDEX_CATALOG = [
    {"symbol": "000001.SS", "name": "上证综指", "region": "中国", "group": "china"},
    {"symbol": "399001.SZ", "name": "深证成指", "region": "中国", "group": "china"},
    {"symbol": "399006.SZ", "name": "创业板指", "region": "中国", "group": "china"},
    {"symbol": "000300.SS", "name": "沪深300", "region": "中国", "group": "china"},
    {"symbol": "000905.SS", "name": "中证500", "region": "中国", "group": "china"},
    {"symbol": "^HSI", "name": "恒生指数", "region": "中国香港", "group": "hong_kong"},
    {"symbol": "HSTECH.HK", "name": "恒生科技指数", "region": "中国香港", "group": "hong_kong"},
    {"symbol": "^GSPC", "name": "标普500", "region": "美国", "group": "us"},
    {"symbol": "^IXIC", "name": "纳斯达克综合", "region": "美国", "group": "us"},
    {"symbol": "^DJI", "name": "道琼斯工业指数", "region": "美国", "group": "us"},
    {"symbol": "^RUT", "name": "罗素2000", "region": "美国", "group": "us"},
    {"symbol": "^VIX", "name": "VIX波动率指数", "region": "美国", "group": "us"},
    {"symbol": "^STOXX50E", "name": "欧洲STOXX50", "region": "欧洲", "group": "europe"},
    {"symbol": "^GDAXI", "name": "德国DAX", "region": "德国", "group": "europe"},
    {"symbol": "^FTSE", "name": "英国富时100", "region": "英国", "group": "europe"},
    {"symbol": "^N225", "name": "日经225", "region": "日本", "group": "asia_pacific"},
    {"symbol": "^KS11", "name": "韩国KOSPI", "region": "韩国", "group": "asia_pacific"},
    {"symbol": "^AXJO", "name": "澳洲ASX200", "region": "澳大利亚", "group": "asia_pacific"},
    {"symbol": "^BSESN", "name": "印度Sensex", "region": "印度", "group": "asia_pacific"},
]

INDEX_BY_SYMBOL = {item["symbol"]: item for item in INDEX_CATALOG}
CORE_INDEX_SYMBOLS = [
    "000001.SS",
    "399001.SZ",
    "^HSI",
    "^GSPC",
    "^IXIC",
    "^N225",
    "^KS11",
]

LIVE_MARKET_CATALOG = [
    {
        "key": "china",
        "name": "中国A股",
        "instrument": "上证综指",
        "symbol": "000001.SS",
        "timezone": "Asia/Shanghai",
        "currency": "CNY",
        "calendar": "XSHG",
        "provider": "eastmoney_global_index",
        "sessions": [("09:30", "11:30"), ("13:00", "15:00")],
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "key": "japan",
        "name": "日本股市",
        "instrument": "日经225",
        "symbol": "^N225",
        "timezone": "Asia/Tokyo",
        "currency": "JPY",
        "calendar": "XTKS",
        "provider": "eastmoney_global_index",
        "sessions": [("09:00", "11:30"), ("12:30", "15:30")],
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "key": "korea",
        "name": "韩国股市",
        "instrument": "KOSPI",
        "symbol": "^KS11",
        "timezone": "Asia/Seoul",
        "currency": "KRW",
        "calendar": "XKRX",
        "provider": "eastmoney_global_index",
        "sessions": [("09:00", "15:30")],
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "key": "us",
        "name": "美国股市",
        "instrument": "标普500",
        "symbol": "^GSPC",
        "timezone": "America/New_York",
        "currency": "USD",
        "calendar": "XNYS",
        "sessions": [("09:30", "16:00")],
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "key": "london_gold",
        "name": "伦敦金",
        "instrument": "现货黄金 XAU",
        "symbol": "XAU",
        "timezone": "Europe/London",
        "currency": "USD",
        "sessions": [("00:00", "23:00")],
        "weekdays": [0, 1, 2, 3, 4],
        "provider": "sina_global_futures",
        "daily_break_timezone": "America/New_York",
        "daily_breaks": [("17:00", "18:00")],
    },
]

RESEARCH_TARGETS = {
    "000063.SZ": {
        "name": "中兴通讯",
        "market": "A股",
        "thesis": "关注算力基础设施与通信设备订单、利润兑现和经营现金流变化",
    },
    "300308.SZ": {
        "name": "中际旭创",
        "market": "A股",
        "thesis": "关注高速光模块需求、盈利兑现、客户集中度与估值消化",
    },
    "NVDA": {
        "name": "英伟达",
        "market": "美股",
        "cik": "0001045810",
        "thesis": "关注数据中心需求、Blackwell交付、毛利率变化与高估值消化",
    },
    "600519.SS": {
        "name": "贵州茅台",
        "market": "A股",
        "thesis": "关注高端白酒需求、渠道库存、批价与经营现金流变化",
    },
}

# Natural-language aliases used by the chat router.  This deliberately stays
# small and auditable: default research targets plus several common demo
# symbols.  User-defined watchlist names are merged at request time.
SECURITY_NAME_ALIASES = {
    "中兴通讯": "000063.SZ",
    "中兴": "000063.SZ",
    "ZTE": "000063.SZ",
    "中际旭创": "300308.SZ",
    "中际": "300308.SZ",
    "英伟达": "NVDA",
    "NVIDIA": "NVDA",
    "贵州茅台": "600519.SS",
    "茅台": "600519.SS",
    "宁德时代": "300750.SZ",
    "平安银行": "000001.SZ",
}

PEER_GROUPS = {
    "000063.SZ": {
        "label": "通信设备与企业网络固定同行样本",
        "basis": "业务相邻且可从同一实时估值源取得一致字段；样本不是完整行业指数",
        "peers": [
            {"symbol": "600498.SS", "name": "烽火通信"},
            {"symbol": "000938.SZ", "name": "紫光股份"},
            {"symbol": "301165.SZ", "name": "锐捷网络"},
        ],
    },
    "300308.SZ": {
        "label": "光模块与光通信固定同行样本",
        "basis": "光模块及光通信产业链相邻公司；商业结构差异仍需单独核对",
        "peers": [
            {"symbol": "300502.SZ", "name": "新易盛"},
            {"symbol": "300394.SZ", "name": "天孚通信"},
            {"symbol": "002281.SZ", "name": "光迅科技"},
        ],
    },
    "NVDA": {
        "label": "全球半导体固定同行样本",
        "basis": "GPU、定制计算与先进半导体产业链相邻公司；业务模式并不完全相同",
        "peers": [
            {"symbol": "AMD", "name": "超威半导体"},
            {"symbol": "AVGO", "name": "博通"},
            {"symbol": "TSM", "name": "台积电"},
        ],
    },
}

_SYMBOL_RE = re.compile(r"^[A-Z0-9^.=-]{1,24}$")


def normalize_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if re.fullmatch(r"\d{6}", value):
        suffix = ".SS" if value[0] in {"5", "6", "9"} else ".SZ"
        return value + suffix
    if value.endswith(".SH"):
        value = value[:-3] + ".SS"
    if not _SYMBOL_RE.fullmatch(value):
        raise ValueError("证券代码格式无效")
    return value
