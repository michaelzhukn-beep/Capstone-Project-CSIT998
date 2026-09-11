"""服务端标签的英文版。V9.6

**为什么英文不写回各个模块,而是集中在这里。**
属性名、设施名、证据项、规划分区……这些中文标签散在 registry / context / nearby /
planning 五个文件里,每一处都紧挨着它的定义和注释。把英文塞回去,等于把每个表
都变成两倍宽,原本一眼能读完的注册表会被撑散;而且改一个词要在两个地方改,
迟早漏一个 —— 而漏掉的那个不会报错,只会在英文界面上突然冒出一句中文。

集中在这里的代价是键要对齐,好处是**对齐这件事可以被测试**:
`check()` 会把中文侧的键全枚举一遍,少一个就报出来。tests/test_registry.py 调它。

界面自己的文案(按钮、段标题、整句)不在这里,在 app/web/i18n.js ——
那些字符串前端自己就能定,不必让它们跑一趟后端。
"""

from app.amenities import context, nearby, planning, registry

# ---------------------------------------------------------------- 抽象属性

ATTRIBUTES_EN = {
    "quiet": "Quiet",
    "lively": "Lively",
    "convenient": "Everyday convenience",
    "shopping": "Shopping",
    "green": "Parks & greenery",
    "beach_access": "Beach access",
    "transport": "Commuting",
    "school_access": "Schools nearby",
    "medical": "Healthcare",
    "fitness": "Fitness",
    "spacious": "Spacious",
    "family": "Family-friendly",
    "away_industry": "Away from industry",
    "low_crime": "Lower crime",
    "away_cemetery": "Away from cemeteries",
}

# 这些注解是**属性的定义**,不是对某套房的判断 —— 界面上写作「高分含义:…」。
ATTRIBUTE_NOTES_EN = {
    "quiet": "far from main and secondary roads, railways and industry, with few late-night venues nearby",
    "lively": "dense shops, restaurants and late-night venues nearby",
    "convenient": "many shops and eateries within walking distance, close to a supermarket and pharmacy",
    "shopping": "close to a shopping centre and supermarket",
    "green": "close to a park or reserve",
    "beach_access": "close to a beach",
    "transport": "close to train, tram and bus stops, and close to the CBD",
    "school_access": "close to schools, childcare and libraries (distance only — this system has no "
                     "school quality or ranking data)",
    "medical": "close to a hospital and pharmacy",
    "fitness": "close to a gym and sports centre",
    "spacious": "large for its property type (building area where available, otherwise land size)",
    "family": "close to primary schools, childcare and parks, larger in size, away from main roads",
    "away_industry": "far from industrial land, substations and petrol stations",
    "low_crime": "a lower offence rate per 100,000 in its local government area (Victorian Crime "
                 "Statistics Agency). **The granularity is LGA, not suburb** — every property in the "
                 "same LGA scores the same; the crime data is recent while the sales are 2016–2018, so "
                 "treat it as a relative indicator only",
    "away_cemetery": "far from cemeteries (only 79 exist across the region, so the percentile is coarse)",
}

# ---------------------------------------------------------------- 周边设施

KINDS_EN = {
    "train_station": "Train station", "tram_stop": "Tram stop", "bus_stop": "Bus stop",
    "airport": "Airport", "kindergarten": "Childcare / kindergarten", "primary_school": "Primary school",
    "secondary_school": "Secondary school", "university": "University / TAFE", "library": "Library",
    "hospital": "Hospital", "pharmacy": "Pharmacy", "bank": "Bank", "supermarket": "Supermarket",
    "mall": "Shopping centre", "police": "Police station", "gym": "Gym",
    "sports_centre": "Sports centre", "park": "Park", "beach": "Beach",
}

# ---------------------------------------------------------------- 环境证据
# (标签, 单位)。单位要跟着翻 —— 「米」在英文界面里必须是 m,否则数字后面
# 挂一个汉字,比整句没翻译还刺眼。

EVIDENCE_EN = {
    "train_station_m": ("Nearest train station", "m"),
    "tram_stop_m": ("Nearest tram stop", "m"),
    "bus_stop_m": ("Nearest bus stop", "m"),
    "airport_m": ("Nearest airport", "m"),
    "kindergarten_m": ("Nearest childcare", "m"),
    "primary_school_m": ("Nearest primary school", "m"),
    "secondary_school_m": ("Nearest secondary school", "m"),
    "university_m": ("Nearest university / TAFE", "m"),
    "library_m": ("Nearest library", "m"),
    "hospital_m": ("Nearest hospital", "m"),
    "pharmacy_m": ("Nearest pharmacy", "m"),
    "bank_m": ("Nearest bank", "m"),
    "supermarket_m": ("Nearest supermarket", "m"),
    "mall_m": ("Nearest shopping centre", "m"),
    "police_m": ("Nearest police station", "m"),
    "gym_m": ("Nearest gym", "m"),
    "sports_centre_m": ("Nearest sports centre", "m"),
    "park_m": ("Nearest park", "m"),
    "beach_m": ("Nearest beach", "m"),
    "cemetery_m": ("Nearest cemetery", "m"),
    "major_road_m": ("Nearest main road", "m"),
    "secondary_road_m": ("Nearest secondary road", "m"),
    "railway_m": ("Nearest railway line", "m"),
    "industrial_m": ("Nearest industrial land", "m"),
    "substation_m": ("Nearest substation", "m"),
    "fuel_m": ("Nearest petrol station", "m"),
    "nightlife_300m": ("Late-night venues within 300 m", ""),
    "shop_800m": ("Shops and eateries within 800 m", ""),
    "size_m2": ("Size", "m²"),
    "distance_cbd_km": ("Distance to CBD", "km"),
    "crime_rate_per_100k": ("LGA offence rate", "per 100k"),
}

# ---------------------------------------------------------------- 排序口径
# 抽象属性那 15 条是照着属性名生成的,不在这里逐条列 —— 逐条列就等于
# 把属性名抄第二遍,而抄第二遍的东西迟早和第一遍不一致。

SORT_EN_FIXED = {
    "gross_yield": "Gross rental yield, high to low",
    "cap_rate": "Capitalisation rate, high to low",
    "roi": "Return on investment, high to low",
    "predicted_gap": "Estimate above asking, largest first",
    "predicted_gap_neg": "Estimate below asking, largest first",
    "price_asc": "Price, low to high",
    "price_desc": "Price, high to low",
    "near_place_distance": "Distance to the named place, nearest first",
}

PLANNING_NEEDS_EN = {
    "no_heritage": "no overlay that restricts alterations",
    "low_density_around": "surrounded mainly by zones that limit density (high-rise is not legally possible)",
    "no_risk_overlay": "no registered risk overlay (acquisition, flooding, bushfire, contamination, etc.)",
}

PROPERTY_TYPES_EN = {"house": "House", "apartment": "Apartment", "townhouse": "Townhouse"}

# UNSUPPORTED 的**键**本身是中文,而且会被 LLM 原样填进 unsupported_asks
# 再显示给用户 —— 所以键和值都要翻。
UNSUPPORTED_KEY_EN = {
    "采光朝向": "aspect and natural light",
    "装修房况": "condition and renovation",
    "房龄新旧": "property age",
    "学校排名": "school rankings",
    "街道或小区级治安": "street-level crime",
    "分类型犯罪": "crime by offence type",
    "空气与噪音实测": "measured air quality and noise",
    "物业与邻居": "body corporate and neighbours",
    "户型格局": "floor plan and layout",
    "楼层视野": "floor level and views",
    "升值潜力": "capital growth forecasts",
    "步行/驾车时间": "walking or driving time",
    "到 CBD 的距离要求": "a distance-to-CBD filter",
}

UNSUPPORTED_EN = {
    "采光朝向": "the dataset has no aspect, floor level or window information",
    "装修房况": "the dataset has no information on condition or fit-out",
    "房龄新旧": "the year built is in the database, but the retrieval layer does not return it",
    "学校排名": "school locations and **enrolment zone boundaries** are available, but no rankings, "
                "ratings or teaching-quality data",
    "街道或小区级治安": "note: **ordinary \"safe area\" requests are supported** via the low_crime "
                        "attribute. What is missing is anything finer than LGA level — the official "
                        "suburb table has raw counts without a population denominator, so counts cannot "
                        "be compared across suburbs",
    "分类型犯罪": "note: **ordinary \"safe area\" requests are supported** via the low_crime attribute. "
                  "What is missing is a comparable breakdown by offence type — only the overall rate exists",
    "空气与噪音实测": "only distances to noise sources are available, with no measured decibel or air "
                      "quality readings",
    "物业与邻居": "the dataset has no body-corporate fees, management quality or resident information",
    "户型格局": "only room counts are available — no floor plans, frontage or usable-area ratios",
    "楼层视野": "the dataset has no floor level, aspect or view information",
    "升值潜力": "only 2016–2018 sale prices exist, too short a span to support a trend forecast",
    "步行/驾车时间": "all distances are **straight-line**; there is no road network, so walking or "
                     "driving time cannot be computed. \"Close to X\" can be answered (as the crow "
                     "flies); \"N minutes' walk to X\" cannot",
    "到 CBD 的距离要求": "straight-line kilometres to the CBD are in the database and feed the transport "
                         "attribute, but there is **no standalone CBD-distance filter** — a request for "
                         "\"within N km of the CBD\" has to be reported as unfilterable",
}

# ---------------------------------------------------------------- 规划分区与叠加层
# 这两张表按**中文标签**做键。分区代码的前缀匹配逻辑在 planning.py 里,
# 照抄一遍前缀表就等于埋一个"两张表会漂移"的坑;按标签查,漏了就在
# check() 里当场报出来。

ZONE_LABELS_EN = {
    "邻里住宅区(限制加密)": "Neighbourhood Residential (density limited)",
    "一般住宅区": "General Residential",
    "住宅增长区(鼓励加密)": "Residential Growth (density encouraged)",
    "住房选择与交通区(近车站,强制加密)": "Housing Choice & Transport (near stations, density mandated)",
    "低密度住宅区": "Low Density Residential",
    "农村生活区": "Rural Living",
    "镇区": "Township",
    "混合用途区": "Mixed Use",
    "活动中心区(规划的高密度核心)": "Activity Centre (planned high-density core)",
    "综合开发区": "Comprehensive Development",
    "特定片区(重大再开发)": "Priority Precinct (major redevelopment)",
    "首府城市区(CBD)": "Capital City (CBD)",
    "码头区(Docklands)": "Docklands",
    "城市增长区(规划中的新城)": "Urban Growth (planned new suburbs)",
    "优先开发区": "Priority Development",
    "商业一区(商住混合)": "Commercial 1 (mixed residential)",
    "商业二区": "Commercial 2",
    "一般住宅区(旧代码 R1Z)": "General Residential (legacy code R1Z)",
    "住宅区(旧代码 R2Z)": "Residential (legacy code R2Z)",
    "住宅区(旧代码 R3Z)": "Residential (legacy code R3Z)",
    "商业一区(旧代码 B1Z)": "Commercial 1 (legacy code B1Z)",
    "商业二区(旧代码 B2Z)": "Commercial 2 (legacy code B2Z)",
    "商业区(旧代码 B3Z)": "Business (legacy code B3Z)",
    "商业区(旧代码 B4Z)": "Business (legacy code B4Z)",
    "商业区(旧代码 B5Z)": "Business (legacy code B5Z)",
    "工业一区": "Industrial 1",
    "工业二区": "Industrial 2",
    "工业三区": "Industrial 3",
    "工业区": "Industrial",
    "公园与游憩用地": "Public Park & Recreation",
    "公共保育与资源用地": "Public Conservation & Resource",
    "道路用地": "Road",
    "交通用地(主干道/铁路)": "Transport (arterial road / rail)",
    "公共用地(学校/政府/水电)": "Public Use (schools, government, utilities)",
    "农业区": "Farming",
    "农业用地区": "Rural Activity",
    "乡村保育区": "Rural Conservation",
    "绿楔农业区": "Green Wedge Agricultural",
    "绿楔区": "Green Wedge",
    "城市农业区": "Urban Floodway / Urban Farming",
    "特别用途区": "Special Use",
    "港口区": "Port",
}

OVERLAY_LABELS_EN = {
    "历史建筑保护": "Heritage",
    "设计与开发控制(限高等)": "Design & Development (height limits etc.)",
    "建筑形态控制": "Built Form",
    "邻里特征保护": "Neighbourhood Character",
    "特定控制": "Specific Controls",
    "重要景观保护": "Significant Landscape",
    "植被保护": "Vegetation Protection",
    "环境重要性保护": "Environmental Significance",
    "须先报开发总体规划": "Development Plan required first",
    "须符合已并入的片区规划": "Incorporated Plan applies",
    "重建区": "Restructure",
    "停车控制": "Parking",
    "道路封闭": "Road Closure",
    "City Link 工程叠加": "City Link Project",
    "受保护聚落边界": "Protected Settlement Boundary",
    "政府已划定将来征收": "Public Acquisition (earmarked)",
    "特殊建筑(排水/内涝)": "Special Building (drainage / overland flow)",
    "洪泛淹没区": "Land Subject to Inundation",
    "洪道区": "Floodway",
    "山火管理": "Bushfire Management",
    "须做环境审计(土壤污染)": "Environmental Audit (soil contamination)",
    "侵蚀管理": "Erosion Management",
    "盐渍化管理": "Salinity Management",
    "机场环境(噪声)": "Airport Environs (noise)",
    "墨尔本机场环境(噪声)": "Melbourne Airport Environs (noise)",
    "乡村洪道区": "Rural Floodway",
    "开发须缴基建费": "Development Contributions",
    "基础设施贡献": "Infrastructure Contributions",
}


# ---------------------------------------------------------------- 翻译入口


def sort_labels_en(sort_labels: dict) -> dict:
    """排序口径。抽象属性那些照着属性名生成,固定的几条查表。"""
    out = {}
    for key in sort_labels:
        if key in SORT_EN_FIXED:
            out[key] = SORT_EN_FIXED[key]
        else:
            out[key] = "“" + ATTRIBUTES_EN.get(key, key) + "” score, high to low"
    return out


def assumptions_describe_en(snapshot: dict) -> list[str]:
    return [
        "Operating expenses = %.1f%% of annual rent; industry convention is 25%%–30%%, and the dataset "
        "contains no actual expenses" % (float(snapshot.get("opex_rate", 0.28)) * 100),
        "Acquisition costs beyond stamp duty $%s (conveyancing, inspections and the like) — a rough "
        "figure you can change to a real quote" % f"{int(snapshot.get('other_acquisition_costs', 2000)):,}",
    ]


def translate_meta(meta: dict) -> dict:
    """把 /api/meta 的每一项换成英文。**结构一个字段都不动** ——
    前端不该知道自己拿的是哪种语言,只有值变了。"""
    out = dict(meta)
    out["attributes"] = dict(ATTRIBUTES_EN)
    out["attribute_notes"] = dict(ATTRIBUTE_NOTES_EN)
    out["kinds"] = dict(KINDS_EN)
    out["evidence_labels"] = {k: list(v) for k, v in EVIDENCE_EN.items()}
    out["sort_labels"] = sort_labels_en(meta.get("sort_labels") or {})
    out["planning_needs"] = dict(PLANNING_NEEDS_EN)
    out["property_types"] = dict(PROPERTY_TYPES_EN)
    out["unsupported"] = {UNSUPPORTED_KEY_EN.get(k, k): v for k, v in UNSUPPORTED_EN.items()}
    # unsupported_asks 是 LLM 按**中文键**填的(那份枚举在提示词里,两种语言共用
    # 同一套键,否则解析结果会跟着界面语言变 —— 那才是真麻烦)。
    # 界面要显示英文,就得有这张键的对照表。
    out["unsupported_key"] = dict(UNSUPPORTED_KEY_EN)
    assumptions = meta.get("assumptions") or {}
    if assumptions.get("snapshot"):
        out["assumptions"] = {**assumptions,
                              "describe": assumptions_describe_en(assumptions["snapshot"])}
    return out


def describe_planning_en(info: dict) -> str:
    """planning.describe() 的英文版。这段话会直接喂给 LLM 看,
    所以它的措辞比界面文案更要紧 —— 「9 lots zoned for high density」和
    「9 high-rise buildings」是两回事,写岔了模型就会跟着说岔。"""
    if not info or "zone" not in info:
        return "No planning zone data for these coordinates"

    parts = ["Zone " + str(info["zone"]) + " (" + str(info.get("zone_label") or "") + ")"]

    overlays = info.get("overlays") or []
    if overlays:
        shown = ", ".join(o["code"] + " " + o["label"] for o in overlays[:4])
        if len(overlays) > 4:
            shown += " and " + str(len(overlays)) + " in total"
        parts.append("Overlays: " + shown)
    else:
        parts.append("No overlay controls")

    total = info.get("nearby_total") or 0
    if total:
        radius = info.get("radius_m", 350)
        bits = [str(total) + " lots within a ±" + str(radius) + " m square"]
        if info.get("nearby_low"):
            bits.append(str(info["nearby_low"]) + " legally limited in density")
        if info.get("nearby_high"):
            bits.append(str(info["nearby_high"]) + " permitting high-density development")
        if info.get("nearby_open"):
            bits.append(str(info["nearby_open"]) + " park or open space")
        parts.append("; ".join(bits))
    return ". ".join(parts)


_PLANNING_CAVEAT_EN = ("A zone states what is legally **permitted**, not a prediction of what will "
                       "happen; zoning data is current while sale prices are from 2016–2018, so no "
                       "causal link can be drawn between them")


def translate_property(entry: dict) -> dict:
    """一条房源里所有中文的值。目前只有规划分区那几项 ——
    学区是学校名、区名是地名、设施名走 meta,都不用翻。"""
    plan = entry.get("planning")
    if not plan:
        return entry
    out = dict(entry)
    p = dict(plan)
    if p.get("zone_label"):
        p["zone_label"] = ZONE_LABELS_EN.get(p["zone_label"], p["zone_label"])
    p["overlays"] = [{**o, "label": OVERLAY_LABELS_EN.get(o.get("label"), o.get("label"))}
                     for o in (p.get("overlays") or [])]
    p["summary"] = describe_planning_en(p)
    p["caveat"] = _PLANNING_CAVEAT_EN
    out["planning"] = p
    return out


def apply(payload, lang: str):
    """给 SSE 事件里的房源列表批量套上翻译。lang 不是 en 就原样返回。"""
    if lang != "en" or not payload:
        return payload
    if isinstance(payload, list):
        return [translate_property(m) for m in payload]
    return translate_property(payload)


# ---------------------------------------------------------------- 自洽检查


def check() -> list[str]:
    """中文侧有、英文侧没有的键 —— 每一条都会在英文界面上冒出一句中文。
    由 tests/test_registry.py 调用:加了新属性/新设施/新分区却忘了配英文,
    在测试里炸,而不是等演示时被人看见。"""
    missing = []
    for key in context.ATTRIBUTE_ZH:
        if key not in ATTRIBUTES_EN:
            missing.append("attributes: " + key)
    for key in context.ATTRIBUTES:
        if context.ATTRIBUTES[key].get("note") and key not in ATTRIBUTE_NOTES_EN:
            missing.append("attribute_notes: " + key)
    for key in nearby.KIND_ZH:
        if key not in KINDS_EN:
            missing.append("kinds: " + key)
    for key in registry.all_evidence_keys():
        if key not in EVIDENCE_EN:
            missing.append("evidence: " + key)
    for key in registry.UNSUPPORTED:
        if key not in UNSUPPORTED_EN or key not in UNSUPPORTED_KEY_EN:
            missing.append("unsupported: " + key)
    for _prefix, label, _density in planning._ZONE_FAMILIES:
        if label not in ZONE_LABELS_EN:
            missing.append("zone: " + label)
    for label, _effect in planning._OVERLAY_FAMILIES.values():
        if label not in OVERLAY_LABELS_EN:
            missing.append("overlay: " + label)
    return missing
