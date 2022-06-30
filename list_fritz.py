import httpx
import os
from dotenv import load_dotenv
from lib import get_fritz_sid

load_dotenv()

sid = get_fritz_sid()
res = httpx.get(f'{os.getenv("FRITZ_URL")}/webservices/homeautoswitch.lua?switchcmd=getdevicelistinfos&sid={sid}')

print(res.text)
