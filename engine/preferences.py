"""User preferences shared by desktop sessions with different localhost ports."""
import json
import os
from pathlib import Path
import tempfile
from threading import RLock

THEME_COLORS=('blue','teal','green','purple','rose','amber')


def config_directory():
    override=os.environ.get('CIMC_CONFIG_DIRECTORY','')
    if override and Path(override).is_absolute():return Path(override)
    if os.name=='nt':
        return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'CIMCStudio'
    configured=os.environ.get('XDG_CONFIG_HOME','')
    base=Path(configured) if configured and Path(configured).is_absolute() else Path.home()/'.config'
    return base/'cimc-studio'


class Preferences:
    def __init__(self,directory=None):
        self.path=Path(directory or config_directory())/'preferences.json'
        self.lock=RLock()

    def read(self):
        with self.lock:
            try:
                value=json.loads(self.path.read_text(encoding='utf-8'))
                theme=value.get('themeColor') if isinstance(value,dict) else None
            except (OSError,ValueError):theme=None
            return {'themeColor':theme if isinstance(theme,str) and theme in THEME_COLORS else 'blue'}

    def update(self,value):
        if not isinstance(value,dict) or value.get('themeColor') not in THEME_COLORS:
            raise ValueError('请选择有效的主题颜色')
        saved={'themeColor':value['themeColor']}
        with self.lock:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            descriptor,name=tempfile.mkstemp(prefix='.preferences-',suffix='.json',dir=self.path.parent)
            temporary=Path(name)
            try:
                with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
                    json.dump(saved,stream,ensure_ascii=False)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary,self.path)
            finally:
                if temporary.exists():temporary.unlink()
        return saved
