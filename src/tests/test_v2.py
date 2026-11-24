from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import json
import logging
import tempfile
import unittest
from unittest.mock import patch

from bridge import Bridge
from library import select_words,distribution
from lookup import LookupResult,Sense
from preferences import Preferences,DEFAULTS
from store import Store


class V2Tests(unittest.TestCase):
    def setUp(self):
        directory=Path(__file__).resolve().parents[2]/'验证'
        directory.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=directory)
        self.home=Path(self.temp.name)
        self.bridge=Bridge(self.home)
        self.store=Store(self.bridge._db,today=lambda:date(2026,11,25))
        for word,level,added,due,correct,attempts in [
            ('Zebra',4,'2026-11-20','2026-12-01',4,4),
            ('apple',1,'2026-11-21','2026-11-24',1,4),
            ('Beta',3,'2026-11-22','2026-11-25',2,4),
            ('new word',0,'2026-11-23','2026-11-23',0,0),
            ('same day',0,'2026-11-23','2026-11-26',0,1),
        ]:
            ident=self.store.save_word(word,'中文释义',notes='搜索备注')
            with self.store.conn:
                self.store.conn.execute('UPDATE words SET mastery=?,added=?,due=?,last_review=? WHERE id=?',
                    (level,added,due,'2026-11-20' if attempts else None,ident))
                for n in range(attempts):
                    self.store.conn.execute('''INSERT INTO reviews(word_id,word,reviewed,direction,result)
                        VALUES(?,?,?,?,?)''',(ident,word,'2026-11-20','英译中','认识' if n<correct else '不认识'))

    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def select(self,**kwargs):
        return select_words(self.store.words(),'2026-11-25',**kwargs)

    def test_all_sort_orders_and_unattempted_accuracy_last(self):
        self.assertEqual([w['word'] for w in self.select(sort='az')],['apple','Beta','new word','same day','Zebra'])
        self.assertEqual([w['word'] for w in self.select(sort='za')],['Zebra','same day','new word','Beta','apple'])
        self.assertEqual(self.select(sort='added_desc')[0]['word'],'same day')
        self.assertEqual(self.select(sort='added_asc')[0]['word'],'Zebra')
        self.assertEqual(self.select(sort='mastery_desc')[0]['word'],'Zebra')
        self.assertEqual(self.select(sort='mastery_asc')[0]['mastery'],0)
        self.assertEqual(self.select(sort='due')[0]['word'],'new word')
        accuracy=self.select(sort='accuracy')
        self.assertEqual([w['word'] for w in accuracy],['same day','apple','Beta','Zebra','new word'])
        self.assertIsNone(accuracy[-1]['accuracy'])
        self.assertEqual(self.select(sort='reviewed_oldest')[0]['word'],'new word')

    def test_filters_distribution_search_and_deleted(self):
        for category,expected in [('new',['new word']),('due',['Beta','apple']),('weak',['same day','apple']),
                                  ('learning',['Beta']),('mastered',['Zebra'])]:
            with self.subTest(category=category):
                self.assertEqual({w['word'] for w in self.select(category=category)},set(expected))
        self.assertEqual(distribution(self.store.words()),{'new':1,'weak':2,'learning':1,'mastered':1})
        self.assertEqual(len(self.select(search='备注')),5)
        self.assertEqual(len(self.select(search=' APPLE ')),1)
        ident=self.store.find_word('apple')['id'];self.store.delete_word(ident)
        self.assertFalse(any(w['word']=='apple' for w in self.select()))
        self.assertEqual(self.select(search='不存在'),[])
        for key,value in [('sort','bad'),('category','bad')]:
            with self.assertRaises(ValueError):self.select(**{key:value})

    def test_preferences_invalid_file_fallback_and_persistence(self):
        p=Preferences(self.home/'preferences.json')
        self.assertEqual(p.read(),DEFAULTS)
        result=p.update({'theme':'paper','view':'table','sort':'accuracy'})
        self.assertEqual(Preferences(p.path).read(),result)
        with self.assertRaises(ValueError):p.update({'theme':'not-a-theme'})
        p.path.write_text('{broken',encoding='utf-8');self.assertEqual(p.read(),DEFAULTS)
        p.path.write_text(json.dumps({'theme':'focus','view':[]}));self.assertEqual(p.read()['theme'],'focus')
        self.assertEqual(p.read()['view'],'cards')

    def test_bridge_shared_schema_and_calls_from_multiple_threads(self):
        def read(_):
            response=self.bridge.call('words',{'sort':'az'})
            self.assertTrue(response['ok']);return len(response['data'])
        with ThreadPoolExecutor(max_workers=6) as pool:self.assertEqual(list(pool.map(read,range(12))),[5]*12)
        self.assertEqual(self.bridge.call('bootstrap')['data']['stats']['total'],5)
        r=self.bridge.call('preferences',{'theme':'focus'})
        self.assertTrue(r['ok']);self.assertEqual(Bridge(self.home).call('bootstrap')['data']['preferences']['theme'],'focus')
        self.assertEqual(self.store.conn.execute('PRAGMA user_version').fetchone()[0],1)

    def test_lookup_existing_and_explicit_refresh_never_overwrites(self):
        with patch('bridge.fetch_youdao') as fetch:
            result=self.bridge.call('lookup',{'word':'apple'})
            self.assertTrue(result['data']['existing']);fetch.assert_not_called()
        result=LookupResult('apple','apple',(Sense('n.','苹果'),),'https://dict.youdao.com/w/eng/apple/')
        with patch('bridge.fetch_youdao',return_value=result):
            response=self.bridge.call('lookup',{'word':'apple','refresh':True})
            self.assertIn('苹果',response['data']['word']['meaning'])
            self.assertEqual(self.store.find_word('apple')['meaning'],'中文释义')
        saved=self.bridge.call('save',{'word':'resilient','meaning':'有韧性','pos':'adj.','notes':'笔记'})
        self.assertTrue(saved['ok']);self.assertIsNotNone(self.store.find_word('resilient'))

    def test_bridge_quiz_history_backup_and_errors(self):
        questions=self.bridge.call('start')['data'];q=questions[0]
        check=self.bridge.call('check',{'id':q['id'],'answer':' '+q['word'].upper()+' '})
        self.assertTrue(check['data']['matches'])
        result=self.bridge.call('answer',{'id':q['id'],'answer':'x','result':'认识'})
        self.assertTrue(result['ok']);self.assertEqual(sum(q['result'] is not None for q in result['data']),1)
        history=self.bridge.call('history',{'id':q['word_id']});self.assertTrue(history['ok'])
        backup=self.bridge.call('backup');self.assertTrue(Path(backup['data']['path']).is_file())
        with patch('bridge.logging.exception'):
            self.assertFalse(self.bridge.call('__dict__')['ok'])
            self.assertFalse(self.bridge.call('answer',{'id':q['id'],'result':'invalid'})['ok'])
            self.assertFalse(self.bridge.call('preferences',{'theme':'invalid'})['ok'])


if __name__=='__main__':unittest.main(verbosity=2)
