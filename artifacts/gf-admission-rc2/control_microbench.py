import asyncio,json,time,platform
from pathlib import Path
from test_admission_broker import stack,enqueue,command
async def main():
    b,s,ledger,clock=stack(max_records=4096)
    values=[]
    try:
        for i in range(1000):
            start=time.perf_counter_ns()
            await enqueue(b,str(i),None)
            await b.handle(command(b,"finish",str(i)))
            values.append((time.perf_counter_ns()-start)/1000)
            await asyncio.sleep(0)
        values.sort()
        report=dict(python=platform.python_version(),n=len(values),unit="microseconds per enqueue+finish pair",
                    p50=values[499],p95=values[949],p99=values[989],maximum=max(values),
                    native_adds=len(ledger.adds),native_residual=sum(ledger.loads.values()),
                    scope="in-process broker and fake ledger; includes growing tombstones; no IPC/NPU/production throughput claim")
        print(json.dumps(report,indent=2))
    finally:
        await b.close()
asyncio.run(main())
