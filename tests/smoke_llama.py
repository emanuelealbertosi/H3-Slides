"""Real CPU-only llama.cpp lifecycle smoke test, independent of other apps/GPU."""
import asyncio
import json
from pathlib import Path
import sys
import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from h3_slides.llm import ChildGuard, LlamaManager


async def main():
    config = json.loads((ROOT / "config.example.json").read_text())
    config.update(llama_port=8097, gpu_layers=0, context_size=1024)
    guard = ChildGuard()
    manager = LlamaManager(ROOT, config, guard)
    model = next(m for m in manager.catalog() if m["name"] == "gpt2-it-184m")
    try:
        await manager.start(model["id"])
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as client:
            async with client.post("http://127.0.0.1:8097/completion",
                                   json={"prompt":"La presentazione", "n_predict":8,"temperature":0}) as response:
                result = await response.json()
                assert response.status == 200, result
                assert isinstance(result["content"], str)
        print("llama.cpp reale: avvio, inferenza CPU e risposta HTTP verificati")
    finally:
        await manager.stop()
        guard.close()
    assert not manager.status()["running"]
    print("Processo gestito terminato; nessun altro runtime modificato")


asyncio.run(main())
