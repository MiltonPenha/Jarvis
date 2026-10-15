"""Stable, application-local microphone selection; does not change Windows settings."""
import sounddevice as sd

def input_devices():
    apis=sd.query_hostapis()
    result=[]
    for index,device in enumerate(sd.query_devices()):
        if device['max_input_channels']<=0:
            continue
        api=apis[device['hostapi']]['name']
        result.append({'id':api+'::'+device['name'],'index':index,'name':device['name'],
                       'hostapi':api,'sample_rate':int(device['default_samplerate'])})
    return sorted(result,key=lambda d:(d['hostapi']!='Windows WASAPI',d['name']))

def resolve_input(selection=None):
    devices=input_devices()
    if selection in (None,''):
        index=int(sd.default.device[0])
        device=next((d for d in devices if d['index']==index),None)
    elif isinstance(selection,int) or str(selection).isdigit():
        device=next((d for d in devices if d['index']==int(selection)),None)
    else:
        matches=[d for d in devices if d['id']==selection]
        if not matches:
            matches=[d for d in devices if d['name']==selection]
            matches.sort(key=lambda d:d['hostapi']!='Windows WASAPI')
        device=matches[0] if matches else None
    if device is None:
        raise ValueError('Microfone selecionado indisponível. Escolha um dispositivo em Configurações.')
    return device

def capture_parameters(selection=None,preferred_rate=16000):
    device=resolve_input(selection)
    rate=int(preferred_rate)
    try:
        sd.check_input_settings(device=device['index'],channels=1,samplerate=rate)
    except sd.PortAudioError:
        rate=device['sample_rate']
        sd.check_input_settings(device=device['index'],channels=1,samplerate=rate)
    return device,rate
