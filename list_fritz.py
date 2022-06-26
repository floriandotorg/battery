import httpx
import hashlib
import xml.etree.ElementTree as ET

fritz_url = '***REMOVED***'
fritz_user = '***REMOVED***'
fritz_password = '***REMOVED***'
fritz_ain = '***REMOVED***'

def get_fritz_sid():
  res = httpx.get(f'{fritz_url}/login_sid.lua?username={fritz_user}')
  for item in ET.fromstring(res.text).findall('./Challenge'):
    challenge = item.text
  md5_sum = hashlib.md5()
  md5_sum.update((challenge + '-' + fritz_password).encode('utf_16_le'))
  response = f'{challenge}-{md5_sum.hexdigest()}'
  res = httpx.get(f'{fritz_url}/login_sid.lua?username={fritz_user}&response={response}')
  for item in ET.fromstring(res.text).findall('./SID'):
    return item.text
  raise Exception('Fritz!Box SID could not be retrieved')

sid = get_fritz_sid()
res = httpx.get(f'{fritz_url}/webservices/homeautoswitch.lua?switchcmd=getswitchpower&sid={sid}&ain=***REMOVED***')

print(res.text)