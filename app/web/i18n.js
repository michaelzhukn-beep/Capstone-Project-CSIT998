/* 界面文案的中英两份。V9.6
 *
 * 为什么单独一个文件、而且用具名 key 而不是"拿中文原文当 key":
 * 界面上大量句子是拼出来的 ——「两个数差 4.9%,而我们估公寓…只能准到 ±12.0%」。
 * 若按片段翻译,英文语序会碎成「The two numbers differ by」+「4.9%」+「, and we estimate」…
 * 中译英最容易出事的正是语序。所以凡是带数字的句子,这里都写成**函数**,
 * 整句在一处成形,两种语言各自按各自的语序写。
 *
 * 服务端来的标签(属性名、设施名、排序口径、证据项、规划分区…)不在这里 ——
 * 它们跟着 /api/meta?lang= 走,见 app/i18n.py。原则是:
 * **一个字符串只有一个出处**,前端有一份、后端再有一份的,迟早对不上。
 */
(function () {
  'use strict';

  const zh = {
    dir: 'zh',
    htmlLang: 'zh-CN',
    switchTo: 'EN',                 // 按钮上显示的是**要切过去**的那个语言
    switchTitle: 'Switch to English',

    // ---- 顶栏与欢迎页(index.html 里用 data-i18n 标出来的那些) ----
    title: '筑明AI · 墨尔本找房',
    brand: '筑明AI',
    btnAssume: '假设',
    btnNew: '新对话',
    welcomeH: '探索你的理想居所',
    welcomeP: '输入预算、区域或偏好。<br>所有评估数据均基于实测、假设校验与模型测算。',
    // 首屏飘着的例子。**每一条都是能直接跑通的查询**,不是好看的口号 ——
    // 点下去解析不出东西的例子,比没有例子更糟。这八条都拿真解析器验过:
    // 价格、房型、房间数、设施距离、抽象属性、区名、排序口径,各覆盖一部分。
    chips: [
      '100万内 · 近车站 · 3房',
      '墨大周边 · 宜居公寓',
      '80万内 · 高租金回报',
      'Richmond · 低于市场估值',
      '近公园 · 安静 · 2房',
      'Box Hill · 近学校',
      '50万内 · 通勤方便',
      '近海 · 3房',
    ],
    inputPlaceholder: '输入预算、区域或偏好,例如「100万内 · 近车站 · 3房」',
    sendAria: '发送',
    detailAria: '房源细节',

    // ---- 进度 ----
    nodes: {
      parse_intent: '在理解你的要求', search: '在检索房源', analyze: '在算指标',
      enrich: '在算周边与环境', rank: '在筛选排序', present: '在整理结果', explain: '在写说明',
    },
    nodeStatus: n => '正在' + n + '…',
    statusInit: '正在理解你的要求…',
    statusRefine: '按新条件重新找…',
    statusRebatch: '在为这一批重写说明…',
    errPrefix: '出错了:',

    // ---- 对话 ----
    expand: '展开全文',
    collapse: '收起',
    jumpTo: n => '跳到第 ' + n + ' 套',
    jumpRange: (a, b) => '跳到第 ' + a + '–' + b + ' 套',

    // ---- 条件卡 ----
    condHead: '你的条件 <span>点一下改 · × 删除</span>',
    mustLabel: '必须 · 不满足的不会出现',
    wishLabel: '希望 · 满足不了会告诉你,不会硬凑',
    sortGroup: '排序',
    remove: '删除',
    unset: label => label + ' 未定',
    budgetMax: '预算上限',
    budgetMin: '预算下限',
    aud: '澳元',
    bedroomsLabel: '房数',
    bathroomsLabel: '卫数',
    roomsUnit: '间',
    beds: v => v + ' 房',
    baths: v => v + ' 卫',
    typeLabel: '房型',
    typeAny: '房型 不限',
    suburbLabel: '区域(英文区名)',
    suburbAny: '区域 不限',
    scoreChip: (attr, n) => attr + ' ≥ ' + n,
    minScoreTitle: attr => attr + ' 最低评分(0~100)',
    points: '分',
    distChip: (kind, d) => '距' + kind + ' ≤ ' + d,
    distTitle: kind => '距' + kind + '不超过(米)',
    metres: '米',
    nearPlaceChip: (name, d) => '距「' + name + '」' + (d ? ' ≤ ' + d : ''),
    nearPlaceTitle: name => '距「' + name + '」不超过(米,留空=只排序)',
    schoolZoneChip: s => '学区 ' + s,
    yieldChip: p => '毛回报 ≥ ' + p,
    yieldTitle: '毛租金回报率不低于(%)',
    noSoft: '没有软条件 —— 直接在对话里补一句就行,比如"要离火车站近"。',
    sortDefault: '语义相关度(默认)',
    unsupportedNote: list => '本系统没有这类数据,未纳入筛选:' + list.join('、'),
    conflictNote: attr => '「安静」和「热闹」互斥,已忽略「' + attr + '」',
    foundN: n => '找到 ' + n + ' 套',
    foundNone: '没有找到符合条件的',
    seeResults: '看结果',

    // ---- 小编辑框 ----
    cancel: '取消',
    apply: '应用',
    any: '不限',
    assumeTitle: '当前生效的假设',

    // ---- 结果区表头 ----
    byRelevance: '按语义相关度',
    range: (a, b) => '第 ' + a + '–' + b + ' 套',
    count: n => n + ' 套',
    noResultsTitle: '没有找到',
    resultsTitle: '结果',
    emptyMsg: '没有找到符合条件的房源,放宽条件再试。',

    // ---- 卡片 ----
    attrDegree: a => a + '度',
    toPlace: name => '距「' + name + '」',
    nearPlaceBadge: (name, d) => '距「' + name + '」' + d,
    byOpexAssumption: '按运营支出假设',
    valGap: '估值差',
    modelValueSub: v => '模型估值 ' + v,
    grossYieldShort: '毛回报',
    annualRentSub: v => '年租金 ' + v,
    weakNote: s => '(这一项属全库最差的 ' + s + '%)',
    primaryZoneBadge: s => s + ' 小学学区',
    yieldBadge: p => '毛回报 ' + p,
    gapAbove: p => '估值高于售价 ' + p,
    gapBelow: p => '估值低于售价 ' + p,
    heritageOverlay: '历史保护叠加层',
    lowDensityAround: '周边限制加密',
    riskLead: '提醒',
    nextBatch: n => '换一批(还有 ' + n + ' 套)',
    backToFirst: '回到第 1 批',
    batchDone: '这批候选看完了。想看不一样的,改条件比继续翻更有用。',

    // ---- 地图 ----
    mapOffline: '地图需要联网加载,当前没连上',
    mapNoCoords: '这一批房源没有坐标',

    // ---- 详情窗 ----
    semiDetached: '半独立屋',
    closeEsc: '关闭(Esc)',
    close: '关闭',
    carSpaces: n => n + ' 车位',
    toCbd: km => '距 CBD ' + km + ' km',
    rank: r => '高于全库 ' + r + '% 的房源',

    sec1: '1. 价格区间',
    askingPrice: '卖方指导价',
    modelEstimate: '模型估值',
    verdictNormal: (gap, tn, err) =>
      '经模型评估,价格正常。两者相差 ' + gap + ',在' + tn + '的典型误差 ±' + err + ' 以内。',
    verdictAbove: (gap, tn, err) =>
      '模型估值高于指导价 ' + gap + ',超出' + tn + '的典型误差 ±' + err
      + ',差异显著。指导价明显低于估值通常另有原因,建议实地核实后再判断。',
    verdictBelow: (gap, tn, err) =>
      '模型估值低于指导价 ' + gap + ',超出' + tn + '的典型误差 ±' + err
      + ',差异显著。指导价偏高,建议核实其定价依据。',
    rangeNote: (lo, hi) =>
      '估值区间 ' + lo + ' ~ ' + hi + ',约半数房源落在该区间内 —— 这是它的确切含义,并非 95% 置信区间。'
      + '模型依据所在区、房型、房间数、地块面积等特征估算,未纳入装修、朝向与楼层。',

    sec2: '2. 区位与环境',
    straightLine: '以上为地图直线距离,非步行或驾车路程,实际路程通常更远。',
    score0100: '评分 0~100',
    scoreBasis: '评分依据:',
    highMeans: '高分含义:',

    // ---- 距离测算 ----
    measureTitle: '距离测算',
    measureKind: '直线',
    measureFrom: '起点',
    measureTo: '终点',
    measureToPlaceholder: '输入地名(英文),如 Flinders Street Station',
    measureGo: '测算',
    measureBusy: '测算中…',
    measureNote: '两点之间的直线距离。本系统没有路网数据,算不出步行或驾车路程 ——'
      + '地图上那根直线就是它量的东西。',
    measurePair: (a, b) => a + ' → ' + b,
    measureLook: '在地图上查看 →',
    measureClear: '清除',
    sec3: '3. 购置成本',
    rowPrice: '房价',
    rowPriceNote: '卖方指导价',
    rowDuty: '印花税',
    rowDutyNote: rate => '维州法定,按价格分档累进,本套实际税率 ' + rate,
    rowFees: '过户杂费',
    rowFeesNote: '过户、验房等费用。数据集未提供,按下方假设取值',
    rowFeesNoteEditable: '过户、验房等费用;数据集未提供,可按实际报价修改',
    // 拆成两段,中间夹一个输入框。整句读起来仍然是一句完整的话,
    // 而不是"改这里 → 28%"那种把说明和控件分开的写法。
    opexNoteParts: ['运营支出按年租金的 ', '% 计,含物管、维修、保险与空置;可修改'],
    rowTotal: '合计',
    rowTotalNote: '购置总成本,不含贷款相关费用',

    sec4: '4. 出租测算',
    rowRent: '年租金收入',
    rowRentNote: p => '毛租金回报率 ' + p,
    rowNoi: '扣除运营支出后',
    rowNoiNote: p => '支出按年租金的 ' + p + ' 计,含物管、维修、保险与空置',
    rowRoi: '投资回报率',
    rowRoiNote: '上一行净收入 ÷ 购置总成本',
    jargonTitle: '指标口径与计算式',
    jgYield: '毛租金回报率(Gross Yield)',
    jgYieldF: p => '年租金 ÷ 房价 = ' + p,
    jgNoi: '净营运收入(NOI)',
    jgNoiF: v => '年租金扣除运营支出 = ~' + v,
    jgCap: '资本化率(Cap Rate)',
    jgCapF: p => 'NOI ÷ 房价 = ~' + p,
    jgRoi: '投资回报率(ROI)',
    jgRoiF: p => 'NOI ÷(房价+印花税+杂费)= ~' + p,
    rentCaveat: '本栏仅年租金为实测数据,其余两项建立在运营支出假设之上,假设变更后随之重算。',

    sec5: '5. 学区、规划与治安',
    primaryZone: '小学学区',
    secondaryZone: '中学学区',
    notInZone: '不在公立学区内',
    planningZone: '规划分区',
    overlays: '叠加管制',
    none: '无',
    nearbyRadius: r => '周边 ±' + r + ' m',
    nearbyLots: (total, low, high, open) => total + ' 块地'
      + (low ? ' · ' + low + ' 块限制加密' : '') + (high ? ' · ' + high + ' 块允许高密度' : '')
      + (open ? ' · ' + open + ' 块公园绿地' : ''),
    noZoneData: '该坐标无分区数据',
    crimeLabel: lga => '治安 · ' + lga,
    crimeRate: n => n + ' 起 / 10 万人',
    crimeScope: '市政区(LGA)统计,非街道层级',
    sec5Caveat: '规划分区说明法律上「允许」的用途,不预测实际是否会发生;叠加管制是在分区之上附加的限制,'
      + '如景观保护、洪水风险。分区、学区与治安为当前数据,成交价为 2016–2018 年,两者之间不构成因果关系。',

    legendTitle: '数据来源标识',
    legendMeasured: '实测数据或法定数值',
    legendAssume: '基于下方假设计算',
    legendModel: '模型预测,存在误差',

  };

  const en = {
    dir: 'en',
    htmlLang: 'en',
    switchTo: '中文',
    switchTitle: '切换到中文',

    title: 'Nestwise · Melbourne Property',
    brand: 'Nestwise',
    btnAssume: 'Assumptions',
    btnNew: 'New chat',
    welcomeH: 'Find the home that fits',
    welcomeP: 'Enter a budget, a suburb, or a preference.<br>Every figure is measured, assumption-checked, or model-estimated.',
    chips: [
      'Under $1M · near station · 3 bed',
      'Near Melbourne Uni · quiet apartment',
      'Under $800k · best rental yield',
      'Richmond · below model estimate',
      'Near parks · quiet · 2 bed',
      'Box Hill · near schools',
      'Under $500k · easy commute',
      'Near the beach · 3 bed',
    ],
    inputPlaceholder: 'Budget, suburb or preference — e.g. Under $1M · 3 bed',
    sendAria: 'Send',
    detailAria: 'Property details',

    nodes: {
      parse_intent: 'Reading your request', search: 'Searching listings', analyze: 'Computing metrics',
      enrich: 'Measuring the surroundings', rank: 'Filtering and ranking', present: 'Assembling results',
      explain: 'Writing the summary',
    },
    nodeStatus: n => n + '…',
    statusInit: 'Reading your request…',
    statusRefine: 'Searching again with the new filters…',
    statusRebatch: 'Rewriting the summary for this batch…',
    errPrefix: 'Error: ',

    expand: 'Show more',
    collapse: 'Show less',
    jumpTo: n => 'Jump to property ' + n,
    jumpRange: (a, b) => 'Jump to properties ' + a + '–' + b,

    condHead: 'Your filters <span>click to edit · × to remove</span>',
    mustLabel: 'Required · results that miss these are excluded',
    wishLabel: 'Preferred · if these cannot be met you will be told, not fudged',
    sortGroup: 'Sort',
    remove: 'Remove',
    unset: label => label + ': any',
    budgetMax: 'Max price',
    budgetMin: 'Min price',
    aud: 'AUD',
    bedroomsLabel: 'Bedrooms',
    bathroomsLabel: 'Bathrooms',
    roomsUnit: 'rooms',
    beds: v => v + ' bed',
    baths: v => v + ' bath',
    typeLabel: 'Property type',
    typeAny: 'Type: any',
    suburbLabel: 'Suburb',
    suburbAny: 'Suburb: any',
    scoreChip: (attr, n) => attr + ' ≥ ' + n,
    minScoreTitle: attr => 'Minimum ' + attr + ' score (0–100)',
    points: 'score',
    distChip: (kind, d) => kind + ' ≤ ' + d,
    distTitle: kind => 'Max distance to ' + kind + ' (m)',
    metres: 'm',
    nearPlaceChip: (name, d) => '“' + name + '”' + (d ? ' ≤ ' + d : ''),
    nearPlaceTitle: name => 'Max distance to “' + name + '” (m; leave blank to sort only)',
    schoolZoneChip: s => 'School zone: ' + s,
    yieldChip: p => 'Gross yield ≥ ' + p,
    yieldTitle: 'Minimum gross rental yield (%)',
    noSoft: 'No preferences yet — just add one in the chat, e.g. "close to a train station".',
    sortDefault: 'Semantic relevance (default)',
    unsupportedNote: list => 'No data for these, so they were not used as filters: ' + list.join(', '),
    conflictNote: attr => '“Quiet” and “lively” are mutually exclusive; “' + attr + '” was ignored.',
    foundN: n => n + ' found',
    foundNone: 'No matches',
    seeResults: 'See results',

    cancel: 'Cancel',
    apply: 'Apply',
    any: 'Any',
    assumeTitle: 'Assumptions currently in effect',

    byRelevance: 'By semantic relevance',
    range: (a, b) => 'Properties ' + a + '–' + b,
    count: n => n + (n === 1 ? ' property' : ' properties'),
    noResultsTitle: 'No matches',
    resultsTitle: 'Results',
    emptyMsg: 'No properties match these filters. Try relaxing one.',

    attrDegree: a => a,
    toPlace: name => 'To “' + name + '”',
    nearPlaceBadge: (name, d) => '“' + name + '” ' + d,
    byOpexAssumption: 'Based on the expense assumption',
    valGap: 'Est. vs asking',
    modelValueSub: v => 'Model estimate ' + v,
    grossYieldShort: 'Gross yield',
    annualRentSub: v => 'Annual rent ' + v,
    weakNote: s => ' (bottom ' + s + '% database-wide)',
    primaryZoneBadge: s => s + ' primary zone',
    yieldBadge: p => 'Gross yield ' + p,
    gapAbove: p => 'Estimate ' + p + ' above asking',
    gapBelow: p => 'Estimate ' + p + ' below asking',
    heritageOverlay: 'Heritage overlay',
    lowDensityAround: 'Low-density surroundings',
    riskLead: 'Note',
    nextBatch: n => 'Next batch (' + n + ' left)',
    backToFirst: 'Back to batch 1',
    batchDone: 'That is the whole shortlist. Changing a filter will get you further than paging on.',

    mapOffline: 'The map needs an internet connection and could not load',
    mapNoCoords: 'No coordinates for this batch',

    semiDetached: 'Semi-detached',
    closeEsc: 'Close (Esc)',
    close: 'Close',
    carSpaces: n => n + (n === 1 ? ' car space' : ' car spaces'),
    toCbd: km => km + ' km to CBD',
    rank: r => 'Higher than ' + r + '% of all listings',

    // 房型标签在别处是标题(大写单数「Apartment」),塞进句子中间要小写复数。
    // House / Apartment / Townhouse 三个都是加 s 即可,所以够用;
    // 将来若加了不规则的房型名,这里要跟着改 —— 不改不会报错,只会读起来别扭。
    typeIn: tn => tn.toLowerCase() + 's',
    sec1: '1. Price check',
    askingPrice: 'Asking price',
    modelEstimate: 'Model estimate',
    verdictNormal: (gap, tn, err) =>
      'Assessed as normally priced. The two differ by ' + gap + ', within the typical error of ±'
      + err + ' for ' + en.typeIn(tn) + '.',
    verdictAbove: (gap, tn, err) =>
      'The model estimate is ' + gap + ' above the asking price, beyond the typical error of ±' + err
      + ' for ' + en.typeIn(tn) + ' — a material difference. An asking price well below the estimate usually has a '
      + 'reason; verify in person before drawing a conclusion.',
    verdictBelow: (gap, tn, err) =>
      'The model estimate is ' + gap + ' below the asking price, beyond the typical error of ±' + err
      + ' for ' + en.typeIn(tn) + ' — a material difference. The asking price looks high; ask what it is based on.',
    rangeNote: (lo, hi) =>
      'Estimated range ' + lo + ' – ' + hi + '. About half of all properties fall inside this range — '
      + 'that is its exact meaning, not a 95% confidence interval. The estimate uses suburb, property '
      + 'type, room counts and land size; it does not see condition, aspect or floor level.',

    sec2: '2. Location & environment',
    straightLine: 'Distances above are straight-line, not walking or driving routes; real travel is usually longer.',
    score0100: 'Score 0–100',
    scoreBasis: 'Based on: ',
    highMeans: 'A high score means: ',

    measureTitle: 'Distance tool',
    measureKind: 'straight line',
    measureFrom: 'From',
    measureTo: 'To',
    measureToPlaceholder: 'Place name, e.g. Flinders Street Station',
    measureGo: 'Measure',
    measureBusy: 'Measuring…',
    measureNote: 'Straight-line distance between two points. This system has no road network, '
      + 'so walking and driving routes cannot be computed — the straight line drawn on the map '
      + 'is exactly what is being measured.',
    measurePair: (a, b) => a + ' → ' + b,
    measureLook: 'View on the map →',
    measureClear: 'Clear',
    sec3: '3. Purchase cost',
    rowPrice: 'Price',
    rowPriceNote: 'Vendor asking price',
    rowDuty: 'Stamp duty',
    rowDutyNote: rate => 'Victorian statutory duty, banded and progressive; effective rate ' + rate + ' here',
    rowFees: 'Settlement costs',
    rowFeesNote: 'Conveyancing, inspections and similar. Not in the dataset; taken from the assumption below',
    rowFeesNoteEditable: 'Conveyancing, inspections and similar; not in the dataset, editable to match a quote',
    opexNoteParts: ['Operating expenses at ', '% of annual rent — management, repairs, insurance and vacancy; editable'],
    rowTotal: 'Total',
    rowTotalNote: 'Total acquisition cost, excluding any finance costs',

    sec4: '4. Rental outlook',
    rowRent: 'Annual rent',
    rowRentNote: p => 'Gross rental yield ' + p,
    rowNoi: 'After operating expenses',
    rowNoiNote: p => 'Expenses at ' + p + ' of annual rent — management, repairs, insurance and vacancy',
    rowRoi: 'Return on investment',
    rowRoiNote: 'Net income above ÷ total acquisition cost',
    jargonTitle: 'Definitions and formulas',
    jgYield: 'Gross rental yield',
    jgYieldF: p => 'Annual rent ÷ price = ' + p,
    jgNoi: 'Net operating income (NOI)',
    jgNoiF: v => 'Annual rent less operating expenses = ~' + v,
    jgCap: 'Capitalisation rate',
    jgCapF: p => 'NOI ÷ price = ~' + p,
    jgRoi: 'Return on investment (ROI)',
    jgRoiF: p => 'NOI ÷ (price + stamp duty + settlement costs) = ~' + p,
    rentCaveat: 'Only the annual rent here is measured data. The other two rest on the operating-expense '
      + 'assumption and are recalculated whenever it changes.',

    sec5: '5. Schools, planning & crime',
    primaryZone: 'Primary school zone',
    secondaryZone: 'Secondary school zone',
    notInZone: 'Not in a public school zone',
    planningZone: 'Planning zone',
    overlays: 'Overlays',
    none: 'None',
    nearbyRadius: r => 'Within ±' + r + ' m',
    nearbyLots: (total, low, high, open) => total + ' lots'
      + (low ? ' · ' + low + ' low-density' : '') + (high ? ' · ' + high + ' high-density' : '')
      + (open ? ' · ' + open + ' open space' : ''),
    noZoneData: 'No zoning data for these coordinates',
    crimeLabel: lga => 'Crime · ' + lga,
    crimeRate: n => n + ' per 100,000',
    crimeScope: 'Local government area, not street level',
    sec5Caveat: 'A planning zone states what the law permits, not what will happen; overlays are extra '
      + 'controls layered on top of the zone, such as landscape protection or flood risk. Zoning, school '
      + 'zones and crime figures are current, while sale prices are from 2016–2018 — no causal link '
      + 'should be drawn between them.',

    legendTitle: 'How to read the numbers',
    legendMeasured: 'Measured data or statutory value',
    legendAssume: 'Derived from the assumptions below',
    legendModel: 'Model prediction, subject to error',

  };

  window.I18N = { zh: zh, en: en };
})();
