# H3-slides

Studio locale per trasformare PDF, Markdown e immagini in presentazioni modificabili.
Progetto indipendente da H3-Comics: non ne modifica file, processi o configurazioni.

## Avvio

1. Scaricare lo ZIP **H3-Slides-windows-x64** dalle [release GitHub](https://github.com/emanuelealbertosi/H3-Slides/releases) e **estrarlo tutto**
   in una cartella scrivibile, per esempio F:\H3-Slides. Non eseguire i BAT dentro lo ZIP.
2. Aprire **Avvia-H3-slides.bat**. Al primo avvio esegue automaticamente
   l'installazione, poi apre http://127.0.0.1:8766. Per installare senza avviare
   usare **Installa-H3-slides.bat**.
3. Scegliere un modello GGUF dal disco, oppure configurare un'API remota.

L'installer Windows x64 scarica un **Python 3.12 privato**, Node con npm,
Slidev, Manim/Manim Slides, Chromium e llama.cpp. Non richiede Python, Node,
Git o LM Studio preinstallati, non cambia PATH/registro di Windows e non
richiede normalmente privilegi amministrativi. Richiede Internet e diversi GB
liberi, oltre allo spazio e alla RAM/VRAM dei modelli. La prima installazione
puo richiedere diversi minuti; quelle successive riusano i componenti locali.
Runtime uv/llama.cpp sono fissati nel manifest con SHA256; Node e verificato
contro il file checksum ufficiale. Dipendenze Python/Node hanno versioni bloccate.

Con una GPU NVIDIA viene scelto llama.cpp CUDA 12.4; sugli altri PC viene
installato il motore CPU (piu lento). I driver GPU devono essere gia funzionanti:
l'app non li installa o modifica. Il supporto AMD/Intel e CPU, non accelerazione GPU.
Il controllo iniziale del binario non garantisce che ogni GGUF entri in memoria.
Per forzare una prima installazione CPU: **Installa-H3-slides.bat -LlamaBackend cpu**.
Per non scaricare il motore locale: **Installa-H3-slides.bat -LlamaBackend skip**.
Un motore locale esistente funzionante viene conservato; questi parametri non
sono un aggiornamento automatico di una distribuzione llama.cpp gia presente.
I **modelli, documenti, progetti e credenziali non sono inclusi** nello ZIP/Git.
L'uso di API remote puo avere costi secondo il proprio provider.

- Per chiudere: **Ferma-H3-slides.bat**. Arresta l'app e i processi figli gestiti
  (llama.cpp, Slidev e renderer). Non ferma ComfyUI, H3-Comics o LM Studio.
- Il launcher controlla porta e cartella per evitare copie duplicate o arrestare
  un'altra installazione. Avvii/installazioni simultanei nella stessa cartella sono bloccati.

Installazione e verifiche dettagliate: [INSTALLAZIONE.md](INSTALLAZIONE.md).

### Primo avvio e scelta del modello

Se il catalogo locale e vuoto, l'app apre **Configura il modello locale**:

1. Premere **Sfoglia file GGUF** e scegliere il modello sul disco, oppure
   incollare il percorso completo e premere **Usa questo file**.
2. Il file viene collegato senza copiarlo, scaricarlo o trasferirlo nel browser.
   La scelta resta in data/model_files.json, escluso da Git, ed e riutilizzata
   al prossimo avvio. Si puo aggiungere un altro file da **Scegli GGUF dal disco**.
3. Se si preferisce un provider remoto, scegliere **Uso un'API remota**.
   **Configura dopo** permette di usare l'editor senza caricare alcun modello.

La barra laterale separa **Crea**, **Progetti** e **Admin**. Progetti mostra
l'archivio locale e riapre una presentazione senza confondere il brief corrente.
Tutta la configurazione LLM e nella pagina **Admin**, accessibile dal menu o
dal percorso **/admin**: provider, modello, Vision, connessione e inferenza.
Passare da Crea ad Admin non ricarica la pagina e conserva il brief non salvato
e la chiave in memoria. Un vero ricaricamento richiede di reinserire la chiave
e confermare nuovamente il consenso. Admin e una pagina di impostazioni,
non un'area con autenticazione separata: non esporre l'app su reti non fidate.

Per un **Server API (LM Studio o provider remoto)**, in Admin inserire la **Base URL API**
e la chiave, solo se richiesta dal server. LM Studio gia avviato sullo stesso PC
accetta **http://localhost:1234** oppure **http://127.0.0.1:1234/v1**: per localhost
e IP privati, se l'indirizzo non contiene un percorso viene aggiunto /v1.
Un server su un altro PC richiede il suo IP privato e la porta configurata.
HTTP e consentito su loopback, IP LAN privati e Tailscale; usarlo solo con server
e reti fidate. I server pubblici richiedono HTTPS e il prefisso previsto dal
provider (per esempio /v1 oppure /api/v1). **Modello sul server**
legge automaticamente il catalogo GET /models; **Aggiorna modelli** lo rilegge.
La scelta viene ricordata per indirizzo del server, ma la chiave resta solo
in memoria e va reinserita dopo un ricaricamento. Il catalogo non invia prompt
o allegati e non genera contenuti. Scegliere un modello per chat e verificare
se supporta Vision. Se il server non espone il catalogo, usare **Alternativa:
ID manuale**. Errori di connessione o autenticazione non vengono nascosti.

**Inferenza API** permette di scegliere massimo token di output (128–131072),
temperatura, top-p e timeout per risposta (30–3600 secondi). Il default resta
3500 token, temperatura 0.35, top-p 0.95 e timeout 360 secondi. Con
**Lascia il limite di output al server** la richiesta omette max_tokens.
I valori validi si salvano automaticamente in questo browser per coppia
indirizzo/modello, anche per gli ID manuali. Non si trasferiscono su un altro PC.
Il limite effettivo dipende anche dal server e dal contesto disponibile:
aumentare l'output non aumenta il contesto. Contesto, GPU e caricamento in
LM Studio si configurano in LM Studio; H3-Slides non avvia o arresta quel server.
I profili **llama.cpp integrato** mantengono caricamento e inferenza completi,
si salvano con **Salva profilo** in data/llm_profiles.json e si applicano alle
generazioni successive. Le impostazioni API sono incluse nella singola richiesta;
modificarle non cambia i job gia avviati.

Il selettore nativo si apre sul PC che esegue l'app (Windows); da una sessione
remota usare il percorso sul server. La selezione annullata non cambia nulla.
Il controllo rifiuta file mancanti, intestazioni GGUF non valide, proiettori
mmproj scelti come modello principale e modelli suddivisi privi di una parte.
Per un GGUF suddiviso scegliere 00001-of-xxxxx e tenere tutte le parti insieme.
Un'intestazione valida non garantisce integrita completa, compatibilita con
llama.cpp, qualita instruction/vision o memoria GPU sufficiente.
Se il file viene spostato o il disco scollegato, l'app avvisa e richiede una
nuova scelta; non passa silenziosamente a un modello diverso.

L'assenza di llama-server.exe viene segnalata separatamente: scegliere i pesi
non installa il motore. Rilanciare l'installer senza -LlamaBackend skip, oppure
usare un'API remota. Nessun download di modelli automatico.

### Controllo e riparazione dell'installazione

- **Verifica-H3-slides.bat** verifica Python, librerie, Node, Slidev, PPTX e
  l'avvio headless di Chromium. Non carica GGUF e non modifica i progetti.
- L'installer prepara Python 3.12 x64, controlla i conflitti Python e ripara
  Node incompleto (anche quando manca npm). Prima di sostituirlo conserva il
  vecchio runtime in una cartella node-backup sotto runtime.
- Facoltativamente passare -PythonExecutable seguito dal percorso di un proprio
  Python 3.12 x64; altrimenti viene usato il Python privato della cartella runtime.
- L'installer non aggiorna dipendenze mentre l'app di quella cartella e attiva:
  usare prima **Ferma-H3-slides.bat**. Gli altri progetti non sono arrestati.
- Lo stato finale distingue componenti applicativi mancanti (errore) da
  modello/motore locale da configurare (avviso; la modalita remota resta possibile).
- All'avvio viene ripetuto un controllo rapido delle dipendenze fondamentali:
  eventuali errori indicano come riparare l'installazione prima di avviare un server.

## Flusso di lavoro

1. Scrivi un argomento o istruzioni, scegli numero slide e tema. Le fonti sono facoltative.
2. Scegli **llama.cpp integrato** e un GGUF, oppure **API remota compatibile OpenAI**.
3. Genera: la scaletta compare prima, poi ogni slide viene salvata e mostrata.
4. Modifica testo, note, immagine, layout e animazione dal pulsante della slide.
   Le modifiche sono protette da revisioni: una risposta LLM in ritardo non le sovrascrive.
5. Riordina trascinando le slide o con le frecce. Pausa e annullamento sono nel pannello job.
6. Esporta il risultato o apri Slidev live. Gli export sono snapshot: le modifiche
   successive richiedono una nuova esportazione.

Il prompt modificato e salvato durante il lavoro viene letto dalle slide successive.
Un nuovo clic su Genera completa le slide ancora mancanti. **Rigenera** rifà una
singola slide; **Rigenera tutte le slide** riscrive in sequenza tutti i contenuti
di una presentazione terminata, dopo conferma. La rigenerazione completa conserva
scaletta, ordine, numero di slide, brief, fonti, tema e impostazioni, ma sostituisce
testi, immagini scelte e diagrammi delle slide. Per un progetto interamente nuovo
usa Nuovo progetto.

Se **Diagrammi Manim** è attivo, durante Genera o Rigenera ogni slide di contenuto
riceve un diagramma pertinente; soltanto la copertina viene esclusa. L'opzione è
vincolante anche se il modello restituisce diagram.kind=none. **Crea diagrammi
mancanti** completa un progetto esistente senza rigenerarne i testi; **Progetta
Manim** sulla singola scheda forza o riprogetta soltanto quella scena.

### Solo argomento, senza documenti

Puoi scrivere semplicemente «La rivoluzione francese» e premere Genera.
Senza allegati e con Ricerca web disattivata il modello usa la propria conoscenza generale: non naviga sul web,
non consulta bibliografie e non garantisce informazioni aggiornate. Il percorso
salta indicizzazione e RAG; l'origine è indicata nei log e nelle note delle slide.
Non vengono create citazioni a file inesistenti. Testi, diagrammi, modifica,
rigenerazione ed export restano disponibili con modello locale o API remota.

### Ricerca web facoltativa e gratuita

Attivare **Ricerca web**, scrivere una query dedicata, scegliere 3–5 fonti e
confermare esplicitamente l'invio. Al motore viene inviata solo la query:
non il documento, il prompt completo o le credenziali del modello.
Questa conferma è distinta da quella per inviare fonti a un LLM remoto.
La ricerca funziona anche con il modello locale, senza API di ricerca a pagamento.

- **SearXNG locale** (predefinito): indicare l'indirizzo del proprio servizio.
  Il JSON deve essere abilitato. Configurazione e launcher opzionali indipendenti
  dal PC sono in [deploy/searxng](deploy/searxng/README.md).
- **DuckDuckGo HTML**: non richiede un'app aggiuntiva, ma può bloccare richieste
  automatiche. CAPTCHA, rifiuti e limiti vengono segnalati; non sono aggirati.
  Non c'è passaggio automatico a un altro provider, gratuito o a pagamento.

L'app legge pagine pubbliche rispettando robots.txt, scarta URL locali/privati,
non esegue script delle pagine e usa gli estratti come dati non attendibili,
non come istruzioni. Limiti di tempo, redirect e dimensione proteggono il recupero.
Le fonti effettivamente lette, gli URL e la data di consultazione restano nel
progetto e nelle note delle slide; il testo integrale della cache resta locale.
La cache vale un'ora per progetto e query; **Aggiorna ricerca** la esclude.
Se il motore fallisce o non si leggono pagine utilizzabili il job si ferma:
non presenta conoscenza interna del modello come ricerca effettuata.

La ricerca precede il caricamento del LLM e appare nei log del job. Non aggiorna
da sola slide già pronte: usare Rigenera per una slide oppure Rigenera tutte.
I risultati vanno verificati dall'utente; il recupero di fonti non elimina
allucinazioni, errori o incompletezza. Le immagini del web non sono importate
automaticamente: questa funzione riguarda solo fonti testuali.

SearXNG non viene avviato con H3-slides. Il servizio container opzionale richiede
un motore compatibile (per esempio Podman con Compose) e, su Windows, virtualizzazione
funzionante. L'app non cambia impostazioni di sistema e non dipende da una
distribuzione WSL personale o da percorsi di altre applicazioni.

Gli allegati non devono essere libri: puoi usare report PDF, appunti Markdown,
schermate o foto leggibili. Per un PDF generico scegli **Documento intero**:
non richiede indice né numerazione stampata e legge tutte le pagine.
Per estrarre una sezione specifica scegli **Cerca le pagine pertinenti dal prompt**.
Le immagini richiedono un modello vision; PDF protetti vanno sbloccati dall'utente
e scansioni lunghe senza testo richiedono OCR (oltre 60 pagine).

## Admin · Modelli

Il pulsante in alto apre i profili dei GGUF locali. Per ogni modello si salvano:

- caricamento: contesto, layer GPU (-1 massimo offload, 0 CPU), thread, batch,
  micro-batch, Flash Attention, cache K/V, mmap e layer MoE da tenere su CPU;
- inferenza: temperatura, top-p, top-k, min-p, penalità ripetizione,
  token massimi, seed e thinking.

**Salva profilo** non interrompe né riavvia un processo. **Carica / riavvia**
applica il profilo immediatamente; altrimenti sarà usato dalla prossima generazione.
Le modifiche al runtime sono bloccate mentre un job è attivo. I profili persistono
in data/llm_profiles.json; le API key remote non vengono salvate lì.
I default rimangono Gemma 12B Q6, massimo offload GPU, contesto 16K e thinking
disattivato. La compatibilità effettiva di cache, contesto e offload dipende dal
modello e dalla VRAM disponibile. Admin è un pannello locale, non un sistema
di autenticazione o gestione utenti.

## Editor e materiale visivo

Composer adattivo con 12 famiglie: copertina, editoriale asimmetrico, confronto,
griglia, passaggi, cronologia, idea/approfondimento, citazione, immagine a
sinistra/destra/panoramica e paragrafi a fasce. Il planner propone la composizione
già nella scaletta. Il renderer misura il testo e prova disposizioni alternative
e spaziature più compatte senza cancellare parole o cambiare i font manuali.
La scelta automatica varia in modo deterministico, stabile al ricaricamento.
La tendina su ogni slide imposta la composizione preferita; l'etichetta indica
quella effettiva dopo il controllo dello spazio. **Ricomponi** salva una nuova
variante senza chiamare l'LLM. **Dividi** distribuisce paragrafi/punti su più
slide conservando letteralmente testo, citazioni, fonti, immagini e note;
richiede conferma e rispetta il limite totale di 30 slide.
Funziona anche sui progetti precedenti, senza rigenerare i contenuti.
Sfondo, accento e sei font configurabili. Anteprima immediata,
salvataggio nel progetto ed esportazioni coerenti (non identiche al pixel).
Nel **Creatore di temi** sono disponibili Prisma, Aurora, Notte, Editoriale e Laboratorio:
combinano sfondo, accento, font, box colorati, bordi e angoli. Personalizzare
colori del testo/titoli, riempimenti dei quattro tipi di box, bordi, raggio e
dimensioni. Il testo automatico sceglie un colore con contrasto almeno 4,5:1;
le combinazioni manuali insufficienti producono un avviso, senza cambiare
silenziosamente la scelta. Ogni box calcola il contrasto sul proprio sfondo.
Dimensione 0 significa automatica; aumentarla può far sforare testi lunghi.
**Salva tema** crea un preset personale riutilizzabile (stesso nome: aggiornamento).
**Salva brief** conserva lo stile del progetto, anche se già prodotto:
non occorre rigenerare i testi. Esportare di nuovo per aggiornare i file.
I temi personali sono in data/themes.json; i preset distribuiti sono in
static/theme-presets.json. Non contengono codice, URL remoti o percorsi del PC.
Accenni / approfondito / completo guidano i prossimi testi generati senza
cancellare quelli già presenti. Doppio clic sui testi per modificarli nella
scheda, oppure Modifica per note, fonti, immagini e diagrammi.

Le immagini delle fonti sono facoltative anche nei progetti esistenti: disattivarle
le nasconde dagli export, non elimina gli originali. Con **Diagrammi Manim**,
il modello scelto in Admin esegue un secondo passaggio dedicato e restituisce
solo una scena dichiarativa validata: oggetti, coordinate, relazioni, fasi e dati.
Il codice Python che compila e renderizza la scena e distribuito con l'app e
non proviene mai dal modello.

Sono disponibili blocchi, decisioni, documenti, database, griglie di valori,
grafici a barre e lineari, diagrammi di Venn, Gantt, timeline, alberi e reti.
Venn/Gantt/timeline/albero/rete sono oggetti composti nativi: il modello ne
specifica insiemi, attività e tempi, eventi, gerarchie o archi; il compilatore
Manim dell'app costruisce forme e relazioni. Nei flowchart inizio/fine, decisioni
e archivi usano forme semantiche e un flusso collegato di soli rettangoli viene
rifiutato. Se il prompt nomina esplicitamente Gantt, Venn, timeline, albero,
rete o diagramma di flusso, una famiglia diversa non supera la validazione.
I collegamenti sono instradati deterministicamente attorno agli altri oggetti;
testi, sovrapposizioni, dimensione minima e limiti del canvas vengono verificati
prima del salvataggio.
Piccoli sconfinamenti e sovrapposizioni geometriche prodotti dal modello vengono
corretti deterministicamente tenendo conto dell'intera scena. Se un diagramma
automatico resta non valido dopo le correzioni, la slide viene salvata senza
diagramma e il resto della presentazione prosegue; il log mantiene il motivo.
**Crea diagrammi mancanti** riprova in blocco senza toccare i testi e continua
anche se una singola scena non riesce; **Progetta Manim** riprova la sola slide.
Gli errori comuni dei modelli remoti (numeri serializzati come testo, etichette
troppo lunghe e piccoli difetti geometrici) vengono corretti prima del render.
Se i tre tentativi LLM restano inutilizzabili, l'app costruisce e verifica una
scena Manim conservativa usando titolo, box ed eventuali etichette già approvate,
invece di lasciare silenziosamente la slide senza diagramma.
Il render 1800 × 1200 viene riusato nell'editor, nel PPTX, nel PDF e in Slidev;
l'export Manim anima progressivamente la stessa scena. Un diagramma attivo ha
priorità sulla figura della stessa slide.

**Progetta Manim** crea o riprogetta la scena usando l'LLM locale o remoto
selezionato. **Renderizza Manim** ricostruisce invece un progetto già valido
senza interrogare il modello, per esempio dopo un cambio di tema. Nell'editor
si possono modificare titolo, conclusione, oggetti, coordinate, dimensioni,
dati e relazioni. I vecchi diagrammi flow/cycle/comparison restano leggibili
e possono essere convertiti esplicitamente; non vengono più mostrati come
segnaposto SVG.

**Riprogetta tutti i diagrammi** interroga nuovamente il modello per ogni slide
di contenuto senza riscriverne i testi. Serve, per esempio, per sostituire in
blocco vecchi fallback con le famiglie semantiche disponibili. Il modello non
scrive né esegue Python libero: produce una DSL dichiarativa validata. Questa
scelta mantiene l'app distribuibile senza dare a una risposta LLM accesso a
file, rete o processi del computer.

## Runtime distribuiti dall'installer

- Node.js 24.19.0 dedicato in runtime/node.
- Slidev 52.19.1 e tema default in node_modules.
- Chromium per gli export PDF in runtime/browsers.
- Python 3.12.14 privato in runtime/python e dipendenze isolate in .venv.
- Manim Community 0.21.0; Manim Slides 5.6.0, compreso il player Qt.
- llama.cpp build b10778, binari e DLL in runtime/llama.
  Le installazioni precedenti conservano il loro motore funzionante.

llama.cpp viene avviato **dall'app**, in un processo dedicato su 127.0.0.1:8096,
solo quando serve generare. Non richiede LM Studio in esecuzione.
Il catalogo predefinito legge i GGUF nella cartella locale models.
Percorsi aggiuntivi si impostano in model_roots di config.local.json,
ignorato da Git: possono puntare a pesi già presenti senza duplicarli.
Nessun percorso personale è necessario nel codice o nella configurazione esempio.
I file mmproj accanto al GGUF abilitano i modelli vision.

Per le presentazioni usare un modello instruction/vision compatibile con il
formato chat e JSON; un modello base come GPT-2 non è un planner adeguato.
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
| PPTX modificabile | Testi e immagini nativi PowerPoint; diagrammi Manim come render ad alta risoluzione; note e fonti nelle note relatore |
| PDF | Rendering statico delle slide dell'editor, con verifica dei principali overflow |
| Slidev | Sorgenti Markdown e immagini nello ZIP; anteprima live sulla porta 3031 |
| Manim | MP4 e presentazione HTML con pause; oggetti e relazioni della scena appaiono per fasi |

Il PPTX non è una serie di screenshot di Slidev. I motori PPTX, web e Manim
usano lo stesso progetto strutturato, ma il loro layout non è identico al pixel.
Le animazioni non diventano animazioni native PowerPoint e il PDF è statico.
L'HTML Manim incorpora i video; il framework RevealJS può richiedere Internet.

Il renderer usa testo, immagini e scene dichiarative e non richiede LaTeX.
Grafici specialistici, formule LaTeX e codice Manim libero restano fuori dallo
schema. L'LLM non può eseguire Python o JavaScript arbitrario sul computer.

Importazione: PDF completi fino a 1.500 pagine, 250 MB/file e 12 milioni di
caratteri; Markdown fino a 240.000 caratteri; PNG/JPG/WEBP fino a 40 megapixel.

### Ricerca delle fonti (RAG strutturale locale)

È possibile caricare un libro intero e scrivere, per esempio, «20 slide della
lezione 1 dell'UDA 1». L'app indicizza tutte le pagine, trova l'indice, chiede
al modello di individuare la sezione e verifica i confini sui titoli reali.
I numeri stampati sono distinti dalle pagine fisiche del PDF: l'offset non è
preimpostato. La selezione, la motivazione e le pagine compaiono nelle fonti
e nei log prima della produzione delle slide e restano salvate nel progetto.
Solo le pagine selezionate vengono lette per la generazione e rasterizzate;
le figure raster native abbastanza grandi sono disponibili separatamente.
Il file originale resta integro sul PC. La selezione viene ricalcolata quando
cambia il brief.

Per ogni slide un recupero lessicale BM25 seleziona anche i passaggi originali
più pertinenti all'interno della sezione, con i loro riferimenti di pagina.
Questo è retrieval strutturale e lessicale, non ricerca semantica con embeddings:
per un libro lungo serve un indice testuale e una numerazione verificabile.
Se la sezione è ambigua l'app si ferma senza inventare intervalli. Per un PDF
testuale breve senza indice usa una mappa sintetica delle pagine. Un libro
scansionato richiede OCR preventivo; documenti scansionati brevi (fino a 60
pagine) e immagini possono essere letti tramite un modello vision.
Le figure vettoriali non sono estratte separatamente. La sintesi a blocchi
può perdere dettagli: la revisione rimane necessaria per materiali accurati.

Una generazione alla volta, massimo 30 slide. Accenni genera fino a 3 punti
essenziali; Approfondito e Completo scelgono da 1 a 4 paragrafi in box.
Budget complessivo rispettivamente 1300/1600 caratteri e massimo 650/800 per
paragrafo. Con immagini/diagrammi diventano 740/960 complessivi e 370/480 per
paragrafo. Più box significa distribuire il budget, non moltiplicare il testo.
I testi importanti rimangono sulla slide, non soltanto nelle note.
Titoli in grassetto; box differenziati per spiegazione, esempio, concetto chiave
e citazione. Un brano citato deve corrispondere a un passaggio originale
recuperato da un allegato: fonte e pagina vengono ricavate dal passaggio.
Le fonti web non autorizzano la copia indiscriminata di testi esterni.
Editor dei box con titolo, paragrafo, tipo/colore e fonte; doppio clic sui testi
per la modifica diretta. Fino a 4 box manuali. PPTX conserva forme e testi
modificabili; PDF/Slidev condividono il layout; Manim mostra i box in sequenza.
Gli export PPTX/PDF/Slidev bloccano lo sforamento dopo il tentativo di ricomposizione.
PDF e Slidev usano lo stesso HTML misurato; PPTX usa quelle posizioni per testi,
riquadri e immagini. I diagrammi Manim rimangono modificabili nella struttura
dentro H3-Slides e vengono inseriti negli export statici come render PNG.
Il formato rimane 16:9: non sono pagine PDF di altezza variabile come le schede Gamma.
Le metriche tipografiche e le ombre di PowerPoint possono differire leggermente.
Manim video usa gli stessi oggetti della scena e li presenta secondo le fasi
definite, invece di ricostruire un diagramma semplificato separato.
La scaletta pianifica anche il numero di paragrafi. Il budget viene diviso per
paragrafo e accompagnato da indicazioni in parole, adatte anche a modelli piccoli.
La generazione controlla lunghezza e conclusione dei paragrafi e prova fino a due
correzioni con limiti più stretti se il modello non rispetta il formato. Come ultima misura adatta
solo spiegazioni generate a frasi complete, mantenendo la versione estesa
nelle note e segnalando l'adattamento nel log. Le citazioni non vengono tagliate.
Durante **Rigenera tutte**, se una singola risposta resta fuori schema dopo
i tentativi di correzione, la versione precedente di quella slide viene
conservata e il job prosegue con le successive. Il log indica campo e motivo
della mancata validazione, senza salvare il prompt o la risposta completa.
Le slide precedenti restano intatte: per ottenere paragrafi nuovi scegliere
Approfondito/Completo, salvare il brief e rigenerare la singola slide.
Editor a campi e riordino, non ancora un canvas PowerPoint libero.
Un job interrotto da un riavvio mantiene le slide pronte, ma non riparte da solo:
Genera rilegge le fonti e completa quelle mancanti. Le API key remote non sono
salvate né nei progetti né nelle preferenze del browser: reinserirle dopo il refresh.
In modalità remota è richiesta la conferma esplicita dell'invio delle fonti.

## Dati e log

- data/projects.sqlite3: progetti, slide, revisioni, fonti ed eventi.
- data/assets: PDF originali, indici testuali locali, figure e pagine selezionate.
- data/slidev: copie derivate per Slidev live, sincronizzate dall'editor.
- data/search_settings.json: indirizzo del proprio SearXNG, solo locale.
- data/themes.json: temi personali; le copie applicate sono anche nei progetti.
- data/model_files.json: collegamenti ai GGUF scelti sul disco e ultima scelta.
- outputs: esportazioni versionate e snapshot del progetto.
- logs/app.log: servizio; logs/llama.log: motore locale; logs/slidev.log: vista live.

Le modifiche vanno fatte nell'editor H3-slides. Le copie Slidev live sono derivate
e possono essere sovrascritte alla sincronizzazione; gli ZIP esportati sono indipendenti.
Il servizio è solo locale: Tailscale non è stato configurato per questo nuovo progetto.

## Verifica e sviluppo

Eseguire dalla cartella del progetto:

    .venv\Scripts\python.exe -m pytest tests -q
    runtime\node\node.exe --test tests/export.test.mjs tests/composer.test.mjs tests/dependency-security.test.mjs tests/remote-models.test.mjs
    runtime\node\node.exe scripts/dependency-check.mjs
    .venv\Scripts\python.exe tests/smoke_llama.py --model "D:\Modelli\piccolo-modello.gguf"

I test della pipeline usano un LLM simulato controllato e verificano salvataggio
incrementale, modifiche durante la generazione, annullamento, protezione dei percorsi,
API, browser e veri export PPTX/PDF/Slidev/Manim. Il test smoke separato carica un
piccolo GGUF già sul PC in CPU: prova l'integrazione llama.cpp, non la qualità
editoriale del modello instruction/vision.

Per provare quattro slide con un proprio GGUF instruction già installato:

    .venv\Scripts\python.exe tests/smoke_composer_llama.py --model "D:\Modelli\modello.gguf"

Usa una libreria isolata sotto logs/composer-smoke-* e la porta 8097 (configurabile
con --port); non tocca i progetti né i profili personali, non scarica pesi,
genera PDF/PPTX di verifica e chiude il proprio processo llama.cpp alla fine.

Dipendenze applicative in requirements.txt, lock Python in requirements.lock,
lock Node in package-lock.json. Runtime e dati non vanno pubblicati su Git.
La 0.2.1 include una distribuzione controllata di PPTXGenJS senza la dipendenza
inutilizzata image-size, applicata anche a Slidev. Codice originale, licenza,
provenienza e verifiche sono in [vendor](vendor/README.md). Non eliminare questa
cartella dallo ZIP: serve anche durante una installazione senza Git.
L'audit npm della 0.2.1 non segnala vulnerabilita note; vedere [SECURITY.md](SECURITY.md)
per ambito del controllo e limiti. Non e una certificazione di sicurezza totale.
L'installazione standalone attuale è per Windows x64: non è un singolo eseguibile,
non include modelli e non ha un installer Linux/macOS verificato.

## Documentazione degli strumenti

- https://sli.dev/guide/exporting.html
- https://docs.manim.community/en/stable/
- https://manim-slides.eertmans.be/latest/
- https://github.com/ggml-org/llama.cpp/tree/master/tools/server
