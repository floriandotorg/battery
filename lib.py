import httpx
import logging
import os
import struct
import serial
import RPi.GPIO as GPIO
from dotenv import load_dotenv

load_dotenv()

shelly_url = os.getenv("SHELLY_URL")
shelly_user = os.getenv("SHELLY_USER")
shelly_pass = os.getenv("SHELLY_PASSWORD")

log = logging.getLogger(__name__)


def gpio_set_pin(pin, val):
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.HIGH if val else GPIO.LOW)

def shelly_get_reading():
    with httpx.Client(timeout=5.0, transport=httpx.HTTPTransport(retries=3)) as client:
        res = httpx.get(
            f"{shelly_url}/status", auth=httpx.BasicAuth(shelly_user, shelly_pass)
        ).json()
    [a, b, c] = res["emeters"]
    return a["power"] + b["power"] + c["power"]

def soyo_set_power(power):
    def calc_checksum(b1, b2, b3, b4, b5, b6):
        calc = (0xFF - b1 - b2 - b3 - b4 - b5 - b6) % 256
        return calc & 0xFF

    soyo_power_data = [
        0x24,
        0x56,
        0x00,
        0x21,
        (power >> 8) & 0xFF,
        power & 0xFF,
        0x80,
        0,
    ]

    soyo_power_data[7] = calc_checksum(*soyo_power_data[1:7])

    with serial.Serial("/dev/ttyS0", 4800) as ser:
        ser.write(bytes(soyo_power_data))


def get_jkbms_data():
    with serial.Serial("/dev/ttyS0", 115200, timeout=1) as ser:
        ser.write(b'\x01\x10\x16\x20\x00\x01\x02\x00\x00\xd6\xf1')
        frame = ser.read(300)
        return {
            'cell_voltages': [v * 0.001 for v in struct.unpack('8h', frame[6:6+8*2])],
            'cells_enabled': struct.unpack('4B', frame[70:74]),
            'battery_percentage': struct.unpack('B', frame[173:174])[0],
            'total_capacity': struct.unpack('I', frame[178:182])[0] * 0.001,
            'remaining_capacity': struct.unpack('I', frame[174:178])[0] * 0.001,
            'battery_voltage': struct.unpack('I', frame[150:154])[0] * 0.001,
            'battery_power': struct.unpack('I', frame[154:158])[0] * 0.001
        }

