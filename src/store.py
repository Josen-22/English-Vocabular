"""Local vocabulary storage and deterministic, resumable daily quizzes."""
from contextlib import contextmanager, closing
from datetime import date, datetime, timedelta
from pathlib import Path
import random
import sqlite3
import unicodedata

SCHEMA_VERSION = 1
INTERVALS = (1, 1, 3, 7, 14, 30)
RESULTS = {"认识", "模糊", "不认识"}


def word_key(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def spelling_matches(answer, word):
    return answer.strip().casefold() == word.strip().casefold()


class Store:
    def __init__(self, path, today=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.today = today or date.today
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        version = self.conn.execute('PRAGMA user_version').fetchone()[0]
        tables = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if version not in (0, SCHEMA_VERSION) or (version == 0 and tables):
            self.conn.close()
            raise ValueError('数据库版本不兼容，请使用正确的单词本数据文件。')
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE,
                word TEXT NOT NULL, pos TEXT NOT NULL DEFAULT '',
                meaning TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '', added TEXT NOT NULL,
                mastery INTEGER NOT NULL DEFAULT 0 CHECK(mastery BETWEEN 0 AND 5),
                last_review TEXT, due TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sessions (
                day TEXT PRIMARY KEY, created TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY, day TEXT NOT NULL REFERENCES sessions(day),
                ordinal INTEGER NOT NULL, word_id INTEGER NOT NULL REFERENCES words(id),
                word TEXT NOT NULL, meaning TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('meaning','spelling')),
                is_new INTEGER NOT NULL, answer TEXT, result TEXT, answered_at TEXT,
                UNIQUE(day,ordinal), UNIQUE(day,word_id)
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY, word_id INTEGER NOT NULL REFERENCES words(id),
                word TEXT NOT NULL, reviewed TEXT NOT NULL, direction TEXT NOT NULL,
                answer TEXT NOT NULL DEFAULT '', result TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '', batch TEXT NOT NULL DEFAULT '',
                question_id INTEGER UNIQUE REFERENCES questions(id), import_key TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS imports (
                digest TEXT PRIMARY KEY, imported_at TEXT NOT NULL, filename TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS reviews_word ON reviews(word_id);
            PRAGMA user_version=1;
        """)
        self.conn.commit()

    def close(self):
        self.conn.close()

    @contextmanager
    def transaction(self):
        with self.conn:
            yield self.conn

    def get_word(self, ident):
        return self.conn.execute("SELECT * FROM words WHERE id=?", (ident,)).fetchone()

    def find_word(self, word):
        return self.conn.execute("SELECT * FROM words WHERE key=?", (word_key(word),)).fetchone()

    def save_word(self, word, meaning, pos='', source='', notes='', ident=None):
        word, meaning = word.strip(), meaning.strip()
        if not word or not meaning:
            raise ValueError("请填写单词和中文释义。")
        existing = self.find_word(word)
        if existing and existing['id'] != ident:
            raise ValueError("这个单词已在单词本中，请先打开已有词条编辑。")
        with self.conn:
            if ident is None:
                cursor = self.conn.execute(
                    "INSERT INTO words(key,word,meaning,pos,source,notes,added,due) VALUES(?,?,?,?,?,?,?,?)",
                    (word_key(word), word, meaning, pos.strip(), source.strip(), notes.strip(),
                     self.today().isoformat(), self.today().isoformat()))
                return cursor.lastrowid
            if self.get_word(ident) is None:
                raise ValueError("词条不存在。")
            self.conn.execute(
                "UPDATE words SET key=?,word=?,meaning=?,pos=?,source=?,notes=?,deleted=0 WHERE id=?",
                (word_key(word), word, meaning, pos.strip(), source.strip(), notes.strip(), ident))
            return ident

    def delete_word(self, ident):
        # Soft deletion keeps historical questions and reviews intact.
        with self.conn:
            self.conn.execute("UPDATE words SET deleted=1 WHERE id=?", (ident,))

    def words(self, search='', include_deleted=False):
        rows = self.conn.execute("""
            SELECT w.*, COUNT(r.id) AS attempts,
                COALESCE(SUM(r.result='认识'),0) AS correct
            FROM words w LEFT JOIN reviews r ON r.word_id=w.id
            GROUP BY w.id ORDER BY w.id
        """).fetchall()
        key = word_key(search)
        return [r for r in rows if (include_deleted or not r['deleted']) and
                (not key or key in word_key(' '.join(str(r[k]) for k in
                 ('word', 'meaning', 'pos', 'source', 'notes'))))]

    def stats(self):
        rows = self.words()
        return {'total': len(rows), 'new': sum(r['attempts'] == 0 for r in rows),
                'due': sum(r['attempts'] > 0 and r['due'] <= self.today().isoformat() for r in rows)}

    def questions(self, day=None):
        return self.conn.execute("SELECT * FROM questions WHERE day=? ORDER BY ordinal",
                                 ((day or self.today()).isoformat(),)).fetchall()

    def start_day(self):
        day = self.today().isoformat()
        if self.conn.execute("SELECT 1 FROM sessions WHERE day=?", (day,)).fetchone():
            return self.questions()
        rows = self.words()
        if not rows:
            return []  # Adding words later today can still start a quiz.
        new = [r for r in rows if not r['attempts']]
        old = sorted((r for r in rows if r['attempts']), key=lambda r:
                     (r['due'] > day, r['mastery'], r['last_review'] or '', r['id']))
        # Seed makes ties reproducible; persistence is the source of truth afterward.
        rng = random.Random(day)
        rng.shuffle(new)
        selected = new[:5] + old[:5]
        selected += (new[5:] + old[5:])[:10-len(selected)]
        rng.shuffle(selected)
        kinds = ['meaning'] * ((len(selected)+1)//2) + ['spelling'] * (len(selected)//2)
        rng.shuffle(kinds)
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO sessions VALUES(?,?)", (day, datetime.now().isoformat()))
            # Another instance may have created this session while we selected.
            if not self.questions():
                self.conn.executemany("""
                    INSERT INTO questions(day,ordinal,word_id,word,meaning,kind,is_new)
                    VALUES(?,?,?,?,?,?,?)""",
                    [(day, i+1, r['id'], r['word'], r['meaning'], kind, int(not r['attempts']))
                     for i, (r, kind) in enumerate(zip(selected, kinds))])
        return self.questions()

    def answer(self, question_id, answer, result):
        if result not in RESULTS:
            raise ValueError("无效的掌握情况。")
        with self.conn:
            self.conn.execute("UPDATE questions SET answer=answer WHERE id=?", (question_id,))
            q = self.conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
            if q is None:
                raise ValueError("题目不存在。")
            if q['day'] != self.today().isoformat():
                raise ValueError("已进入新的一天，请打开今日抽测。")
            if q['result'] is not None:
                return False
            w = self.get_word(q['word_id'])
            level = (min(5, w['mastery']+1) if result == '认识' else
                     max(0, w['mastery']-1) if result == '模糊' else 0)
            reviewed = self.today().isoformat()
            due = (self.today() + timedelta(days=INTERVALS[level])).isoformat()
            self.conn.execute("UPDATE questions SET answer=?,result=?,answered_at=? WHERE id=?",
                              (answer, result, datetime.now().isoformat(), question_id))
            self.conn.execute("UPDATE words SET mastery=?,last_review=?,due=? WHERE id=?",
                              (level, reviewed, due, w['id']))
            self.conn.execute("""INSERT INTO reviews
                (word_id,word,reviewed,direction,answer,result,batch,question_id)
                VALUES(?,?,?,?,?,?,?,?)""", (w['id'], q['word'], reviewed,
                '英译中' if q['kind'] == 'meaning' else '中译英', answer, result,
                reviewed+' 每日抽测', question_id))
        return True

    def reviews(self, word_id=None):
        if word_id is None:
            return self.conn.execute("SELECT * FROM reviews ORDER BY reviewed,id").fetchall()
        return self.conn.execute("SELECT * FROM reviews WHERE word_id=? ORDER BY reviewed,id",
                                 (word_id,)).fetchall()

    def backup(self, target):
        target = Path(target)
        if target.resolve() == self.path.resolve():
            raise ValueError("备份文件不能覆盖正在使用的数据库。")
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(target)) as dest:
            self.conn.backup(dest)
        return target

    @staticmethod
    def validate_backup(path):
        if not Path(path).is_file():
            raise ValueError("备份文件不存在。")
        source = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)
        try:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != 'ok':
                raise ValueError("备份文件已损坏。")
            if source.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise ValueError("备份版本不兼容。")
            required = {'words', 'reviews', 'questions', 'sessions', 'imports'}
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not required <= tables or source.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("备份结构或关联记录不完整。")
            # Check the complete shape before touching the live database.
            for table, columns in {
                'words': 'id,key,word,pos,meaning,source,notes,added,mastery,last_review,due,deleted',
                'reviews': 'id,word_id,word,reviewed,direction,answer,result,notes,batch,question_id,import_key',
                'questions': 'id,day,ordinal,word_id,word,meaning,kind,is_new,answer,result,answered_at',
                'sessions': 'day,created', 'imports': 'digest,imported_at,filename'
            }.items():
                source.execute(f"SELECT {columns} FROM {table} LIMIT 0")
        except Exception:
            source.close()
            raise
        return source

    def restore(self, source_path, backup_dir):
        if Path(source_path).resolve() == self.path.resolve():
            raise ValueError("请选择备份文件，不要选择当前数据库。")
        source = self.validate_backup(source_path)
        try:
            safety = Path(backup_dir) / ('恢复前_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
            self.backup(safety)
            source.backup(self.conn)
            return safety
        finally:
            source.close()
