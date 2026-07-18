# E2E UI-Tests (mailservice/tests/e2e/test_webui.py) — SnappyMail & PostfixAdmin Eigenheiten

Hart erarbeitete, nicht offensichtliche Fakten für `mailservice/tests/e2e/test_webui.py`.
SnappyMail-Version 2.38.2 (SPA, Knockout.js + Squire-Editor).

## PostfixAdmin 4.x
- Setup ist zweistufig: `form[name=authenticate]` mit `setup_password`, dann
  `form[name=create_admin]`. Das `create_admin`-Formular braucht `setup_password`
  ERNEUT (Re-Auth pro Request), sonst wird der Admin still nicht angelegt.
- Buttons sind `<button type=submit>`, nicht `<input type=submit>` → Selektor `[type=submit]`.
- `create-domain.php`/`create-mailbox.php` existieren nicht mehr → `edit.php?table=domain`
  bzw. `edit.php?table=mailbox`. Felder: `value[domain]`, `value[local_part]`,
  `value[name]`, `value[password]`, `value[password2]`.

## SnappyMail Admin-Login
- Login-Button: `button.buttonLogin` (kein `type=submit`).
- Das `Login`-Feld hat `required` → `reportValidity()` blockiert sonst. Darum muss
  `admin_login = "admin"` in der `application.ini` gesetzt UND das Login-Feld
  ausgefüllt sein (`SM_ADMIN_USER`).
- Domains-Tab: `a[href='#/domains']` (zuverlässiger als Text-Lookup).
- «Add Domain»/«Save» sind `<a>`-Elemente, keine Buttons:
  `a[data-bind*='createDomain']`, `footer a[data-bind*='createOrAddCommand']`.

## SnappyMail Domain-Config — Host-Auto-Fill-Falle
- Beim Fokussieren des LEEREN SMTP-Host-Felds spiegelt das `smtpHostFocus`-Binding
  den IMAP-Host hinein (`imap`→`smtp`-Ersetzung). Ein einzelnes `.fill("postfix")`
  rennt dann in eine KO-Race und ergibt `"dovecotpostfix"`.
  → SMTP-Host ZWEIMAL füllen: erstes Füllen macht das Feld nicht-leer (Auto-Fill
  feuert nur bei `!smtpHost()`), zweites setzt sauber.
- Genauso: Domain-`Name` IMMER ZULETZT füllen, sonst füllt `imapHostFocus` den
  IMAP-Host mit dem Domainnamen.

## SnappyMail User-Compose
- Nach Login öffnet SnappyMail ~1s später ein «Edit Identity»-Popup
  (`dialog#V-PopupsIdentity`), wenn keine Identity gespeichert ist — es überlagert
  alles. Behandeln: Name füllen + `button.buttonAddIdentity` → speichert dauerhaft.
- Compose-Button: `a.buttonCompose` (zweimal vorhanden → `.first`).
- To-Feld: `emailsTags`-Binding ersetzt das Original-`<input>` durch
  `<ul class="emailaddresses"><input></ul>`. Adresse mit echtem `type()` + `Enter`
  als Tag committen.
- Body: Squire-Editor `div.squire-wysiwyg` INNERHALB `.textAreaParent` (zwei
  Elemente, eindeutig: `.textAreaParent > .squire-wysiwyg`). Meldet sich oft als
  «not visible» → per JS `el.focus()` + `page.keyboard.type()`.
- Send-Button: `a[data-bind*='sendCommand']`.
- **Sent-Ordner-Falle:** `sendCommand()` prüft `sentFolder()`; ist er leer (Konto
  hat nur INBOX, kein Sent), öffnet SnappyMail `dialog#V-PopupsFolderSystem` STATT
  zu senden — keinerlei SMTP-Verbindung. Lösung: im Picker Sent auf «Do not use»
  (`select_option("__UNUSE__")`) setzen, schliessen, dann Send ERNEUT klicken.
- Nach dem finalen Send NICHT auf `networkidle` warten (kann in der Lücke vor dem
  Request schon idle sein → `page.close()` bricht den laufenden Send ab). Stattdessen
  auf `dialog#V-PopupsCompose` state=hidden warten (= Send erfolgreich).

## Infrastruktur
- PHP-FPM-Basis (`mwaeckerlin/php-fpm`) hat `display_errors = on` → PHP-Deprecated-
  Warnungen landen in HTTP-Bodies und zerstören JSON/HTML. In den Dockerfiles von
  postfixadmin und rainloop per `sed` `display_errors`/`display_startup_errors`
  abschalten + `clear_env = no` (sonst keine Env-Vars im FPM-Worker).
- PostfixAdmin: NICHT `config.inc.php` ersetzen (verliert 4.x-Defaults wie `dkim`),
  sondern eigene Overrides in `config.local.php`. Beide Dateien müssen unter
  `/root/etc/postfixadmin/` liegen, weil `COPY --from=build /root/ /` Symlink-Ziele
  ausserhalb `/root/` nicht mitkopiert.
- Docker-Compose: `$` in YAML-Werten als `$$` escapen (bcrypt-Hashes `$2y$12$...`).
