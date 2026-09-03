"""Real llama.cpp lifecycle smoke test, CPU by default; never downloads weights."""
import asyncio
import argparse
import json
from pathlib import Path
import sys
import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from h3_slides.llm import ChildGuard, LlamaManager


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True, help="Un GGUF piccolo gia presente, usato in CPU")
    parser.add_argument("--port", type=int, default=8097)
    parser.add_argument("--gpu-layers", type=int, default=0)
    parser.add_argument("--llama-executable", type=Path)
    args = parser.parse_args()
    model_path = args.model.resolve()
    if not model_path.is_file():
        raise SystemExit("Modello non trovato: nessun file scaricato.")
    config = json.loads((ROOT / "config.example.json").read_text())
    config.update(llama_port=args.port, gpu_layers=args.gpu_layers, context_size=1024, model_roots=[str(model_path.parent)])
    if args.llama_executable:
        config["llama_executable"] = str(args.llama_executable.resolve())
    guard = ChildGuard()
    manager = LlamaManager(ROOT, config, guard)
    model = next(m for m in manager.catalog() if Path(m["id"]).resolve() == model_path)
    try:
        await manager.start(model["id"])
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as client:
            async with client.post(f"http://127.0.0.1:{args.port}/completion",
                                   json={"prompt":"La presentazione", "n_predict":8,"temperature":0}) as response:
                result = await response.json()
                assert response.status == 200, result
                assert isinstance(result["content"], str)
        print(f"llama.cpp reale: avvio, inferenza (gpu_layers={args.gpu_layers}) e risposta HTTP verificati")
    finally:
        await manager.stop()
        guard.close()
    assert not manager.status()["running"]
    print("Processo gestito terminato; nessun altro runtime modificato")


asyncio.run(main())
