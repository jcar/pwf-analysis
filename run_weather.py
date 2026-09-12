from pwf.db import init
from pwf import weather
conn = init()
print(weather.backfill(conn, progress=lambda m: print(m, flush=True)), flush=True)
