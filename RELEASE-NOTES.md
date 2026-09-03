# H3-Slides 0.2.0 — prima release standalone Windows

## Installazione

Estrarre H3-Slides-windows-x64-0.2.0.zip e aprire **Avvia-H3-slides.bat**.
Il primo avvio scarica e configura automaticamente Python, Node, Slidev,
Manim/Manim Slides, Chromium e llama.cpp. Poi scegliere un GGUF dal disco,
oppure un'API remota. Non sono inclusi modelli, documenti o credenziali.

Sono presenti BAT dedicati per installare/riparare, verificare e arrestare.
L'installer mantiene Python e runtime nella propria cartella, con lock delle
dipendenze, checksum dei download principali e log. CUDA 12.4 viene scelto
su NVIDIA; sugli altri PC e disponibile CPU. Non vengono installati driver.
Nessuna dipendenza da H3-Comics, ComfyUI o LM Studio in esecuzione.

## Presentazioni

- Argomento libero oppure PDF/Markdown/immagini; ricerca web facoltativa.
- Generazione incrementale, editor dei contenuti e riordino.
- Composer adattivo con 12 famiglie di layout, temi, box e contrasto automatico.
- Diagrammi deterministici e animazioni Manim; anteprima Slidev.
- Export PPTX modificabile, PDF, Slidev e Manim.
- Modello locale integrato o endpoint remoto compatibile.

## Verifiche di rilascio

Installazione in una cartella nuova con spazi, usando il Python privato
3.12.14 scaricato dall'installer: **99 test Python e 11 JavaScript superati**,
compresi export reali PPTX/PDF/Slidev/Manim e controlli browser.
Provati avvio senza GGUF, doppio avvio, arresto e isolamento rispetto a un'altra
copia attiva; l'installer rifiuta di aggiornare dipendenze mentre l'app e avviata.
Verificata inferenza reale CPU e CUDA/NVIDIA con un piccolo GGUF gia presente,
senza scaricare pesi. Provato anche il bootstrap automatico dal BAT di avvio.
Questa prova non equivale a test su ogni versione di Windows, driver e GPU.

## Limiti noti

Release iniziale per uso personale locale, **senza autenticazione**.
Non esporre la porta su Internet. La prima installazione richiede Internet;
non e un EXE offline. SearXNG e facoltativo e richiede un motore container a parte.
llama.cpp/modelli richiedono hardware e driver compatibili. L'app non addestra
modelli e non esegue liberamente codice prodotto dall'LLM.

Restano **4 segnalazioni npm di livello alto**, ereditate dalla libreria
image-size usata dall'ecosistema PPTX/Slidev. I parser non necessari sono
disabilitati nel nostro export, ma non si dichiara eliminato il rischio
upstream. DOMPurify e stato aggiornato tramite override.
Dettagli e mitigazioni: [SECURITY.md](https://github.com/emanuelealbertosi/H3-Slides/blob/v0.2.0/SECURITY.md).
