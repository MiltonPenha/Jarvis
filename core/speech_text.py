"""Text preparation shared by local engines. Never rewrite proper names."""
import re

def number_pt(value):
    value=int(value)
    units=['zero','um','dois','três','quatro','cinco','seis','sete','oito','nove','dez',
           'onze','doze','treze','catorze','quinze','dezesseis','dezessete','dezoito','dezenove']
    tens=['','','vinte','trinta','quarenta','cinquenta','sessenta','setenta','oitenta','noventa']
    if value<20:return units[value]
    if value<100:return tens[value//10]+(' e '+units[value%10] if value%10 else '')
    if value==100:return 'cem'
    return str(value)

def prepare_speech(text,limit=700):
    text=re.split(r'\n\s*Elementos:\s*\n',str(text),maxsplit=1)[0]
    text=re.sub(r'```.*?```',' Os detalhes do código estão na tela. ',text,flags=re.S)
    text=re.sub(r'\[([^\]]+)\]\([^)]+\)',r'\1',text)
    text=re.sub(r'https?://\S+','',text)
    text=re.sub(r'<[^>]+>','',text)
    lines=[line for line in text.splitlines() if not line.lstrip().startswith(('|','Traceback','File "')) and not re.match(r'^\s*[a-f0-9]+:v\d+:\d+\.',line)]
    text=re.sub(r'[`*_#>~]','',' '.join(lines))
    # Numeric rewriting requires a unit/context: numbers in titles stay intact.
    text=re.sub(r'(?<!\w)(100|\d{1,2})([,.]\d+)?\s*%',lambda m:number_pt(m[1])+(' vírgula '+' '.join(number_pt(n) for n in m[2][1:]) if m[2] else '')+' por cento',text)
    text=re.sub(r'(?i)(\b(?:às|para|horário de)\s+)([01]?\d|2[0-3]):([0-5]\d)\b',
                lambda m:m[1]+number_pt(m[2])+' horas'+(' e '+number_pt(m[3])+' minutos' if int(m[3]) else ''),text)
    text=re.sub(r'\s+',' ',text).strip()
    if len(text)>limit:
        suffix=' Os detalhes completos estão na tela.'
        budget=max(1,limit-len(suffix))
        shortened=text[:budget];point=max(shortened.rfind('.'),shortened.rfind('!'),shortened.rfind('?'))
        text=shortened[:point+1] if point>budget//2 else shortened.rsplit(' ',1)[0][:max(0,budget-1)].rstrip(' ,;:')+'.'
        text+=suffix
    return text

def speech_chunks(text,limit=180):
    """Prefer sentence boundaries, then punctuation/words. Never drop a suffix."""
    chunks=[]
    while len(text)>limit:
        candidates=[m.end() for m in re.finditer(r'[.!?;,:](?:\s+|$)',text[:limit+1]) if m.end()<=limit]
        cut=candidates[-1] if candidates and candidates[-1]>=limit//3 else text.rfind(' ',0,limit+1)
        if cut<1:cut=limit
        chunks.append(text[:cut].strip());text=text[cut:].strip()
    if text:chunks.append(text)
    return chunks
