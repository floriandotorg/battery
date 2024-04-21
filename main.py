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
history_length_discharge_start = int(30/(interval_time))
history_length_discharge_stop = int(60/(interval_time))
history_length_charge_start = int(2*60/(interval_time))
history_length_charge_stop = int(30/(interval_time))
discharge_minimum_consumption = 100
charge_minimum_consumption = -650
charge_power = 557
discharge_power_factor = 1.05
charge_cutoff_voltage = 3.5
charge_release_voltage = 3.33
dischage_cutoff_voltage = 3.0
discharge_release_voltage = 3.2
charge_ac_relay_pin = 17
charge_dc_relay_pin = 27

def everything_off():
    soyo_set_power(0)
    gpio_set_pin(charge_ac_relay_pin, True)
    gpio_set_pin(charge_dc_relay_pin, False)

def set_charging():
    soyo_set_power(0)
    gpio_set_pin(charge_ac_relay_pin, False)
    time.sleep(10)
    gpio_set_pin(charge_dc_relay_pin, True)

def set_discharging():
    soyo_set_power(0)
    gpio_set_pin(charge_dc_relay_pin, False)
    gpio_set_pin(charge_ac_relay_pin, True)


class State(Enum):
    DISCHARGE = -1
    IDLE = 0
    CHARGE = 1
    INIT = 99

while True:
    last_error = None
    try:
        discharge_power = 0
        state = State.INIT
        buff = deque(maxlen=max(history_length_discharge_start, history_length_discharge_stop, history_length_charge_start, history_length_charge_stop))

        def switch_state(newState):
            global state
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

            buff.clear()
            state = newState

        battery_consumption = 0
        switch_state(State.IDLE)

        while True:
            interval_start_time = time.perf_counter()

            if state == State.CHARGE:
                battery_consumption = charge_power
            elif state == State.DISCHARGE:
                battery_consumption = -discharge_power
            else:
                battery_consumption = 0

            current_consumption = shelly_get_reading()

            log.info(f'current consumption: {current_consumption:.0f} W')
            log.info(f'battery consumption: {battery_consumption:.0f} W')

            current_consumption_without_battery = current_consumption - battery_consumption

            log.info(f'current consumption without battery: {current_consumption_without_battery:.0f} W')

            buff.append(current_consumption)
            buffvals = list(buff)

            bms_data = get_jkbms_data()

            # stop discharging if current consumption is below discharge_minimum_consumption
            if state == State.DISCHARGE and len(buffvals) >= history_length_discharge_stop and median(buffvals[-history_length_discharge_stop:]) + discharge_power < discharge_minimum_consumption:
                log.info('stopping discharge because of low consumption')
                switch_state(State.IDLE)

            # stop discharging if any cell is below dischage_cutoff_voltage
            if state == State.DISCHARGE and min(bms_data['cell_voltages']) <= dischage_cutoff_voltage:
                log.info('stopping discharge because of low cell voltage')
                switch_state(State.IDLE)

            # start discharging if current consumption is above discharge_minimum_consumption and no cell is below discharge_release_voltage
            if state == State.IDLE and len(buffvals) >= history_length_discharge_start and median(buffvals[-history_length_discharge_start:]) >= discharge_minimum_consumption and min(bms_data['cell_voltages']) >= discharge_release_voltage:
                switch_state(State.DISCHARGE)

            # start charging if current consumption is below charge_minimum_consumption and no cell is above charge_release_voltage
            if state == State.IDLE and len(buffvals) >= history_length_charge_start and median(buffvals[-history_length_charge_start:]) < charge_minimum_consumption and max(bms_data['cell_voltages']) <= charge_release_voltage:
                switch_state(State.CHARGE)

            # stop charging if current consumption is above charge_minimum_consumption
            if state == State.CHARGE and len(buffvals) >= history_length_charge_stop and median(buffvals[-history_length_charge_stop:]) > 0:
                log.info('stopping charge because of high consumption')
                switch_state(State.IDLE)

            # stop charging if any cell is above charge_cutoff_voltage
            if state == State.CHARGE and max(bms_data['cell_voltages']) >= charge_cutoff_voltage:
                log.info('stopping charge because of high cell voltage')
                switch_state(State.IDLE)

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
