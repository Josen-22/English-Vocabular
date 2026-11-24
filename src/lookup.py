"""Fetch and parse Youdao's public English/Chinese dictionary HTML.

No API credentials, JavaScript execution or third-party parser is needed.
Only the basic dictionary block is used; web translations and examples are not.
"""
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
import unicodedata
from queue import Queue, Empty
from threading import Event, Thread

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 10


class DictionaryError(Exception):
    """A user-readable lookup failure, safe to show without clearing the form."""


class HeadwordMismatch(DictionaryError):
    def __init__(self, query, candidate):
        self.query, self.candidate = query, candidate
        super().__init__(f'有道返回的词条是“{candidate}”，与“{query}”不一致。请确认后输入该词重新查询。')


def normalize_query(query):
    query = ' '.join(unicodedata.normalize('NFKC', query).split())
    if not query:
        raise DictionaryError('请先输入要查询的单词或短语。')
    if len(query) > 100:
        raise DictionaryError('单词或短语请控制在 100 个字符以内。')
    return query


def query_key(query):
    return normalize_query(query).casefold()


def dictionary_url(query):
    return 'https://dict.youdao.com/w/eng/' + quote(normalize_query(query), safe='') + '/'


@dataclass(frozen=True)
class Sense:
    pos: str
    meaning: str


@dataclass(frozen=True)
class LookupResult:
    query: str
    headword: str
    senses: tuple[Sense, ...]
    source_url: str

    @property
    def pos(self):
        return ' / '.join(dict.fromkeys(s.pos for s in self.senses if s.pos))

    @property
    def meaning(self):
        return '\n'.join((s.pos + ' ' if s.pos else '') + s.meaning for s in self.senses)


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()

    def text(self):
        if self.tag in ('script', 'style', 'noscript'):
            return ''
        return ''.join(child.text() if isinstance(child, _Node) else child for child in self.children)


class _HTMLTree(HTMLParser):
    VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node('root')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


POS_PREFIX = re.compile(
    r'^(?P<pos>(?:(?:n|v|vt|vi|adj|adv|pron|prep|conj|num|art|int|aux|det|abbr|modal|phr)\.'
    r'\s*(?:[/&,、]\s*)?)+)\s*(?P<meaning>.+)$', re.I)


def parse_youdao(html, query):
    query = normalize_query(query)
    # The live HTML sometimes contains literal usage labels like <英，非正式>.
    # Preserve these as text instead of letting an HTML parser discard the label.
    html = re.sub(r'<[\u3400-\u9fff][^<>]*>', lambda m: escape(m.group()), html)
    parser = _HTMLTree()
    parser.feed(html)
    parser.close()
    block = next((n for n in parser.root.walk() if n.attrs.get('id') == 'phrsListTab'), None)
    if block is None:
        if any(marker in html.casefold() for marker in ('captcha','验证码','安全验证','访问过于频繁')):
            raise DictionaryError('有道暂时限制了访问，请稍后重试，或点击“查看有道原网页”。')
        raise DictionaryError('没有找到基础英汉释义，可能是拼写有误、词条未收录或网页结构变化。')
    head = next((n for n in block.walk() if 'keyword' in n.attrs.get('class','').split()), None)
    headword = ' '.join(head.text().split()) if head else ''
    if not headword:
        raise DictionaryError('未识别到有道词条标题，暂不填入释义，请稍后重试。')
    if query_key(headword) != query_key(query):
        raise HeadwordMismatch(query, headword)
    senses = []
    for container in block.children:
        if not isinstance(container, _Node) or 'trans-container' not in container.attrs.get('class','').split():
            continue
        for ul in container.children:
            if not isinstance(ul, _Node) or ul.tag != 'ul':
                continue
            for li in ul.children:
                if not isinstance(li, _Node) or li.tag != 'li':
                    continue
                line = ' '.join(li.text().split())
                if not re.search(r'[\u3400-\u9fff]', line):
                    continue
                match = POS_PREFIX.match(line)
                pos, meaning = (match['pos'].strip(' /&,、'), match['meaning'].strip()) if match else ('', line)
                sense = Sense(pos, meaning)
                if sense not in senses:
                    senses.append(sense)
    if not senses:
        raise DictionaryError('该词条没有可识别的中文基础释义，请检查拼写或查看有道原网页。')
    return LookupResult(query, headword, tuple(senses), dictionary_url(query))


def fetch_youdao(query):
    query = normalize_query(query)
    request = Request(dictionary_url(query), headers={
        'User-Agent': 'Mozilla/5.0 (compatible; LocalVocabulary/1.1; personal dictionary lookup)',
        'Accept': 'text/html', 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    })
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            target = urlparse(response.url)
            if target.scheme != 'https' or not (target.hostname == 'youdao.com' or
                                                (target.hostname or '').endswith('.youdao.com')):
                raise DictionaryError('词典页面发生了异常跳转，未读取或填入结果。')
            if response.headers.get_content_type() not in ('text/html','application/xhtml+xml'):
                raise DictionaryError('有道返回的不是词典网页，请稍后重试。')
            data = response.read(MAX_BYTES+1)
            if len(data) > MAX_BYTES:
                raise DictionaryError('词典网页内容过大，已停止读取，请查看有道原网页。')
            html = data.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
    except HTTPError as exc:
        if exc.code in (403,429):
            raise DictionaryError('有道暂时限制了访问，请稍后重试，或查看有道原网页。') from exc
        raise DictionaryError(f'有道网页访问失败（HTTP {exc.code}），请稍后重试。') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise DictionaryError('连接有道失败或超过 10 秒，请检查网络后重试。当前内容已保留。') from exc
    return parse_youdao(html, query)


class LookupWorker:
    """One daemon worker; replace queued queries with the most recent request.

    The thread never accesses Tk or SQLite. A timed-out request cannot prevent
    closing the application, and rapid typing cannot spawn unlimited threads.
    """
    def __init__(self, fetcher=fetch_youdao):
        self.fetcher = fetcher
        self.requests = Queue(maxsize=1)
        self.results = Queue()
        self.stopped = Event()
        self.thread = None

    def submit(self, token, query):
        if self.stopped.is_set():
            return
        try:
            self.requests.get_nowait()
        except Empty:
            pass
        self.requests.put_nowait((token,query))
        if self.thread is None:
            self.thread = Thread(target=self._run, name='youdao-lookup', daemon=True)
            self.thread.start()

    def _run(self):
        while not self.stopped.is_set():
            try:
                token, query = self.requests.get(timeout=0.2)
            except Empty:
                continue
            try:
                result, error = self.fetcher(query), None
            except Exception as exc:
                result, error = None, str(exc) if isinstance(exc, DictionaryError) else '读取词典失败，请稍后重试。当前内容已保留。'
            if not self.stopped.is_set():
                self.results.put((token,query,result,error))

    def close(self):
        self.stopped.set()
