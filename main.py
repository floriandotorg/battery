import traceback
import time
from datetime import datetime, timezone
import logging
import json
from collections import deque
from statistics import median
from enum import Enum
from lib import *

logging.basicConfig(level='INFO', format='[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M')
logging.getLogger('httpx').setLevel(logging.WARNING)
log = logging.getLogger(__name__)

interval_time = 0.5
history_length_discharge_start = int(30/interval_time)
history_length_discharge_stop = int(60/interval_time)
history_length_charge_start = int(10/interval_time)
history_length_charge_stop = int(10/interval_time)
discharge_minimum_consumption = 100
discharge_power_factor = 1.05
charge_cutoff_voltage = 3.4
discharge_cutoff_voltage_summer = 3.2
discharge_cutoff_voltage_winter = 3.2
discharge_minimum_percentage_summer = 25
discharge_minimum_percentage_winter = 40
charging_pins = [0,1,5,6,13,22,23,24,26,27]
charging_levels = [
    {
        'pins': charging_pins[:1],
        'charging_power': 95,
        'turn_on_threshold': -200,
        'cutoff_threshold': -100
    },
    {
        'pins': charging_pins[:3],
        'charging_power': 280,
        'turn_on_threshold': -500,
        'cutoff_threshold': -350
    },
    {
        'pins': charging_pins[:6],
        'charging_power': 550,
        'turn_on_threshold': -800,
        'cutoff_threshold': -650
    },
    {
        'pins': charging_pins,
        'charging_power': 915,
        'turn_on_threshold': -1200,
        'cutoff_threshold': -1000
    }
]

class State(Enum):
    DISCHARGE = -1
    IDLE = 0
    CHARGE = 1
    INIT = 99


def everything_off():
    soyo_set_power(0)
    for pin in charging_pins:
        gpio_set_pin(pin, True)

last_error = None
was_fully_charged_today = False

while True:
    try:
        discharge_power = 0
        state = State.INIT
        buff = deque(maxlen=max(history_length_discharge_start, history_length_discharge_stop, history_length_charge_start, history_length_charge_stop))
        charging_level = 0

        def set_charging_level(level):
            global charging_level
            if charging_level == level:
                return

            pins_to_turn_on = charging_levels[level - 1]['pins'] if level > 0 and level <= len(charging_levels) else []
            for pin in charging_pins:
                gpio_set_pin(pin, pin not in pins_to_turn_on)
                time.sleep(0.5)

            print(f'setting charging_level from {charging_level} to {level}')
            charging_level = level

        def set_charging():
            soyo_set_power(0)
            set_charging_level(1)

        def set_discharging():
            soyo_set_power(0)
            set_charging_level(0)

        def switch_state(newState):
            global state, charging_level
            if newState == state:
                return

            log.info(f'====> switch state {state} -> {newState}')

            discharge_power = 0

            if newState == State.CHARGE:
                set_charging()
            elif newState == State.DISCHARGE:
                set_discharging()
            else:
                everything_off()
                charging_level = 0

            buff.clear()
            state = newState

        battery_consumption = 0
        switch_state(State.IDLE)

        while True:
            interval_start_time = time.perf_counter()

            discharge_cutoff_voltage =  discharge_cutoff_voltage_winter if datetime.now().month in [11, 12, 1, 2] else discharge_cutoff_voltage_summer
            discharge_minimum_percentage = discharge_minimum_percentage_winter if datetime.now().month in [11, 12, 1, 2] else discharge_minimum_percentage_summer

            #with open('/app/num.txt', 'r') as file:
            #    num = int(file.read().strip())

            if datetime.now().hour >= 0 and datetime.now().hour < 3:
                was_fully_charged_today = False

            if state == State.CHARGE:
                battery_consumption = charging_levels[charging_level - 1]['charging_power']
            elif state == State.DISCHARGE:
                battery_consumption = -discharge_power
            else:
                battery_consumption = 0

            current_consumption = shelly_get_reading()
            # current_consumption = num + battery_consumption

            log.info(f'charging level: {charging_level}')
            log.info(f'current consumption: {current_consumption:.0f} W')
            log.info(f'battery consumption: {battery_consumption:.0f} W')

            current_consumption_without_battery = current_consumption - battery_consumption

            log.info(f'current consumption without battery: {current_consumption_without_battery:.0f} W')

            buff.append(current_consumption_without_battery)

            bms_data = get_jkbms_data()

            log.info(f'battery percentage: {bms_data['battery_percentage']}')

            # stop discharging if current consumption is below discharge_minimum_consumption
            if state == State.DISCHARGE and len(list(buff)) >= history_length_discharge_stop and median(list(buff)[-history_length_discharge_stop:]) + discharge_power < discharge_minimum_consumption:
                log.info('stopping discharge because of low consumption')
                switch_state(State.IDLE)

            # stop discharging if any cell is below discharge_cutoff_voltage
            if state == State.DISCHARGE and min(bms_data['cell_voltages']) <= discharge_cutoff_voltage:
                log.info('stopping discharge because of low cell voltage')
                switch_state(State.IDLE)

            # start discharging if current consumption is above discharge_minimum_consumption and no cell is below discharge_release_voltage
            if state == State.IDLE and len(list(buff)) >= history_length_discharge_start and median(list(buff)[-history_length_discharge_start:]) >= discharge_minimum_consumption and bms_data['battery_percentage'] > discharge_minimum_percentage:
                switch_state(State.DISCHARGE)

            # start charging if current consumption is below charge_minimum_consumption and no cell is above charge_release_voltage
            if state == State.IDLE and len(list(buff)) >= history_length_charge_start and median(list(buff)[-history_length_charge_start:]) < charging_levels[0]['turn_on_threshold'] and was_fully_charged_today == False:
                switch_state(State.CHARGE)

            # stop charging if current consumption is above charge_minimum_consumption
            if state == State.CHARGE and len(list(buff)) >= history_length_charge_stop and median(list(buff)[-history_length_charge_stop:]) >= charging_levels[charging_level - 1]['cutoff_threshold']:
                print(median(list(buff)[-history_length_charge_stop:]))
                print('>=')
                print(charging_levels[charging_level - 1]['cutoff_threshold'])
                if charging_level < 2:
                    log.info('stopping charge because of high consumption')
                    switch_state(State.IDLE)
                else:
                    set_charging_level(charging_level - 1)
                    buff.clear()

            # stop charging if any cell is above charge_cutoff_voltage
            if state == State.CHARGE and max(bms_data['cell_voltages']) >= charge_cutoff_voltage:
                log.info('stopping charge because of high cell voltage')
                switch_state(State.IDLE)
                was_fully_charged_today = True

            if state == State.CHARGE and len(list(buff)) >= history_length_charge_start and median(list(buff)[-history_length_charge_start:]) < (charging_levels[charging_level]['turn_on_threshold'] if charging_level < len(charging_levels) else float('-inf')):
                set_charging_level(charging_level + 1)
                buff.clear()

            if state == State.DISCHARGE:
                discharge_power = int(max(0, min(600, current_consumption_without_battery * discharge_power_factor)))
                log.info(f"setting inverter to {discharge_power}")
                for _ in range(50):
                    soyo_set_power(discharge_power)

            with open('/www/battery.json', 'w') as file:
                json.dump({
                    'last_updated': datetime.now(timezone.utc).isoformat(),
                    'last_error': last_error,
                    'state': str(state),
                    'battery_percentage': bms_data['battery_percentage'],
                    'battery_power': bms_data['battery_power'],
                    'avg_cell_voltage': sum(bms_data['cell_voltages']) / len(bms_data['cell_voltages']),
                    'cell_drift': max(bms_data['cell_voltages']) - min(bms_data['cell_voltages']),
                    'was_fully_charged_today': was_fully_charged_today
                }, file)

            time.sleep(max(0, interval_time - (time.perf_counter() - interval_start_time)))
    except KeyboardInterrupt:
        break
    except Exception as err:
        log.warning(f'==========> ERROR: {err}')
        log.warning(traceback.format_exc())
        last_error = datetime.now(timezone.utc).isoformat()
    finally:
        try:
            everything_off()
        except Exception as err:
            log.error(f'==========> ERROR DURING SHUTDOWN: {err}')
            log.error(traceback.format_exc())

