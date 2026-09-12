"""One-shot full crawl. Resumable: re-running picks up where it left off."""
import sys, time
from datetime import datetime
from pwf.db import init
from pwf import crawl

def progress(done, total, stats, label):
    print(f"{datetime.now():%H:%M:%S} [{label}] {done}/{total} "
          f"ok={stats['ok']} missing={stats['missing']} failed={stats['failed']}",
          flush=True)

t0 = time.time()
conn = init()
print(f"=== index crawl start {datetime.now():%H:%M:%S} ===", flush=True)
print("index stats:", crawl.crawl_index(conn, progress=progress), flush=True)

max_id = crawl.discover_max_id(conn)
print(f"=== max report id = {max_id} ===", flush=True)
print(f"=== report crawl start {datetime.now():%H:%M:%S} ===", flush=True)
print("report stats:", crawl.crawl_reports(conn, max_id=max_id, progress=progress), flush=True)

n = conn.execute("select count(*) from raw_pages").fetchone()[0]
print(f"=== done in {(time.time()-t0)/60:.1f} min, {n} pages cached ===", flush=True)
