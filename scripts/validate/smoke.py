#!/usr/bin/env python3
"""Small streaming smoke run; do not substitute these observations for AISBench."""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import httpx


async def run(args):
    mgmt_headers = {}
    if os.getenv("FGJSQ_MGMT_API_KEY_FILE"):
        mgmt_headers["X-Motor-Management-Key"] = Path(os.environ["FGJSQ_MGMT_API_KEY_FILE"]).read_text().strip()
    api_headers = {}
    if os.getenv("FGJSQ_SMOKE_API_KEY"):
        api_headers["Authorization"] = "Bearer " + os.environ["FGJSQ_SMOKE_API_KEY"]
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
        async def loads():
            result = await client.get(args.mgmt.rstrip("/") + "/fgjsq/v1/loads", headers=mgmt_headers)
            result.raise_for_status()
            return result.json()
        before = await loads()
        async def request(index):
            start = time.monotonic()
            first_byte = None
            first_content = None
            text_parts = []
            saw_done = False
            async with client.stream("POST", args.url.rstrip("/") + "/v1/chat/completions",
                                     headers=api_headers, json={"model": args.model, "messages": [{"role": "user", "content": args.prompt}],
                                           "stream": True, "max_tokens": 16}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line and first_byte is None:
                        first_byte = time.monotonic() - start
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        saw_done = True
                        continue
                    value = json.loads(data)
                    for choice in value.get("choices", []):
                        delta = choice.get("delta", {})
                        content = delta.get("content") or delta.get("reasoning") or delta.get("reasoning_content")
                        if content:
                            first_content = first_content if first_content is not None else time.monotonic() - start
                            text_parts.append(content)
            return dict(index=index, first_sse_line_s=first_byte, first_content_s=first_content,
                        elapsed_s=time.monotonic()-start, done=saw_done, output_chars=sum(map(len,text_parts)))
        results = await asyncio.gather(*(request(i) for i in range(args.concurrency)))
        after = None
        for _ in range(50):
            after = await loads()
            if after["open_fg"] == after["open_native"] == 0:
                break
            await asyncio.sleep(0.1)
        matched = after["metrics"].get("matched", 0) - before["metrics"].get("matched", 0)
        ok = all(x["done"] and x["output_chars"] > 0 for x in results) and matched > 0 and after["open_fg"] == after["open_native"] == 0
        report = dict(passed=ok, requests=results, before=before, after=after, matched_delta=matched,
                      scope="HTTP chain smoke; no throughput claim")
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
        print(json.dumps({"passed":ok,"matched_delta":matched,"output":str(args.output)}))
        return 0 if ok else 1


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",required=True)
    parser.add_argument("--mgmt",required=True)
    parser.add_argument("--model",required=True)
    parser.add_argument("--prompt",default="请简短介绍自己。")
    parser.add_argument("--concurrency",type=int,default=3)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    raise SystemExit(asyncio.run(run(args)))


if __name__=="__main__":
    main()
