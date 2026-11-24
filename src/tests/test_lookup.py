from email.message import Message
from io import BytesIO
from pathlib import Path
from threading import Event
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import time
import unittest

from lookup import (DictionaryError, HeadwordMismatch, LookupWorker, MAX_BYTES,
                    dictionary_url, fetch_youdao, normalize_query, parse_youdao)

FIXTURES = Path(__file__).parent/'fixtures'


def fixture(name):
    return (FIXTURES/(name+'.html')).read_text(encoding='utf-8')


class Response(BytesIO):
    def __init__(self, content, url='https://dict.youdao.com/w/eng/retain/', content_type='text/html; charset=utf-8'):
        super().__init__(content)
        self.url = url
        self.headers = Message()
        self.headers['Content-Type'] = content_type


class LookupTests(unittest.TestCase):
    def test_actual_basic_verb_fixture(self):
        result = parse_youdao(fixture('retain'),' Retain ')
        self.assertEqual(result.headword,'retain')
        self.assertEqual(result.pos,'v.')
        self.assertIn('保持',result.meaning)
        self.assertNotIn('retaining',result.meaning)

    def test_multiple_pos_and_literal_chinese_usage_label(self):
        result = parse_youdao(fixture('firm'),'firm')
        self.assertEqual(result.pos,'n. / adj. / v. / adv.')
        self.assertEqual(len(result.senses),4)
        self.assertTrue(result.meaning.startswith('n. 公司'))
        self.assertIn('<英，非正式>',result.meaning)
        self.assertIn('\nadj.',result.meaning)

    def test_phrase_and_url_encoding(self):
        result=parse_youdao(fixture('come_out'),' come   out ')
        self.assertIn('出版',result.meaning)
        self.assertEqual(result.headword,'come out')
        self.assertEqual(result.source_url,'https://dict.youdao.com/w/eng/come%20out/')
        self.assertIn('%26',dictionary_url('come & go'))
        self.assertIn('%2F',dictionary_url('and/or'))

    def test_missing_pos_remains_blank_and_entities_are_text(self):
        html='''<div id="phrsListTab"><span class="keyword">x</span>
            <div class="trans-container"><ul><li>含义 &amp; &lt;标签&gt;</li></ul></div></div>'''
        result=parse_youdao(html,'x')
        self.assertEqual(result.pos,'')
        self.assertEqual(result.meaning,'含义 & <标签>')

    def test_exclude_web_meanings_scripts_and_additional_sections(self):
        html=fixture('retain')+'<div id="webTrans"><div class="trans-container"><ul><li>广告假释义</li></ul></div></div>'
        html=html.replace('v. 保持','<script>广告脚本</script>v. 保持')
        result=parse_youdao(html,'retain')
        self.assertNotIn('广告',result.meaning)

    def test_mismatched_headword_never_returns_other_words(self):
        with self.assertRaises(HeadwordMismatch) as ctx:
            parse_youdao(fixture('retain'),'retaining')
        self.assertEqual(ctx.exception.candidate,'retain')

    def test_missing_block_empty_list_and_captcha(self):
        for html in ['<html>没有结果</html>',fixture('retain').replace('phrsListTab','new-layout'),
                     '<div id="phrsListTab"><span class="keyword">retain</span></div>']:
            with self.subTest(html=html[:50]),self.assertRaises(DictionaryError):
                parse_youdao(html,'retain')
        with self.assertRaisesRegex(DictionaryError,'限制'):
            parse_youdao('<html>安全验证 captcha</html>','retain')

    def test_http_request_timeout_headers_and_response(self):
        response=Response(fixture('retain').encode())
        with patch('lookup.urlopen',return_value=response) as request:
            result=fetch_youdao('retain')
        self.assertEqual(result.headword,'retain')
        self.assertEqual(request.call_args.kwargs['timeout'],10)
        self.assertEqual(request.call_args.args[0].full_url,dictionary_url('retain'))
        self.assertTrue(response.closed)

    def test_network_errors_preserve_clear_messages(self):
        errors=[TimeoutError(),URLError('offline')]
        for error in errors:
            with self.subTest(error=error),patch('lookup.urlopen',side_effect=error):
                with self.assertRaisesRegex(DictionaryError,'连接有道失败'):
                    fetch_youdao('retain')
        for code in [403,429,500]:
            with self.subTest(code=code),patch('lookup.urlopen',side_effect=HTTPError('https://dict.youdao.com',code,'failed',{},None)):
                with self.assertRaises(DictionaryError):
                    fetch_youdao('retain')

    def test_response_limits_and_unexpected_types_or_redirect(self):
        for response in [Response(b'x'*(MAX_BYTES+1)),Response(b'{}',content_type='application/json'),
                         Response(b'',url='https://other.example/retain')]:
            with self.subTest(url=response.url),patch('lookup.urlopen',return_value=response):
                with self.assertRaises(DictionaryError):
                    fetch_youdao('retain')
            self.assertTrue(response.closed)

    def test_input_validation(self):
        self.assertEqual(normalize_query('  come\t out  '),'come out')
        for query in ['', '  ', 'x'*101]:
            with self.assertRaises(DictionaryError):
                normalize_query(query)

    def test_worker_latest_pending_query_and_daemon_close(self):
        started,release,finished=Event(),Event(),Event()
        called=[]

        def fetch(query):
            called.append(query)
            if query=='first':
                started.set()
                release.wait(2)
            else:
                finished.set()
            return query

        worker=LookupWorker(fetch)
        try:
            worker.submit(1,'first')
            self.assertTrue(started.wait(1))
            worker.submit(2,'obsolete')
            worker.submit(3,'latest')
            self.assertTrue(worker.thread.daemon)
            release.set()
            self.assertTrue(finished.wait(2))
            self.assertEqual(called,['first','latest'])
            self.assertEqual(worker.results.get(timeout=1)[0],1)
            self.assertEqual(worker.results.get(timeout=1)[0],3)
        finally:
            release.set()
            worker.close()
            worker.thread.join(1)

    def test_worker_does_not_publish_after_close(self):
        started,release=Event(),Event()

        def fetch(query):
            started.set()
            release.wait(1)
            return 'result'

        worker=LookupWorker(fetch)
        worker.submit(1,'retain')
        self.assertTrue(started.wait(1))
        worker.close()
        release.set()
        worker.thread.join(1)
        self.assertTrue(worker.results.empty())


if __name__=='__main__':
    unittest.main(verbosity=2)
