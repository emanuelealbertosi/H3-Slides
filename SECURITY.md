# Sicurezza e limiti della release

H3-Slides e un'applicazione personale **locale**, non un servizio multiutente.
Tenere il bind su 127.0.0.1; non pubblicare porte su Internet/LAN senza
autenticazione e isolamento aggiunti esternamente. Admin non e un login.
Importare soltanto documenti di origine fidata e mantenere sistema/runtime aggiornati.

## Dipendenze: verifica del 3 settembre 2026

L'audit npm della prima release segnala ancora vulnerabilita di disponibilita
(DoS) in **image-size**, anche ereditate da PPTXGenJS e Slidev.
Le versioni pubblicate di image-size fino alla 2.0.2 risultano interessate:
[ICNS](https://github.com/advisories/GHSA-w3rx-r6r6-pgpr),
[HEIF/JXL](https://github.com/advisories/GHSA-5p2g-fcmc-qvqq).
Non viene applicato il downgrade incompatibile di PPTXGenJS/Slidev proposto
da npm audit fix --force.

Nell'export H3-Slides i parser non PNG/JPEG sono disabilitati e le immagini
importate sono normalizzate da Pillow. Questo riduce la superficie esposta
nel nostro export, ma **non elimina le segnalazioni upstream** ne garantisce
la sicurezza di tutti i comandi/funzionalita degli strumenti distribuiti.
Non aprire deck Slidev di terzi non fidati tramite questa installazione.
DOMPurify viene vincolato alla versione 3.4.14 per correggere le segnalazioni
della versione transitiva precedente; le dipendenze vanno rivalutate prima
di distribuzioni pubbliche o usi multiutente.

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
~~~

Verifica-H3-slides.bat e i test verificano funzionamento, non sono uno scanner
di sicurezza. Non disabilitare TLS, antivirus o controlli dei download.
