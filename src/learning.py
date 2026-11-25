"""Additive learning metadata and practice sessions, compatible with core v1 tables."""
from datetime import datetime,timedelta
import json
import random
import re

from lookup import POS_PREFIX
from store import Store,RESULTS,INTERVALS,word_key


def sense_options(meaning,pos=''):
    options=[]
    for line in meaning.splitlines():
        line=line.strip()
        if not line:continue
        match=POS_PREFIX.match(line)
        label,definition=(match['pos'].strip(' /&,、'),match['meaning']) if match else (pos,line)
        depth=0;parts=[];buffer=[]
        for ch in definition:
            if ch in '(（[':depth+=1
            elif ch in ')）]':depth=max(0,depth-1)
            if ch in ';；' and depth==0:
                parts.append(''.join(buffer).strip());buffer=[]
            else:buffer.append(ch)
        parts.append(''.join(buffer).strip())
        for part in parts:
            value={'pos':label,'meaning':part}
            if part and value not in options:options.append(value)
    return options


class LearningStore(Store):
    def __init__(self,path,today=None):
        super().__init__(path,today)
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS word_learning (
                word_id INTEGER PRIMARY KEY REFERENCES words(id),
                study_meaning TEXT NOT NULL DEFAULT '', senses_json TEXT NOT NULL DEFAULT '[]',
                uk_phonetic TEXT NOT NULL DEFAULT '', us_phonetic TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS daily_settings (
                day TEXT PRIMARY KEY REFERENCES sessions(day), config_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS practice_sessions (
                id INTEGER PRIMARY KEY,mode TEXT NOT NULL CHECK(mode IN ('daily_wrong','weak')),
                created TEXT NOT NULL,source_day TEXT,completed TEXT,config_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS practice_questions (
                id INTEGER PRIMARY KEY,session_id INTEGER NOT NULL REFERENCES practice_sessions(id),
                ordinal INTEGER NOT NULL,word_id INTEGER NOT NULL REFERENCES words(id),
                word TEXT NOT NULL,meaning TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('meaning','spelling')),
                answer TEXT,result TEXT,answered_at TEXT,
                UNIQUE(session_id,word_id),UNIQUE(session_id,ordinal)
            );
            CREATE TABLE IF NOT EXISTS practice_reviews (
                review_id INTEGER PRIMARY KEY REFERENCES reviews(id),
                question_id INTEGER NOT NULL UNIQUE REFERENCES practice_questions(id)
            );
            CREATE INDEX IF NOT EXISTS practice_sessions_completed ON practice_sessions(completed,id);
        ''')
        self.conn.commit()

    def _enrich(self,row,metadata=None):
        if row is None:return None
        result=dict(row)
        extra=metadata if metadata is not None else self.conn.execute('SELECT * FROM word_learning WHERE word_id=?',(row['id'],)).fetchone()
        result.update({'study_meaning':extra['study_meaning'] if extra else '',
                       'uk_phonetic':extra['uk_phonetic'] if extra else '',
                       'us_phonetic':extra['us_phonetic'] if extra else ''})
        try:result['senses']=json.loads(extra['senses_json']) if extra else []
        except (ValueError,TypeError):result['senses']=[]
        if not isinstance(result['senses'],list) or not result['senses']:
            result['senses']=sense_options(result['meaning'],result['pos'])
        return result

    def get_word(self,ident):
        return self._enrich(super().get_word(ident))

    def find_word(self,word):
        return self._enrich(super().find_word(word))

    def words(self,search='',include_deleted=False):
        rows=super().words(search,include_deleted)
        metadata={r['word_id']:r for r in self.conn.execute('SELECT * FROM word_learning')}
        return [self._enrich(r,metadata.get(r['id'],{})) for r in rows]

    def import_metadata(self,ident,study_meaning,uk_phonetic,us_phonetic):
        # Caller owns the workbook transaction. Existing metadata is never replaced.
        self.conn.execute('''INSERT OR IGNORE INTO word_learning
            (word_id,study_meaning,uk_phonetic,us_phonetic) VALUES(?,?,?,?)''',
            (ident,study_meaning,uk_phonetic,us_phonetic))

    def save_word(self,word,meaning,pos='',source='',notes='',ident=None,*,study_meaning=None,
                  senses=None,uk_phonetic=None,us_phonetic=None):
        old=self.get_word(ident) if ident is not None else None
        if old and old['key']!=word_key(word):
            uk_phonetic=us_phonetic=''  # A renamed word must not inherit another word's phonetics.
        if study_meaning is not None and not isinstance(study_meaning,str):raise ValueError('学习义项应为文字。')
        if any(v is not None and not isinstance(v,str) for v in (uk_phonetic,us_phonetic)):raise ValueError('音标应为文字。')
        if senses is not None:
            if not isinstance(senses,list) or any(not isinstance(s,dict) or not isinstance(s.get('meaning'),str) or not isinstance(s.get('pos',''),str) for s in senses):
                raise ValueError('义项格式不正确。')
            senses_json=json.dumps([{'pos':s.get('pos',''),'meaning':s['meaning']} for s in senses],ensure_ascii=False)
        else:senses_json=None
        with self.conn:
            ident=self._save_word(word,meaning,pos,source,notes,ident)
            self.conn.execute('INSERT OR IGNORE INTO word_learning(word_id) VALUES(?)',(ident,))
            for key,value in [('study_meaning',study_meaning.strip() if study_meaning is not None else None),
                              ('senses_json',senses_json),('uk_phonetic',uk_phonetic),('us_phonetic',us_phonetic)]:
                if value is not None:self.conn.execute(f'UPDATE word_learning SET {key}=? WHERE word_id=?',(value,ident))
        return ident

    def start_day(self,count=10,new_percent=50,meaning_percent=50):
        existed=self.conn.execute('SELECT 1 FROM sessions WHERE day=?',(self.today().isoformat(),)).fetchone()
        questions=super().start_day(count,new_percent,meaning_percent)
        if not existed and questions:
            config={'daily_count':count,'new_percent':new_percent,'meaning_percent':meaning_percent}
            with self.conn:self.conn.execute('INSERT OR IGNORE INTO daily_settings VALUES(?,?)',(self.today().isoformat(),json.dumps(config)))
        return questions

    def daily_config(self):
        row=self.conn.execute('SELECT config_json FROM daily_settings WHERE day=?',(self.today().isoformat(),)).fetchone()
        return json.loads(row[0]) if row else None

    def practice(self,session_id=None):
        if session_id is None:
            row=self.conn.execute('SELECT * FROM practice_sessions WHERE completed IS NULL ORDER BY id DESC LIMIT 1').fetchone()
        else:row=self.conn.execute('SELECT * FROM practice_sessions WHERE id=?',(session_id,)).fetchone()
        if row is None:return None
        result=dict(row)
        result['questions']=[dict(q)|{'is_new':0} for q in self.conn.execute('SELECT * FROM practice_questions WHERE session_id=? ORDER BY ordinal',(row['id'],))]
        return result

    def start_practice(self,mode='daily_wrong',count=10,meaning_percent=50):
        if mode not in ('daily_wrong','weak'):raise ValueError('不支持的专项模式。')
        if type(count) is not int or not 1<=count<=50 or type(meaning_percent) is not int or not 0<=meaning_percent<=100:
            raise ValueError('专项数量或题型比例不正确。')
        unfinished=self.conn.execute('SELECT id FROM practice_sessions WHERE mode=? AND completed IS NULL ORDER BY id DESC LIMIT 1',(mode,)).fetchone()
        if unfinished:return self.practice(unfinished['id'])
        words=self.words()
        if mode=='daily_wrong':
            questions=self.questions()
            if not questions or any(q['result'] is None for q in questions):raise ValueError('请先完成今天的每日抽测，再练本轮错词。')
            ids={q['word_id'] for q in questions if q['result']!='认识'}
            chosen=[w for w in words if w['id'] in ids]
        else:chosen=[w for w in words if w['attempts'] and w['mastery']<=1]
        chosen=sorted(chosen,key=lambda w:(w['mastery'],w['due'],w['last_review'] or '',w['id']))[:count]
        if not chosen:return None
        random.Random(self.today().isoformat()+mode).shuffle(chosen)
        meaning_count=(len(chosen)*meaning_percent+50)//100
        kinds=['meaning']*meaning_count+['spelling']*(len(chosen)-meaning_count)
        random.Random(self.today().isoformat()+mode+'kinds').shuffle(kinds)
        with self.conn:
            ident=self.conn.execute('INSERT INTO practice_sessions(mode,created,source_day,config_json) VALUES(?,?,?,?)',
                (mode,datetime.now().isoformat(),self.today().isoformat() if mode=='daily_wrong' else None,
                 json.dumps({'daily_count':count,'meaning_percent':meaning_percent}))).lastrowid
            self.conn.executemany('''INSERT INTO practice_questions(session_id,ordinal,word_id,word,meaning,kind)
                VALUES(?,?,?,?,?,?)''',[(ident,n+1,w['id'],w['word'],w['study_meaning'] or w['meaning'],kind)
                for n,(w,kind) in enumerate(zip(chosen,kinds))])
        return self.practice(ident)

    def answer_practice(self,ident,answer,result):
        if result not in RESULTS:raise ValueError('无效的掌握情况。')
        with self.conn:
            self.conn.execute('UPDATE practice_questions SET answer=answer WHERE id=?',(ident,))
            q=self.conn.execute('SELECT * FROM practice_questions WHERE id=?',(ident,)).fetchone()
            if q is None:raise ValueError('专项题目不存在。')
            if q['result'] is not None:return False
            w=self.get_word(q['word_id'])
            level=min(5,w['mastery']+1) if result=='认识' else max(0,w['mastery']-1) if result=='模糊' else 0
            reviewed=self.today().isoformat();now=datetime.now().isoformat()
            self.conn.execute('UPDATE words SET mastery=?,last_review=?,due=? WHERE id=?',
                (level,reviewed,(self.today()+timedelta(days=INTERVALS[level])).isoformat(),w['id']))
            self.conn.execute('UPDATE practice_questions SET answer=?,result=?,answered_at=? WHERE id=?',(answer,result,now,ident))
            session=self.practice(q['session_id'])
            label='错词复测' if session['mode']=='daily_wrong' else '薄弱词专项'
            review=self.conn.execute('''INSERT INTO reviews(word_id,word,reviewed,direction,answer,result,batch)
                VALUES(?,?,?,?,?,?,?)''',(w['id'],q['word'],reviewed,'英译中' if q['kind']=='meaning' else '中译英',answer,result,
                reviewed+' '+label+' #'+str(q['session_id']))).lastrowid
            self.conn.execute('INSERT INTO practice_reviews VALUES(?,?)',(review,ident))
            if not self.conn.execute('SELECT 1 FROM practice_questions WHERE session_id=? AND result IS NULL',(q['session_id'],)).fetchone():
                self.conn.execute('UPDATE practice_sessions SET completed=? WHERE id=?',(now,q['session_id']))
        return True
