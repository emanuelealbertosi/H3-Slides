# Installazione Windows x64

## Tre BAT

- **Avvia-H3-slides.bat**: installa se necessario e apre l'app.
- **Installa-H3-slides.bat**: installa/ripara i componenti senza avviare.
- **Ferma-H3-slides.bat**: chiude esclusivamente questa installazione e i suoi figli.

**Verifica-H3-slides.bat** controlla i componenti senza caricare modelli.
Estrarre sempre lo ZIP in una cartella locale scrivibile. Evitare Program Files,
cartelle sincronizzate in uso e percorsi di rete. Sono supportati percorsi con spazi.
Non servono Git, Python o Node preinstallati. Internet serve per scaricare
le dipendenze al primo avvio. Non e un pacchetto offline o un singolo EXE.
La distribuzione verificata e Windows x64; Linux, macOS e Windows ARM non hanno
un installer supportato in questa release.

## Modello e GPU

Non vengono inclusi/scaricati pesi GGUF. Al primo avvio scegliere il proprio
modello instruction compatibile con llama.cpp dal selettore dell'app.
Per leggere immagini serve anche un modello vision e il suo mmproj compatibile.
I pesi restano nella loro cartella: H3-Slides salva solo un collegamento locale.
Oppure selezionare API remota, endpoint compatibile, modello e chiave.
Le chiavi non sono salvate: reinserirle dopo il refresh. Le fonti vengono
inviate al provider solo dopo la conferma prevista nell'interfaccia.

Auto sceglie CUDA 12.4 su NVIDIA e CPU negli altri casi. Se il binario CUDA
non si avvia, auto prova CPU. Un GGUF troppo grande o incompatibile puo comunque
fallire: ridurre contesto/layer GPU in Admin o scegliere un altro modello.
Il driver NVIDIA rimane responsabilita dell'utente. Se Windows segnala una DLL
MSVC di sistema mancante, installare il Visual C++ Redistributable x64 ufficiale
Microsoft e riprovare; non scaricare singole DLL da siti sconosciuti.
Le librerie CUDA della distribuzione llama.cpp sono scaricate dall'installer.

Installazione alternativa da terminale, nella cartella estratta:

~~~powershell
.\Installa-H3-slides.bat -LlamaBackend cpu
.\Installa-H3-slides.bat -LlamaBackend skip
~~~

Il primo forza CPU; il secondo prepara l'app per API remote senza scaricare
llama.cpp. Su installazioni esistenti il motore funzionante viene preservato.
Python privato non modifica registro o PATH dell'utente. Opzione avanzata:
passare -PythonExecutable "D:\Python312\python.exe" per usare un Python 3.12 x64 esistente.

## Errori e aggiornamenti

I log d'installazione sono in **logs/setup-AAAAmmgg-HHMMSS.log**.
Errori di rete, checksum, antivirus, driver e dipendenze vengono segnalati:
correggere la causa e rilanciare Installa. Non disabilitare antivirus o TLS.
Un'installazione fallita non viene marcata come completata.
Node/llama sostituiti vengono conservati in runtime/*-backup-*.
L'installer rifiuta di modificare dipendenze mentre questa app e attiva.

Prima di aggiornare: Ferma, fare una copia di **data**, **outputs** e
**config.local.json**, poi estrarre il nuovo sorgente nella stessa cartella
e rilanciare Installa. Lo ZIP non contiene queste cartelle/dati personali.
Non spostare una .venv gia creata fra cartelle: i percorsi del Python privato
sono assoluti. Per cambiare cartella estrarre una nuova installazione, installare,
poi trasferire solo dati/configurazione a servizi fermi.

Se una porta e occupata non viene ucciso il programma che la usa.
Copiare config.example.json in config.local.json e scegliere altre porte per
port e llama_port. Configurare sempre host su 127.0.0.1.
Questa app non include autenticazione: non esporla su Internet o su una LAN
non fidata. Vedere [SECURITY.md](SECURITY.md).

## Distribuzione e licenze

Lo ZIP contiene sorgenti, script e lock; i runtime vengono scaricati
direttamente dalle distribuzioni degli strumenti. Non contiene modelli,
chiavi, documenti, librerie personali, cache o installazioni di altre app.
La somma SHA256 dello ZIP e allegata alla stessa release.
Gli strumenti di terze parti restano soggetti alle rispettive licenze:
Python, uv, Node.js, llama.cpp, Slidev, Chromium/Playwright, Manim e Manim Slides.
Le relative licenze sono nelle distribuzioni scaricate. Non viene concessa
automaticamente una nuova licenza ai documenti importati o ai modelli scelti.
La ricerca SearXNG e opzionale e separata: richiede un motore container gia pronto;
non e necessaria per generare presentazioni o esportarle.
