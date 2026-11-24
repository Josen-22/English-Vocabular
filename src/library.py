"""Predictable library filtering and ordering, shared by desktop and tests."""
from store import word_key

SORTS = {'added_desc','added_asc','az','za','mastery_asc','mastery_desc','due','accuracy','reviewed_oldest'}
FILTERS = {'all','new','due','weak','learning','mastered'}


def select_words(rows, today, search='', category='all', sort='added_desc'):
    if category not in FILTERS or sort not in SORTS:
        raise ValueError('不支持的筛选或排序方式。')
    needle=word_key(search)
    selected=[]
    for row in rows:
        w=dict(row)
        attempts=w['attempts']
        w['accuracy']=w['correct']/attempts if attempts else None
        w['is_new']=not attempts
        w['is_due']=bool(attempts and w['due']<=today)
        w['is_weak']=bool(attempts and w['mastery']<=1)
        w['is_mastered']=w['mastery']>=4
        w['is_learning']=bool(attempts and 2<=w['mastery']<=3)
        if category!='all' and not w[{'new':'is_new','due':'is_due','weak':'is_weak','learning':'is_learning','mastered':'is_mastered'}[category]]:
            continue
        if needle and needle not in word_key(' '.join(w[k] for k in ('word','meaning','pos','source','notes'))):
            continue
        selected.append(w)
    keys={
        'added_desc':lambda w:(w['added'],w['id']),
        'added_asc':lambda w:(w['added'],w['id']),
        'az':lambda w:(word_key(w['word']),w['id']),
        'za':lambda w:(word_key(w['word']),w['id']),
        'mastery_asc':lambda w:(w['mastery'],w['due'],word_key(w['word'])),
        'mastery_desc':lambda w:(-w['mastery'],w['due'],word_key(w['word'])),
        'due':lambda w:(w['due'],w['mastery'],word_key(w['word'])),
        'accuracy':lambda w:(w['accuracy'] is None,w['accuracy'] if w['accuracy'] is not None else 1,-w['attempts'],word_key(w['word'])),
        'reviewed_oldest':lambda w:(w['last_review'] is not None,w['last_review'] or '',word_key(w['word'])),
    }
    return sorted(selected,key=keys[sort],reverse=sort in ('added_desc','za'))


def distribution(rows):
    groups={'new':0,'weak':0,'learning':0,'mastered':0}
    for w in rows:
        group='new' if not w['attempts'] else 'weak' if w['mastery']<=1 else 'learning' if w['mastery']<=3 else 'mastered'
        groups[group]+=1
    return groups
