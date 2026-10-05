"""地理数据与抽象属性的**唯一真相源**。V5。

## 为什么要有这个文件

V4 时加一个新词要改五个地方:OSM 查询、基准线脚本、权重表、提示词里的同义词
清单、测试。毕设规模撑得住,**商用撑不住** —— 五处里漏改一处,系统不报错,
只是那个词安静地失效。

现在改成:**这个文件是唯一要改的地方**,其余全部从它生成 ——

    SOURCES    ->  pipeline/fetch_osm.py 生成 Overpass 查询
               ->  build_context_baseline.py 决定要算哪些分位表
               ->  app/amenities/nearby.py 决定能回答"最近的 X 在哪"
    ATTRIBUTES ->  app/amenities/context.py 的评分
               ->  graph.py 里给 LLM 的同义词清单(prompt_block())
               ->  排序口径的中文标签
               ->  tests 逐条遍历

加一个新属性的完整流程:
    1. 在 SOURCES 里加数据源(如果需要新数据)
    2. 在 ATTRIBUTES 里加一条,写清同义词和权重
    3. python pipeline/fetch_osm.py            # 重抓数据
    4. python pipeline/build_context_baseline.py  # 重算分位基准
就这两步脚本,不用碰任何其他代码。

## 加数据源之前先数一遍

OSM 各类标签的完整度差别极大。加之前先在 Overpass 上数一下大墨尔本有多少个,
低于 50 个就别加 —— 分位数会全是噪声,给出的分反而误导人。
实测(2026-09-08):菜市场 40 个、垃圾处理站 15 个,都被否掉了。

## 注册表**不管**的三类数据

注册表描述的是"OSM 上的点/线/面 -> 距离或密度 -> 分位数 -> 评分"这一条链路。
有三类数据不走这条链路,各自独立成模块,这是**有意的**:

  学区边界  app/amenities/zones.py —— 多边形归属判断,产出的是**事实**
            (「所属小学学区:Balwyn Primary School」),不是评分。
            事实不需要权重也不需要分位数,要么是要么不是。
  犯罪率    app/amenities/suburb_stats.py —— 按区名查表,粒度是 LGA 级,
            比这里的点级数据粗一个数量级,必须单独标注。
  规划分区  app/amenities/planning.py —— 同样是多边形归属,但产出的是**法条**
            (「分区 NRZ1,法律上限制加密」)。它不但要答"这块地是什么",
            还要答"周边那些地能盖什么",维度和这里的"距最近的 X 多远"不同。

硬把它们塞进 SOURCES 只会让"数据源"这个概念失去意义。

数据来源:OpenStreetMap(© OpenStreetMap contributors,ODbL)。
"""

# ---------------------------------------------------------------- 数据源
#
# geometry:
#   point —— 用 `out center`,取质心。适合建筑、站点这类小要素。
#   line  —— 用 `out geom`,沿线按 RESAMPLE_M 米重采样。**道路、铁路必须用这个**:
#            一条 20 公里的高速,质心可能在离你 10 公里的地方,毫无意义。
#   area  —— 同 line,采的是边界轮廓。适合工业区、公园这类"边界才重要"的面。
#            **公园按质心算是错的**:审计实测 Richmond 片区 11% 的房源"距公园"被报远了
#            100 米以上(249 Punt Rd 报 301 米,实际到公园边 39 米)。面要素另外保留一个
#            带名字的中心点,供"最近的公园叫什么""离 Albert Park 近"按名字查找用。
#
# measure:
#   nearest —— 算到最近一个的距离,证据键为 <kind>_m
#   count   —— 数半径内有几个,证据键为 <kind>_<radius>m
#
# user_facing:
#   True  —— 会在结果里直接显示"最近的 X 在 Y 米外",且支持"离 X 多少米内"筛选
#   False —— 只作为抽象属性的证据,不单独展示(如主干道:用户不会问"最近的
#            主干道在哪",但它是"安静"的核心依据)
#
# match:
#   ("amenity", ("hospital",))  —— 标签 amenity=hospital
#   ("shop", "*")               —— 只要带 shop 这个键就算
#   exclude 同样写法,命中就**不算**这个源(如铁路线排除带 service 标签的侧线)
#   **显式声明,不从 overpass 字符串里反解。** 反解看着省事,实际是靠字符串
#   匹配猜标签,加一个带正则的源就会悄悄失配 —— 不报错,只是那个源永远是空的。
#
# count 里的数字是在大墨尔本实测的数量(2026-09-08;三级路、电车线、酒吧夜店、商店餐饮为 2026-09-15),
# 用来判断这个源够不够用。线状源记的是 OSM 线段(way)条数。

SOURCES = {
    # ---- 交通 ----
    "train_station": {
        "match": ("railway", ('station',)),
        "zh": "火车站", "overpass": 'nwr["railway"="station"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 258},
    "tram_stop": {
        "match": ("railway", ('tram_stop',)),
        "zh": "电车站", "overpass": 'nwr["railway"="tram_stop"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 1630},
    "bus_stop": {
        "match": ("highway", ('bus_stop',)),
        "zh": "公交站", "overpass": 'nwr["highway"="bus_stop"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 15787},
    "airport": {
        "match": ("aeroway", ('aerodrome',)),
        "zh": "机场", "overpass": 'nwr["aeroway"="aerodrome"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 26},

    # ---- 教育 ----
    "kindergarten": {
        "match": ("amenity", ('kindergarten', 'childcare')),
        "zh": "幼儿园/托儿所",
        "overpass": 'nwr["amenity"~"^(kindergarten|childcare)$"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 1242},
    "primary_school": {
        "match": ("amenity", ("school",)),
        "zh": "小学", "overpass": 'nwr["amenity"="school"]', "school_level": "primary",
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 1253},
    "secondary_school": {
        "match": ("amenity", ("school",)),
        "zh": "中学", "overpass": None, "school_level": "secondary",   # 与小学同一次查询
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 587},
    "university": {
        "match": ("amenity", ('university', 'college')),
        "zh": "大学/学院", "overpass": 'nwr["amenity"~"^(university|college)$"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 189},
    "library": {
        "match": ("amenity", ('library',)),
        "zh": "图书馆", "overpass": 'nwr["amenity"="library"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 209},

    # ---- 医疗 ----
    "hospital": {
        "match": ("amenity", ('hospital',)),
        "zh": "医院", "overpass": 'nwr["amenity"="hospital"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 156},
    "pharmacy": {
        "match": ("amenity", ('pharmacy',)),
        "zh": "药房", "overpass": 'nwr["amenity"="pharmacy"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 725},

    # ---- 生活 ----
    "bank": {
        "match": ("amenity", ('bank',)),
        "zh": "银行", "overpass": 'nwr["amenity"="bank"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 462},
    "supermarket": {
        "match": ("shop", ('supermarket',)),
        "zh": "超市", "overpass": 'nwr["shop"="supermarket"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 1043},
    "mall": {
        "match": ("shop", ('mall',)),
        "zh": "购物中心", "overpass": 'nwr["shop"="mall"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 309},
    "police": {
        "match": ("amenity", ('police',)),
        "zh": "警察局", "overpass": 'nwr["amenity"="police"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 128},
    "gym": {
        "match": ("leisure", ('fitness_centre',)),
        "zh": "健身房", "overpass": 'nwr["leisure"="fitness_centre"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 599},
    "sports_centre": {
        "match": ("leisure", ('sports_centre',)),
        "zh": "体育中心", "overpass": 'nwr["leisure"="sports_centre"]',
        "geometry": "point", "measure": "nearest", "user_facing": True, "count": 819},

    # ---- 环境:正面 ----
    "park": {
        "match": ("leisure", ('park', 'garden')),
        "zh": "公园绿地", "overpass": 'nwr["leisure"~"^(park|garden)$"]',
        "geometry": "area", "measure": "nearest", "user_facing": True, "count": 16785},
    "beach": {
        "match": ("natural", ('beach',)),
        "zh": "海滩", "overpass": 'nwr["natural"="beach"]',
        "geometry": "area", "measure": "nearest", "user_facing": True, "count": 223},

    # ---- 环境:负面(离得越远越好)----
    "major_road": {
        "match": ("highway", ('motorway', 'trunk', 'primary')),
        "zh": "主干道", "overpass": 'way["highway"~"^(motorway|trunk|primary)$"]',
        "geometry": "line", "measure": "nearest", "user_facing": False, "count": 18885},
    # 次干道单独一类,**不是**并进 major_road。
    # 起因:一套紧挨 Burnley Street(OSM highway=secondary)的房子,"距最近主干道"
    # 报出 397 米,于是"安静"拿了高分 —— 因为 secondary 根本不在 major_road 的
    # 定义里。实测这类误判占全库 8.1%(次干道 ≤100m 却因主干道 ≥300m 而算作安静)。
    # 分成两类而不是合并:高速和次干道的噪音量级差着一档,合并会让"离高速 50 米"
    # 和"离次干道 50 米"得到同一个分,那是另一种失真。
    "secondary_road": {
        "match": ("highway", ('secondary',)),
        "zh": "次干道", "overpass": 'way["highway"~"^(secondary)$"]',
        "geometry": "line", "measure": "nearest", "user_facing": False, "count": 12849},
    # 三级路和电车线。起因(审计 BUG-08):安静分原本看不到它们 —— Richmond 片区离三级路
    # ≤25 米的房源安静分中位 30、≥150 米的中位 29,分数完全区分不了"贴着车流"和"远离车流"。
    # 住宅小街(residential)**不加**:几乎每套房都临一条,加进来只会让分数整体平移。
    "tertiary_road": {
        "match": ("highway", ('tertiary',)),
        "zh": "三级路", "overpass": 'way["highway"="tertiary"]',
        "geometry": "line", "measure": "nearest", "user_facing": False, "count": 33326},
    "tram_line": {
        # 车厂、侧线同样排除(理由同下面的 railway)
        "match": ("railway", ('tram',)), "exclude": ("service", "*"),
        "zh": "电车线", "overpass": 'way["railway"="tram"]',
        "geometry": "line", "measure": "nearest", "user_facing": False, "count": 1032},
    "railway": {
        # 带 service 标签的是站场、侧线、检修线,不走客运列车,不算噪音源。
        # 这个排除原本写在 Overpass 查询里(["service"!~"."]),负向正则在公共端点上
        # 反复 504 超时,于是挪到本地:查询只取 railway=rail,抓回来再按 exclude 剔掉。
        "match": ("railway", ('rail',)), "exclude": ("service", "*"),
        "zh": "铁路线", "overpass": 'way["railway"="rail"]',
        "geometry": "line", "measure": "nearest", "user_facing": False, "count": 2517},
    "industrial": {
        "match": ("landuse", ('industrial',)),
        "zh": "工业用地", "overpass": 'way["landuse"="industrial"]',
        "geometry": "area", "measure": "nearest", "user_facing": False, "count": 1351},
    "substation": {
        "match": ("power", ('substation',)),
        "zh": "变电站", "overpass": 'nwr["power"="substation"]',
        "geometry": "point", "measure": "nearest", "user_facing": False, "count": 833},
    "fuel": {
        "match": ("amenity", ('fuel',)),
        "zh": "加油站", "overpass": 'nwr["amenity"="fuel"]',
        "geometry": "point", "measure": "nearest", "user_facing": False, "count": 959},
    "cemetery": {
        "match": ("landuse", ('cemetery',)),
        "zh": "墓地", "overpass": 'nwr["landuse"="cemetery"]',
        "geometry": "area", "measure": "nearest", "user_facing": False, "count": 79},

    # ---- 密度类(数半径内有几个,不是算距离)----
    # 只算真正的夜间场所。餐厅和快餐原本也在这里,结果 300 米内出现第一家外卖店,
    # 安静分就掉 16 分 —— 和开了一家夜店扣得一样多(审计 BUG-09)。餐饮挪到下面的 shop。
    "nightlife": {
        "match": ("amenity", ('bar', 'pub', 'nightclub')),
        "zh": "酒吧夜店",
        "overpass": 'nwr["amenity"~"^(bar|pub|nightclub)$"]',
        "geometry": "point", "measure": "count", "radius_m": 300,
        "user_facing": False, "count": 1186},
    "shop": {
        # 只要带 shop 标签的都算,外加咖啡馆、餐厅、快餐。"*" = 只看这个键存不存在。
        "match": ("shop", "*"), "extra_match": ("amenity", ("cafe", "restaurant", "fast_food")),
        "zh": "商店餐饮",
        "overpass": 'nwr["shop"];nwr["amenity"~"^(cafe|restaurant|fast_food)$"]',
        "geometry": "point", "measure": "count", "radius_m": 800,
        "user_facing": False, "count": 28931},
}

# 沿线/沿边界重采样的间距(米)。50 米意味着距离误差上界 25 米,对噪音评估足够。
RESAMPLE_M = 50

# 房源自身列提供的证据(不来自 OSM)
PROPERTY_EVIDENCE = {
    "distance_cbd_km": {"zh": "距 CBD", "unit": "公里"},
    "size_m2": {"zh": "面积", "unit": "㎡"},
}

# 按区名查表得来的证据(不来自 OSM,也不是房源自身的列)。
# **粒度是 LGA 级**,比点级的 OSM 数据粗一个数量级 —— 标签里就写明,
# 免得输出时忘了标注。见 app/amenities/suburb_stats.py。
SUBURB_EVIDENCE = {
    "crime_rate_per_100k": {"zh": "所在 LGA 罪案率", "unit": "起/10万人"},
}

# 这些证据按**房型分别**算分位。拿公寓的面积和别墅比毫无意义 ——
# 实测公寓中位 85㎡、别墅 220㎡、联排 152㎡。
BY_TYPE_KEYS = ("size_m2",)


def evidence_key(kind: str) -> str:
    """数据源 -> 它产出的证据键名。"""
    source = SOURCES[kind]
    if source["measure"] == "count":
        return f"{kind}_{source['radius_m']}m"
    return f"{kind}_m"


def evidence_label(key: str) -> tuple[str, str]:
    """证据键 -> (中文标签, 单位)。"""
    for kind, source in SOURCES.items():
        if evidence_key(kind) == key:
            if source["measure"] == "count":
                return f"{source['radius_m']} 米内{source['zh']}", "家"
            return f"距最近{source['zh']}", "米"
    meta = PROPERTY_EVIDENCE.get(key) or SUBURB_EVIDENCE.get(key)
    return (meta["zh"], meta["unit"]) if meta else (key, "")


USER_FACING_KINDS = tuple(k for k, v in SOURCES.items() if v["user_facing"])

# ---------------------------------------------------------------- 抽象属性
#
# parts 的每一项是 证据键 -> (方向, 权重):
#   near —— 离得越近,这个属性越强(距离取反后的分位)
#   far  —— 离得越远越强
#   many —— 数量越多越强
#   few  —— 数量越少越强
#
# 权重是**明示的设计选择,不是训练出来的**,写在这里就是为了能被质疑和修改。
# 每个属性都得能一句话说清依据什么 —— 说不清的就不该存在。
#
# synonyms 是给 LLM 的映射线索,不是关键词匹配表。用户的说法是无穷的,
# 这份清单只需要覆盖典型说法,剩下的靠 LLM 的同义改写能力。

ATTRIBUTES = {
    "quiet": {
        "zh": "安静",
        "synonyms": ["安静", "清静", "不吵", "僻静", "别靠马路", "别靠铁路",
                     "怕吵", "睡眠浅", "闹中取静", "清净"],
        # 权重按噪音量级递减:主干道 > 次干道 ≈ 铁路 > 三级路 > 电车线。
        #   V5:主干道 .29 次干道 .17 铁路 .17 夜生活 .25 工业 .12
        #   现:主干道 .26 次干道 .15 三级路 .10 铁路 .14 电车线 .07 夜生活 .18 工业 .10
        # 夜生活从 .25 降到 .18:它现在只数酒吧/夜店/pub,不再含餐厅快餐,数量少了一个量级。
        "parts": {"major_road_m": ("far", 0.26), "secondary_road_m": ("far", 0.15),
                  "tertiary_road_m": ("far", 0.10), "railway_m": ("far", 0.14),
                  "tram_line_m": ("far", 0.07), "nightlife_300m": ("few", 0.18),
                  "industrial_m": ("far", 0.10)},
        "note": "远离主干道、次干道、三级路、铁路与电车线和工业区,周边酒吧夜店少",
    },
    "lively": {
        "zh": "热闹",
        "synonyms": ["热闹", "繁华", "有人气", "烟火气", "夜生活", "年轻人多",
                     "别太冷清", "市口好"],
        "parts": {"shop_800m": ("many", 0.55), "nightlife_300m": ("many", 0.45)},
        "note": "周边商店餐饮与酒吧夜店密集",
    },
    "convenient": {
        "zh": "生活便利",
        "synonyms": ["生活便利", "买东西方便", "配套齐全", "楼下就有超市",
                     "吃饭方便", "日常采买方便"],
        "parts": {"shop_800m": ("many", 0.50), "supermarket_m": ("near", 0.30),
                  "pharmacy_m": ("near", 0.20)},
        "note": "步行范围内商店餐饮多、离超市和药房近",
    },
    "shopping": {
        "zh": "购物方便",
        "synonyms": ["购物", "逛街", "商场", "购物中心", "买衣服", "shopping"],
        "parts": {"mall_m": ("near", 0.60), "supermarket_m": ("near", 0.40)},
        "note": "离购物中心与超市近",
    },
    "green": {
        "zh": "近公园绿地",
        "synonyms": ["公园", "绿化", "绿地", "遛弯", "散步", "遛狗",
                     "推婴儿车", "看得到树"],
        "parts": {"park_m": ("near", 1.0)},
        "note": "离公园或绿地近",
    },
    "beach_access": {
        "zh": "近海",
        "synonyms": ["海边", "海滩", "近海", "看海", "海景", "beach"],
        "parts": {"beach_m": ("near", 1.0)},
        "note": "离海滩近",
    },
    "transport": {
        "zh": "通勤方便",
        "synonyms": ["通勤", "上班方便", "交通便利", "近地铁", "近火车站",
                     "近电车", "tram", "公共交通", "不想开车", "离公司近"],
        "parts": {"train_station_m": ("near", 0.40), "tram_stop_m": ("near", 0.25),
                  "bus_stop_m": ("near", 0.15), "distance_cbd_km": ("near", 0.20)},
        "note": "离火车站、电车站、公交站近,且离 CBD 近",
    },
    "school_access": {
        "zh": "教育配套",
        # 注意这里**没有"学区"**。"学区"在澳洲指的是招生边界内,是一个确定的
        # 事实,由 app/amenities/zones.py 负责;这个属性测的是"离学校多远",
        # 是另一回事。实测只有 54% 的房源"最近的小学"就是"所属学区的小学" ——
        # 把两者混为一谈,近一半的情况会答错。
        "synonyms": ["附近有学校", "小孩上学", "近幼儿园", "近中学",
                     "孩子读书", "上学方便", "教育配套"],
        "parts": {"primary_school_m": ("near", 0.40), "secondary_school_m": ("near", 0.28),
                  "kindergarten_m": ("near", 0.22), "library_m": ("near", 0.10)},
        # 这句必须一直挂着:我们只有**距离**,没有任何学校排名或招生数据。
        "note": "离中小学、幼儿园与图书馆近(只衡量距离,不代表学校质量 —— 本系统没有排名数据)",
    },
    "medical": {
        "zh": "医疗方便",
        "synonyms": ["医疗", "近医院", "看病方便", "养老", "老人住", "就医"],
        "parts": {"hospital_m": ("near", 0.65), "pharmacy_m": ("near", 0.35)},
        "note": "离医院与药房近",
    },
    "fitness": {
        "zh": "运动健身",
        "synonyms": ["健身", "运动", "健身房", "球场", "游泳", "跑步"],
        "parts": {"gym_m": ("near", 0.50), "sports_centre_m": ("near", 0.50)},
        "note": "离健身房与体育中心近",
    },
    "spacious": {
        "zh": "宽敞",
        "synonyms": ["宽敞", "大一点", "面积大", "够住", "别太挤",
                     "三代同堂", "活动空间"],
        "parts": {"size_m2": ("many", 1.0)},
        "note": "面积在同房型中偏大(有建筑面积用建筑面积,否则用地块面积)",
    },
    "family": {
        "zh": "适合家庭",
        "synonyms": ["适合家庭", "带孩子", "一家人住", "family friendly",
                     "小孩成长", "有孩子"],
        "parts": {"primary_school_m": ("near", 0.28), "park_m": ("near", 0.20),
                  "size_m2": ("many", 0.20), "major_road_m": ("far", 0.20),
                  "kindergarten_m": ("near", 0.12)},
        "note": "离小学、幼儿园和公园近,面积大,远离主干道",
    },
    "away_industry": {
        "zh": "远离工业与污染源",
        "synonyms": ["别靠工厂", "工业区", "污染", "变电站", "高压线",
                     "加油站", "环境干净"],
        "parts": {"industrial_m": ("far", 0.50), "substation_m": ("far", 0.30),
                  "fuel_m": ("far", 0.20)},
        "note": "远离工业用地、变电站与加油站",
    },
    "low_crime": {
        "zh": "治安较好",
        "synonyms": ["治安", "安全", "犯罪率低", "安全性", "社会治安", "太平"],
        "parts": {"crime_rate_per_100k": ("few", 1.0)},
        # 这段话必须一直挂着:粒度、时间、以及"这不是警察局距离"
        "note": ("所在 LGA 的每 10 万人罪案率较低(维州罪案统计局官方数据)。"
                 "**粒度是 LGA 级不是 suburb 级**,同一个 LGA 内所有房源同分;"
                 "且数据是近期的、房源是 2016–2018 年的,只能当相对指标看"),
    },
    "away_cemetery": {
        "zh": "远离墓地",
        "synonyms": ["墓地", "公墓", "陵园", "别挨着墓地", "忌讳"],
        "parts": {"cemetery_m": ("far", 1.0)},
        # 数量少要说明:79 个墓地在大墨尔本是合理的(墓地少而大),
        # 但分位表的分辨率因此不高,给分要保守解读。
        "note": "远离墓地(全区仅 79 处,分位分辨率有限)",
    },
}
ATTRIBUTE_KEYS = tuple(ATTRIBUTES)

# 可能存在取舍的属性对,不是逻辑互斥。保留两项并用实际候选验证交集。
# 名称保留兼容旧调用方;不允许据此自动删除条件。
CONFLICTS = (("quiet", "lively"),)

# **数据里根本没有的东西。** 问到这些必须明确回答"本系统没有这项数据",
# 而不是悄悄用一个沾边的属性顶上去 —— 用户会以为系统考虑过了。
#
# 尤其注意"治安":库里有警察局位置,但**警察局离得近不等于治安好** ——
# 市中心警局最密集,犯罪率通常也最高。拿它当治安指标是典型的伪科学,
# 而且因为"看起来有数据支撑",比明说不知道更容易骗到人。
UNSUPPORTED = {
    "采光朝向": "数据集没有朝向、楼层、窗户信息",
    "装修房况": "数据集没有装修状况、房屋成色的信息",
    "房龄新旧": "建成年份虽在库中,但检索层不返回该字段,线上拿不到",
    "学校排名": "有学校位置和**招生学区边界**,但没有任何排名、评级或教学质量数据",
    # ⚠️ 这两条的措辞要小心。实测第一版写成"街道级治安 -> 已有 LGA 级罪案率,
    # 但没有更细的……",LLM 看到"治安"就把整个需求丢进了 unsupported,
    # 而**「治安」本身是支持的**(low_crime 属性)。所以两条都以"注意:治安
    # 属于支持范围"开头,把否定的范围收窄到真正不支持的那一小块。
    "街道或小区级治安": ("注意:**普通的「治安好」是支持的**,用 low_crime 属性。"
                        "这里指的是比 LGA 更细的街道/小区级治安 —— 官方 suburb 级表"
                        "只有原始案件数、没有人口分母,拿计数跨区比较推不出结论"),
    "分类型犯罪": ("注意:**普通的「治安好」是支持的**,用 low_crime 属性。"
                   "这里指的是按入室盗窃、暴力犯罪等**分类**的可比指标 —— 只有总体罪案率"),
    "空气与噪音实测": "只有到噪音源的距离,没有任何实测分贝或空气质量数据",
    "物业与邻居": "数据集没有物业费、管理质量或住户构成的信息",
    "户型格局": "只有房间数量,没有户型图、面宽、得房率等信息",
    "楼层视野": "数据集没有楼层、朝向或视野信息",
    "升值潜力": "只有 2016–2018 年的成交价,没有足以支撑趋势预测的时间跨度",
    # 实测踩到:用户说"步行 5 分钟到 CBD",系统把它改写成了
    # amenity_needs=[{kind: train_station, max_distance_m: 400}] —— 一个**完全不同**
    # 的条件,而且 unsupported_asks 是空的。用户永远不会知道自己要的东西被换掉了。
    "步行/驾车时间": ("所有距离都是**直线距离**,没有路网,算不出步行或驾车时间。"
                      "「离 X 近」可以答(直线),「步行 N 分钟到 X」不能答"),
    # 「到 CBD 的距离要求」曾列在这里(当时有数据、没做筛选条件)。2026-10-05 起是硬条件
    # max_distance_cbd_km(直线公里),不再是「不支持」;「步行 N 分钟到 CBD」仍归上面那条。
}


def all_evidence_keys() -> tuple[str, ...]:
    """所有会被算出来的证据键。基准线脚本按它决定要建哪些分位表。"""
    return (tuple(evidence_key(k) for k in SOURCES)
            + tuple(PROPERTY_EVIDENCE) + tuple(SUBURB_EVIDENCE))


def used_evidence_keys() -> set[str]:
    """真正被某个属性用到的证据键。没被用到的源可以考虑删掉。"""
    return {key for spec in ATTRIBUTES.values() for key in spec["parts"]}


# 提示词里的缩进。生成的块要和周围手写的部分对齐,不然读起来是乱的 ——
# 而提示词的可读性直接影响模型照不照做。
_INDENT = " " * 21


def prompt_block() -> str:
    """生成给 LLM 的属性清单。**提示词从注册表生成,不手写** ——
    手写的话,注册表加了属性却忘了改提示词,那个属性就永远不会被触发,
    而且不报错,只是安静地失效。这正是 V4 要改掉的毛病。"""
    return "\n".join(
        f"{_INDENT}{name:<15}{spec['zh']}:" + "、".join(spec["synonyms"])
        for name, spec in ATTRIBUTES.items())


def unsupported_block() -> str:
    """生成"数据里没有、必须直说"的清单。"""
    return "\n".join(f"{_INDENT}{k:<16}-> {v}" for k, v in UNSUPPORTED.items())


def amenity_kinds_block() -> str:
    """生成可用的设施类别清单。只列 user_facing 的 —— 主干道、铁路线这类
    用户不会直接问,列出来只会诱导模型误用。"""
    return "\n".join(f"{_INDENT}{k:<18}{SOURCES[k]['zh']}" for k in USER_FACING_KINDS)


def sort_labels() -> dict[str, str]:
    """排序口径的中文标签,也从注册表生成。"""
    return {k: f"「{v['zh']}」评分从高到低" for k, v in ATTRIBUTES.items()}
