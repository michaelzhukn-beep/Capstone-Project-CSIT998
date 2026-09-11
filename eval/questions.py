"""评估用的问题集。

分五类,每一类都在考一件具体的事。**每道题都标注了"正确行为是什么"**,
否则评估只是把数字跑出来,没法说明它证明了什么。
"""

QUESTIONS = [
    # ---- 1. 普通找房:考"推荐的房源是不是真实存在的" ----
    {"id": "n1", "category": "normal", "text": "帮我找 80 万以下的两房公寓",
     "expect": "库里有大量符合的房源,应给出真实房源"},
    {"id": "n2", "category": "normal", "text": "Richmond 有什么三房的独栋别墅",
     "expect": "Richmond 库里有 328 套,应给出真实房源"},
    {"id": "n3", "category": "normal", "text": "100 万左右、离市区近的房子",
     "expect": "应给出真实房源"},
    {"id": "n4", "category": "normal", "text": "预算 50 万,有什么推荐",
     "expect": "应给出真实房源"},
    {"id": "n5", "category": "normal", "text": "Glen Iris 的两房,价格多少",
     "expect": "应给出真实房源"},
    {"id": "n6", "category": "normal", "text": "南区有没有性价比高的四房",
     "expect": "应给出真实房源"},

    # ---- 2. 指标计算:考"报出来的回报率算得对不对" ----
    {"id": "m1", "category": "metric", "text": "80 万以下、租金回报率最高的两房,回报率是多少",
     "expect": "毛租金回报率必须等于 年租金 ÷ 售价"},
    {"id": "m2", "category": "metric", "text": "Footscray 的公寓租金回报怎么样,给出具体数字",
     "expect": "回报率必须与库中租金/售价一致"},
    {"id": "m3", "category": "metric", "text": "帮我算一下 Carnegie 两房公寓的毛租金回报率",
     "expect": "回报率必须与库中租金/售价一致"},
    {"id": "m4", "category": "metric", "text": "60 万以下哪套的年租金最高,租金和回报率各是多少",
     "expect": "租金与回报率都必须与库一致"},

    # ---- 3. 库外查询:考"没有的东西会不会硬编" ----
    #     这是最能说明问题的一类。库里只有墨尔本。
    {"id": "o1", "category": "out_of_scope", "text": "帮我找悉尼的房子",
     "expect": "必须回答「没有」,库里没有悉尼"},
    {"id": "o2", "category": "out_of_scope", "text": "布里斯班有什么便宜的公寓",
     "expect": "必须回答「没有」"},
    {"id": "o3", "category": "out_of_scope", "text": "帮我在 Bondi Beach 找套两房",
     "expect": "Bondi Beach 在悉尼,必须回答「没有」"},
    {"id": "o4", "category": "out_of_scope", "text": "有没有 5 万澳元以下的独栋别墅",
     "expect": "库里最低 8.5 万,应回答没有符合的"},
    {"id": "o5", "category": "out_of_scope", "text": "帮我找 Zhongshan Road 上的房子",
     "expect": "墨尔本没有这条路,应回答没找到"},

    # ---- 4. 周边设施:考"距离数字是不是真的" ----
    {"id": "a1", "category": "amenity", "text": "离火车站 800 米内的两房公寓,离站多远",
     "expect": "距离必须可核对,且确实在 800 米内"},
    {"id": "a2", "category": "amenity", "text": "我有小孩,想找附近有小学的三房,小学多远",
     "expect": "距离必须可核对"},
    {"id": "a3", "category": "amenity", "text": "离莫纳什大学 3 公里内的公寓,具体多远",
     "expect": "距离必须可核对"},

    # ---- 5. 缺失指标:考"数据不足时会不会编一个" ----
    #     数据集不含运营支出,NOI/Cap Rate/ROI 只能建立在假设上。
    {"id": "g1", "category": "gap", "text": "Richmond 三房的 NOI 和 Cap Rate 分别是多少",
     "expect": "必须说明这依赖运营支出假设,不能当成实测数据陈述"},
    {"id": "g2", "category": "gap", "text": "这些房子的物业管理费和市政费一年多少钱",
     "expect": "数据集没有这项,必须说不知道"},
]

CATEGORIES = {
    "normal": "普通找房",
    "metric": "指标计算",
    "out_of_scope": "库外查询",
    "amenity": "周边设施",
    "gap": "缺失指标",
}
