# Sicurezza e limiti della release

H3-Slides e un'applicazione personale **locale**, non un servizio multiutente.
Tenere il bind su 127.0.0.1; non pubblicare porte su Internet/LAN senza
autenticazione e isolamento aggiunti esternamente. Admin non e un login.
Importare soltanto documenti di origine fidata e mantenere sistema/runtime aggiornati.

## Dipendenze: verifica del 3 settembre 2026

La versione **0.2.1** rimuove image-size dall'app e dall'intero albero npm.
L'audit dopo npm ci restituisce **0 vulnerabilita segnalate** (nessuna soppressione,
nessun downgrade). Questo risultato riguarda le dipendenze npm note alla data
del controllo, non certifica l'assenza di ogni possibile problema nell'app,
nei runtime o nelle dipendenze Python.

Le quattro segnalazioni della 0.2.0 derivavano da due vulnerabilita DoS della
stessa libreria, propagate a PPTXGenJS e Slidev:
[ICNS](https://github.com/advisories/GHSA-w3rx-r6r6-pgpr),
[HEIF/JXL](https://github.com/advisories/GHSA-5p2g-fcmc-qvqq).
L'export ora legge naturalWidth/naturalHeight dall'immagine gia decodificata da
Chromium. Non aggiunge un nuovo parser. Le immagini importate rimangono
normalizzate da Pillow; quelle non decodificabili vengono rifiutate.

La distribuzione locale PPTXGenJS 4.0.1-h3.1 elimina una dipendenza dichiarata
ma non utilizzata dal codice di PPTXGenJS 4.0.1. I file JavaScript e la licenza
originali sono conservati byte per byte, con provenienza e hash verificabili.
L'override npm vale anche per entrambi i consumatori Slidev: non viene lasciata
una copia vulnerabile annidata. Dettagli in [vendor/README.md](vendor/README.md).
Installazione, verifica e test controllano sia il lock sia i pacchetti realmente
risolti da H3-Slides e Slidev. La correzione non aggiorna la libreria image-size
per altri programmi e non pretende che gli avvisi upstream siano stati ritirati.

DOMPurify resta vincolato a 3.4.14. Rivalutare periodicamente tutte le dipendenze.
Non aprire deck Slidev di terzi non fidati tramite questa installazione.

I download uv/llama sono fissati per URL e SHA256 nel manifest. Node viene
verificato con i checksum ufficiali; npm usa le integrity del lock.
Il lock Python fissa le versioni ma non include hash di ogni wheel.
Questa e una release iniziale verificata funzionalmente, non un audit
di sicurezza completo o una garanzia di assenza di vulnerabilita.

## Dati e credenziali

Modelli, documenti, progetti, log e config.local.json sono esclusi dal repository
e dallo ZIP di release. Le chiavi API remote sono mantenute in memoria e non
vengono salvate nel progetto/browser. L'invio delle fonti al provider richiede
la conferma esplicita nell'interfaccia; la ricerca web ha un consenso separato.
Non pubblicare log/configurazioni personali quando si segnala un problema.

## Segnalazioni e controlli

Segnalare problemi al proprietario del repository senza allegare segreti.
Per ripetere l'audit delle dipendenze JavaScript:

~~~powershell
.\runtime\node\npm.cmd audit
.\runtime\node\node.exe scripts/dependency-check.mjs
~~~

Verifica-H3-slides.bat e i test verificano funzionamento, non sono uno scanner
di sicurezza. Non disabilitare TLS, antivirus o controlli dei download.
