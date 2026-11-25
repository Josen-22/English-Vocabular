"""Seven local calendar days, with honest denominators and separate exercise kinds."""
from datetime import timedelta


def weekly_report(store):
    end=store.today();start=end-timedelta(days=6)
    rows=[dict(r) for r in store.conn.execute('''SELECT r.*,p.question_id AS practice_question_id
        FROM reviews r LEFT JOIN practice_reviews p ON p.review_id=r.id
        WHERE r.reviewed>=? AND r.reviewed<=? ORDER BY r.reviewed,r.id''',(start.isoformat(),end.isoformat()))]
    days=[]
    for offset in range(7):
        day=(start+timedelta(days=offset)).isoformat()
        items=[r for r in rows if r['reviewed']==day]
        days.append({'day':day,'attempts':len(items),'words':len({r['word_id'] for r in items}),
                     'correct':sum(r['result']=='认识' for r in items),
                     'practice':sum(r['practice_question_id'] is not None for r in items)})
    accuracy={}
    for key,direction in [('meaning','英译中'),('spelling','中译英')]:
        selected=[r for r in rows if r['direction']==direction]
        correct=sum(r['result']=='认识' for r in selected)
        accuracy[key]={'attempts':len(selected),'correct':correct,'rate':correct/len(selected) if selected else None}
    missed={}
    for r in rows:
        if r['result']=='认识':continue
        group=missed.setdefault(r['word_id'],{'word_id':r['word_id'],'word':r['word'],'misses':0,'fuzzy':0,'wrong':0})
        group['word']=r['word'];group['misses']+=1;group['fuzzy']+=int(r['result']=='模糊');group['wrong']+=int(r['result']=='不认识')
    completed=store.conn.execute('''SELECT COUNT(*) FROM sessions s WHERE s.day>=? AND s.day<=?
        AND EXISTS(SELECT 1 FROM questions q WHERE q.day=s.day)
        AND NOT EXISTS(SELECT 1 FROM questions q WHERE q.day=s.day AND q.result IS NULL)''',
        (start.isoformat(),end.isoformat())).fetchone()[0]
    return {'start':start.isoformat(),'end':end.isoformat(),'study_days':sum(d['attempts']>0 for d in days),
            'reviewed_words':len({r['word_id'] for r in rows}),'attempts':len(rows),'completed_daily':completed,
            'practice_attempts':sum(r['practice_question_id'] is not None for r in rows),
            'other_attempts':sum(r['direction'] not in ('英译中','中译英') for r in rows),
            'accuracy':accuracy,'days':days,'missed':sorted(missed.values(),key=lambda r:(-r['misses'],r['word'].casefold()))[:10]}
