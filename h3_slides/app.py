import asyncio
from contextlib import suppress
import html
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse
import zipfile
from aiohttp import web
from pydantic import ValidationError
from .ingest import ingest, MAX_BYTES
from .llm import ChildGuard, LlamaManager
from .models import Generation, ProjectInput, SlideContent, SlideEdit
from .storage import Store, uid
from .worker import Worker
from .slidev import write_slidev
from .local_models import choose_model_file
from .composition import split_content
from .remote_models import RemoteModelRequest, list_remote_models


def public_project(project):
    return {**project, "sources": [{k: v for k, v in source.items() if k != "text"}
                                 for source in project["sources"]]}


@web.middleware
async def errors(request, handler):
    try:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and urlparse(origin).netloc != request.host:
                raise web.HTTPForbidden(text="Origine non consentita")
            if request.headers.get("X-H3-Slides") != "1":
                raise web.HTTPForbidden(text="Header di sicurezza mancante")
        response = await handler(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response
    except web.HTTPException as exc:
        return web.json_response({"error": exc.text}, status=exc.status)
    except KeyError:
        return web.json_response({"error": "Risorsa non trovata"}, status=404)
    except ValidationError as exc:
        details = "; ".join(".".join(map(str, e["loc"])) + ": " + e["msg"]
                            for e in exc.errors(include_input=False, include_url=False)[:3])
        return web.json_response({"error": "Dati non validi: " + details[:500]}, status=400)
    except (ValueError, json.JSONDecodeError) as exc:
        return web.json_response({"error": str(exc)[:600]}, status=400)
    except Exception:
        logging.exception("Errore H3-slides")
        return web.json_response({"error": "Operazione fallita. Vedi logs/app.log per i dettagli."}, status=500)


async def run_child(app, args, cwd, log_path, env=None, timeout=1200):
    with log_path.open("wb") as log:
        process = subprocess.Popen([str(arg) for arg in args], cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                   env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        app["guard"].assign(process)
        try:
            code = await asyncio.wait_for(asyncio.to_thread(process.wait), timeout)
        except BaseException:
            if process.poll() is None:
                process.kill()
                await asyncio.to_thread(process.wait)
            raise
    if code:
        details = log_path.read_text(encoding="utf-8", errors="replace")[-600:]
        raise ValueError(f"Esportazione fallita: {details}")


def create_app(root=None, data_root=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    config = json.loads((root / "config.example.json").read_text(encoding="utf-8-sig"))
    local = root / "config.local.json"
    if local.exists():
        config.update(json.loads(local.read_text(encoding="utf-8-sig")))
    (root / "logs").mkdir(exist_ok=True)
    app = web.Application(middlewares=[errors], client_max_size=MAX_BYTES + 1024*1024)
    app["root"], app["config"] = root, config
    app["store"] = store = Store(Path(data_root or root / "data"))
    app["guard"] = guard = ChildGuard()
    app["manager"] = manager = LlamaManager(root, config, guard, profile_root=store.root)
    app["worker"] = worker = Worker(store, manager)
    app["export_lock"] = asyncio.Lock()
    app["stop_event"] = asyncio.Event()
    picker_lock = asyncio.Lock()
    slidev_state = {"process": None, "project_id": None, "log": None}

    def sync_slidev(p):
        if slidev_state["project_id"] == p["id"]:
            write_slidev(p, store.root / "assets" / p["id"], root / "data" / "slidev" / p["id"])

    store.on_project_saved = sync_slidev

    async def slidev_preview(request):
        import socket
        def reachable():
            try:
                with socket.create_connection(("localhost", 3031), timeout=.2):
                    return True
            except OSError:
                return False
        p = store.project(request.match_info["pid"])
        process = slidev_state["process"]
        if process and process.poll() is None and slidev_state["project_id"] == p["id"]:
            return web.json_response({"url": "http://localhost:3031"})
        if process and process.poll() is None:
            process.terminate()
            await asyncio.to_thread(process.wait)
        if slidev_state["log"]:
            slidev_state["log"].close()
        if reachable():
            raise ValueError("Porta Slidev 3031 occupata: non termino processi esterni")
        entry = write_slidev(p, store.root / "assets" / p["id"], root / "data" / "slidev" / p["id"])
        log = (root / "logs/slidev.log").open("ab", buffering=0)
        process = subprocess.Popen([str(root / "runtime/node/node.exe"),
                    str(root / "node_modules/@slidev/cli/bin/slidev.mjs"), str(entry),
                    "--port", "3031", "--bind", "127.0.0.1"], cwd=root,
                    stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        guard.assign(process)
        slidev_state.update(process=process, log=log, project_id=p["id"])
        for _ in range(60):
            if process.poll() is not None:
                raise ValueError("Slidev non avviato: controlla logs/slidev.log")
            if reachable():
                return web.json_response({"url": "http://localhost:3031"})
            await asyncio.sleep(.5)
        raise ValueError("Slidev ancora in avvio: controlla logs/slidev.log")

    async def index(request):
        return web.FileResponse(root / "static" / "index.html")

    async def health(request):
        return web.json_response({"app": "H3-slides", "version": "0.2.1", "llama": manager.status()})

    async def models(request):
        catalog = manager.catalog()
        return web.json_response({"models": catalog, "status": manager.status(),
                                  "default_model": manager.local_files.read().get("default_model", ""),
                                  "runtime_available": manager.executable_path().is_file(),
                                  "gpu_layers": config["gpu_layers"], "context_size": config["context_size"]})

    async def local_model(request):
        if worker.active() or manager.lock.locked():
            raise ValueError("Attendi o annulla la generazione prima di cambiare la configurazione dei modelli")
        if picker_lock.locked():
            raise ValueError("Una selezione del modello e gia aperta")
        async with picker_lock:
            if request.match_info["action"] == "pick":
                path = await choose_model_file(root, guard)
                if not path:
                    return web.json_response({"cancelled": True})
            elif request.match_info["action"] == "register":
                body = await request.json()
                path = body.get("path") if isinstance(body, dict) else None
            else:
                raise ValueError("Azione non valida")
            if worker.active():
                raise ValueError("Generazione avviata durante la scelta: riprova quando termina")
            model_id = manager.local_files.register(path)
            return web.json_response({"model": model_id, "cancelled": False})

    async def remote_models(request):
        settings = RemoteModelRequest.model_validate(await request.json())
        return web.json_response(await list_remote_models(settings))

    async def llm_control(request):
        if manager.lock.locked():
            raise ValueError("Caricamento del modello in corso: attendi il completamento")
        if worker.active():
            raise ValueError("Attendi o annulla il job attivo prima di cambiare il runtime LLM")
        body = await request.json()
        if request.match_info["action"] == "stop":
            await manager.stop()
        elif request.match_info["action"] == "start":
            await manager.start(body.get("model", ""))
        else:
            raise ValueError("Azione non valida")
        return web.json_response(manager.status())

    async def admin_llm(request):
        from .runtime_settings import LoadingSettings, InferenceSettings
        if request.method == "POST":
            if manager.lock.locked():
                raise ValueError("Attendi il completamento del caricamento prima di salvare un profilo")
            if worker.active():
                raise ValueError("Attendi o annulla la generazione prima di modificare i profili LLM")
            return web.json_response(manager.save_profile(await request.json()))
        catalog = manager.catalog()
        return web.json_response({"models": catalog, "profiles": {m["id"]: manager.profile(m["id"]) for m in catalog},
                                  "status": manager.status(),
                                  "loading_schema": LoadingSettings.model_json_schema(),
                                  "inference_schema": InferenceSettings.model_json_schema()})

    async def search_settings(request):
        if request.method == "POST":
            if worker.active():
                raise ValueError("Attendi o annulla la generazione prima di modificare la ricerca")
            return web.json_response(worker.search_config.save(await request.json()))
        return web.json_response(worker.search_config.read())

    async def themes(request):
        from .themes import ThemeLibrary
        library = ThemeLibrary(store.root)
        if request.method == "POST":
            return web.json_response(library.save(await request.json()))
        return web.json_response(library.list())

    async def projects(request):
        if request.method == "POST":
            project = store.create(ProjectInput.model_validate(await request.json()).model_dump())
            return web.json_response(public_project(project), status=201)
        return web.json_response([{"id": p["id"], "title": p["title"], "updated_at": p["updated_at"],
                                  "slide_count": len(p["slides"])} for p in store.projects()])

    async def project(request):
        p = store.project(request.match_info["pid"])
        if request.method == "PATCH":
            values = ProjectInput.model_validate(await request.json()).model_dump(exclude_unset=True)
            old_style = tuple(p.get(k) for k in ("theme", "font", "background_color", "accent_color"))
            p.update(values)
            if old_style != tuple(p.get(k) for k in ("theme", "font", "background_color", "accent_color")):
                for slide in p["slides"]:
                    slide.pop("diagram_render", None)
            p["revision"] += 1
            store.save_project(p)
        return web.json_response(public_project(p))

    async def upload(request):
        pid = request.match_info["pid"]
        store.project(pid)
        if worker.active():
            raise ValueError("Aggiungi nuove fonti prima della generazione o dopo averla annullata")
        reader = await request.multipart()
        source = None
        while part := await reader.next():
            if part.name != "file" or not part.filename:
                continue
            raw = bytearray()
            while chunk := await part.read_chunk():
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    raise ValueError("Massimo 250 MB per file")
            source = ingest(store, pid, part.filename, bytes(raw))
            p = store.project(pid)
            p["sources"].append(source)
            store.save_project(p)
        if source is None:
            raise ValueError("Nessun file allegato")
        return web.json_response(public_project(store.project(pid)))

    async def remove_source(request):
        pid, source_id = request.match_info["pid"], request.match_info["source_id"]
        if worker.active():
            raise ValueError("Attendi la fine della generazione o annullala prima di rimuovere una fonte")
        p = store.project(pid)
        source = next((item for item in p["sources"] if item.get("id") == source_id), None)
        if source is None:
            raise KeyError()
        image_names = {item.get("id") for item in source.get("images", []) if item.get("id")}
        file_names = image_names | {
            source.get("pdf_file"), source.get("page_index_file")
        }
        file_names.discard(None)
        p["sources"] = [item for item in p["sources"] if item.get("id") != source_id]
        for slide in p["slides"]:
            if slide.get("content", {}).get("image_id") in image_names:
                slide["content"]["image_id"] = ""
                slide["revision"] = slide.get("revision", 0) + 1
        p["revision"] += 1
        store.save_project(p)

        # Save first: a filesystem cleanup failure must never restore a source
        # in the project after the user has explicitly removed it.
        for name in file_names:
            try:
                store.asset_path(pid, name).unlink(missing_ok=True)
            except (OSError, ValueError):
                logging.warning("Impossibile rimuovere asset della fonte %s: %s", source_id, name)
        asset_root = (store.root / "assets" / pid).resolve()
        if asset_root.is_dir():
            for cache in asset_root.glob("rag-*.json"):
                with suppress(OSError):
                    cache.unlink()
        slidev_root = (store.root / "slidev" / pid / "assets").resolve()
        if slidev_root.is_dir():
            for name in image_names:
                target = (slidev_root / name).resolve()
                if target.is_relative_to(slidev_root):
                    with suppress(OSError):
                        target.unlink()
        return web.json_response(public_project(store.project(pid)))

    async def slide(request):
        p = store.project(request.match_info["pid"])
        item = next((s for s in p["slides"] if s["id"] == request.match_info["sid"]), None)
        if item is None:
            raise KeyError()
        edit = SlideEdit.model_validate(await request.json())
        if item["revision"] != edit.revision:
            return web.json_response({"error": "Slide aggiornata altrove: ricarica prima di salvare", "slide": item}, status=409)
        assets = {i["id"] for source in p["sources"] for i in source["images"]}
        if edit.content.image_id and edit.content.image_id not in assets:
            raise ValueError("Immagine non appartenente a questo progetto")
        if any(len(point) > 160 for point in edit.content.bullets):
            raise ValueError("Massimo 160 caratteri per punto")
        rendered = None
        if edit.content.diagram.kind == "manim":
            rendered = await worker.renderer.render(p["id"], edit.content.diagram.model_dump(), p)
            # Recheck after rendering: an edit made meanwhile must win.
            p = store.project(request.match_info["pid"])
            item = next((s for s in p["slides"] if s["id"] == request.match_info["sid"]), None)
            if item is None or item["revision"] != edit.revision:
                return web.json_response({"error": "Slide aggiornata durante il rendering: ricarica prima di salvare",
                                          "slide": item}, status=409)
        item.update(content=edit.content.model_dump(), revision=item["revision"] + 1, status="ready")
        if rendered:
            item["diagram_render"] = rendered
        elif edit.content.diagram.kind != "manim":
            item.pop("diagram_render", None)
        store.save_project(p)
        return web.json_response(item)

    async def split_slide(request):
        p = store.project(request.match_info["pid"])
        item = next((s for s in p["slides"] if s["id"] == request.match_info["sid"]), None)
        if item is None:
            raise KeyError()
        body = await request.json()
        if body.get("revision") != item["revision"]:
            return web.json_response({"error": "Slide aggiornata altrove: ricarica prima di dividere"}, status=409)
        if item["status"] != "ready":
            raise ValueError("Attendi che la slide sia pronta")
        pieces = split_content(item["content"])
        if len(p["slides"])+len(pieces)-1 > 30:
            raise ValueError("La divisione supera il limite di 30 slide per progetto")
        at = p["slides"].index(item)
        new = [{**item, "id": item["id"] if i == 0 else uid(),
                "revision": item["revision"]+1 if i == 0 else 1, "content": content}
               for i, content in enumerate(pieces)]
        p["slides"][at:at+1] = new
        p["count"] = len(p["slides"])
        store.save_project(p)
        return web.json_response(public_project(p))

    async def reorder(request):
        p = store.project(request.match_info["pid"])
        ids = (await request.json()).get("ids", [])
        if len(ids) != len(p["slides"]) or len(set(ids)) != len(ids) or set(ids) != {s["id"] for s in p["slides"]}:
            raise ValueError("Ordine non valido: includi ogni slide una sola volta")
        by_id = {s["id"]: s for s in p["slides"]}
        p["slides"] = [by_id[sid] for sid in ids]
        store.save_project(p)
        return web.json_response(public_project(p))

    async def generate(request):
        req = Generation.model_validate(await request.json())
        if req.provider.mode == "remote" and not req.provider.remote_consent:
            raise ValueError("Conferma esplicitamente l'invio delle fonti all'API remota")
        return web.json_response(worker.submit(request.match_info["pid"], req), status=202)

    async def jobs(request):
        return web.json_response(store.jobs())

    async def job_control(request):
        jid, action = request.match_info["jid"], request.match_info["action"]
        job = store.job(jid)
        if job["status"] not in ("running", "queued", "paused"):
            raise ValueError("Il job è già terminato")
        if action == "cancel":
            store.event(jid, "Annullamento richiesto", status="cancelled")
            worker.tasks[jid].cancel()
        elif action == "pause":
            store.event(jid, "Pausa richiesta; la chiamata LLM corrente può completarsi", status="paused")
        elif action == "resume":
            store.event(jid, "Generazione ripresa", status="running")
        else:
            raise ValueError("Azione non valida")
        return web.json_response(store.job(jid))

    async def asset(request):
        path = store.asset_path(request.match_info["pid"], request.match_info["name"])
        if not path.is_file():
            raise KeyError()
        return web.FileResponse(path)

    async def export(request):
        if app["export_lock"].locked():
            raise ValueError("Un'esportazione è già in corso")
        p = store.project(request.match_info["pid"])
        if not p["slides"] or any(s["status"] != "ready" for s in p["slides"]):
            raise ValueError("Completa o modifica le slide mancanti prima di esportare")
        fmt = request.match_info["fmt"]
        if fmt not in ("pptx", "pdf", "slidev", "manim"):
            raise ValueError("Formato non valido")
        async with app["export_lock"]:
            eid = uid()
            output = root / "outputs" / p["id"] / eid
            output.mkdir(parents=True)
            snapshot = output / "project.json"
            assets = store.root / "assets" / p["id"]
            env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(root / "runtime" / "browsers"),
                       H3_SLIDES_SNAPSHOT=str(snapshot), H3_SLIDES_ASSETS=str(assets))
            if fmt in ("pptx", "pdf"):
                for slide in p["slides"]:
                    diagram = slide["content"].get("diagram", {})
                    if p.get("use_manim_diagrams") and diagram.get("kind") != "none":
                        slide["diagram_render"] = await worker.renderer.render(p["id"], diagram, p)
                snapshot.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
                await run_child(app, [root / "runtime/node/node.exe", root / "scripts/export.mjs",
                                     snapshot, assets, output, fmt], root, output / "export.log", env)
                filename = "presentazione." + fmt
            elif fmt == "slidev":
                for slide in p["slides"]:
                    diagram = slide["content"].get("diagram", {})
                    if p.get("use_manim_diagrams") and diagram.get("kind") != "none":
                        slide["diagram_render"] = await worker.renderer.render(p["id"], diagram, p)
                write_slidev(p, assets, output, strict=True)
                filename = "slidev.zip"
                with zipfile.ZipFile(output / filename, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(output / "slides.md", "slides.md")
                    archive.write(output / "style.css", "style.css")
                    for image in (output / "assets").glob("*"):
                        if image.suffix.lower() not in (".jpg", ".png"):
                            continue
                        archive.write(image, "assets/" + image.name)
            else:
                snapshot.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
                await run_child(app, [sys.executable, "-m", "manim", "-ql", "--disable_caching",
                                     str(root / "scripts/manim_deck.py"), "H3Deck"], output,
                                     output / "manim.log", env)
                await run_child(app, [root / ".venv/Scripts/manim-slides.exe", "convert",
                                     "H3Deck", "presentazione.html", "--one-file"], output,
                                     output / "manim-slides.log", env)
                filename = "manim-video-slides.zip"
                with zipfile.ZipFile(output / filename, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(output / "presentazione.html", "presentazione.html")
                    videos = list(output.glob("media/videos/**/H3Deck.mp4"))
                    if not videos:
                        raise ValueError("Video Manim non prodotto")
                    archive.write(videos[0], "presentazione.mp4")
            return web.json_response({"url": f"/api/exports/{p['id']}/{eid}/{filename}", "filename": filename})

    async def download(request):
        p = store.project(request.match_info["pid"])
        eid, name = request.match_info["eid"], request.match_info["name"]
        if len(eid) != 36 or any(c not in "0123456789abcdef-" for c in eid):
            raise KeyError()
        if name not in ("presentazione.pptx", "presentazione.pdf", "slidev.zip", "manim-video-slides.zip"):
            raise KeyError()
        path = root / "outputs" / p["id"] / eid / name
        if not path.is_file():
            raise KeyError()
        return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def shutdown(request):
        app["stop_event"].set()
        return web.json_response({"stopping": True})

    async def idle():
        import time
        while True:
            await asyncio.sleep(15)
            if not worker.active() and manager.status()["running"] and time.time()-manager.last_used > config["idle_unload_seconds"]:
                await manager.stop()

    async def startup(app):
        app["idle_task"] = asyncio.create_task(idle())

    async def cleanup(app):
        app["idle_task"].cancel()
        with suppress(asyncio.CancelledError):
            await app["idle_task"]
        await worker.close()
        await manager.stop()
        guard.close()
        if slidev_state["log"]:
            slidev_state["log"].close()
        store.db.close()

    app.router.add_get("/", index)
    app.router.add_get("/library", index)
    app.router.add_get("/library/", index)
    app.router.add_get("/admin", index)
    app.router.add_get("/admin/", index)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/models", models)
    app.router.add_post("/api/remote-models", remote_models)
    app.router.add_post("/api/local-models/{action}", local_model)
    app.router.add_get("/api/admin/llm", admin_llm)
    app.router.add_post("/api/admin/llm", admin_llm)
    app.router.add_get("/api/admin/search", search_settings)
    app.router.add_post("/api/admin/search", search_settings)
    app.router.add_get("/api/themes", themes)
    app.router.add_post("/api/themes", themes)
    app.router.add_post("/api/llm/{action}", llm_control)
    app.router.add_get("/api/projects", projects)
    app.router.add_post("/api/projects", projects)
    app.router.add_get("/api/projects/{pid}", project)
    app.router.add_patch("/api/projects/{pid}", project)
    app.router.add_post("/api/projects/{pid}/sources", upload)
    app.router.add_delete("/api/projects/{pid}/sources/{source_id}", remove_source)
    app.router.add_patch("/api/projects/{pid}/slides/{sid}", slide)
    app.router.add_post("/api/projects/{pid}/reorder", reorder)
    app.router.add_post("/api/projects/{pid}/slides/{sid}/split", split_slide)
    app.router.add_post("/api/projects/{pid}/generate", generate)
    app.router.add_post("/api/projects/{pid}/slidev", slidev_preview)
    app.router.add_get("/api/jobs", jobs)
    app.router.add_post("/api/jobs/{jid}/{action}", job_control)
    app.router.add_get("/api/assets/{pid}/{name}", asset)
    app.router.add_post("/api/projects/{pid}/export/{fmt}", export)
    app.router.add_get("/api/exports/{pid}/{eid}/{name}", download)
    app.router.add_post("/api/shutdown", shutdown)
    app.router.add_static("/static", root / "static", show_index=False)
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    return app


async def serve():
    app = create_app()
    root = app["root"]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(root / "logs/app.log", encoding="utf-8"), logging.StreamHandler()])
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, app["config"]["host"], app["config"]["port"])
        await site.start()
        print(f"H3-slides: http://127.0.0.1:{app['config']['port']}", flush=True)
        await app["stop_event"].wait()
    finally:
        await runner.cleanup()


def main():
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
