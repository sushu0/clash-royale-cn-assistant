import json
from collections import Counter, defaultdict
from pathlib import Path

root = Path(r'D:\codex\CodexWork\clash')
groups = defaultdict(list)
for line_no, raw in enumerate((root / 'outputs/cn-random-mastery.jsonl').open(encoding='utf-8'), 1):
    try:
        row = json.loads(raw)
    except ValueError:
        continue
    if row.get('battle', 0) >= 1199:
        row['source_line'] = line_no
        groups[(row.get('session'), row.get('battle'))].append(row)
counts = Counter()
examples = defaultdict(list)
for key, rows in groups.items():
    ends = [r for r in rows if r.get('event') == 'battle_finished' and r.get('outcome') == '失败']
    if not ends:
        continue
    counts['losses'] += 1
    last_defense = None
    found = set()
    for row in rows:
        scene = row.get('cues', {})
        decision = row.get('decision', {})
        if row.get('event') == 'play':
            if scene.get('far_warnings') and row.get('category') in {'cycle', 'support'}:
                found.add('far_cycle_support')
                if len(examples['far_cycle_support']) < 8:
                    examples['far_cycle_support'].append(row)
            if decision.get('category') == 'prepare' and decision.get('reserve', 0) < 3:
                found.add('heavy_low_reserve')
                if len(examples['heavy_low_reserve']) < 8:
                    examples['heavy_low_reserve'].append(row)
            if row.get('confirmed') and decision.get('target'):
                last_defense = row
        elif row.get('event') == 'strategy_observe':
            reason = (row.get('observation') or {}).get('reason', '')
            if '已有可见友军接敌' in reason and last_defense and last_defense.get('category') == 'spell':
                found.add('spell_commit_hold')
                if len(examples['spell_commit_hold']) < 8:
                    examples['spell_commit_hold'].append({'spell': last_defense, 'hold': row})
    counts.update(found)
out = {'counts': dict(counts), 'examples': dict(examples)}
(root / 'work/loss-optimization-20261004/quick-trace.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(out['counts'], ensure_ascii=False))
for label, items in examples.items():
    for row in items[:3]:
        if 'spell' in row:
            row = row['spell']
        print(label, row.get('session'), row.get('battle'), row.get('source_line'), row.get('card_hint'), row.get('decision'), 'far', row.get('cues', {}).get('far_warnings'))
