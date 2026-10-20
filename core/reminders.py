"""Persistent local alarms. UTC storage, Windows timezone display, restart recovery."""
from datetime import datetime, timedelta, timezone
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
import dateparser
from tzlocal import get_localzone
from core.config import config
from core.safety import redact


def parse_when(text, now=None):
    zone = get_localzone()
    now = now or datetime.now(zone)
    if now.tzinfo is None: now = now.replace(tzinfo=zone)
    text = text.strip().lower()
    text = re.sub(r'^daqui\s+(?:a\s+)?', 'em ', text)
    numbers = {'um':'1','uma':'1','dois':'2','duas':'2','três':'3','tres':'3','cinco':'5','dez':'10','quinze':'15','trinta':'30'}
    for word, number in numbers.items(): text = re.sub(r'\b'+word+r'\b', number, text)
    relative = re.fullmatch(r'(?:em\s+)?(\d+)\s*(segundos?|s|minutos?|min|horas?|h|dias?)', text)
    if relative:
        count = int(relative[1]); unit = relative[2]
        seconds = count*(1 if unit.startswith('s') else 60 if unit.startswith('m') else 3600 if unit.startswith('h') else 86400)
        result = now+timedelta(seconds=seconds)
    else:
        # A date without a time must not silently become an alarm at the current time.
        if not re.search(r'\d{1,2}(?::\d{2}|h\d{0,2})|\b(?:às|as)\s+\d|meio[- ]dia|meia[- ]noite', text):
            raise ValueError('Diga um horário, por exemplo: amanhã às 8:30 ou em 10 minutos.')
        text = text.replace('meio-dia','12:00').replace('meia-noite','00:00')
        text = re.sub(r'\b(\d{1,2})h(\d{2})?\b', lambda m: m[1]+':'+(m[2] or '00'), text)
        text = re.sub(r'\b(?:às|as)\s+(\d{1,2})(?!\d|:)', lambda m: m[1]+':00', text)
        text = re.sub(r'\b(?:às|as)\s*', '', text)
        clock=re.fullmatch(r'(?:(hoje|amanhã|amanha)\s+)?(\d{1,2}):(\d{2})(?:\s+da\s+(manhã|manha|tarde|noite))?',text)
        if clock:
            hour=int(clock[2]); minute=int(clock[3]); period=clock[4]
            if period in ('tarde','noite') and hour<12: hour+=12
            if period in ('manhã','manha') and hour==12: hour=0
            result=now.replace(hour=hour,minute=minute,second=0,microsecond=0)
            if clock[1] in ('amanhã','amanha') or (not clock[1] and result<=now): result+=timedelta(days=1)
        else:
            result = dateparser.parse(text, languages=['pt'], settings={'RELATIVE_BASE':now,
                'TIMEZONE':str(zone), 'RETURN_AS_TIMEZONE_AWARE':True, 'PREFER_DATES_FROM':'future', 'DATE_ORDER':'DMY'})
        if result and not re.search(r'amanh|hoje|\d[/.-]\d', text) and result<=now:
            result += timedelta(days=1)
    if not result or result<=now or result>now+timedelta(days=366):
        raise ValueError('Horário inválido ou passado. Use um horário futuro de até um ano.')
    return result.astimezone(timezone.utc)


class ReminderStore:
    def __init__(self, path=None):
        self.path = Path(path or config.DATA_DIR/'reminders.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS reminders
                (id TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, due TEXT NOT NULL,
                 state TEXT NOT NULL, created TEXT NOT NULL)''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10); db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def create(self, text, when, kind='reminder'):
        if kind not in ('alarm','reminder'): raise ValueError('Tipo de aviso inválido.')
        text = redact(text.strip())
        if not text or len(text)>1000: raise ValueError('Informe um texto de até 1000 caracteres.')
        due = parse_when(when)
        identifier = str(uuid.uuid4())
        with self.db() as db:
            db.execute('INSERT INTO reminders VALUES(?,?,?,?,?,?)',
                (identifier, kind, text, due.isoformat(), 'scheduled', datetime.now(timezone.utc).isoformat()))
        local = due.astimezone(get_localzone()).strftime('%d/%m/%Y às %H:%M:%S')
        return {'verified':True, 'id':identifier, 'due':due.isoformat(), 'spoken_message':f'Senhor, aviso agendado para {local}.',
            'message':f'Senhor, {"alarme" if kind=="alarm" else "lembrete"} agendado para {local}: {text}. O JARVIS precisa estar aberto e o computador acordado.'}

    def list(self):
        with self.db() as db:
            rows = db.execute("SELECT * FROM reminders WHERE state IN ('scheduled','due') ORDER BY due LIMIT 200").fetchall()
        return [dict(row) for row in rows]

    def tick(self, now=None):
        now = now or datetime.now(timezone.utc)
        with self.db() as db:
            db.execute("UPDATE reminders SET state='due' WHERE state='scheduled' AND due<=?", (now.isoformat(),))
        return [row for row in self.list() if row['state']=='due']

    def dismiss(self, identifier):
        with self.db() as db:
            row = db.execute('SELECT * FROM reminders WHERE id=?', (identifier,)).fetchone()
            if not row: raise ValueError('Lembrete não encontrado. Consulte a lista.')
            db.execute("UPDATE reminders SET state='dismissed' WHERE id=?", (identifier,))
        return {'verified':True, 'message':'Senhor, aviso encerrado: '+row['text']}


reminders = ReminderStore()
