"""Shared path, redaction and verified atomic write primitives."""
import hashlib
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

def redact(value):
    text = str(value)
    for key, secret in os.environ.items():
        if any(word in key.upper() for word in ('API_KEY','TOKEN','PASSWORD','SECRET')) and len(secret) > 7:
            text = text.replace(secret, '[SEGREDO REMOVIDO]')
    return re.sub(r'(?i)(sk-[\w-]{16,}|AIza[\w-]{20,})', '[SEGREDO REMOVIDO]', text)

def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def checked_path(root, relative, must_exist=False):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise PermissionError('Caminho fora do diretório autorizado.')
    for part in path.relative_to(root).parts:
        low = part.lower()
        if low.startswith('.') or low in ('node_modules','__pycache__') or any(x in low for x in ('credential','secret','private_key')) or low.endswith(('.pem','.key','.pfx')):
            raise PermissionError('Arquivo privado ou interno não autorizado.')
    if must_exist and not path.is_file():
        raise FileNotFoundError(relative)
    return path

def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.jarvis-', dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
        if path.read_text(encoding='utf-8') != text:
            raise IOError('A verificação após a gravação falhou.')
    finally:
        Path(tmp).unlink(missing_ok=True)
    return digest(text)

@contextmanager
def file_lock(path):
    """Cross-process lock for read/hash/write compare-and-swap operations."""
    from core.config import config
    lock = config.DATA_DIR/'locks'/(digest(str(Path(path).resolve()))+'.lock')
    lock.parent.mkdir(parents=True,exist_ok=True)
    with open(lock,'a+b') as handle:
        if handle.seek(0,2)==0:
            handle.write(b'0');handle.flush()
        handle.seek(0)
        deadline=time.monotonic()+10
        while True:
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>deadline:raise TimeoutError('Arquivo ocupado por outra gravação.')
                time.sleep(.05)
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_UN)
