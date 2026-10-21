# TODO

## Aufträge von Marc

- 2026-10-15 offen: SnappyMail-Signaturschlüssel bleibt provisorisch. Gemessen am 15.10.2026: das Projekt veröffentlicht in `SECURITY.md` den Fingerabdruck `445D 2651 24E6 0726 71E6 4D07 33F8 68A7 E35E 8277` für verschlüsselte Meldungen an `security@snappymail.eu`, verifiziert auf keys.openpgp.org. Der Schlüssel, der die Tarballs signiert, `1016 E470 7914 5542 F8BA 1335 4820 8BA1 3290 F3EB`, steht dort nicht (404 über Adresse und Fingerabdruck), nicht im README, nicht im Release-Text, snappymail.eu sagt nichts dazu, und er trägt keine Beglaubigung durch den Kontaktschlüssel: genau eine Signatur, die eigene. Nachprüfen, sobald das Projekt einen Release-Fingerabdruck nennt, den Schlüssel auf einem verifizierenden Keyserver veröffentlicht oder ihn mit dem Kontaktschlüssel beglaubigt; dann den Vermerk in `rainloop/snappymail-signing-key.asc` durch die bestätigende Quelle ersetzen.
- 2026-09-09 offen: `postfix:1` und `postfix:1.11.0` auf Docker Hub neu bauen (Marc, `Trigger`-Knopf). Beide Images entstanden Minuten vor dem Push der PID-Reparatur und enthalten sie nicht; ohne den Neubau bleibt postfix beim nächsten Containerwechsel wieder stehen.
- 2026-09-09 offen: zwei Advisories `smarty/smarty` im PostfixAdmin-Image, CVE-2026-62992 und CVE-2026-62993, beide medium, aus dem Alpine-Paket. Lagen bisher unter dem entfernten `--no-security-blocking`.
- 2026-09-05 offen: `mwaeckerlin/postgrey` in der Produktions-YAML ohne Tag, zieht `latest` vom 19.07., bei Marc läuft der Bau vom 13.07. Das Repository ist archiviert, ein `:1` kann nicht entstehen; nur der Digest nagelt es fest.
- 2026-09-05 offen: Entscheidung zur Reproduzierbarkeit. Die Versions-Images werden gegen das jeweils aktuelle Alpine gebaut und unterscheiden sich damit vom Stand, der bei Marc läuft. Ein reproduzierbares Versions-Image braucht gepinnte Basisimages und Paketversionen.
- 2026-09-05 offen: postgrey ist auf GitHub archiviert, die Tags 1.0.0 bis 3.2.0 liegen nur lokal. Push erst nach dem Entarchivieren.
- 2026-09-05 offen: postfixadmin startet in der Produktion etwa stündlich neu, Ursache unbekannt. Erst auf Marcs Wort untersuchen.
