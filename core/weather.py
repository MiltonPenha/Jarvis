"""Observed weather, never generated facts. Approximate IP location is labelled."""
import time
import httpx

CONDITIONS = {0:'céu limpo',1:'predominantemente limpo',2:'parcialmente nublado',3:'nublado',
    45:'neblina',48:'neblina',51:'garoa leve',53:'garoa',55:'garoa intensa',61:'chuva leve',
    63:'chuva',65:'chuva forte',71:'neve leve',73:'neve',75:'neve forte',80:'pancadas leves',
    81:'pancadas de chuva',82:'pancadas fortes',95:'trovoadas',96:'trovoadas com granizo',99:'trovoadas com granizo'}
_location = None


def weather(city=''):
    global _location
    with httpx.Client(timeout=12, follow_redirects=True) as client:
        if city:
            response = client.get('https://geocoding-api.open-meteo.com/v1/search', params={'name':city,'count':1,'language':'pt','format':'json'})
            response.raise_for_status(); matches=response.json().get('results', [])
            if not matches: raise ValueError('Cidade não encontrada. Informe cidade e estado.')
            place=matches[0]; approximate=False
        else:
            if not _location or time.monotonic()-_location[0]>1800:
                response=client.get('https://ipwho.is/'); response.raise_for_status(); data=response.json()
                if not data.get('success') or not data.get('city'):
                    raise ValueError('Não consegui localizar o computador pelo IP. Diga: tempo em [cidade].')
                _location=(time.monotonic(), {'name':data['city'],'admin1':data.get('region',''),
                    'latitude':data['latitude'],'longitude':data['longitude']})
            place=_location[1]; approximate=True
        response=client.get('https://api.open-meteo.com/v1/forecast', params={
            'latitude':place['latitude'],'longitude':place['longitude'], 'timezone':'auto',
            'current':'temperature_2m,apparent_temperature,relative_humidity_2m,weather_code',
            'daily':'temperature_2m_max,temperature_2m_min,precipitation_probability_max', 'forecast_days':1})
        response.raise_for_status(); data=response.json(); current=data['current']; daily=data['daily']
    label=', '.join(filter(None,[place['name'], place.get('admin1')]))
    text=(f"Senhor, em {label}: {current['temperature_2m']} °C, sensação de {current['apparent_temperature']} °C e "
        f"{CONDITIONS.get(current['weather_code'],'condição informada pelo serviço meteorológico')}. "
        f"Hoje, mínima de {daily['temperature_2m_min'][0]} °C, máxima de {daily['temperature_2m_max'][0]} °C "
        f"e probabilidade de precipitação de {daily['precipitation_probability_max'][0]}%.")
    if approximate: text+=' Localização aproximada pelo IP; pode diferir da sua cidade.'
    return {'verified':True,'message':text,'spoken_message':f"Senhor, em {place['name']}, {current['temperature_2m']} graus, {CONDITIONS.get(current['weather_code'],'com previsão no painel')}.", 'location':label,'approximate':approximate,
        'observed_at':current['time'],'sources':[{'title':'Open-Meteo','url':'https://open-meteo.com/'}]}
