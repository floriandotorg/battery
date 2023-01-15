import httpx
import socket
import httpcore
import hashlib
import logging
import time
import os
from dotenv import load_dotenv
import xml.etree.ElementTree as ET
from collections import deque
from statistics import median
from urllib.parse import quote
from datetime import datetime, time as dt_time

load_dotenv()

fritz_url = os.getenv("FRITZ_URL")
fritz_user = os.getenv("FRITZ_USER")
fritz_password = os.getenv("FRITZ_PASSWORD")
fritz_charge_ain = os.getenv("FRITZ_CHARGE_AIN")
fritz_discharge_ain = os.getenv("FRITZ_DISCHARGE_AIN")

powerfox_user = os.getenv("POWERFOX_USER")
powerfox_pass = os.getenv("POWERFOX_PASSWORD")

arduino_url = os.getenv("ARDUINO_URL")

blynk_token = os.getenv("BLYNK_TOKEN")

shelly_url = os.getenv("SHELLY_URL")
shelly_user = os.getenv("SHELLY_USER")
shelly_pass = os.getenv("SHELLY_PASSWORD")

log = logging.getLogger(__name__)

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

def fritz_send_command(cmd, ain):
  sid = get_fritz_sid()
  res = httpx.get(f'{fritz_url}/webservices/homeautoswitch.lua?switchcmd={cmd}&sid={sid}&ain={ain}')
  if res.status_code != 200:
    raise Exception(f'Fritz!Box API call failed: {res.text}')
  return res.text

def fritz_charge_switch_on():
  log.debug('fritz charge switch on')
  fritz_send_command('setswitchon', fritz_charge_ain)

def fritz_charge_switch_off():
  log.debug('fritz charge switch off')
  fritz_send_command('setswitchoff', fritz_charge_ain)

def fritz_discharge_switch_on():
  log.debug('fritz discharge switch on')
  fritz_send_command('setswitchon', fritz_discharge_ain)

def fritz_discharge_switch_off():
  log.debug('fritz discharge switch off')
  fritz_send_command('setswitchoff', fritz_discharge_ain)

def fritz_get_power_reading(ain):
  res = fritz_send_command('getswitchpower', ain)
  if res == 'inval':
    raise Exception('Fritz!Box API could not retrieve power reading')
  return int(res) / 1000

def fritz_get_discharge_power():
  return fritz_get_power_reading(fritz_discharge_ain)

def fritz_get_charge_power():
  return fritz_get_power_reading(fritz_charge_ain)

def powerfox_get_reading():
  for n in range(10):
    try:
      res = httpx.get('https://backend.powerfox.energy/api/2.0/my/main/current\?unit\=kwh', auth=httpx.BasicAuth(powerfox_user, powerfox_pass), timeout=5)
      if res.status_code != 200:
        raise Exception(f'Powerfox API call failed: {res.text}')
      return res.json()['Watt']
    except httpx.ConnectTimeout or socket.timeout or httpcore.ReadTimeout or httpx.ReadTimeout or TimeoutError:
      log.warn(f'powerfox request failed (retry: {n + 1})')
      pass

def shelly_get_reading():
  res = httpx.get(f'{shelly_url}/status', auth=httpx.BasicAuth(shelly_user,shelly_pass)).json()
  [a, b, c] = res['emeters']
  return a['power'] + b['power'] + c['power']

def request_arduino_url(path, method='GET'):
  for n in range(10):
    try:
      if method == 'GET':
        res = httpx.get(path, timeout=10)
      elif method == 'POST':
        res = httpx.post(path, timeout=10)
      else:
        raise Exception(f'Unknown method: {method}')
      if res.status_code != 200:
        raise Exception(f'Arduino API call failed: {res.text}')
      if method == 'GET':
        return res.json()
      else:
        return
    except httpx.ConnectTimeout or socket.timeout or httpcore.ReadTimeout or httpx.ReadTimeout or TimeoutError:
      log.warn(f'{method} request failed to Arduino: {path} (retry: {n + 1})')
      pass
    time.sleep(10)

def arduino_get_battery_info():
  return request_arduino_url(f'{arduino_url}/b')

def arduino_set_relais(onoff):
  log.debug(f'set discharge relais to {onoff}')
  request_arduino_url(f'{arduino_url}/r/0/{1 if onoff else 0}', method='POST')

def arduino_set_power_setting(n):
  log.debug(f'set power setting to {n}')
  request_arduino_url(f'{arduino_url}/cr/{n}', method='POST')

def blynk_write_pin(pin, value):
  res = httpx.get(f'https://blynk.cloud/external/api/update?token={blynk_token}&{pin}={value}')
  if res.status_code != 200:
    raise Exception(f'Blynk API call failed: {res.text}')

def blynk_read_pin(pin):
  res = httpx.get(f'https://blynk.cloud/external/api/get?token={blynk_token}&{pin}')
  if res.status_code != 200:
    raise Exception(f'Blynk API call failed: {res.text}')
  return res.text

def blynk_log_event(event_code, event_description = ''):
  res = httpx.get(f'https://blynk.cloud/external/api/logEvent?token={blynk_token}&code={event_code}&description={quote(event_description)}')
  if res.status_code != 200:
    raise Exception(f'Blynk API call failed: {res.text}')
