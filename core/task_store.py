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
            if 'plan' not in {row['name'] for row in db.execute('PRAGMA table_info(tasks)')}:
                db.execute('ALTER TABLE tasks ADD COLUMN plan TEXT')
            if 'input' not in {row['name'] for row in db.execute('PRAGMA table_info(tasks)')}:
                db.execute('ALTER TABLE tasks ADD COLUMN input TEXT')

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
            data['plan'] = json.loads(data['plan']) if data.get('plan') else None
            data['input'] = json.loads(data['input']) if data.get('input') else {}
            return data

    def input_trace(self,task,data):
        with self.connect() as db:
            row=db.execute('SELECT input FROM tasks WHERE id=?',(task,)).fetchone()
            if not row:raise KeyError(task)
            merged={**(json.loads(row['input']) if row['input'] else {}),**data}
            db.execute('UPDATE tasks SET input=? WHERE id=?',(redact(json.dumps(merged,ensure_ascii=False)),task))

    def pending_music(self,session):
        """Recover only an unresolved explicit music goal, never DOM handles."""
        with self.connect() as db:
            rows=db.execute('SELECT id,input,plan FROM tasks WHERE session=? ORDER BY created DESC LIMIT 20',(session,)).fetchall()
            for row in rows:
                trace=json.loads(row['input']) if row['input'] else {}
                calls=trace.get('intent',[])
                if not calls and row['plan']:
                    calls=[{'action':item['action'],'query':item.get('target','')} for item in json.loads(row['plan']).get('steps',[])]
                requested=[item['query'] for item in calls if item.get('action')=='play_music' and item.get('query')]
                if not requested:continue
                results=[json.loads(item['result']) for item in db.execute('SELECT result FROM tools WHERE task=? AND name=? AND result IS NOT NULL',(row['id'],'play_music'))]
                if any(result.get('verified') for result in results):return ''
                if results:return requested[-1]
        return ''

    def last_music_goal(self,session):
        """Recover the intent, including failed searches; never recover DOM handles."""
        with self.connect() as db:
            rows=db.execute('SELECT id,input,created,result FROM tasks WHERE session=? ORDER BY created DESC LIMIT 50',(session,)).fetchall()
        for row in rows:
            trace=json.loads(row['input'] or '{}')
            goal=trace.get('music_goal') or trace.get('music_intent')
            if goal and goal.get('accepted') and goal.get('query'):
                if 'confirmation' not in goal:
                    # Upgrade a previously displayed, uniquely bound proposal.
                    # Never infer consent or restore a merely generic question.
                    import re
                    import hashlib
                    decision=trace.get('music_selection',{}).get('decision',{})
                    title=decision.get('suggested_title','')
                    choices=[item for item in decision.get('observed',[]) if item.get('title')==title and item.get('channel')==decision.get('suggested_artist')]
                    if title and row['result']=='Senhor, você quis dizer '+title+'?' and len(choices)==1:
                        candidate=choices[0];video=candidate.get('video_id','')
                        if re.fullmatch(r'[\w-]{11}',video) and decision.get('evidence',{}).get(video,{}).get('eligible'):
                            from core.music_followup import offer_confirmation
                            pending=offer_confirmation(candidate,goal['query'],row['id'],goal.get('tab_url',''))
                            pending.update(id=hashlib.sha256((row['id']+video).encode()).hexdigest()[:32],session=session,
                                created_at=datetime.fromisoformat(row['created']).timestamp())
                            goal={**goal,'confirmation':pending}
                return {**goal,'observed_at':goal.get('observed_at',datetime.fromisoformat(row['created']).timestamp()),'task_id':row['id']}
        return {}

    def last_playback(self,session):
        """Only confirmed media evidence for this conversation; never page handles."""
        from urllib.parse import urlparse,parse_qs
        import re
        with self.connect() as db:
            rows=db.execute("SELECT tools.result FROM tools JOIN tasks ON tasks.id=tools.task WHERE tasks.session=? AND tools.name IN ('play_music','media') AND tools.result IS NOT NULL ORDER BY tasks.created DESC,tools.updated DESC LIMIT 100",(session,)).fetchall()
        for row in rows:
            result=json.loads(row['result']);url=result.get('url','');parsed=urlparse(url)
            video=parse_qs(parsed.query).get('v',[''])[0]
            if result.get('verified') is True and parsed.hostname in ('youtube.com','www.youtube.com') and parsed.path=='/watch' and re.fullmatch(r'[\w-]{11}',video) and result.get('video_id')==video:
                return {'url':url,'video_id':video}
        return None

    def save_plan(self,task,plan):
        """An admitted local plan is immutable across checkpoint resume."""
        value=json.dumps(plan,ensure_ascii=False,sort_keys=True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT plan FROM tasks WHERE id=?',(task,)).fetchone()
            if not row: raise KeyError(task)
            if row['plan'] and row['plan']!=value: raise ValueError('Esta tarefa já possui um plano admitido. Envie um novo pedido para mudar as etapas.')
            db.execute('UPDATE tasks SET plan=? WHERE id=?',(value,task))

    def list(self,session=None):
        with self.connect() as db:
            rows = db.execute('SELECT id,session,prompt,state,created,updated,result,error,usage FROM tasks WHERE (? IS NULL OR session=?) ORDER BY created DESC LIMIT 100',(session,session)).fetchall()
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
        return {'tasks':sum(u.get('provider') not in ('local-cpu','direct','deterministic') for u in usage)+len(rows)-len(usage),'tokens':sum(u.get('input_tokens',0)+u.get('output_tokens',0) for u in usage if u.get('provider') not in ('local-cpu','direct','deterministic')),
                'estimated_usd':known if complete else None,'known_estimate_usd':known}
