# TODO

## Aufträge von Marc

- 2026-09-05 offen: Vergleich `1` gegen `1.10.0` gegen Produktion. Der Teil `1` gegen Produktion ist gemessen (dovecot und postfixadmin-proxy weichen ab, Ursache: ungepinnte Basisimages und Alpine-Pakete). Der Teil gegen `1.10.0` wartet auf die Tag-Builds; nach drei Stunden existiert auf Docker Hub kein einziges Versions-Tag.
- 2026-09-05 offen: Build-Rules auf Docker Hub vervollständigen (Marc). Fehlend: die Tag-Regel in allen Repositories, die Branch-Builds von `postfix` (1 und 2) und `postfixadmin`, sowie die php-fpm-Variante von `rainloop`.
- 2026-09-05 offen: Entscheidung zur Reproduzierbarkeit. `postfixadmin-proxy:1` trägt heute die PostfixAdmin-Anwendung aus dem aktuellen Alpine-Paket und damit einen anderen Anwendungsstand als die Produktion. Ein reproduzierbares Versions-Image braucht gepinnte Basisimages und gepinnte Paketversionen.
- 2026-09-05 offen: postgrey ist auf GitHub archiviert, die Tags 1.0.0 bis 3.2.0 liegen nur lokal. Push erst nach dem Entarchivieren.
- 2026-09-05 offen: postfixadmin startet in der Produktion etwa stündlich neu, Ursache unbekannt. Erst auf Marcs Wort untersuchen.
- 2026-09-05 offen: CHANGELOG mit den restaurierten Versionen 1.0.0 bis 1.10.0 und diese Datei warten auf `/commit`.
