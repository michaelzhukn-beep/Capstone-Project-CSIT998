"""真实数据的多轮变更回归。仅模拟 LLM,检索/评分/排序/SSE 都走实际代码。"""
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from app.api import server
from app.orchestration import graph as g, refinement as r

def events(response):
    out = {}
    for block in response.text.split('\n\n'):
        lines = block.splitlines()
        event = next((s[7:] for s in lines if s.startswith('event: ')), None)
        data = next((s[6:] for s in lines if s.startswith('data: ')), None)
        if event and data:
            out[event] = json.loads(data)
    assert 'error' not in out, out.get('error')
    assert 'done' in out
    return out

reply = {"intent": "new_search", "semantic_query": "quiet townhouse near park", "bedrooms": 2,
         "property_type": "townhouse", "sort_by": "quiet", "amenity_needs": [{"kind":"park","max_distance_m":1500}],
         "abstract_needs": [{"attribute":"quiet","min_score":60,"operator":"gte","value_source":"inferred"},
                            {"attribute":"green","min_score":60,"operator":"gte","value_source":"inferred"}]}
def fake_ask(*args, **kwargs):
    return json.dumps(reply)

with patch.object(g, '_ask', side_effect=fake_ask), patch.object(g, '_ask_streaming', return_value='测试说明'), TestClient(server.app) as client:
    thread = 'relative-real-data-regression'
    def send(message):
        return events(client.post('/api/chat', json={'thread_id':thread,'message':message}))
    first = send('联排别墅，安静，2房，近公园')
    old = deepcopy(server.GRAPH.get_state(g.new_session(thread)).values)
    assert old['metrics'] and all(m['context_scores']['quiet'] >= 60 for m in old['metrics'])
    baseline = r.baseline_for(old['metrics'], 'lively')
    reply = {'intent':'refine','changes':[{'action':'relative','field':'lively','direction':'increase','degree':'slight','source':'再热闹一点'}]}
    second = send('再热闹一点')
    new = deepcopy(server.GRAPH.get_state(g.new_session(thread)).values)
    assert new['params']['bedrooms'] == 2 and new['params']['property_type'] == 'townhouse'
    # 反向属性(安静)的门槛是系统推断的,可以为「再热闹一点」让出最多 10 分,但词条必须保留且必须说明;
    # 与这次调整无关的门槛(绿化)一分都不能动。
    before_needs = {n['attribute']: n for n in old['params']['abstract_needs']}
    after_needs = {n['attribute']: n for n in new['params']['abstract_needs']}
    assert set(after_needs) == set(before_needs), 'relative change must not drop any preference'
    assert after_needs['green'] == before_needs['green']
    quiet_floor = after_needs['quiet']['min_score']
    assert r.AUTO_FLOOR <= quiet_floor <= before_needs['quiet']['min_score']
    if quiet_floor < before_needs['quiet']['min_score']:
        assert '放宽到 ≥' + str(quiet_floor) in new['ranking'], new['ranking']
    assert new['metrics'] and not new.get('turn_notice'), new.get('turn_notice')
    # 「一点」至少挪 10 分(所有者定),上限为步幅的 1.5 倍
    assert all(baseline + 10 <= m['context_scores']['lively'] <= baseline + 23 for m in new['metrics']), \
        [m['context_scores']['lively'] for m in new['metrics']]
    assert all(m['context_scores']['quiet'] >= quiet_floor and m['context_scores']['green'] >= 60 for m in new['metrics'])
    assert '评分变化' in new['ranking'] and '「热闹」' in new['ranking'] and '「安静」' in new['ranking'], new['ranking']
    assert all(m['amenities']['park']['distance_m'] <= 1500 for m in new['metrics'])
    assert [m['id'] for m in new['metrics']] != [m['id'] for m in old['metrics']]
    print('Real DB relative change:', {'before_lively':[m['context_scores']['lively'] for m in old['metrics']],
                                     'after_lively':[m['context_scores']['lively'] for m in new['metrics']],
                                     'after_quiet':[m['context_scores']['quiet'] for m in new['metrics']]}, flush=True)
    fixture = {'initial': {'params':old['params'],'metrics':old['metrics'],'ranking':old['ranking']},
               'relative': {'params':new['params'],'metrics':new['metrics'],'ranking':new['ranking']}}
    third = send('再热闹一点')
    current = deepcopy(server.GRAPH.get_state(g.new_session(thread)).values)
    assert current['params']['relative_preferences'][0]['baseline'] == r.baseline_for(new['metrics'],'lively')

    # An impossible filter edit must restore both the state and streamed cards, with no LLM summary.
    impossible = deepcopy(current['params'])
    # 「必须」才硬筛;「优先」的不可能分数只会排序并注明 0 套满足,不会触发恢复(2026-10-07 相对目标不再跨轮继承)
    impossible['abstract_needs'] = [{'attribute':'quiet','operator':'gt','min_score':100,'strength':'required'}]
    with patch.object(g, '_ask_streaming', side_effect=AssertionError('no-result must bypass LLM')):
        no_match = events(client.post('/api/refine', json={'thread_id':thread,'params':impossible}))
    after = server.GRAPH.get_state(g.new_session(thread)).values
    assert after['params'] == current['params'] and after['metrics'] == current['metrics']
    assert no_match['done']['notice'] and no_match['done']['params'] == current['params']
    assert [m['id'] for m in no_match['results']['metrics']] == [m['id'] for m in current['metrics']]

    # Questions don't search; new explanatory turns must not repeat the old failure notice.
    reply = {'intent':'about_results','changes':[]}
    with patch.object(g,'search_properties',side_effect=AssertionError('question cannot search')):
        question = send('第二套是不是更吵')
    assert question['answer']['answer'] == '测试说明' and question['done']['notice'] is None
    assert question['done']['params'] == current['params']

    # Ambiguity and parser failure preserve the whole result; a request exception rolls back history too.
    reply = {'intent':'clarify','changes':[],'clarification':'没有昼夜噪声数据，是否改用整体安静度？'}
    clarification = send('白天热闹，晚上不能吵')
    assert clarification['done']['params'] == current['params'] and '昼夜' in clarification['answer']['answer']
    saved = deepcopy(server.GRAPH.get_state(g.new_session(thread)).values)
    reply = {'intent':'refine','changes':[{'action':'prioritize','field':'lively','source':'最热闹的'}]}
    with patch.object(g,'search_properties',side_effect=RuntimeError('intentional search failure')):
        text = client.post('/api/chat',json={'thread_id':thread,'message':'最热闹的'}).text
        assert 'event: error' in text
    restored = server.GRAPH.get_state(g.new_session(thread)).values
    for key in ('params','metrics','more','ranking','history','batch_offset'):
        assert restored[key] == saved[key], key

    if os.environ.get('RELATIVE_FIXTURE_PATH'):
        Path(os.environ['RELATIVE_FIXTURE_PATH']).write_text(json.dumps(fixture,ensure_ascii=False),encoding='utf-8')
print('Relative refinement API passed: real DB, repeated steps, no-match restoration, questions, clarification, transaction rollback.')
