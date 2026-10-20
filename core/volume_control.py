"""One volume policy/calculator and verified transaction for every audio target."""
from decimal import Decimal,ROUND_HALF_UP
import math
import os
import time


def percent(value):
    return int(Decimal(str(value)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def minimum():
    return max(1,min(100,int(os.getenv('JARVIS_MIN_AUDIBLE_VOLUME','1'))))


def destination(mode,value,before):
    current=Decimal(str(before['volume_percent']))
    muted=bool(before['muted'])
    if mode in ('absolute','relative','multiply'):
        if type(value) not in (int,float) or not math.isfinite(value):
            raise ValueError('Informe um valor numérico de volume.')
        amount=Decimal(str(value))
        if mode=='multiply' and amount<0:raise ValueError('O fator de volume não pode ser negativo.')
        target=amount if mode=='absolute' else current+amount if mode=='relative' else current*amount
        target=max(0,min(100,percent(target)))
        # Only an explicit absolute zero authorizes silence from a level change.
        target=0 if mode=='absolute' and value==0 else max(minimum(),target)
        return target,target==0
    if mode=='mute':return percent(current),True
    if mode=='unmute':return max(minimum(),percent(current)),False
    if mode=='status':return percent(current),muted
    raise ValueError('Modo de volume inválido.')


def adjust(mode,value,read,write,cancelled=lambda:False,scope='player',timeout=3):
    """Read live state, calculate once, write at most once, then observe only."""
    if cancelled():raise ValueError('Ajuste de volume cancelado.')
    before=read()
    target,muted=destination(mode,value,before)
    changed=mode!='status' and (abs(before['volume_percent']-target)>.01 or before['muted']!=muted)
    if cancelled():raise ValueError('Ajuste de volume cancelado.')
    write_error=None
    if changed:
        try:write(target,muted)
        except Exception as exc:write_error=type(exc).__name__
    deadline=time.monotonic()+timeout
    while True:
        if cancelled():raise ValueError('Ajuste de volume interrompido; confira o alvo antes de repetir.')
        after=read()
        verified=write_error is None and (mode=='status' or abs(after['volume_percent']-target)<=.51 and after['muted']==muted)
        if verified or write_error or time.monotonic()>=deadline:break
        time.sleep(.08)
    observed=percent(after['volume_percent'])
    message=('Senhor, '+('áudio silenciado.' if mode=='mute' else f'volume ajustado para {observed}%.' if mode!='status' else f"volume {'do sistema' if scope=='system' else 'da música'} em {observed}%"+(' e no mudo.' if after['muted'] else '.'))) if verified else 'Senhor, o alvo não confirmou o volume solicitado. Confira o áudio antes de repetir.'
    return {'verified':verified,'scope':scope,'volume_percent':observed,'muted':after['muted'],
        **({'error':'Não consegui aplicar o volume: '+write_error+'. Confira o áudio antes de repetir.'} if write_error else {}),
        'message':message,'spoken_message':message,'state':after,
        'volume_change':{'operation':mode,'value':value,'target':scope,'before_percent':percent(before['volume_percent']),
            'before_muted':before['muted'],'destination_percent':target,'destination_muted':muted,
            'observed_percent':observed,'observed_muted':after['muted'],'write_requested':changed,'applied':changed and verified,'verified':verified}}
