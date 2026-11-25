"""Local-only presentation settings; invalid settings fall back safely."""
from pathlib import Path
import json
import os
from library import SORTS,FILTERS

DEFAULTS={'theme':'clean','view':'cards','sort':'added_desc','filter':'all',
          'daily_count':10,'new_percent':50,'meaning_percent':50,'audio_cache':False}
ALLOWED={'theme':{'clean','paper','focus'},'view':{'cards','table'},'sort':SORTS,'filter':FILTERS}


def valid_setting(key,value):
    if key in ALLOWED:
        return isinstance(value,str) and value in ALLOWED[key]
    if key=='audio_cache':
        return type(value) is bool
    if key in ('daily_count','new_percent','meaning_percent'):
        return type(value) is int and (1<=value<=50 if key=='daily_count' else 0<=value<=100)
    return False


class Preferences:
    def __init__(self,path):
        self.path=Path(path)

    def read(self):
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            return dict(DEFAULTS)
        if not isinstance(data,dict):
            return dict(DEFAULTS)
        return {k:data.get(k) if valid_setting(k,data.get(k)) else default
                for k,default in DEFAULTS.items()}

    def update(self,changes):
        if not isinstance(changes,dict) or any(not valid_setting(k,v) for k,v in changes.items()):
            raise ValueError('界面设置无效。')
        result=self.read()
        result.update(changes)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            os.replace(temporary,self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return result
