import httpx
import socket
import httpcore
import hashlib
import traceback
import time
import xml.etree.ElementTree as ET
from collections import deque
from statistics import median
from urllib.parse import quote
from datetime import datetime, time as dt_time

fritz_url = '***REMOVED***'
fritz_user = '***REMOVED***'
fritz_password = '***REMOVED***'
fritz_charge_ain = '***REMOVED***'
fritz_discharge_ain = '***REMOVED***'

powerfox_user = '***REMOVED***'
powerfox_pass = '***REMOVED***'

arduino_url = '***REMOVED***'

blynk_token = '***REMOVED***'

history_length = 6
arduino_charge_addr = 1
arduino_discharge_addr = 0
charging_voltage = 15
discharging_voltage = 60
max_charging_power = 75
max_discharging_power = 300
battery_min = 10
battery_level_max = 90
battery_level_min = 10
battery_level_discharge_min = 20
charging_efficiency = 0.70
discharge_power = 85

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
  print('fritz charge switch on')
  fritz_send_command('setswitchon', fritz_charge_ain)

def fritz_charge_switch_off():
  print('fritz charge switch off')
  fritz_send_command('setswitchoff', fritz_charge_ain)

def fritz_discharge_switch_on():
  print('fritz discharge switch on')
  fritz_send_command('setswitchon', fritz_discharge_ain)

def fritz_discharge_switch_off():
  print('fritz discharge switch off')
  fritz_send_command('setswitchoff', fritz_discharge_ain)

def fritz_get_reading(ain):
  res = fritz_send_command('getswitchpower', ain)
  if res == 'inval':
    raise Exception(f'Fritz!Box API could not retrieve power reading')
  return int(res) / 1000

def powerfox_get_reading():
  res = httpx.get('https://backend.powerfox.energy/api/2.0/my/main/current\?unit\=kwh', auth=httpx.BasicAuth(powerfox_user, powerfox_pass), timeout=45)
  if res.status_code != 200:
    raise Exception(f'Powerfox API call failed: {res.text}')
  return res.json()['Watt']

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
    except httpx.ConnectTimeout or socket.timeout or httpcore.ReadTimeout or httpx.ReadTimeout:
      print(f'{method} request failed to Arduino: {path}')
      pass
    time.sleep(10)

def get_arduino_vc(addr):
  return request_arduino_url(f'{arduino_url}/vc/{addr}')

def get_arduino_battery():
  return request_arduino_url(f'{arduino_url}/b')['b']

def set_arduino_power(addr, power):
  print(f'set arduino power at {addr} to {power}')
  request_arduino_url(f'{arduino_url}/p/{addr}/{power}', method='POST')

def set_arduino_vc(addr, v, c):
  print(f'set arduino at {addr} to {v/1000:.1f} V and {c:.0f} mA (power: {v/1000*c/1000:.0f} W)')
  request_arduino_url(f'{arduino_url}/vc/{addr}/{int(v)}/{int(c)}', method='POST')

def set_arduino_discharge_relais(onoff):
  print(f'set discharge relais to {onoff}')
  request_arduino_url(f'{arduino_url}/r/0/{1 if onoff else 0}', method='POST')

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

def everything_off():
  fritz_charge_switch_off()
  fritz_discharge_switch_off()
  set_arduino_discharge_relais(0)

def clamp_amp(a):
  return max(0, min(a, 5))

def set_charging_power(power):
  v = get_arduino_vc(arduino_charge_addr)['v']
  if v < 5:
    v = charging_voltage
  # remove discharge "/ 2"
  set_arduino_vc(arduino_charge_addr, charging_voltage * 1000, clamp_amp(power / 2 / v) * 1000)

  # remove discharge
  v = get_arduino_vc(arduino_discharge_addr)['v']
  if v < 5:
    v = charging_voltage
  set_arduino_vc(arduino_discharge_addr, charging_voltage * 1000, clamp_amp(power / 2 / v) * 1000)

def set_charging():
  set_arduino_discharge_relais(0)
  fritz_discharge_switch_off()
  fritz_charge_switch_on()
  time.sleep(2)
  set_arduino_vc(arduino_charge_addr, charging_voltage, 0)
  set_arduino_vc(arduino_discharge_addr, discharging_voltage, 0) # remove discharge
  set_arduino_power(arduino_charge_addr, 1)
  set_arduino_power(arduino_discharge_addr, 1) # remove discharge

def set_discharging_power(power):
  raise NotImplementedError() # remove discharge
  set_arduino_vc(arduino_discharge_addr, discharging_voltage, clamp_amp(power / discharging_voltage) * 1000)

def set_discharging():
  fritz_discharge_switch_on()
  # fritz_charge_switch_off()
  # assert power > -1 and power <= max_discharging_power
  # set_arduino_discharge_relais(1)
  # time.sleep(2)
  # set_arduino_vc(arduino_discharge_addr, discharging_voltage, 0)
  # set_arduino_power(arduino_discharge_addr, 1)

def is_discharge_time():
  # simulation
  if blynk_read_pin('V2') == '1':
    return blynk_read_pin('V7') == '1'

  check_time = datetime.utcnow().time()
  begin_time = dt_time(20,0)
  end_time = dt_time(3,00)
  return check_time >= begin_time or check_time <= end_time

STATE_DISCHARGE = -1
STATE_IDLE = 0
STATE_CHARGE = 1
STATE_INIT = 99

state_names = {
  -1: 'DISCHARGE',
  0: 'IDLE',
  1: 'CHARGE',
  99: 'INIT'
}

while True:
  try:
    state = STATE_INIT
    buff = deque(maxlen=history_length)

    def is_charging():
      return state > 0

    def is_idle():
      return state == 0

    def is_discharing():
      return state < 0

    def switch_state(newState):
      global state
      if newState == state:
        return

      print(f'\n====> switch state {state_names[state]} -> {state_names[newState]}')

      if newState > 0:
        set_charging()
      elif newState < 0:
        set_discharging()
      else:
        everything_off()

      buff.clear()
      state = newState

      blynk_write_pin('V1', state)
      print()

    battery_consumption = 0
    switch_state(STATE_IDLE)

    while True:
      if is_charging():
        charging = get_arduino_vc(arduino_charge_addr)
        charging2 = get_arduino_vc(arduino_discharge_addr) # remove dischage
        battery_consumption = (charging['v'] * charging['c'] + charging2['v'] * charging2['c']) / charging_efficiency
      else:
        battery_consumption = 0

      simulation = blynk_read_pin('V2') == '1'
      if simulation:
        current_consumption = int(blynk_read_pin('V3')) + battery_consumption
        battery_level = int(blynk_read_pin('V4'))
      else:
        current_consumption = powerfox_get_reading()
        battery_level = get_arduino_battery()

      print(f'battery: {battery_level}%')
      blynk_write_pin('V6', battery_level)

      print(f'current consumption: {current_consumption:.0f} W')
      blynk_write_pin('V0', current_consumption)

      print(f'battery consumption: {battery_consumption:.0f} W')

      current_consumption_without_battery = current_consumption - battery_consumption

      print(f'current consumption without battery: {current_consumption_without_battery:.0f} W')

      buff.append(current_consumption)
      if len(buff) >= history_length:
        median_current_consumption = median(buff)
        if is_idle() and median_current_consumption < -50 and battery_level < battery_level_max and not is_discharge_time():
          switch_state(STATE_CHARGE)
        elif (is_charging() and median_current_consumption > 0) or (is_charging() and battery_level >= battery_level_max):
          switch_state(STATE_IDLE)
        elif is_discharing() and (battery_level <= battery_level_min or not is_discharge_time() or (median_current_consumption + discharge_power) < 150):
          switch_state(STATE_IDLE)
        elif is_idle() and is_discharge_time() and battery_level >= battery_level_discharge_min and median_current_consumption >= 150:
          switch_state(STATE_DISCHARGE)

      if is_charging():
        if current_consumption > 0:
          charging_power = 0
        else:
          charging_power = max(0, min(max_charging_power*2, abs(current_consumption_without_battery) * charging_efficiency * 0.8))
        print(f'=> setting charging power to: {charging_power:.0f} W')
        set_charging_power(charging_power)

        charging = get_arduino_vc(arduino_charge_addr)
        charging2 = get_arduino_vc(arduino_discharge_addr)
        watts = charging['v'] * charging['c'] + charging2['v'] * charging2['c']
        print(f"charging {watts:.0f} W")
        blynk_write_pin('V5', watts)
      elif is_discharing():
        blynk_write_pin('V5', -fritz_get_reading(fritz_discharge_ain) if not simulation else discharge_power)
      else:
        blynk_write_pin('V5', 0)

      print()

      time.sleep(10)
  except KeyboardInterrupt:
    break
  except Exception as err:
    print(f'==========> ERROR: {err}')
    print(traceback.format_exc())
    try:
      blynk_log_event('warning', f'Error: {err}')
    except:
      pass
  finally:
    try:
      everything_off()
    except Exception as err:
      print(f'==========> ERROR: {err}')
      print(traceback.format_exc())
