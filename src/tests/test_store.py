from collections import Counter
from datetime import date, timedelta
from pathlib import Path
import hashlib
import sqlite3
import tempfile
import unittest
from zipfile import ZipFile

from openpyxl import load_workbook
from excel_io import export_workbook, import_workbook
from store import Store, spelling_matches

ORIGINAL = Path('D:/CC聊天记录/雅思学习/雅思迭代单词本.xlsx')


class StoreTests(unittest.TestCase):
    def setUp(self):
        (Path(__file__).resolve().parents[2]/'验证').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'验证')
        self.home = Path(self.temp.name)
        self.day = date(2026,11,24)
        self.store = Store(self.home/'data.sqlite3', today=lambda:self.day)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def add_words(self, count, old=0):
        ids = []
        for n in range(count):
            ident = self.store.save_word(f'word {n}', f'含义 {n}', notes='测试备注')
            ids.append(ident)
            if n < old:
                with self.store.conn:
                    self.store.conn.execute('''INSERT INTO reviews
                        (word_id,word,reviewed,direction,answer,result)
                        VALUES(?,?,?,?,?,?)''', (ident,f'word {n}',str(self.day-timedelta(days=7)),
                        '英译中','', '认识'))
        return ids

    def test_crud_duplicates_search_and_history_retention(self):
        ident = self.store.save_word('  Come OUT  ','出现',pos='phr.',source='听力',notes='短语')
        self.assertEqual(self.store.find_word('come   out')['id'],ident)
        with self.assertRaises(ValueError):
            self.store.save_word('come out','另一释义')
        with self.assertRaises(ValueError):
            self.store.save_word('','空词')
        with self.assertRaises(ValueError):
            self.store.save_word('abc','   ')
        self.assertEqual(len(self.store.words('出现')),1)
        self.assertEqual(len(self.store.words('短语')),1)
        self.store.save_word('come out','出版',ident=ident)
        self.store.start_day()
        q = self.store.questions()[0]
        self.store.answer(q['id'],'出版','认识')
        self.store.delete_word(ident)
        self.assertEqual(self.store.words(),[])
        self.assertEqual(len(self.store.reviews(ident)),1)
        self.assertEqual(self.store.questions()[0]['word'],'come out')
        self.assertEqual(len(self.store.words(include_deleted=True)),1)

    def test_balanced_new_old_and_independent_question_kinds(self):
        self.add_words(30,old=15)
        questions = self.store.start_day()
        self.assertEqual(len(questions),10)
        self.assertEqual(sum(q['is_new'] for q in questions),5)
        self.assertEqual(Counter(q['kind'] for q in questions),{'meaning':5,'spelling':5})
        self.assertEqual(len({q['word_id'] for q in questions}),10)
        self.assertEqual([tuple(q) for q in questions],[tuple(q) for q in self.store.start_day()])

    def test_pool_shortages_and_empty_day(self):
        self.assertEqual(self.store.start_day(),[])
        self.add_words(3,old=1)
        questions = self.store.start_day()
        self.assertEqual(len(questions),3)
        self.assertEqual(Counter(q['kind'] for q in questions),{'meaning':2,'spelling':1})
        self.assertEqual(sum(q['is_new'] for q in questions),2)

    def test_all_new_or_all_old_can_fill_ten(self):
        self.add_words(12)
        self.assertEqual(sum(q['is_new'] for q in self.store.start_day()),10)
        self.day += timedelta(days=1)
        with self.store.conn:
            for w in self.store.words():
                self.store.conn.execute('''INSERT INTO reviews(word_id,word,reviewed,direction,result)
                    VALUES(?,?,?,?,?)''',(w['id'],w['word'],str(self.day),'英译中','认识'))
        questions = self.store.start_day()
        self.assertEqual(len(questions),10)
        self.assertEqual(sum(q['is_new'] for q in questions),0)

    def test_due_then_weak_then_oldest_review_priority(self):
        ids = self.add_words(7,old=7)
        with self.store.conn:
            for n, ident in enumerate(ids):
                self.store.conn.execute('UPDATE words SET mastery=?,last_review=?,due=? WHERE id=?',
                    (0 if n==6 else (n%3),f'2026-11-{10+n:02}',
                     '2026-12-01' if n==6 else '2026-11-20',ident))
        # 7 old words means all are selected. Use a full pool to test exclusion.
        for n in range(7,13):
            ident=self.store.save_word(f'word {n}',f'含义 {n}')
            with self.store.conn:
                self.store.conn.execute('''INSERT INTO reviews(word_id,word,reviewed,direction,result)
                    VALUES(?,?,?,?,?)''',(ident,f'word {n}','2026-11-01','英译中','认识'))
                self.store.conn.execute("UPDATE words SET mastery=5,due='2026-11-20' WHERE id=?",(ident,))
        selected = {q['word_id'] for q in self.store.start_day()}
        self.assertNotIn(ids[6],selected)  # Future-due level zero loses to due level five.
        self.assertTrue(set(ids[:6]) <= selected)

    def test_answers_atomic_idempotent_and_schedule(self):
        self.add_words(6)
        questions = self.store.start_day()
        results = [('认识',0,1,1),('模糊',3,2,3),('不认识',5,0,1),
                   ('认识',5,5,30),('模糊',0,0,1),('认识',3,4,14)]
        for q,(result,before,after,interval) in zip(questions,results):
            with self.store.conn:
                self.store.conn.execute('UPDATE words SET mastery=? WHERE id=?',(before,q['word_id']))
            self.assertTrue(self.store.answer(q['id'],'my answer',result))
            self.assertFalse(self.store.answer(q['id'],'double click','不认识'))
            w = self.store.get_word(q['word_id'])
            self.assertEqual(w['mastery'],after)
            self.assertEqual(w['due'],str(self.day+timedelta(days=interval)))
        self.assertEqual(len(self.store.reviews()),6)
        self.assertEqual(sum(w['correct'] for w in self.store.words()),3)
        with self.assertRaises(ValueError):
            self.store.answer(questions[0]['id'],'','无效')

    def test_reopen_resume_complete_and_day_rollover(self):
        self.add_words(15)
        questions = self.store.start_day()
        self.store.answer(questions[0]['id'],'','认识')
        self.store.close()
        self.store = Store(self.home/'data.sqlite3',today=lambda:self.day)
        self.assertEqual(sum(q['result'] is not None for q in self.store.questions()),1)
        for q in self.store.questions()[1:]:
            self.store.answer(q['id'],'','模糊')
        self.assertEqual(len(self.store.start_day()),10)
        self.assertEqual(sum(q['result'] is not None for q in self.store.start_day()),10)
        old_day = self.day
        self.day += timedelta(days=1)
        self.assertEqual(self.store.questions(),[])
        self.assertEqual(len(self.store.start_day()),10)
        self.assertEqual(len(self.store.questions(old_day)),10)
        with self.assertRaises(ValueError):
            self.store.answer(questions[0]['id'],'','认识')

    def test_snapshot_edit_delete_and_new_word_dont_change_daily_group(self):
        self.add_words(12)
        questions = self.store.start_day()
        q = questions[0]
        self.store.save_word('renamed','新意思',ident=q['word_id'])
        self.store.delete_word(q['word_id'])
        self.store.save_word('another','另外')
        self.assertEqual([tuple(q) for q in questions],[tuple(q) for q in self.store.start_day()])
        self.store.answer(q['id'],'','认识')
        self.assertEqual(self.store.reviews()[0]['word'],q['word'])

    def test_spelling_and_manual_override(self):
        self.assertTrue(spelling_matches('  ReTAIN  ','retain'))
        self.assertFalse(spelling_matches('come  out','come out'))
        self.assertFalse(spelling_matches('penalize','penalise'))
        self.add_words(1)
        q=self.store.start_day()[0]
        self.store.answer(q['id'],'acceptable variant','认识')
        self.assertEqual(self.store.reviews()[0]['result'],'认识')

    def test_backup_restore_progress_and_invalid_backup(self):
        self.add_words(12,old=4)
        questions=self.store.start_day()
        self.store.answer(questions[0]['id'],'snapshot','认识')
        snapshot=[tuple(q) for q in self.store.questions()]
        backup=self.store.backup(self.home/'backup.sqlite3')
        self.store.save_word('new after backup','测试')
        self.store.answer(questions[1]['id'],'after backup','模糊')
        safety=self.store.restore(backup,self.home/'backups')
        self.assertTrue(safety.exists())
        self.assertIsNone(self.store.find_word('new after backup'))
        self.assertEqual(snapshot,[tuple(q) for q in self.store.questions()])
        saved=Store(safety)
        self.assertIsNotNone(saved.find_word('new after backup'))
        saved.close()
        bad=self.home/'bad.sqlite3'
        bad.write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.restore(bad,self.home/'backups')
        self.assertEqual(snapshot,[tuple(q) for q in self.store.questions()])
        with self.assertRaises(ValueError):
            self.store.backup(self.store.path)

    def test_export_reimport_roundtrip_and_formula_text(self):
        self.add_words(3,old=2)
        ident=self.store.save_word('=not_a_formula','中文 & <文本>\n多行')
        self.store.delete_word(ident)
        path=export_workbook(self.store,self.home/'export.xlsx')
        workbook=load_workbook(path,data_only=False)
        self.assertEqual(workbook['词库'].freeze_panes,'A6')
        self.assertEqual(workbook['词库']['B9'].data_type,'s')
        self.assertEqual(workbook['词库']['D9'].value,'中文 & <文本>\n多行')
        workbook.close()
        other=Store(self.home/'other.sqlite3')
        try:
            result=import_workbook(other,path)
            self.assertEqual(result['words'],4)
            self.assertEqual(result['reviews'],2)
            self.assertEqual(len(other.words()),3)
            self.assertEqual(len(other.words(include_deleted=True)),4)
            self.assertTrue(import_workbook(other,path)['existing'])
            # A different file hash must also deduplicate its logical records.
            changed=self.home/'changed.xlsx'
            with ZipFile(path) as src, ZipFile(changed,'w') as dst:
                for item in src.infolist():
                    dst.writestr(item,src.read(item.filename))
                dst.comment=b'different file bytes, same content'
            result=import_workbook(other,changed)
            self.assertEqual((result['words'],result['reviews']),(0,0))
            result=import_workbook(self.store,path)
            self.assertEqual((result['words'],result['reviews']),(0,0))
        finally:
            other.close()

    def test_import_failure_rolls_back_whole_workbook(self):
        self.add_words(3,old=3)
        path=export_workbook(self.store,self.home/'good.xlsx')
        invalid=self.home/'invalid.xlsx'
        with ZipFile(path) as src,ZipFile(invalid,'w') as dst:
            for item in src.infolist():
                content=src.read(item.filename)
                if item.filename=='xl/worksheets/sheet2.xml':
                    content=content.replace('正确'.encode(),'未知结果'.encode())
                dst.writestr(item,content)
        other=Store(self.home/'rollback.sqlite3')
        try:
            with self.assertRaises(ValueError):
                import_workbook(other,invalid)
            self.assertEqual(other.words(),[])
            self.assertEqual(other.reviews(),[])
            self.assertEqual(other.conn.execute('SELECT COUNT(*) FROM imports').fetchone()[0],0)
        finally:
            other.close()

    @unittest.skipUnless(ORIGINAL.exists(),'原单词本不在此机器')
    def test_original_import_reconciles_counts_mastery_and_source_hash(self):
        before=hashlib.sha256(ORIGINAL.read_bytes()).hexdigest()
        workbook=load_workbook(ORIGINAL,read_only=True,data_only=True)
        rows=[r for r in list(workbook['词库'].values)[5:] if r[1]]
        logs=[r for r in list(workbook['复习记录'].values)[5:] if r[0]]
        workbook.close()
        result=import_workbook(self.store,ORIGINAL)
        self.assertEqual(result['words'],len(rows))
        self.assertEqual(result['reviews'],len(logs))
        for r in rows:
            w=self.store.find_word(r[1])
            self.assertEqual(w['mastery'],r[6])
            self.assertEqual(w['meaning'],r[3])
            self.assertEqual(w['notes'],r[13] or '')
        self.assertEqual(sum(w['attempts'] for w in self.store.words()),len(logs))
        self.assertEqual(sum(w['correct'] for w in self.store.words()),sum(r[5]=='正确' for r in logs))
        self.assertEqual(before,hashlib.sha256(ORIGINAL.read_bytes()).hexdigest())
        self.assertTrue(import_workbook(self.store,ORIGINAL)['existing'])


if __name__=='__main__':
    unittest.main(verbosity=2)
