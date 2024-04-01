import traceback
import time
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
history_length_discharge_start = int(20*60/(interval_time+1))
history_length_discharge_stop = int(30/(interval_time+1))
history_length_charge_start = int(2*60/(interval_time+1))
history_length_charge_stop = history_length_charge_start
discharge_minimum_consumption = 50
charge_minimum_consumption = -650
charge_power = 557
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

            if len(buffvals) >= history_length_discharge_stop and state == State.DISCHARGE and (median(buffvals[-history_length_discharge_stop:]) + discharge_power) < discharge_minimum_consumption:
                switch_state(State.IDLE)

            if len(buffvals) >= history_length_discharge_start and state == State.IDLE and median(buffvals[-history_length_discharge_start:]) >= discharge_minimum_consumption:
                switch_state(State.DISCHARGE)

            if len(buffvals) >= history_length_charge_start and state == State.IDLE and median(buffvals[-history_length_charge_start:]) < charge_minimum_consumption:
                switch_state(State.CHARGE)

            if len(buffvals) >= history_length_charge_stop and state == State.CHARGE and median(buffvals[-history_length_charge_stop:]) > 0:
                switch_state(State.IDLE)

            if state == State.DISCHARGE:
                discharge_power = int(max(0, min(600, current_consumption_without_battery)))
                log.info(f"setting inverter to {discharge_power}")
                for _ in range(100):
                    soyo_set_power(discharge_power)

            with open('/www/battery.json', 'w') as file:
                json.dump({
                    'state': str(state),
                    'power': battery_consumption,
                }, file)

            time.sleep(interval_time)
    except KeyboardInterrupt:
        break
    except Exception as err:
        log.warning(f'==========> ERROR: {err}')
        log.warning(traceback.format_exc())
    finally:
        try:
            everything_off()
        except Exception as err:
            log.error(f'==========> ERROR: {err}')
            log.error(traceback.format_exc())
