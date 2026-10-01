# 数据审计结果

运行于 2026-10-01 19:17,耗时 49s。失败样本见 `data_audit_samples.json`。

| 状态 | 编号 | 检查 | 结果 |
|---|---|---|---|
| PASS | A1 | 行数与必填列空值 | 20800 行;空值 {'price': 0, 'bedrooms': 0, 'bathrooms': 0, 'latitude': 22, 'longitude': 22, 'annual_rent': 0, 'car_spaces': 0, 'land_size': 2827, 'building_area': 10144, 'distance_cbd': 0}(无坐标的 22 套不参与一切地理计算) |
| PASS | A2 | 经纬度在墨尔本范围 | 越界 0 套 |
| INFO | A3 | 价格/房间数极端值 | 58 套:卧室 0 = 16,浴室 0 = 34,卧室>8 = 10,车位>10 = 2 |
| PASS | A4 | 展示与打分用的距 CBD = 坐标直线距离 | 最大偏差 0.050 km |
| INFO | A4b | 数据集自带 distance_cbd 列与坐标直线距离(仅估值模型仍在用) | /差/ 中位 1.11 km,p95 5.04 km,>3km 3103 套(数据集的 Distance 是按邮编/区给的,非逐套) |
| PASS | A5 | 明显录错的建筑面积(<20㎡)不被拿去打分 | land_size=0: 1942;building_area=0: 61;0<building_area<20㎡: 93,打分时仍用到 <20㎡ 面积的 0 |
| PASS | A6 | 房型取值 | {'house': 15728, 'apartment': 3493, 'townhouse': 1579} |
| PASS | B1 | 年租金独立重配(用数据库里显示的卧室数) | 不一致 0 套,其中 0 套是:库里用了「全部房型」中位数,但按显示的卧室数本可匹配到同卧室数的租金(join 用的是原始 Bedroom2,空值没用 Rooms 补) |
| INFO | B2 | 租金匹配粒度占比 | {'precinct_exact_sheet': 16906, 'region_exact_sheet': 3868, 'precinct_all_properties': 26};同区同卧室数只占 81.3% |
| INFO | B4 | 毛回报率极端值 | <1.5%: 960 套;>10%: 7 套;最高 32.0% |
| PASS | C1 | 印花税独立重算(全库) | 不一致 0 套 |
| PASS | C2 | 收益指标独立重算(全库) | 不一致 0 套(opex 28%,杂费 2,000) |
| PASS | C3 | 印花税分档边界与单调性 | 边界 25,000: 350 -> 350;130,000: 2,870 -> 2,870;960,000: 52,670 -> 52,800;1千~300万按千元步进单调: True(960k 处 +130 元跳变是法定表本身的形态) |
| PASS | C5 | 缺输入返回 None 而非 0 | [{"gross_yield": null, "operating_expenses": 8400, "noi": 21600, "cap_rate": null, "roi": null, "stamp_duty": null, "total_cost": null}, {"gross_yield": null, "operating_expenses": null, "noi": null, "cap_rate": null, "roi": null, "stamp_duty": 25070, "total_cost": 527070}, {"gross_yield": null, "operating_expenses": 8400, "noi": 21600, "cap_rate": null, "roi": null, "stamp_duty": null, "total_cost": null}] |
| PASS | D3 | 同输入两次预测一致 | 0 套不一致 |
| PASS | D1/D2 | 区间嵌套顺序、position 与 gap 符号一致(全库) | 违反 0;分布 {'above': 1170, 'within': 18587, 'below': 1043}(below 占 5.0%) |
| INFO | D6 | 单调性:只加面积/房间,估值下降 >3% 的比例 | {'building_area×1.3': '0/985', 'land_size×1.3': '0/1532', 'bedrooms+1': '0/2000', 'bathrooms+1': '0/2000'} |
| PASS | E1/E2 | BallTree 最近距离/半径计数 vs 暴力 haversine(500 套 × 29 类) | 最大偏差(米或个) {"train_station": 0.0, "tram_stop": 0.0, "bus_stop": 0.0, "airport": 0.0, "kindergarten": 0.0, "primary_school": 0.0, "secondary_school": 0.0, "university": 0.0, "library": 0.0, "hospital": 0.0, "pharmacy": 0.0, "bank": 0.0, "supermarket": 0.0, "mall": 0.0, "police": 0.0, "gym": 0.0, "sports_centre": 0.0, "park": 0.0, "beach": 0.0, "major_road": 0.0, "secondary_road": 0.0, "tertiary_road": 0.0, "tram_line": 0.0, "railway": 0.0, "industrial": 0.0, "substation": 0.0, "fuel": 0.0, "cemetery": 0.0, "nightlife": 0.0, "shop": 0.0} |
| PASS | F1 | 分数范围 0–100 / 缺失属性数 | 越界 0;缺失 {'quiet': 0, 'lively': 0, 'convenient': 0, 'shopping': 0, 'green': 0, 'beach_access': 0, 'transport': 0, 'school_access': 0, 'medical': 0, 'fitness': 0, 'spacious': 2480, 'family': 0, 'away_industry': 0, 'low_crime': 0, 'away_cemetery': 0} |
| PASS | F2 | 分位基准 vs 当前全库重算(p10/p50/p90 在基准表里的分位偏移) | 偏移 >0.05 的:无;全部 {'train_station_m': 0.007, 'tram_stop_m': 0.006, 'bus_stop_m': 0.007, 'airport_m': 0.007, 'kindergarten_m': 0.01, 'primary_school_m': 0.009, 'secondary_school_m': 0.012, 'university_m': 0.007, 'library_m': 0.01, 'hospital_m': 0.012, 'pharmacy_m': 0.011, 'bank_m': 0.007, 'supermarket_m': 0.008, 'mall_m': 0.012, 'police_m': 0.015, 'gym_m': 0.008, 'sports_centre_m': 0.007, 'park_m': 0.014, 'beach_m': 0.015, 'major_road_m': 0.006, 'secondary_road_m': 0.01, 'tertiary_road_m': 0.007, 'tram_line_m': 0.006, 'railway_m': 0.009, 'industrial_m': 0.011, 'substation_m': 0.008, 'fuel_m': 0.01, 'cemetery_m': 0.012, 'nightlife_300m': 0.006, 'shop_800m': 0.007, 'distance_cbd_km': 0.006, 'crime_rate_per_100k': 0.007} |
| PASS | F3 | 方向变形测试(1500 套 × 全部分项) | 违反 0 |
| PASS | F4 | score_rank 随分数单调 | 不单调的属性 [] |
| PASS | F6 | 常识相关性 | 安静 vs 热闹 r=-0.77;交通分 vs 距 CBD r=-0.74 |
| PASS | F5b | 控制其他噪音源后,紧邻三级路的安静分明显更低(全库分层) | 主干道/次干道/铁路都 ≥400m 的房源里:三级路 ≤25m 的 440 套中位 67.0,≥300m 的 1298 套中位 76.0,差 9.0 |
| PASS | F7 | 「宽敞」按房型分别排位(各房型中位应接近 50) | {'house': 52.0, 'apartment': 53.0, 'townhouse': 48.5} |
| PASS | E3 | 线状源距离 vs Richmond 原始 OSM 线段精确距离 | major_road: n=601 系统-精确:中位 +1m,p90 +3m,最大 +17m,>50m 的 0 套 (0%);secondary_road: n=433 系统-精确:中位 +1m,p90 +4m,最大 +13m,>50m 的 0 套 (0%);tertiary_road: n=574 系统-精确:中位 +1m,p90 +4m,最大 +12m,>50m 的 0 套 (0%);railway: n=457 系统-精确:中位 +2m,p90 +4m,最大 +8m,>50m 的 0 套 (0%) |
| PASS | F5 | Richmond 片区紧邻三级路(≤25m)却安静分 ≥70 | Richmond 片区:≤25m 的 59 套安静分中位 32.0;≥150m 的 465 套中位 34.0;≤25m 且 ≥70 分 0 套 |
| PASS | E4 | 近公园:系统距离比到公园边界(原始 OSM 轮廓)远 >100m | Richmond 片区 731 套中 0 套 |
| PASS | G1 | 学区归属 vs 原始多边形逐个 contains(400 套) | 不一致 0 |
| PASS | G2/G3 | 同学段命中多个学区 / 无学区 | 多重命中(系统只报第一个){'primary': 0, 'secondary': 0};无小学学区 1,无中学学区 0 |
| PASS | H1 | 每个 suburb 能查到罪案率 | 查不到的 0 个区、0 套:{} |
| PASS | H2 | 同一 LGA 下各区罪案率应相同(数据是 LGA 级) | 不一致的 LGA 0 个;数据年份 2026(成交价 2016–2018) |
| PASS | I2 | 无分区 / 未分类分区与叠加层代码 | 无分区 4;未分类分区 {};未分类叠加层 {} |
| PASS | I3 | can_redevelop / risks 与叠加层一致 | 矛盾 0 |
| PASS | I1 | 分区归属 vs 原始多边形独立判定(300 套) | 不一致或多重 0 |
| PASS | I4 | ±350m 方框实际尺寸 | 东西 699m × 南北 699m |
