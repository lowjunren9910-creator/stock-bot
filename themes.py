"""
themes.py - 主题板块（AI 股、发电股、手套股、REIT …）+ 每个板块的代表照片

主题板块跟 Yahoo 的普通板块不同：一只股票可以同时属于几个主题
（例如 YTL Power 既是「发电与电网」也是「AI 与数据中心」）。
想加减公司：直接改下面 THEMES 里的名单就可以，格式是  "代码": "名称"。

照片全部来自 Unsplash（免费使用，Unsplash License），网页和手机 app 直接从 Unsplash 载入。
照片载入不了时，会自动换成颜色底 + 图标，不会坏掉。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. 照片库：key → (Unsplash 照片编号, 摄影师)
# ---------------------------------------------------------------------------
PHOTOS = {
    "finance": ("1574218732130-6b19257fd9db", "Meriç Dağlı"),
    "bank": ("1601597111158-2fceff292cdc", "Eduardo Soares"),
    "tech": ("1550751827-4bd374c3f58b", "Adi Goldstein"),
    "cyber": ("1526374965328-7f61d4dc18c5", "Markus Spiske"),
    "staples": ("1607349913338-fca6f7fc42d0", "Raul Gonzalez Escobar"),
    "retail": ("1759323321196-2813db509285", "Vishnu Kalanad"),
    "grid": ("1560977466-c02ffbb12189", "Jarosław Kwoczała"),
    "industrial": ("1496247749665-49cf5b1022e9", "Ant Rozetsky"),
    "materials": ("1474674556023-efef886fa147", "Ant Rozetsky"),
    "oilgas": ("1633829131104-e2134f75c6e5", "Arvind Vallabh"),
    "property": ("1596422846543-75c6fc197f07", "Esmonde Yong"),
    "reit": ("1486406146926-c627a92ad1ab", "Sean Pollock"),
    "health": ("1519494026892-80bbd2d6fd0d", "Martha Dominguez de Gouveia"),
    "pharma": ("1631549916768-4119b2e5f926", "Roberto Sorin"),
    "telecom": ("1643155193188-38eb08e2b54f", "David Arrowsmith"),
    "plantation": ("1628713287929-80bdbfb3689d", "Julius Yls"),
    "market": ("1689732888407-310424e3a372", "Austin Hervias"),
    "ai": ("1677442135703-1787eea5ce01", "Steve A Johnson"),
    "semis": ("1587845323226-bad89242c735", "Laura Ockel"),
    "datacenter": ("1558494949-ef010cbdcc31", "Taylor Vick"),
    "power": ("1630142895963-6996ae6b3a5b", "Lukáš Lehotský"),
    "solar": ("1521618755572-156ae0cdd74d", "Zbynek Burival"),
    "gloves": ("1584820927498-cfe5211fd8bf", "Clay Banks"),
    "construction": ("1670859255584-8b162775407f", "James Sullivan"),
    "coal": ("1523848309072-c199db53f137", "Dominik Vanyi"),
    "ev": ("1593941707874-ef25b8b4a92b", "CHUTTERSNAP"),
    "digital": ("1512941937669-90a1b58e7e9c", "William Hook"),
}

# 普通板块（sectors.py 的中文名字）→ 照片 + 图标 + 底色
SECTOR_LOOK = {
    "金融": ("finance", "🏦", "#2b4c7e"), "科技": ("tech", "💻", "#2f5d8a"),
    "必需消费": ("staples", "🛒", "#5b7f3a"), "非必需消费": ("retail", "🛍️", "#a0522d"),
    "公用事业": ("grid", "⚡", "#8a6d1d"), "工业": ("industrial", "🏭", "#5a5f6b"),
    "原材料": ("materials", "⛏️", "#7a4b2a"), "能源": ("oilgas", "🛢️", "#3d3d3d"),
    "房地产": ("property", "🏙️", "#4b3f72"), "医疗保健": ("health", "🏥", "#1f7a74"),
    "电讯媒体": ("telecom", "📡", "#4a5a8a"), "种植": ("plantation", "🌴", "#2f6b3b"),
    "其他": ("market", "📈", "#555"),
}


def photo(key: str | None, width: int = 640) -> dict | None:
    """照片网址 + 摄影师。width 越小载入越快（手机列表用 480 就够）。"""
    if key not in PHOTOS:
        return None
    pid, by = PHOTOS[key]
    return {"url": f"https://images.unsplash.com/photo-{pid}?auto=format&fit=crop&w={width}&q=60",
            "credit": f"{by} / Unsplash",
            "link": "https://unsplash.com/?utm_source=stock-bot&utm_medium=referral"}


def sector_look(name: str) -> dict:
    key, emoji, color = SECTOR_LOOK.get(name, SECTOR_LOOK["其他"])
    return {"emoji": emoji, "color": color, "photo": photo(key)}


# ---------------------------------------------------------------------------
# 2. 主题板块
#    tickers: {市场: {代码: 名称}}；一个市场有 2 只以上有数据，才会显示
# ---------------------------------------------------------------------------
THEMES = [
    {"key": "datacenter", "name": "AI 与数据中心", "emoji": "🧠", "photo": "datacenter", "color": "#24406b",
     "desc": "受惠于数据中心建设潮：供电、建厂房、机电工程、卖地给数据中心的公司。",
     "tickers": {
         "bursa": {"6742.KL": "YTL Power", "5347.KL": "Tenaga", "5398.KL": "Gamuda",
                   "5263.KL": "Sunway Construction", "3336.KL": "IJM Corp", "7161.KL": "Kerjaya",
                   "5288.KL": "Sime Darby Property", "8583.KL": "Mah Sing", "0151.KL": "Kelington",
                   "5211.KL": "Sunway"},
         "idx": {"DCII.JK": "DCI Indonesia", "TLKM.JK": "Telkom", "EMTK.JK": "Elang Mahkota"},
         "us": {"EQIX": "Equinix", "DLR": "Digital Realty", "VRT": "Vertiv", "ANET": "Arista Networks",
                "SMCI": "Super Micro", "DELL": "Dell", "ETN": "Eaton"},
     }},
    {"key": "ai", "name": "AI 股", "emoji": "🤖", "photo": "ai", "color": "#3a2f6b",
     "desc": "人工智能的核心受益者：AI 芯片、云端算力、AI 软件。",
     "tickers": {
         "us": {"NVDA": "NVIDIA", "MSFT": "Microsoft", "GOOGL": "Alphabet", "META": "Meta",
                "AMZN": "Amazon", "AMD": "AMD", "AVGO": "Broadcom", "PLTR": "Palantir",
                "ORCL": "Oracle", "ARM": "Arm Holdings", "CRM": "Salesforce", "NOW": "ServiceNow"},
         "bursa": {"0138.KL": "Zetrix AI (MyEG)", "0097.KL": "ViTrox", "0270.KL": "NationGate",
                   "0166.KL": "Inari Amertron"},
     }},
    {"key": "semis", "name": "半导体", "emoji": "🔬", "photo": "semis", "color": "#2e4a5c",
     "desc": "芯片设计、制造、封装测试和自动化设备。",
     "tickers": {
         "bursa": {"0166.KL": "Inari Amertron", "0097.KL": "ViTrox", "3867.KL": "MPI",
                   "5005.KL": "Unisem", "0208.KL": "Greatech", "0128.KL": "Frontken",
                   "7204.KL": "D&O Green Tech", "5286.KL": "Mi Technovation", "7160.KL": "Pentamaster",
                   "5292.KL": "UWC", "9822.KL": "SAM Engineering", "0127.KL": "JHM Consolidation"},
         "us": {"NVDA": "NVIDIA", "AMD": "AMD", "AVGO": "Broadcom", "TSM": "TSMC", "ASML": "ASML",
                "INTC": "Intel", "QCOM": "Qualcomm", "MU": "Micron", "AMAT": "Applied Materials",
                "LRCX": "Lam Research", "KLAC": "KLA", "TXN": "Texas Instruments", "MRVL": "Marvell"},
     }},
    {"key": "power", "name": "发电与电网", "emoji": "⚡", "photo": "power", "color": "#6b5317",
     "desc": "发电厂、电网和燃气供应。AI 和数据中心让用电量大增，是近年的热门主题。",
     "tickers": {
         "bursa": {"5347.KL": "Tenaga", "6742.KL": "YTL Power", "5264.KL": "Malakoff",
                   "3069.KL": "Mega First", "5272.KL": "Ranhill Utilities", "5209.KL": "Gas Malaysia",
                   "6033.KL": "Petronas Gas"},
         "idx": {"PGEO.JK": "Pertamina Geothermal", "BREN.JK": "Barito Renewables",
                 "POWR.JK": "Cikarang Listrindo", "PGAS.JK": "PGN"},
         "us": {"CEG": "Constellation Energy", "VST": "Vistra", "NRG": "NRG Energy", "GEV": "GE Vernova",
                "NEE": "NextEra Energy", "SO": "Southern Co", "DUK": "Duke Energy", "TLN": "Talen Energy"},
     }},
    {"key": "solar", "name": "太阳能与绿能", "emoji": "☀️", "photo": "solar", "color": "#7a5a12",
     "desc": "太阳能电站工程（EPCC）和再生能源发电。受政府绿能计划推动。",
     "tickers": {
         "bursa": {"0215.KL": "Solarvest", "0223.KL": "Samaiden", "0233.KL": "Pekat",
                   "5184.KL": "Cypark", "3069.KL": "Mega First"},
         "idx": {"PGEO.JK": "Pertamina Geothermal", "BREN.JK": "Barito Renewables"},
         "us": {"FSLR": "First Solar", "ENPH": "Enphase", "NEE": "NextEra Energy"},
     }},
    {"key": "gloves", "name": "手套股", "emoji": "🧤", "photo": "gloves", "color": "#2c6b8a",
     "desc": "大马是全球最大的橡胶手套出口国。看需求、平均售价和原料成本。",
     "tickers": {
         "bursa": {"7113.KL": "Top Glove", "5168.KL": "Hartalega", "7153.KL": "Kossan",
                   "7106.KL": "Supermax", "2127.KL": "Comfort Gloves"},
     }},
    {"key": "reit", "name": "REIT 产托", "emoji": "🏢", "photo": "reit", "color": "#4b3f72",
     "desc": "拥有商场、办公楼、工业地产的信托，主要靠租金派息，适合收息。",
     "tickers": {
         "bursa": {"5235SS.KL": "KLCC Property", "5227.KL": "IGB REIT", "5176.KL": "Sunway REIT",
                   "5212.KL": "Pavilion REIT", "5106.KL": "Axis REIT", "5180.KL": "CapitaLand Malaysia Trust",
                   "5109.KL": "YTL Hospitality REIT", "5116.KL": "Al-Aqar Healthcare REIT",
                   "5280.KL": "KIP REIT", "5123.KL": "Sentral REIT", "5299.KL": "IGB Commercial REIT"},
         "us": {"O": "Realty Income", "PLD": "Prologis", "AMT": "American Tower", "EQIX": "Equinix",
                "DLR": "Digital Realty", "SPG": "Simon Property", "PSA": "Public Storage",
                "WELL": "Welltower", "VICI": "VICI Properties"},
     }},
    {"key": "banks", "name": "银行股", "emoji": "🏦", "photo": "bank", "color": "#2b4c7e",
     "desc": "看利率走势、贷款增长、坏账和派息。",
     "tickers": {
         "bursa": {"1155.KL": "Maybank", "1295.KL": "Public Bank", "1023.KL": "CIMB",
                   "5819.KL": "Hong Leong Bank", "1066.KL": "RHB Bank", "1015.KL": "AMMB",
                   "1082.KL": "HL Financial", "5258.KL": "Bank Islam", "2488.KL": "Alliance Bank",
                   "5185.KL": "Affin Bank", "1171.KL": "MBSB"},
         "idx": {"BBCA.JK": "Bank Central Asia", "BBRI.JK": "Bank Rakyat", "BMRI.JK": "Bank Mandiri",
                 "BBNI.JK": "Bank Negara", "BRIS.JK": "Bank Syariah", "BBTN.JK": "Bank Tabungan Negara",
                 "BNGA.JK": "CIMB Niaga", "ARTO.JK": "Bank Jago"},
         "us": {"JPM": "JPMorgan", "BAC": "Bank of America", "WFC": "Wells Fargo", "C": "Citigroup",
                "GS": "Goldman Sachs", "MS": "Morgan Stanley"},
     }},
    {"key": "oilgas", "name": "油气股", "emoji": "🛢️", "photo": "oilgas", "color": "#3d3d3d",
     "desc": "上游开采、油气服务、船运和下游零售。跟油价关系很大。",
     "tickers": {
         "bursa": {"7277.KL": "Dialog Group", "7293.KL": "Yinson", "5210.KL": "Bumi Armada",
                   "5243.KL": "Velesto", "5199.KL": "Hibiscus Petroleum", "5681.KL": "Petronas Dagangan",
                   "3816.KL": "MISC", "5141.KL": "Dayang", "5142.KL": "Wasco"},
         "idx": {"MEDC.JK": "Medco", "AKRA.JK": "AKR", "PGAS.JK": "PGN"},
         "us": {"XOM": "Exxon", "CVX": "Chevron", "COP": "ConocoPhillips", "EOG": "EOG Resources",
                "SLB": "SLB", "OXY": "Occidental"},
     }},
    {"key": "construction", "name": "建筑股", "emoji": "🏗️", "photo": "construction", "color": "#7a5a2a",
     "desc": "靠拿工程合约赚钱。看新合约、未完成订单和政府基建开支。",
     "tickers": {
         "bursa": {"5398.KL": "Gamuda", "3336.KL": "IJM Corp", "5263.KL": "Sunway Construction",
                   "7161.KL": "Kerjaya", "9679.KL": "WCT", "1651.KL": "MRCB", "8877.KL": "Ekovest"},
         "idx": {"JSMR.JK": "Jasa Marga", "SMGR.JK": "Semen Indonesia"},
     }},
    {"key": "coal", "name": "煤炭股", "emoji": "⛏️", "photo": "coal", "color": "#3a3a3a",
     "desc": "印尼是全球最大的动力煤出口国。跟煤价、中国和印度需求关系大，派息通常高。",
     "tickers": {
         "idx": {"ADRO.JK": "Alamtri (Adaro)", "AADI.JK": "Adaro Andalan", "PTBA.JK": "Bukit Asam",
                 "ITMG.JK": "Indo Tambangraya", "BUMI.JK": "Bumi Resources", "INDY.JK": "Indika Energy",
                 "HRUM.JK": "Harum Energy", "BYAN.JK": "Bayan Resources"},
     }},
    {"key": "ev", "name": "镍矿与电动车", "emoji": "🔋", "photo": "ev", "color": "#1f6b5c",
     "desc": "印尼镍矿是电动车电池的重要原料；美股是电动车厂。",
     "tickers": {
         "idx": {"ANTM.JK": "Aneka Tambang", "INCO.JK": "Vale Indonesia", "MBMA.JK": "Merdeka Battery",
                 "NCKL.JK": "Trimegah Bangun (Harita Nickel)", "MDKA.JK": "Merdeka Copper"},
         "us": {"TSLA": "Tesla", "RIVN": "Rivian", "ALB": "Albemarle"},
     }},
    {"key": "digital", "name": "数字经济", "emoji": "📱", "photo": "digital", "color": "#3c4f7a",
     "desc": "电商、网约车、数字支付和网上平台。",
     "tickers": {
         "idx": {"GOTO.JK": "GoTo", "BUKA.JK": "Bukalapak", "EMTK.JK": "Elang Mahkota", "DCII.JK": "DCI Indonesia"},
         "bursa": {"0138.KL": "Zetrix AI (MyEG)", "5301.KL": "CTOS Digital", "5031.KL": "TIME dotCom",
                   "0023.KL": "Datasonic"},
     }},
    {"key": "cyber", "name": "网络安全", "emoji": "🛡️", "photo": "cyber", "color": "#1d4f4a",
     "desc": "保护企业网络和数据的软件公司，订阅收入为主。",
     "tickers": {"us": {"CRWD": "CrowdStrike", "PANW": "Palo Alto Networks", "FTNT": "Fortinet",
                        "ZS": "Zscaler", "NET": "Cloudflare", "OKTA": "Okta"}},
     },
    {"key": "pharma", "name": "医药与减肥药", "emoji": "💊", "photo": "pharma", "color": "#6b2f4a",
     "desc": "大型药厂，包括 GLP-1 减肥药的两大龙头。",
     "tickers": {"us": {"LLY": "Eli Lilly", "NVO": "Novo Nordisk", "MRK": "Merck", "ABBV": "AbbVie",
                        "JNJ": "J&J", "PFE": "Pfizer"},
                 "bursa": {"7148.KL": "Duopharma", "7081.KL": "Pharmaniaga", "7178.KL": "YSP Southeast Asia"}},
     },
]


def for_market(market: str) -> list[dict]:
    """这个市场有的主题（至少 2 只股票）。"""
    out = []
    for th in THEMES:
        t = th["tickers"].get(market) or {}
        if len(t) >= 2:
            out.append({**th, "members": t})
    return out


def all_tickers(market: str) -> dict:
    """这个市场所有主题股票 {代码: 名称}，给 universe.py 加进股票池。"""
    out = {}
    for th in THEMES:
        out.update(th["tickers"].get(market) or {})
    return out


def look(theme: dict) -> dict:
    return {"emoji": theme["emoji"], "color": theme["color"], "photo": photo(theme["photo"])}
