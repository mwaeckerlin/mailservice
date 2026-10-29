# Web UI Tests

Facts for `mailservice/tests/e2e/test_webui.py` that took long to find and are not obvious. SnappyMail 2.38.2, a single-page application on Knockout.js with the Squire editor.

## PostfixAdmin 4.x

- Setup runs in two steps: `form[name=authenticate]` with `setup_password`, then `form[name=create_admin]`. The `create_admin` form needs `setup_password` AGAIN (authentication per request), or the admin is silently not created.
- Buttons are `<button type=submit>`, not `<input type=submit>`, so the selector is `[type=submit]`.
- `create-domain.php` and `create-mailbox.php` no longer exist: use `edit.php?table=domain` and `edit.php?table=mailbox`. Fields: `value[domain]`, `value[local_part]`, `value[name]`, `value[password]`, `value[password2]`.

## SnappyMail Admin Login

- Login button: `button.buttonLogin` (no `type=submit`).
- The `Login` field is `required`, so `reportValidity()` blocks otherwise. Therefore `admin_login = "admin"` is set in `application.ini` AND the login field is filled (`SM_ADMIN_USER`).
- Domains tab: `a[href='#/domains']`, more reliable than a lookup by text.
- «Add Domain» and «Save» are `<a>` elements, not buttons: `a[data-bind*='createDomain']`, `footer a[data-bind*='createOrAddCommand']`.

## SnappyMail Domain Configuration

- Focusing the EMPTY SMTP host field makes the `smtpHostFocus` binding copy the IMAP host into it (replacing `imap` by `smtp`). A single `.fill("postfix")` then races Knockout and yields `"dovecotpostfix"`. So the SMTP host is filled TWICE: the first fill makes the field non-empty (the auto-fill fires only on `!smtpHost()`), the second sets it cleanly.
- Likewise the domain `Name` is ALWAYS filled LAST, or `imapHostFocus` fills the IMAP host with the domain name.

## SnappyMail Compose

- About one second after login, SnappyMail opens an «Edit Identity» popup (`dialog#V-PopupsIdentity`) when no identity is saved, and it covers everything. Handle it: fill the name and click `button.buttonAddIdentity`, which saves it for good.
- Compose button: `a.buttonCompose` (present twice, so `.first`).
- To field: the `emailsTags` binding replaces the original `<input>` with `<ul class="emailaddresses"><input></ul>`. The address is committed as a tag with a real `type()` followed by `Enter`.
- Body: the Squire editor `div.squire-wysiwyg` INSIDE `.textAreaParent` (two elements, unique as `.textAreaParent > .squire-wysiwyg`). It often reports «not visible», so focus it with `el.focus()` in JavaScript and type with `page.keyboard.type()`.
- Send button: `a[data-bind*='sendCommand']`.
- **Sent folder:** `sendCommand()` checks `sentFolder()`; when it is empty (the account has only INBOX and no Sent), SnappyMail opens `dialog#V-PopupsFolderSystem` INSTEAD of sending, with no SMTP connection at all. Set Sent to «Do not use» in the picker (`select_option("__UNUSE__")`), close it, then click Send AGAIN.
- After the final Send, do NOT wait for `networkidle`: the page can be idle in the gap before the request, and `page.close()` then aborts the running send. Wait for `dialog#V-PopupsCompose` to reach state hidden, which means the send succeeded.

## Infrastructure

- The PHP-FPM base (`mwaeckerlin/php-fpm`) has `display_errors = on`, so PHP deprecation warnings land in HTTP bodies and break JSON and HTML. The Dockerfiles of postfixadmin and rainloop switch `display_errors` and `display_startup_errors` off with `sed`, and set `clear_env = no` (or the FPM worker sees no environment variables).
- PostfixAdmin: do NOT replace `config.inc.php` (it loses 4.x defaults such as `dkim`); put the overrides into `config.local.php`. Both files lie under `/root/etc/postfixadmin/`, because `COPY --from=build /root/ /` does not copy symlink targets outside `/root/`.
