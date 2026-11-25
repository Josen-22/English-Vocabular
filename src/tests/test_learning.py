from datetime import date,timedelta
from email.message import Message
from io import BytesIO
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from bridge import Bridge
from excel_io import export_workbook,import_workbook
from learning import LearningStore,sense_options
from lookup import parse_youdao
from preferences import Preferences
from pronunciation import Pronunciation,MAX_AUDIO_BYTES
from store import Store
from weekly import weekly_report


class LearningTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[2]/'验证';root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.home=Path(self.temp.name)
        self.day=date(2026,11,25)
        self.s=LearningStore(self.home/'test.sqlite3',today=lambda:self.day)

    def tearDown(self):self.s.close();self.temp.cleanup()

    def seed(self,count=10):
        return [self.s.save_word('word '+str(n),'完整释义 '+str(n)) for n in range(count)]

    def complete_day(self):
        questions=self.s.start_day()
        for n,q in enumerate(questions):self.s.answer(q['id'],'回答','认识' if n%3==0 else '模糊' if n%3==1 else '不认识')
        return self.s.questions()

    def test_sense_options_preserve_parenthesis_and_pos(self):
        result=sense_options('n. 公司，商行；小组（管理；经营）\nadj. 稳固的；坚定的')
        self.assertEqual(result,[{'pos':'n.','meaning':'公司，商行'},{'pos':'n.','meaning':'小组（管理；经营）'},
                                 {'pos':'adj.','meaning':'稳固的'},{'pos':'adj.','meaning':'坚定的'}])

    def test_study_meaning_snapshot_and_metadata_persistence(self):
        ident=self.s.save_word('firm','n. 公司；小组\nadj. 坚固的',study_meaning='n. 公司',uk_phonetic='[fɜːm]',us_phonetic='[fɜːrm]')
        q=self.s.start_day()[0]
        self.assertEqual(q['meaning'],'n. 公司')
        self.s.save_word('firm','完整释义仍保留',ident=ident,study_meaning='adj. 坚固的')
        self.assertEqual(self.s.start_day()[0]['meaning'],'n. 公司')
        word=self.s.get_word(ident);self.assertEqual(word['uk_phonetic'],'[fɜːm]')
        self.assertEqual(word['study_meaning'],'adj. 坚固的')

    def test_old_schema_preserved_and_old_app_reads_enriched_database(self):
        ident=self.s.save_word('retain','保留',study_meaning='保留')
        self.assertEqual(self.s.conn.execute('PRAGMA user_version').fetchone()[0],1)
        legacy=Store(self.s.path)
        try:
            self.assertEqual(legacy.get_word(ident)['meaning'],'保留')
            self.assertEqual(len(legacy.words()),1)
        finally:legacy.close()

    def test_renaming_a_word_clears_stale_phonetics(self):
        ident=self.s.save_word('firm','公司',uk_phonetic='[fɜːm]',us_phonetic='[fɜːrm]')
        self.s.save_word('company','公司',ident=ident,uk_phonetic='[fɜːm]',us_phonetic='[fɜːrm]')
        self.assertEqual(self.s.get_word(ident)['uk_phonetic'],'')
        self.assertEqual(self.s.get_word(ident)['us_phonetic'],'')

    def test_metadata_and_core_word_save_are_one_transaction(self):
        self.s.conn.execute("CREATE TRIGGER reject_metadata BEFORE INSERT ON word_learning BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.s.save_word('rollback','应回滚',study_meaning='不能留下词条')
        self.assertIsNone(self.s.find_word('rollback'))

    def test_configured_daily_count_and_extreme_ratios_are_fixed(self):
        self.seed(20)
        first=self.s.start_day(7,100,0)
        self.assertEqual(len(first),7);self.assertTrue(all(q['is_new'] and q['kind']=='spelling' for q in first))
        self.assertEqual([tuple(q) for q in first],[tuple(q) for q in self.s.start_day(20,0,100)])
        self.assertEqual(self.s.daily_config()['daily_count'],7)
        self.day+=timedelta(days=1)
        second=self.s.start_day(3,0,100)
        self.assertEqual(len(second),3);self.assertTrue(all(q['kind']=='meaning' for q in second))
        # Old pool is empty, so new words fill even a zero-new target.
        self.assertTrue(all(q['is_new'] for q in second))

    def test_settings_boundary_validation_and_reloading(self):
        p=Preferences(self.home/'prefs.json')
        p.update({'daily_count':1,'new_percent':0,'meaning_percent':100,'audio_cache':True})
        self.assertEqual(Preferences(p.path).read()['daily_count'],1)
        for changes in [{'daily_count':0},{'daily_count':51},{'daily_count':True},{'new_percent':-1},{'meaning_percent':101},{'audio_cache':'yes'}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):p.update(changes)
        for args in [(0,50,50),(51,50,50),(10,-1,50),(10,50,101)]:
            with self.assertRaises(ValueError):self.s.start_day(*args)

    def test_wrong_practice_requires_completed_day_and_keeps_daily_results(self):
        self.seed()
        with self.assertRaises(ValueError):self.s.start_practice('daily_wrong')
        daily=[tuple(q) for q in self.complete_day()]
        session=self.s.start_practice('daily_wrong',10,0)
        self.assertEqual(len(session['questions']),6)
        self.assertTrue(all(q['kind']=='spelling' for q in session['questions']))
        self.assertEqual(self.s.start_practice('daily_wrong')['id'],session['id'])
        q=session['questions'][0]
        before=len(self.s.reviews())
        self.assertTrue(self.s.answer_practice(q['id'],'manual accepted','认识'))
        self.assertFalse(self.s.answer_practice(q['id'],'double click','不认识'))
        self.assertEqual(len(self.s.reviews()),before+1)
        self.assertEqual(daily,[tuple(q) for q in self.s.questions()])
        self.assertIn('错词复测',self.s.reviews()[-1]['batch'])

    def test_practice_resume_across_restart_and_midnight(self):
        self.seed();self.complete_day();session=self.s.start_practice('daily_wrong')
        self.s.answer_practice(session['questions'][0]['id'],'','认识')
        self.day+=timedelta(days=1)
        self.s.close();self.s=LearningStore(self.home/'test.sqlite3',today=lambda:self.day)
        resumed=self.s.practice();self.assertEqual(resumed['id'],session['id'])
        self.assertEqual(sum(q['result'] is not None for q in resumed['questions']),1)
        for q in resumed['questions'][1:]:self.s.answer_practice(q['id'],'','认识')
        self.assertIsNone(self.s.practice())
        self.assertIsNotNone(self.s.practice(session['id'])['completed'])
        self.assertEqual(self.s.questions(),[])

    def test_weak_practice_excludes_new_mastered_and_deleted(self):
        ids=self.seed(4)
        for ident in ids[:3]:
            with self.s.conn:
                self.s.conn.execute('INSERT INTO reviews(word_id,word,reviewed,direction,result) VALUES(?,?,?,?,?)',
                    (ident,'word '+str(ident-1),self.day.isoformat(),'英译中','不认识'))
        with self.s.conn:self.s.conn.execute('UPDATE words SET mastery=5 WHERE id=?',(ids[1],))
        self.s.delete_word(ids[2])
        session=self.s.start_practice('weak')
        self.assertEqual([q['word_id'] for q in session['questions']],[ids[0]])

    def test_no_wrong_words_does_not_create_empty_session(self):
        self.seed(2)
        for q in self.s.start_day():self.s.answer(q['id'],'','认识')
        self.assertIsNone(self.s.start_practice('daily_wrong'))
        self.assertEqual(self.s.conn.execute('SELECT COUNT(*) FROM practice_sessions').fetchone()[0],0)

    def test_weekly_bounds_unknown_types_and_distinct_word_counts(self):
        ident=self.seed(1)[0]
        records=[(self.day-timedelta(days=7),'英译中','认识'),(self.day-timedelta(days=6),'英译中','模糊'),
                 (self.day,'英译中','认识'),(self.day,'中译英','不认识'),(self.day,'纸面自测','认识'),
                 (self.day+timedelta(days=1),'中译英','认识')]
        with self.s.conn:
            for day,direction,result in records:self.s.conn.execute('INSERT INTO reviews(word_id,word,reviewed,direction,result) VALUES(?,?,?,?,?)',
                (ident,'word 0',day.isoformat(),direction,result))
        report=weekly_report(self.s)
        self.assertEqual((report['study_days'],report['reviewed_words'],report['attempts']),(2,1,4))
        self.assertEqual(report['accuracy']['meaning']['rate'],.5)
        self.assertEqual(report['accuracy']['spelling']['rate'],0)
        self.assertEqual(report['other_attempts'],1)
        self.assertEqual(report['missed'][0]['misses'],2)
        self.assertEqual(len(report['days']),7)
        self.assertEqual(report['days'][0]['attempts'],1)

    def test_empty_report_and_practice_category(self):
        empty=weekly_report(self.s);self.assertIsNone(empty['accuracy']['spelling']['rate'])
        self.seed();self.complete_day();session=self.s.start_practice('daily_wrong')
        q=session['questions'][0];self.s.answer_practice(q['id'],'','认识')
        report=weekly_report(self.s)
        self.assertEqual(report['completed_daily'],1);self.assertEqual(report['practice_attempts'],1)
        self.assertEqual(report['attempts'],11)

    def test_backups_and_excel_preserve_learning_features(self):
        ident=self.s.save_word('firm','公司；稳固',study_meaning='公司',uk_phonetic='[fɜːm]')
        self.s.start_day();backup=self.s.backup(self.home/'backup.sqlite3')
        self.s.save_word('firm','公司；稳固',ident=ident,study_meaning='稳固')
        self.s.restore(backup,self.home/'backups')
        self.assertEqual(self.s.get_word(ident)['study_meaning'],'公司')
        path=export_workbook(self.s,self.home/'export.xlsx')
        other=LearningStore(self.home/'other.sqlite3')
        try:
            import_workbook(other,path);w=other.find_word('firm')
            self.assertEqual(w['study_meaning'],'公司');self.assertEqual(w['uk_phonetic'],'[fɜːm]')
        finally:other.close()

    def test_bridge_integrates_custom_settings_practice_and_weekly(self):
        b=Bridge(self.home,store_factory=lambda path:LearningStore(path,today=lambda:self.day))
        self.assertTrue(b.call('preferences',{'daily_count':3,'meaning_percent':100})['ok'])
        for n in range(5):b.call('save',{'word':'api '+str(n),'meaning':'完整','study_meaning':'短义项'})
        questions=b.call('start')['data'];self.assertEqual(len(questions),3)
        self.assertTrue(all(q['meaning']=='短义项' for q in questions))
        for q in questions:b.call('answer',{'id':q['id'],'result':'不认识'})
        session=b.call('practice_start',{'mode':'daily_wrong'})['data']
        answer=b.call('practice_answer',{'id':session['questions'][0]['id'],'answer':'','result':'认识'})
        self.assertTrue(answer['ok']);self.assertEqual(b.call('weekly')['data']['practice_attempts'],1)

    def test_lookup_fixture_extracts_both_phonetics(self):
        html=(Path(__file__).parent/'fixtures'/'firm.html').read_text(encoding='utf-8')
        result=parse_youdao(html,'firm')
        self.assertIn('fɜ',result.uk_phonetic);self.assertIn('fɜ',result.us_phonetic)


class AudioResponse(BytesIO):
    url='https://dict.youdao.com/dictvoice?audio=retain&type=1'


class AudioTests(unittest.TestCase):
    def setUp(self):
        directory=Path(__file__).resolve().parents[2]/'验证';directory.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=directory);self.home=Path(self.temp.name)
        self.audio=Pronunciation(self.home/'audio')
        self.mp3=b'ID3'+b'\x00'*100

    def tearDown(self):self.temp.cleanup()

    def test_cache_enabled_allows_offline_replay_and_separates_accents(self):
        with patch('pronunciation.urlopen',return_value=AudioResponse(self.mp3)) as request:
            first=self.audio.get('retain','uk',True)
            self.assertFalse(first['cached']);self.assertEqual(request.call_args.kwargs['timeout'],10)
        with patch('pronunciation.urlopen',side_effect=URLError('offline')):
            replay=self.audio.get('retain','uk',False);self.assertTrue(replay['cached'])
            self.assertEqual(first['audio'],replay['audio'])
            with self.assertRaisesRegex(Exception,'发音读取失败'):self.audio.get('retain','us',True)

    def test_disabled_cache_does_not_write_files(self):
        with patch('pronunciation.urlopen',return_value=AudioResponse(self.mp3)):
            self.audio.get('../unsafe phrase','uk',False)
        self.assertFalse(self.audio.directory.exists())

    def test_invalid_audio_oversize_redirect_and_accent(self):
        for data in [b'<html>captcha</html>',b'ID3'+b'x'*MAX_AUDIO_BYTES]:
            with patch('pronunciation.urlopen',return_value=AudioResponse(data)):
                with self.assertRaises(Exception):self.audio.get('retain')
        response=AudioResponse(self.mp3);response.url='https://other.example/audio'
        with patch('pronunciation.urlopen',return_value=response):
            with self.assertRaisesRegex(Exception,'异常跳转'):self.audio.get('retain')
        with self.assertRaises(ValueError):self.audio.get('retain','invalid')


if __name__=='__main__':unittest.main(verbosity=2)
