import io
from pathlib import Path
from PIL import Image, ImageOps
from .storage import uid

MAX_BYTES = 250 * 1024 * 1024
MAX_PAGES = 1500
MAX_TEXT = 240000


def ingest(store, pid, filename, raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("File troppo grande: massimo 250 MB")
    filename = filename.replace("\\", "/").split("/")[-1]
    suffix = Path(filename).suffix.lower()
    source = {"id": uid(), "name": filename, "kind": suffix[1:],
              "text": "", "images": [], "warnings": []}
    if suffix in (".md", ".txt"):
        source["text"] = raw.decode("utf-8-sig")
        if len(source["text"]) > MAX_TEXT:
            raise ValueError("Testo troppo lungo: massimo 240.000 caratteri; dividi il documento")
    elif suffix == ".pdf":
        from .retrieval import index_pdf
        return index_pdf(store, pid, source, raw)
    elif suffix in (".png", ".jpg", ".jpeg", ".webp"):
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("Immagine troppo grande: massimo 40 megapixel")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1600, 1600))
            name = uid() + ".jpg"
            image.save(store.asset_path(pid, name), quality=88)
        source["images"].append({"id": name, "label": filename})
        source["warnings"].append("Per interpretare questa immagine seleziona un modello vision")
    else:
        raise ValueError("Formati accettati: PDF, MD, TXT, PNG, JPG, WEBP")
    return source
