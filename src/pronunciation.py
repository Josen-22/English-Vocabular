"""On-demand public Youdao pronunciation audio, with optional local caching."""
from pathlib import Path
from urllib.parse import urlencode,urlparse
from urllib.request import Request,urlopen
from urllib.error import URLError
import base64
import hashlib
import os
import tempfile

from lookup import normalize_query,DictionaryError

MAX_AUDIO_BYTES=2*1024*1024


def valid_mp3(data):
    return len(data)>10 and (data.startswith(b'ID3') or (data[0]==0xff and data[1]&0xe0==0xe0))


class Pronunciation:
    def __init__(self,directory):
        self.directory=Path(directory)

    def get(self,word,accent='uk',cache=False):
        word=normalize_query(word)
        if accent not in ('uk','us'):raise ValueError('请选择英式或美式发音。')
        key=hashlib.sha256((word.casefold()+'|'+accent).encode('utf-8')).hexdigest()
        path=self.directory/(key+'.mp3')
        if path.is_file():
            data=path.read_bytes()
            if len(data)<=MAX_AUDIO_BYTES and valid_mp3(data):return self._result(data,True)
        url='https://dict.youdao.com/dictvoice?'+urlencode({'audio':word,'type':1 if accent=='uk' else 2})
        try:
            with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0 (LocalVocabulary/2.1)'}),timeout=10) as response:
                target=urlparse(response.url)
                if target.scheme!='https' or not (target.hostname=='youdao.com' or (target.hostname or '').endswith('.youdao.com')):
                    raise DictionaryError('发音资源发生异常跳转。')
                data=response.read(MAX_AUDIO_BYTES+1)
        except (URLError,OSError,TimeoutError) as exc:
            raise DictionaryError('发音读取失败。请检查网络；已缓存的发音可以离线播放。') from exc
        if len(data)>MAX_AUDIO_BYTES or not valid_mp3(data):raise DictionaryError('词典没有返回有效的 MP3 发音，请稍后重试。')
        if cache:
            self.directory.mkdir(parents=True,exist_ok=True)
            fd,temporary=tempfile.mkstemp(suffix='.tmp',dir=self.directory)
            try:
                with os.fdopen(fd,'wb') as file:file.write(data)
                os.replace(temporary,path)
            finally:
                if os.path.exists(temporary):os.unlink(temporary)
        return self._result(data,False)

    @staticmethod
    def _result(data,cached):
        return {'mime':'audio/mpeg','audio':base64.b64encode(data).decode('ascii'),'cached':cached}
