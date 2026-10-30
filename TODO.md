# TODO

## Aufträge von Marc

- 2026-10-21 offen: Einstellungen als Umgebungsvariablen. Was ein Betreiber einstellt, ist eine Umgebungsvariable mit Default; eine Konfigurationsdatei, die gemountet oder bearbeitet werden muss, ist ein Fund. Gilt für jedes Image dieses Projekts.
- 2026-10-21 offen: `PHP_FPM_HOST` in den eigenen Beispielen von postfixadmin und rainloop auf den Servicenamen des php-fpm-Images des Projekts setzen; das Basis-Image mwaeckerlin/nginx hat den Default `php-fpm`.
- 2026-09-26 offen: jedes Image zusätzlich mit `YYYYMMDD`, `<version>` und `<version>-YYYYMMDD` taggen, auch für die übrigen Tags; Versionsbranches bauen und pushen.
- 2026-09-26 offen: einheitliche npm-Scripts `build`, `start`, `test` und die übrigen Namen der Familie in jedem Teilprojekt, die Version in `package.json` nach jedem Commit erhöht, jedes Dockerfile über docker compose gebaut, README aktuell.
- 2026-09-26 offen: Prüfung jedes Teilprojekts gegen die globalen Regeln: Basis-Image, headless, `FEATURES.md`, `TESTS.md`, `CHANGELOG.md`, jedes Feature getestet.
- 2026-09-26 offen: GitHub Actions mit `docker compose build` aller Images der Compose-Datei und Push zu Docker Hub bei jedem Commit auf `master`, Token aus einem Secret.
- 2026-09-26 offen: die Basis-Images und jedes davon abgeleitete Image auch für arm64.
- 2026-10-29 offen: postfixadmin, rainloop und postfixadmin-proxy nach dem PHP-Neubau neu bauen, CVE-2026-109618 und CVE-2026-109619.
- 2026-09-09 offen: `postfix:1` und `postfix:1.11.0` auf Docker Hub neu bauen (Marc, `Trigger`-Knopf). Beide Images entstanden Minuten vor dem Push der PID-Reparatur und enthalten sie nicht; ohne den Neubau bleibt postfix beim nächsten Containerwechsel wieder stehen.
- 2026-09-09 offen: zwei Advisories `smarty/smarty` im PostfixAdmin-Image, CVE-2026-62992 und CVE-2026-62993, beide medium, aus dem Alpine-Paket. Lagen bisher unter dem entfernten `--no-security-blocking`.
- 2026-09-05 offen: `mwaeckerlin/postgrey` in der Produktions-YAML ohne Tag, zieht `latest` vom 19.07., bei Marc läuft der Bau vom 13.07. Das Repository ist archiviert, ein `:1` kann nicht entstehen; nur der Digest nagelt es fest.
- 2026-09-05 offen: Entscheidung zur Reproduzierbarkeit. Die Versions-Images werden gegen das jeweils aktuelle Alpine gebaut und unterscheiden sich damit vom Stand, der bei Marc läuft. Ein reproduzierbares Versions-Image braucht gepinnte Basisimages und Paketversionen.
- 2026-09-05 offen: postgrey ist auf GitHub archiviert, die Tags 1.0.0 bis 3.2.0 liegen nur lokal. Push erst nach dem Entarchivieren.
- 2026-09-05 offen: postfixadmin startet in der Produktion etwa stündlich neu, Ursache unbekannt. Erst auf Marcs Wort untersuchen.
