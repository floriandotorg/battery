import traceback
import time
import json
import logging
import xml.etree.ElementTree as ET
import numpy as np
from collections import deque
from statistics import median
from urllib.parse import quote
from datetime import datetime, time as dt_time
from lib import *

logging.basicConfig(level='DEBUG', format='[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M')
logging.getLogger('httpx').setLevel(logging.WARNING)
log = logging.getLogger(__name__)

interval_time = 1
history_length = 120
charging_efficiency = 0.8
charging_power_factor = 0.9
discharge_power = 85
discharge_minimum_consumption = 100

with open('calibration.json') as file:
  calibration = json.load(file)

charging_power_levels = [c['fritz'] for c in calibration]

battery_power_to_fritz_power_fit = np.polyfit([c['battery'] for c in calibration], charging_power_levels, deg=5)
def battery_power_to_fritz_power(power):
  return np.polyval(battery_power_to_fritz_power_fit, power)

max_charging_power = charging_power_levels[-1]

def everything_off():
  fritz_discharge_switch_off()
  fritz_charge_switch_off()
  arduino_set_power_setting(0)
  arduino_set_relais(0)

def clamp_amp(a):
  return max(0, min(a, 5))

def set_charging_power(power):
  for n, level in enumerate(charging_power_levels):
    if power <= level:
      arduino_set_power_setting(n)
      time.sleep(1)
      return

def set_charging():
  arduino_set_power_setting(0)
  fritz_discharge_switch_off()
  fritz_charge_switch_on()
  time.sleep(2)

def set_discharging():
  fritz_discharge_switch_on()

def is_discharge_time():
  return True

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

      log.info(f'====> switch state {state_names[state]} -> {state_names[newState]}')

      if newState > 0:
        set_charging()
      elif newState < 0:
        set_discharging()
      else:
        everything_off()

      buff.clear()
      state = newState

      blynk_write_pin('V1', state)

    battery_consumption = 0
    switch_state(STATE_IDLE)

    while True:
      battery_level_max = int(blynk_read_pin('V9'))
      battery_level_min = int(blynk_read_pin('V8'))
      battery_level_discharge_min = battery_level_min + 5

      info = arduino_get_battery_info()

      if is_charging():
        battery_consumption = battery_power_to_fritz_power(info['v'] / 100 * info['c'] / 100)
      else:
        battery_consumption = 0

      simulation = blynk_read_pin('V2') == '1'
      if simulation:
        current_consumption = int(blynk_read_pin('V3')) + battery_consumption
        battery_level = int(blynk_read_pin('V4'))
      else:
        current_consumption = shelly_get_reading()
        battery_level = info['b']

      log.info(f'battery: {battery_level}%')
      blynk_write_pin('V6', battery_level)

      log.info(f'current consumption: {current_consumption:.0f} W')
      blynk_write_pin('V0', current_consumption)

      log.info(f'battery consumption: {battery_consumption:.0f} W')

      current_consumption_without_battery = current_consumption - battery_consumption

      log.info(f'current consumption without battery: {current_consumption_without_battery:.0f} W')

      buff.append(current_consumption)
      if len(buff) >= history_length:
        median_current_consumption = median(buff)
        if is_idle() and median_current_consumption < -50 and battery_level < battery_level_max: # and not is_discharge_time()
          switch_state(STATE_CHARGE)
        elif (is_charging() and median_current_consumption > 0) or (is_charging() and battery_level >= battery_level_max):
          switch_state(STATE_IDLE)
        elif is_discharing() and (battery_level <= battery_level_min or not is_discharge_time() or (median_current_consumption + discharge_power) < discharge_minimum_consumption):
          switch_state(STATE_IDLE)
        elif is_idle() and is_discharge_time() and battery_level >= battery_level_discharge_min and median_current_consumption >= discharge_minimum_consumption:
          switch_state(STATE_DISCHARGE)

      if is_charging():
        charging_power = max(0, min(max_charging_power, abs(current_consumption_without_battery) * charging_power_factor))
        log.info(f'=> setting charging power to: {charging_power:.0f} W')
        set_charging_power(charging_power)

        info = arduino_get_battery_info()
        watts = battery_power_to_fritz_power(info['v'] / 100 * info['c'] / 100)
        log.info(f"charging {watts:.0f} W")
        blynk_write_pin('V5', watts)
      elif is_discharing():
        blynk_write_pin('V5', -fritz_get_discharge_power() if not simulation else discharge_power)
      else:
        blynk_write_pin('V5', 0)

      time.sleep(interval_time)
  except KeyboardInterrupt:
    break
  except Exception as err:
    log.warning(f'==========> ERROR: {err}')
    log.warning(traceback.format_exc())
    try:
      blynk_log_event('warning', f'Error: {err}')
    except:
      pass
  finally:
    try:
      everything_off()
    except Exception as err:
      log.error(f'==========> ERROR: {err}')
      log.error(traceback.format_exc())
