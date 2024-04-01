import httpx
import logging
import os
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
