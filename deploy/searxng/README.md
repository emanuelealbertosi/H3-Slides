# Ricerca locale opzionale

H3-slides comunica con SearXNG tramite HTTP: nessuna dipendenza da una
distribuzione WSL personale o percorsi di un particolare computer.
Locale non significa offline: SearXNG consulta motori online.

## Un'istanza già disponibile

Nell'app: Ricerca web → Configura SearXNG su questo computer.
Salvare l'indirizzo locale, per esempio http://127.0.0.1:8080.
In SearXNG abilitare search.formats: [html, json].
L'app non avvia né termina istanze esterne.

## Istanza indipendente

Serve Podman con supporto Compose, oppure un motore Docker/Compose già
installato. Podman è l'opzione open source; verificare le condizioni d'uso
della propria distribuzione Docker. Nessuna API di ricerca a pagamento
è configurata. Su Windows i container Linux richiedono virtualizzazione:
gli script non modificano BIOS, Hyper-V o componenti Windows.

1. Copiare .env.example in .env; sostituire il segreto con una stringa casuale.
   Generatore: python -c "import secrets; print(secrets.token_hex(32))"
2. Dalla radice del progetto: Avvia-Ricerca.bat.
   Con Docker: Avvia-Ricerca.bat -Engine docker.
3. Nell'app scegliere SearXNG e l'indirizzo locale indicato sopra.
4. Ferma-Ricerca.bat arresta solo questa istanza; la cache è conservata.

Il primo avvio scarica l'immagine ufficiale. Porta solo su loopback, nessun
avvio automatico, nessun mount dell'intero disco. Per una release riproducibile
impostare SEARXNG_IMAGE a un tag/digest ufficiale testato invece di latest.
Non pubblicare .env o dati locali.

## Senza container

Scegliere esplicitamente DuckDuckGo nell'app. Non serve altro software,
ma l'interfaccia HTML può imporre CAPTCHA o limiti. L'app non aggira i
blocchi e non cambia motore da sola. Se non è disponibile, usare allegati
o disattivare la ricerca.

Documentazione:
- https://docs.searxng.org/dev/search_api.html
- https://docs.searxng.org/admin/installation-docker.html
