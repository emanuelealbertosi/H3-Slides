"""Optional real-model check; isolated project, no changes to the user's library."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(ROOT))
from h3_slides.llm import ChildGuard, LlamaManager
from h3_slides.models import ProjectInput, Generation
from h3_slides.storage import Store
from h3_slides.worker import Worker


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Existing GGUF; never downloaded")
    parser.add_argument("--port", type=int, default=8097)
    args = parser.parse_args()
    model = str(Path(args.model).resolve())
    output = ROOT / "logs" / ("composer-smoke-" + time.strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True)
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8-sig"))
    config.update(llama_port=args.port, model_roots=[str(Path(model).parent)])
    store = Store(output / "data")
    guard = ChildGuard()
    manager = LlamaManager(ROOT, config, guard, profile_root=store.root)
    saved = ROOT / "data/llm_profiles.json"
    if saved.exists():
        profile = json.loads(saved.read_text(encoding="utf-8")).get(model)
        if profile:
            manager.save_profile(profile)
    worker = Worker(store, manager)
    prompt = ("Crea quattro slide in italiano sulla rappresentazione digitale del suono per studenti. "
              "Prima una copertina introduttiva; poi un confronto tra suono analogico e digitale; "
              "poi i passaggi campionamento, quantizzazione e codifica; infine un esempio concreto "
              "sulle differenze tra WAV e MP3. Paragrafi ragionati e composizioni diverse secondo il contenuto.")
    preset = json.loads((ROOT / "static/theme-presets.json").read_text(encoding="utf-8"))[0]["values"]
    project = store.create(ProjectInput(**preset, title="Prova composer con LLM reale", prompt=prompt,
                                       count=4, use_manim_diagrams=True).model_dump())
    job = worker.submit(project["id"], Generation(provider={"model": model, "vision":False}, prompt=prompt, count=4))
    seen = 0
    started = time.monotonic()
    try:
        while not worker.tasks[job["id"]].done():
            current = store.job(job["id"])
            for event in current["events"][seen:]:
                print(event["message"], flush=True)
            seen = len(current["events"])
            await asyncio.sleep(1)
        await worker.tasks[job["id"]]
        result = store.job(job["id"])
        project = store.project(project["id"])
        (output / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
        report = {"status":result["status"], "seconds":round(time.monotonic()-started,1),
                  "error":result.get("error"), "slides":[{"title":s["content"]["title"],
                  "layout":s["content"]["layout"], "blocks":len(s["content"]["blocks"])} for s in project["slides"]]}
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if result["status"] != "completed":
            raise RuntimeError(result.get("error") or "Generation failed")
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(ROOT / "runtime/browsers"))
        for fmt in ("pdf", "pptx"):
            process = await asyncio.create_subprocess_exec(str(ROOT / "runtime/node/node.exe"),
                str(ROOT / "scripts/export.mjs"), str(output / "project.json"),
                str(store.root / "assets" / project["id"]), str(output / fmt), fmt, env=env)
            if await process.wait():
                raise RuntimeError("Export failed: " + fmt)
        print("Report: " + str(output), flush=True)
    finally:
        await worker.close()
        await manager.stop()
        guard.close()
        store.db.close()


if __name__ == "__main__":
    asyncio.run(main())
