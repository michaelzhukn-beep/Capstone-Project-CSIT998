"""可选的真实 LLM 解析验收(会产生 API 调用)。只检查解析,不生成房源说明。

python tests/check_refinement_language.py --live --fixture <test_refinement_api 导出的真实数据>
"""
import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.orchestration import graph as g

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true')
parser.add_argument('--fixture', required=True)
parser.add_argument('--report')
args = parser.parse_args()
if not args.live:
    parser.error('Pass --live explicitly to call the configured LLM')
fixture = json.loads(Path(args.fixture).read_text(encoding='utf-8'))['initial']
cases = [
    ('再热闹一点', 'relative', 'lively'),
    ('不要这么冷清，有点人气就好', 'relative', 'lively'),
    ('没必要这么安静', 'relative', 'quiet'),
    ('便宜一些，其他不变', 'relative', 'price'),
    ('a little livelier please, keep the other requirements', 'relative', 'lively'),
    ('还是安静更重要', 'priority', 'quiet'),
    ('越热闹越好', 'priority', 'lively'),
    ('不要安静了，改找最热闹的', 'remove_priority', 'lively'),
    ('安静至少70分，预算改成80万', 'set', 'quiet'),
    ('第二套是不是更吵？', 'about_results', None),
    ('白天热闹但晚上不能吵', 'clarify', None),
    ('全部重新开始，只找一房公寓', 'new_search', None),
]
report = []
for text, expected, field in cases:
    state = {**deepcopy(fixture), 'user_query': text, 'lang': 'zh'}
    raw_text = g._ask(g._PARSE_SYSTEM, g._context_message(state))
    raw = g._extract_json(raw_text)
    with patch.object(g, '_ask', return_value=raw_text):
        result = g.parse_intent(state)
    params = result.get('params') or {}
    old = state['params']
    needs = {n['attribute']: n for n in params.get('abstract_needs') or []}
    if expected == 'relative':
        ok = result['intent'] == 'refine' and any(x['field'] == field for x in params.get('relative_preferences') or [])
        ok = ok and params['abstract_needs'] == old['abstract_needs'] and params['bedrooms'] == old['bedrooms']
        if text == '没必要这么安静':
            ok = ok and params['relative_preferences'][0]['direction'] == 'decrease'
    elif expected == 'priority':
        ok = result['intent'] == 'refine' and params['sort_by'] == field and params['abstract_needs'] == old['abstract_needs']
    elif expected == 'remove_priority':
        ok = result['intent'] == 'refine' and params['sort_by'] == field and 'quiet' not in needs and 'green' in needs
    elif expected == 'set':
        ok = result['intent'] == 'refine' and needs.get('quiet', {}).get('min_score') == 70 and params['max_price'] == 800000 and 'green' in needs
    else:
        ok = result['intent'] == expected
        if expected == 'about_results':
            ok = ok and params == old
    report.append({'text':text, 'passed':ok, 'raw':raw, 'result':result})
    print(('PASS' if ok else 'FAIL') + ' ' + text + ' -> ' + result['intent'], flush=True)
    if args.report:
        Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

# 反方向场景(所有者要求):先要热闹,再要安静。热闹词条必须保留,不能被删或改成别的属性。
# 合成的上一轮结果即可 —— 这里只验证解析,不需要真实房源。
lively_first = {'params': g._sanitize({'bedrooms': 2, 'property_type': 'apartment', 'abstract_needs': [
                    {'attribute': 'lively', 'min_score': 60, 'operator': 'gte', 'strength': 'preferred',
                     'value_source': 'inferred'}]}, 'lively apartment'),
                'metrics': [{'id': i, 'suburb': 'Richmond', 'price': 650000, 'bedrooms': 2, 'bathrooms': 1,
                             'context_scores': {'lively': 95 + i, 'quiet': 20 + i}} for i in range(5)],
                'ranking': ''}
for text in ('再安静一点', '安静一些吧', '没这么吵就好', '稍微安静点，但还是要热闹', 'a bit quieter please'):
    state = {**deepcopy(lively_first), 'user_query': text, 'lang': 'zh'}
    raw_text = g._ask(g._PARSE_SYSTEM, g._context_message(state))
    with patch.object(g, '_ask', return_value=raw_text):
        result = g.parse_intent(state)
    params = result.get('params') or {}
    goals = params.get('relative_preferences') or []
    ok = (result['intent'] == 'refine'
          and any(x['field'] == 'quiet' and x['direction'] == 'increase' for x in goals)
          and params['abstract_needs'] == lively_first['params']['abstract_needs'])
    report.append({'text': text, 'passed': ok, 'raw': g._extract_json(raw_text), 'result': result})
    print(('PASS' if ok else 'FAIL') + ' [先热闹] ' + text + ' -> ' + result['intent'], flush=True)
if args.report:
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
assert all(x['passed'] for x in report), 'See report for misclassified utterances'
print(f'{len(report)} real LLM parsing cases passed. This is sampled validation, not proof for every wording.')
