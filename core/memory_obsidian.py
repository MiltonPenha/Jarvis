"""Obsidian is the editable knowledge source. The FTS index is disposable."""
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from core.config import config
from core.safety import atomic_write, checked_path, digest, redact, file_lock

class ObsidianMemory:
    def __init__(self,vault_path=None,index_path=None):
        self.vault_dir = Path(vault_path or config.OBSIDIAN_VAULT_PATH).resolve()
        self.vault_dir.mkdir(parents=True,exist_ok=True)
        self.index_path = Path(index_path or config.DATA_DIR / 'vault-index.sqlite3')
        self.index_path.parent.mkdir(parents=True,exist_ok=True)
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,stamp TEXT); CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(path UNINDEXED,line UNINDEXED,content,tokenize="unicode61 remove_diacritics 2");')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.index_path,timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def refresh(self):
        with self.lock,self.db() as db:
            seen = set()
            for path in self.vault_dir.rglob('*.md'):
                rel = path.relative_to(self.vault_dir).as_posix()
                try:
                    path = checked_path(self.vault_dir,rel,True)
                    stat = path.stat()
                    if stat.st_size > config.MAX_FILE_BYTES:
                        continue
                    stamp = f'{stat.st_mtime_ns}:{stat.st_size}'
                    seen.add(rel)
                    old = db.execute('SELECT stamp FROM files WHERE path=?',(rel,)).fetchone()
                    if old and old['stamp'] == stamp:
                        continue
                    text = redact(path.read_text(encoding='utf-8'))
                    db.execute('DELETE FROM chunks WHERE path=?',(rel,))
                    lines = text.splitlines()
                    for i in range(0,len(lines),12):
                        db.execute('INSERT INTO chunks VALUES(?,?,?)',(rel,i+1,'\n'.join(lines[i:i+12])[:4000]))
                    db.execute('INSERT OR REPLACE INTO files VALUES(?,?)',(rel,stamp))
                except (OSError,UnicodeError,PermissionError):
                    continue
            for row in db.execute('SELECT path FROM files').fetchall():
                if row['path'] not in seen:
                    db.execute('DELETE FROM chunks WHERE path=?',(row['path'],))
                    db.execute('DELETE FROM files WHERE path=?',(row['path'],))

    def search(self,query,limit=5):
        self.refresh()
        words = re.findall(r'\w{3,}',query,flags=re.UNICODE)[:12]
        if not words:
            return []
        expr = ' OR '.join('"'+word+'"' for word in words)
        with self.db() as db:
            rows = db.execute('SELECT path,line,snippet(chunks,2,\'\',\'\',\' … \',45) AS excerpt FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT ?', (expr,max(1,min(limit,10)))).fetchall()
        return [dict(r) for r in rows]

    def read(self,relative,start=1,lines=60):
        path = checked_path(self.vault_dir,relative,True)
        if path.suffix.lower() != '.md' or path.stat().st_size > config.MAX_FILE_BYTES:
            raise ValueError('Somente notas Markdown de até 2 MB.')
        text = path.read_text(encoding='utf-8')
        start = max(1,int(start))
        excerpt = redact('\n'.join(text.splitlines()[start-1:start-1+min(int(lines),100)]))
        return {'path':relative,'line':start,'content':excerpt[:6000], 'truncated':len(text.splitlines())>min(int(lines),100) or len(excerpt)>6000 or start>1, 'sha256':digest(text), 'updated':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()}

    def write(self,relative,content,expected_hash=None,source='user_statement'):
        if source not in ('user_statement','document','observed','inference'):
            raise ValueError('Origem inválida.')
        path = checked_path(self.vault_dir,relative)
        if path.suffix.lower() != '.md' or len(content.encode()) > config.MAX_FILE_BYTES:
            raise ValueError('Somente notas Markdown de até 2 MB.')
        content = redact(content)
        metadata = '<!-- jarvis: '+json.dumps({'source':source,'updated':datetime.now(timezone.utc).isoformat()},ensure_ascii=False)+' -->\n'
        content = metadata+re.sub(r'^<!-- jarvis: .*? -->\r?\n','',content,count=1)
        with self.lock,file_lock(path):
            old = path.read_text(encoding='utf-8') if path.exists() else None
            if old is not None and digest(old) != expected_hash:
                raise ValueError('A nota já existe ou mudou. Leia a versão atual e forneça sha256.')
            if old is not None:
                backup = config.DATA_DIR / 'revisions' / (digest(str(path))[:16]+'-'+digest(old)+'.md')
                atomic_write(backup,old)
            sha = atomic_write(path,content)
            self.refresh()
        return {'verified':True,'path':relative,'sha256':sha,'source':source,'updated':datetime.now(timezone.utc).isoformat()}

obsidian_memory = ObsidianMemory()
