"""Cached, anonymized insights over completed assessment data."""
from __future__ import annotations

from datetime import date

from ai_core import obj, TEXT

PROMPT = ('Ты анализируешь только обезличенные агрегаты учебной группы. Не называй имена. '
          'JSON: {"summary":"типичные ошибки", "recommendations":"что отработать на следующем занятии"}. '
          'Не приписывай отсутствующие причины.')


def _from_documents(engine, group):
    rows = [s for s in engine.list_items('s') if s.get('assessment') and
            (not group or (s.get('training') or {}).get('group') == group)]
    counts = {}
    for session in rows:
        labels = (session['task'].get('field_labels') or {})
        for field, verdict in session['assessment']['fields'].items():
            if verdict['verdict'] in ('incorrect', 'missing', 'partial'):
                label = labels.get(field, field)
                counts[label] = counts.get(label, 0) + 1
    return len(rows), counts


def get_insights(engine, group=None, *, force=False, owner=None):
    group = str(group).strip() if group else None
    repository = getattr(getattr(engine, 'storage', None), '_repo', None)
    period = date.today().isoformat()
    if repository is not None:
        source_updated_at, works, counts = repository.insight_source(group, owner=owner)
        if not works:
            raise ValueError('Для аналитики сначала проверьте работы обучающихся.')
        cached = repository.get_insight_report(group, period, owner=owner)
        if (not force and cached and
                cached.get('source_updated_at') == source_updated_at):
            return cached['report']
    else:
        if owner is not None:
            raise ValueError('Для аналитики преподавателя требуется база данных.')
        works, counts = _from_documents(engine, group)
        source_updated_at = None
        if not works:
            raise ValueError('Для аналитики сначала проверьте работы обучающихся.')

    result = engine.provider.generate(PROMPT, {'works': works, 'errors_by_field': counts},
                                      .2, schema=obj(summary=TEXT, recommendations=TEXT))
    report = {'works': works, 'counts': counts, 'summary': result['summary'],
              'recommendations': result['recommendations']}
    if repository is not None:
        repository.save_insight_report(group, period, report, source_updated_at,
                                       owner=owner)
    return report
