import io
from pathlib import Path
import fitz
from PIL import Image, ImageOps
from pypdf import PdfReader
from .storage import uid

MAX_BYTES = 30 * 1024 * 1024
MAX_PAGES = 60
MAX_TEXT = 240000


def ingest(store, pid, filename, raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("File troppo grande: massimo 30 MB")
    filename = filename.replace("\\", "/").split("/")[-1]
    suffix = Path(filename).suffix.lower()
    sid = uid()
    source = {"id": sid, "name": filename, "kind": suffix[1:], "text": "", "images": [], "warnings": []}

    def save_image(image, label):
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((1600, 1600))
        name = uid() + ".jpg"
        image.save(store.asset_path(pid, name), quality=88)
        source["images"].append({"id": name, "label": label})

    if suffix in (".md", ".txt"):
        source["text"] = raw.decode("utf-8-sig")
        if len(source["text"]) > MAX_TEXT:
            raise ValueError("Testo troppo lungo: massimo 240.000 caratteri; dividi il documento")
    elif suffix == ".pdf":
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError("PDF protetto: carica una copia senza password")
        if len(reader.pages) > MAX_PAGES:
            raise ValueError("Massimo 60 pagine per PDF in questa versione")
        sections = []
        with fitz.open(stream=raw, filetype="pdf") as doc:
            for index, page in enumerate(reader.pages):
                text = (page.extract_text() or "").strip()
                sections.append(f"[{filename}, pagina {index + 1}]\n{text}")
                # Every page is available as reference, including charts and scanned pages.
                rendered = doc[index].get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
                save_image(Image.open(io.BytesIO(rendered.tobytes("png"))),
                           f"{filename}, pagina {index + 1}")
                if len(text) < 30:
                    source["warnings"].append(f"Pagina {index + 1}: serve un modello vision per leggerla")
        source["text"] = "\n\n".join(sections)
        if len(source["text"]) > MAX_TEXT:
            raise ValueError("PDF troppo lungo: dividi il documento (limite 240.000 caratteri)")
    elif suffix in (".png", ".jpg", ".jpeg", ".webp"):
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("Immagine troppo grande: massimo 40 megapixel")
            save_image(image, filename)
        source["warnings"].append("Per interpretare questa immagine seleziona un modello vision")
    else:
        raise ValueError("Formati accettati: PDF, MD, TXT, PNG, JPG, WEBP")
    return source
