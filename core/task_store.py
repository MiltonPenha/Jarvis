"""Durable task/checkpoint ledger; conversation messages belong only to Hermes."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from core.config import config
from core.safety import redact

def now():
    return datetime.now(timezone.utc).isoformat()

class TaskStore:
    def __init__(self,path=None):
        self.path = path or config.DATA_DIR / 'tasks.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, session TEXT NOT NULL, prompt TEXT NOT NULL,
                state TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, result TEXT, usage TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS tools (task TEXT NOT NULL, key TEXT NOT NULL, name TEXT NOT NULL,
                state TEXT NOT NULL, result TEXT, updated TEXT NOT NULL, PRIMARY KEY(task,key));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path,timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self,task,session,prompt):
        with self.connect() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone()
            if row:
                if row['prompt'] != prompt or row['session'] != session:
                    raise ValueError('ID já associado a outro pedido.')
                return False
            db.execute('INSERT INTO tasks(id,session,prompt,state,created,updated) VALUES(?,?,?,?,?,?)',
                       (task,session,prompt,'queued',now(),now()))
        return True

    def update(self,task,state,result=None,usage=None,error=None):
        with self.connect() as db:
            db.execute('UPDATE tasks SET state=?,updated=?,result=COALESCE(?,result),usage=COALESCE(?,usage),error=? WHERE id=?',
                       (state,now(),redact(result) if result is not None else None,json.dumps(usage) if usage is not None else None,redact(error) if error else None,task))

    def get(self,task):
        with self.connect() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone()
            if not row:
                raise KeyError(task)
            data = dict(row)
            data['tools'] = [dict(r) for r in db.execute('SELECT * FROM tools WHERE task=? ORDER BY updated',(task,))]
            data['usage'] = json.loads(data['usage']) if data['usage'] else {}
            return data

    def list(self,session=None):
        with self.connect() as db:
            rows = db.execute('SELECT id,session,prompt,state,created,updated,error,usage FROM tasks WHERE (? IS NULL OR session=?) ORDER BY created DESC LIMIT 100',(session,session)).fetchall()
        results=[]
        for row in rows:
            item=dict(row);item['usage']=json.loads(item['usage']) if item['usage'] else {}
            results.append(item)
        return results

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE tasks SET state='interrupted',error='Servidor reiniciado; revise os checkpoints antes de retomar.' WHERE state IN ('queued','running','cancelling')")

    def claim_tool(self,task,key,name):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM tools WHERE task=? AND key=?',(task,key)).fetchone()
            if row:
                if row['state'] == 'done':
                    return json.loads(row['result'])
                raise RuntimeError('Efeito anterior incerto ou falho. Confira o checkpoint; não será repetido automaticamente.')
            db.execute('INSERT INTO tools VALUES(?,?,?,?,?,?)',(task,key,name,'started',None,now()))
        return None

    def finish_tool(self,task,key,result):
        with self.connect() as db:
            db.execute('UPDATE tools SET state=?,result=?,updated=? WHERE task=? AND key=?',
                       ('failed' if result.get('error') else 'done',json.dumps(result,ensure_ascii=False),now(),task,key))

    def daily_usage(self):
        with self.connect() as db:
            rows = db.execute('SELECT usage FROM tasks WHERE created LIKE ?',(now()[:10]+'%',)).fetchall()
        usage = [json.loads(r['usage']) for r in rows if r['usage']]
        known=sum(u.get('estimated_usd') or 0 for u in usage)
        complete=len(usage)==len(rows) and all(u.get('estimated_usd') is not None for u in usage)
        return {'tasks':len(rows),'tokens':sum(u.get('input_tokens',0)+u.get('output_tokens',0) for u in usage),
                'estimated_usd':known if complete else None,'known_estimate_usd':known}
