import time
import json
from lib import fritz_get_charge_power, fritz_charge_switch_on, fritz_charge_switch_off, arduino_set_power_setting, arduino_get_battery_info

result = []

def print_result(r):
  print(f'\tfritz: {r["fritz"]:.2f} W')
  print(f'\tbattery: {r["battery"]:.2f} W')
  print()

def get_data():
  info = arduino_get_battery_info()
  return {
    'fritz': fritz_get_charge_power(),
    'battery': (info['v'] / 100) * (info['c'] / 100),
  }

try:
  fritz_charge_switch_on()

  for n in range(16):
    arduino_set_power_setting(n)
    for m in range(30):
      time.sleep(20)
      data = get_data()
      if data['fritz'] <= data['battery'] > 0 or (len(result) > 0 and data['fritz'] == result[-1]['fritz']):
        print('data implausible, retrying ..')
        continue
      break
    print_result(data)
    result.append(data)

finally:
  fritz_charge_switch_off()
  arduino_set_power_setting(0)

with open('calibration.json', 'w') as f:
  json.dump(result, f, indent=2)
