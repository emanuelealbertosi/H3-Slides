# H3-slides

Studio locale per trasformare PDF, Markdown e immagini in presentazioni modificabili.
Progetto indipendente da H3-Comics: non ne modifica file, processi o configurazioni.

## Avvio

- Aprire **Avvia-H3-slides.bat**, quindi http://127.0.0.1:8766.
- Per chiudere: **Ferma-H3-slides.bat**. Arresta l'app e i processi figli gestiti
  (llama.cpp, Slidev e renderer). Non ferma ComfyUI, H3-Comics o LM Studio.
- Il launcher controlla la porta per evitare copie duplicate.

## Flusso di lavoro

1. Inserisci titolo, istruzioni, numero slide e tema, poi aggiungi le fonti.
2. Scegli **llama.cpp integrato** e un GGUF, oppure **API remota compatibile OpenAI**.
3. Genera: la scaletta compare prima, poi ogni slide viene salvata e mostrata.
4. Modifica testo, note, immagine, layout e animazione dal pulsante della slide.
   Le modifiche sono protette da revisioni: una risposta LLM in ritardo non le sovrascrive.
5. Riordina trascinando le slide o con le frecce. Pausa e annullamento sono nel pannello job.
6. Esporta il risultato o apri Slidev live. Gli export sono snapshot: le modifiche
   successive richiedono una nuova esportazione.

Il prompt modificato e salvato durante il lavoro viene letto dalle slide successive.
Un nuovo clic su Genera completa le slide ancora mancanti; per rifare una slide pronta
usa Rigenera. Non elimina o sovrascrive automaticamente una presentazione già terminata.
Per un progetto interamente nuovo usa Nuovo progetto.

## Runtime installati

- Node.js 24.19.0 dedicato in runtime/node.
- Slidev 52.19.1 e tema default in node_modules.
- Chromium per gli export PDF in runtime/browsers.
- Python 3.12 e dipendenze isolate in .venv.
- Manim Community 0.21.0; Manim Slides 5.6.0, compreso il player Qt.
- llama.cpp build 10497, binari e DLL in runtime/llama.

llama.cpp viene avviato **dall'app**, in un processo dedicato su 127.0.0.1:8096,
solo quando serve generare. Non richiede LM Studio in esecuzione.
Il catalogo legge i GGUF già presenti in models
e nella cartella locale models: il primo è soltanto un percorso dei pesi,
non una dipendenza dal programma LM Studio. I grandi pesi non sono duplicati.
I file mmproj accanto al GGUF abilitano i modelli vision.

Per le presentazioni usare un modello instruction/vision, per esempio il Gemma
presente nel catalogo; i GPT-2 personali sono visibili ma non sono planner chat adeguati.
L'app non scarica/termina i modelli delle altre applicazioni per liberare VRAM.
Il modello di H3-slides viene scaricato dopo 5 minuti di inattività oppure con
Scarica LLM. La chiusura dell'app termina esclusivamente i suoi figli tramite
Windows Job Object, anche in caso di chiusura forzata.

Copia config.example.json in config.local.json per cambiare percorsi, porta,
context_size, gpu_layers (0 per CPU) e idle_unload_seconds.
Non cambiare il bind da localhost senza aggiungere autenticazione.

## Formati e limiti della prima versione

| Uscita | Contenuto |
|---|---|
| PPTX modificabile | Testi e immagini nativi PowerPoint; note e fonti nelle note relatore |
| PDF | Rendering statico delle slide dell'editor, con verifica dei principali overflow |
| Slidev | Sorgenti Markdown e immagini nello ZIP; anteprima live sulla porta 3031 |
| Manim | MP4 e presentazione HTML con pause; preset di apparizione progressiva |

Il PPTX non è una serie di screenshot di Slidev. I motori PPTX, web e Manim
usano lo stesso progetto strutturato, ma il loro layout non è identico al pixel.
Le animazioni non diventano animazioni native PowerPoint e il PDF è statico.
L'HTML Manim incorpora i video; il framework RevealJS può richiedere Internet.

Il preset Manim usa testo e immagini e non richiede LaTeX. La generazione libera
di scene Python, grafici specialistici, formule LaTeX e animazioni complesse
non è ancora implementata: richiede renderer/sandbox dedicati. L'LLM non può
eseguire Python/JavaScript arbitrario sul computer.

Importazione: PDF fino a 60 pagine e 30 MB/file; Markdown fino a 240.000 caratteri;
PNG/JPG/WEBP fino a 40 megapixel. Le pagine PDF vengono conservate come riferimenti
visivi e il testo viene estratto. Per immagini e pagine scansionate serve un modello
vision: non viene simulato un OCR con un modello solo testo.
I documenti lunghi vengono sintetizzati a blocchi: la sintesi può perdere dettagli,
quindi va sempre rivista per presentazioni dove la completezza è essenziale.
La prima versione non estrae separatamente ogni grafico/figura da PDF complessi.

Una generazione alla volta, massimo 30 slide, massimo 5 punti da 160 caratteri
per slide. Editor a campi e riordino, non ancora un canvas PowerPoint libero.
Un job interrotto da un riavvio mantiene le slide pronte, ma non riparte da solo:
Genera rilegge le fonti e completa quelle mancanti. Le API key remote non sono
salvate né nei progetti né nelle preferenze del browser: reinserirle dopo il refresh.
In modalità remota è richiesta la conferma esplicita dell'invio delle fonti.

## Dati e log

- data/projects.sqlite3: progetti, slide, revisioni, fonti ed eventi.
- data/assets: immagini e pagine PDF rasterizzate.
- data/slidev: copie derivate per Slidev live, sincronizzate dall'editor.
- outputs: esportazioni versionate e snapshot del progetto.
- logs/app.log: servizio; logs/llama.log: motore locale; logs/slidev.log: vista live.

Le modifiche vanno fatte nell'editor H3-slides. Le copie Slidev live sono derivate
e possono essere sovrascritte alla sincronizzazione; gli ZIP esportati sono indipendenti.
Il servizio è solo locale: Tailscale non è stato configurato per questo nuovo progetto.

## Verifica e sviluppo

Eseguire dalla cartella del progetto:

    .venv\Scripts\python.exe -m pytest -q
    runtime\node\node.exe --test tests/export.test.mjs
    .venv\Scripts\python.exe tests/smoke_llama.py

I test della pipeline usano un LLM simulato controllato e verificano salvataggio
incrementale, modifiche durante la generazione, annullamento, protezione dei percorsi,
API, browser e veri export PPTX/PDF/Slidev/Manim. Il test smoke separato carica un
piccolo GGUF già sul PC in CPU: prova l'integrazione llama.cpp, non la qualità
editoriale del modello instruction/vision.

Dipendenze applicative in requirements.txt, lock Python in requirements.lock,
lock Node in package-lock.json. Runtime e dati non vanno pubblicati su Git.

## Documentazione degli strumenti

- https://sli.dev/guide/exporting.html
- https://docs.manim.community/en/stable/
- https://manim-slides.eertmans.be/latest/
- https://github.com/ggml-org/llama.cpp/tree/master/tools/server
