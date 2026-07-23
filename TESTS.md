# Tests

The complete register of all tests, grouped by kind and sorted by the
feature number(s) from [FEATURES.md](FEATURES.md) they cover. The
coverage guard (`tests/coverage-guard.sh`, part of `npm test`) fails
the suite when a numbered feature has no registered test, a feature
number is assigned twice, or a test references an unknown number.

Run everything with `npm test` (coverage guard → image contracts →
compose contracts → queue persistence → full e2e). The e2e suite runs
in a fully isolated stack (domain `test.local`, own DNS); no mail ever
leaves the machine.

## E2E — Frontend (Playwright, real browser)

- **F1** `tests/e2e/test_webui.py` › test_snappymail_user_login — alice logs in to the webmail and sees her mailbox.
- **F1** `tests/e2e/test_webui.py` › test_snappymail_read_mail — a mail delivered via SMTP appears in the webmail list and can be read.
- **F1** `tests/e2e/test_webui.py` › test_snappymail_send_mail — composing and sending in the webmail delivers to the recipient (verified via IMAP).
- **F1** `tests/e2e/test_webui.py` › test_snappymail_admin_configures_domain — the SnappyMail admin wires the mail domain to the IMAP/SMTP backends.
- **F6** `tests/e2e/test_webui.py` › test_snappymail_transport_security_banner — a cleartext-delivered mail shows the red «UNENCRYPTED» banner.
- **F6** `tests/e2e/test_webui.py` › test_snappymail_transport_security_no_banner_for_tls — a TLS-submitted mail shows no banner.
- **F9** `tests/e2e/test_openpgp.py` › test_openpgp_generate_key_in_ui — the generate dialog produces a key pair that appears in the key list.
- **F9** `tests/e2e/test_openpgp.py` › test_openpgp_signed_encrypted_roundtrip — sign + encrypt in one account, ciphertext-only on the wire (raw IMAP), decrypt + signature-verify in the recipient's webmail (server-side GnuPG store via php-gnupg).
- **F9** `tests/e2e/test_openpgp.py` › test_openpgp_passphrase_protected_key_roundtrip — the same roundtrip with a passphrase-PROTECTED key: signing and decrypting hand the passphrase to the php-gnupg backend through the dialog (the concern upstream disabled the backend over).
- **F11** `tests/e2e/test_webui.py` › test_postfixadmin_setup_creates_admin — setup.php provisions the schema and creates the admin account.
- **F11** `tests/e2e/test_webui.py` › test_postfixadmin_mail_users_created — the provisioned mailboxes are listed in PostfixAdmin.
- **F11** `tests/e2e/test_webui.py` › test_postfixadmin_create_mailbox — creating a mailbox through the UI works end-to-end.
- **F11** `tests/e2e/test_alias.py` › test_alias_delivers_to_target_mailbox — an alias created through the PostfixAdmin UI receives mail on the MX and it arrives in the target INBOX with the alias To intact (UI → DB → postfix virtual map → delivery).
- **F23** `tests/e2e/test_webui.py` › test_postfixadmin_branding_rendered — FOOTER_TEXT/FOOTER_LINK really render into the admin UI.
- **F23** `tests/e2e/test_webui.py` › test_postfixadmin_default_aliases_created — creating a domain provisions the DEFAULT_ALIASES role accounts (abuse/hostmaster/postmaster/webmaster).

## E2E — Backend/API (against the real running stack)

- **F2** `tests/e2e/test_imap.py` › test_imap_login / test_imap_wrong_password_rejected — IMAP login good and bad case.
- **F2** `tests/e2e/test_imap.py` › test_imap_mail_delivered_to_inbox / test_imap_fetch_message_body — SMTP→LMTP→IMAP delivery and body retrieval.
- **F2** `tests/e2e/test_imap.py` › test_imap_folder_create_and_delete / test_imap_capability / test_imap_independent_mailboxes — folder management, capabilities, mailbox isolation between users.
- **F2** `tests/e2e/test_pop3.py` › test_pop3_login / test_pop3_wrong_password_rejected / test_pop3_list_and_retrieve / test_pop3_stat — POP3 over STLS: login good/bad, list, retrieve, stat.
- **F2** `tests/e2e/test_sieve.py` › test_managesieve_login / test_managesieve_wrong_password / test_managesieve_put_and_list / test_managesieve_set_active / test_managesieve_delete — ManageSieve script lifecycle, good and bad login.
- **F2** `tests/e2e/test_sieve.py` › test_sieve_fileinto_filter / test_sieve_non_matching_mail_to_inbox / test_sieve_multiple_rules — server-side filtering at delivery time, match and non-match cases.
- **F2** `tests/e2e/test_tls.py` › test_imaps_login_on_993 / test_pop3s_login_on_995 / test_imap_starttls_on_143 — the published encrypted client ports.
- **F3** `tests/e2e/test_imap.py` › test_imap_cleartext_login_refused_without_tls — cleartext IMAP login is refused even with valid credentials.
- **F3** `tests/e2e/test_pop3.py` › test_pop3_cleartext_login_refused_without_stls — cleartext POP3 login is refused even with valid credentials.
- **F3** `tests/e2e/test_sieve.py` › test_sieve_cleartext_auth_refused_without_tls — cleartext ManageSieve auth is refused.
- **F3** `tests/e2e/test_smtp.py` › test_smtp_plaintext_auth_refused_without_tls — SASL is not offered before STARTTLS.
- **F3** `tests/e2e/test_tls.py` › test_cleartext_optin_imap_login / test_cleartext_optin_pop3_login — the deliberate `DOVECOT_ALLOW_CLEARTEXT=yes` softening works on the certless opt-in service (the default keeps refusing).
- **F12** `tests/e2e/test_tls.py` › test_cleartext_auth_optin_smtp — the deliberate `POSTFIX_ALLOW_CLEARTEXT_AUTH=yes` softening opens SASL without TLS on the opt-in service (the secure default refuses).
- **F21** `tests/e2e/test_imap.py` › test_default_pass_scheme_effective — a legacy database row with a bare PLAIN password authenticates when `DEFAULT_PASS_SCHEME` says so, and a wrong password still fails (the migration scenario the knob exists for).
- **F4** `tests/e2e/test_smtp.py` › test_smtp_delivery_to_local_user / test_smtp_delivery_to_second_user — accepted submission is delivered.
- **F5** `tests/e2e/test_greylisting.py` › test_authenticated_submission_not_greylisted — SASL-authenticated submission is never greylisted, whatever the content.
- **F6** `tests/e2e/test_tls.py` › test_transport_security_header_plaintext / test_transport_security_header_tls — the header records `none` for a cleartext hop and the TLS version for an encrypted one.
- **F6** `tests/e2e/test_tls.py` › test_transport_security_header_not_forgeable — a sender-supplied header copy is stripped and replaced with the real value.
- **F7** `tests/e2e/test_spam_score_reject.py` › test_gtube_spam_rejected / test_clean_mail_not_rejected — GTUBE draws a 5xx at SMTP time, clean mail passes.
- **F7** `tests/e2e/test_virus_reject.py` › test_clamd_detects_eicar_directly / test_eicar_inline_body_rejected / test_eicar_attachment_rejected — EICAR is detected and rejected at SMTP time, inline and as attachment.
- **F7** `tests/e2e/test_greylisting.py` › test_clean_unknown_sender_not_greylisted — clean first-time senders are never delayed (regression guard against postgrey-style blanket delays).
- **F7** `tests/e2e/test_greylisting.py` › test_midscore_mail_greylisted_then_accepted — the defer/retry path: a deterministic mid-score mail draws a 4xx and is accepted and delivered on the retry of the same message.
- **F22** `tests/e2e/test_greylisting.py` › test_check_local_greylists_local_clients — `RSPAMD_CHECK_LOCAL=true` removes the local-client greylist bypass (4xx then accept for a client inside local_addrs); the reverse (bypass) direction is technically not reproducible in the stack and documented in the test.
- **F22** `tests/e2e/test_bayes_per_user.py` › test_bayes_per_user_separates_recipients — `RSPAMD_BAYES_PER_USER=true` really separates statistics by recipient: after training past min_learns for alice only, the same mail gets a Bayes verdict for alice and none for charlie.
- **F13** `tests/e2e/test_dkim_notify.py` › test_dkim_key_notification_mail_delivered — `NOTIFY_EMAIL`/`NOTIFY_SMTP` really deliver the generated DKIM DNS records by mail (asserted in the fake-smtp store).
- **F7** `tests/e2e/test_smtp.py` › test_smtp_unknown_local_recipient_rejected — mail to a nonexistent mailbox is rejected with a permanent error, never accepted into a void.
- **F7** `tests/e2e/test_bayes_autolearn.py` › test_move_to_junk_advances_spam_learn_counter / test_move_out_of_junk_advances_ham_learn_counter — event-driven Bayes training fires on IMAP moves into/out of Junk.
- **F8** `tests/e2e/test_delivery_mode.py` › test_forged_spam_headers_stripped_on_ingress — sender-forged X-Spam-* verdict headers are stripped before delivery (below-threshold case).
- **F10** `tests/e2e/test_relay_family.py` › test_smtp_relay_banner_and_ehlo / test_smtp_relay_relays_to_external_mx — smtp-relay boots and REALLY relays to an external MX (asserted in the fake-smtp store).
- **F10** `tests/e2e/test_relay_family.py` › test_smtp_relay_tls_starttls_handshake — smtp-relay-tls offers STARTTLS with the mounted cert and completes the handshake.
- **F10** `tests/e2e/test_relay_family.py` › test_mailforward_banner_and_ehlo / test_mailforward_forwards_mapped_alias / test_mailforward_rejects_unmapped_recipient — mailforward forwards a mapped alias end-to-end and rejects unmapped recipients with a 5xx.
- **F20** `tests/e2e/test_relay_family.py` › test_smtp_relay_milter_hook_effective — the `OPENDKIM` milter hook feeds relayed mail through the wired milter (rspamd headers on the delivered copy).
- **F20** `tests/e2e/test_relay_family.py` › test_mailforward_milter_hook_effective — the `GREYLIST` milter hook does the same for forwards.
- **F21** — the wiring knobs are exercised by the stacks themselves: every e2e service connects exclusively through them (`DB_*`, `RSPAMD`, `REDIS_HOST`, `CLAMAV_HOST`, `MAILHOST`, `MAPPINGS`, `MYNETWORKS`, `AUTHSERV_ID` — pinned by test_dkim_spf.py::test_authserv_id_in_authentication_results — and `PHP_FPM_HOST`, exercised with a non-default value by the schema-upgrade proxy); a wrong value would fail the respective suite.
- **F12** `tests/e2e/test_smtp.py` › test_smtp_relay_rejected_for_external — the MX refuses to relay for unauthenticated senders.
- **F12** `tests/e2e/test_smtp.py` › test_smtp_sasl_auth_accepted / test_smtp_sasl_wrong_password_rejected — authenticated submission good and bad case.
- **F12** `tests/e2e/test_tls.py` › test_smtp_starttls_offered_and_negotiates / test_submission_auth_over_starttls — STARTTLS on the MX, authenticated submission over it.
- **F12** `tests/e2e/test_tls.py` › test_submission_587_requires_auth / test_submission_587_refuses_cleartext_auth / test_smtps_465_wrappermode_submission — the dedicated submission services enforce TLS + auth (587 STARTTLS, 465 implicit).
- **F12** `tests/e2e/test_tls.py` › test_smtp_auth_disabled_without_cert — without a certificate no AUTH is offered and a forced attempt is refused server-side.
- **F12** `tests/e2e/test_tls.py` › test_tls_required_rejects_cleartext / test_tls_required_accepts_over_tls — the `SMTPD_TLS_REQUIRED=yes` opt-in rejects cleartext and accepts TLS delivery.
- **F13** `tests/e2e/test_dkim_spf.py` › test_dkim_signature_present / test_dkim_signature_fields — outgoing mail is DKIM-signed with the right domain and selector.
- **F13** `tests/e2e/test_dkim_spf.py` › test_spf_result_in_authentication_results / test_authserv_id_in_authentication_results — the SPF verdict and the wired authserv-id land in Authentication-Results.
- **F13** `tests/e2e/test_dkim_multidomain_sign.py` › test_multidomain_sign_from_second_domain / test_multidomain_sign_from_first_domain_still_works — per-domain keys in DOMAINS mode.
- **F13** `tests/e2e/test_dkim_verify.py` › eight verify cases — correct/missing/bad signatures across the permissive, reject and log stacks (accept, reject, and never-reject-in-log semantics).
- **F13** `tests/e2e/test_dmarc.py` › five DMARC cases — p=reject fails unsigned, p=none and no-record accept, log mode never rejects, correctly signed mail passes p=reject.
- **F14** `tests/e2e/test_delivery_mode.py` › test_clean_mail_lands_in_inbox_default_reject_mode / test_gtube_reaches_neither_inbox_nor_junk — default reject mode: clean → INBOX, spam → SMTP reject, zero deliveries.
- **F14** `tests/e2e/test_delivery_mode.py` › test_mark_mode_spam_flag_mail_lands_in_inbox — mark mode delivers flagged mail to INBOX (headers only, no Junk detour), over the real LMTP interface.
- **F14** `tests/e2e/test_delivery_mode.py` › test_folder_mode_spam_flag_mail_lands_in_junk / test_folder_mode_clean_mail_lands_in_inbox — folder mode routes flagged mail to Junk and leaves clean mail in INBOX.
- **F16** `tests/e2e/test_quota.py` › test_quota_sql_userdb_login_works / test_quota_append_over_limit_refused / test_quota_lmtp_over_limit_tempfails / test_quota_unlimited_mailbox_unaffected — quota is enforced (APPEND refused, LMTP tempfails — never a silent drop), unlimited mailboxes unaffected.
- **F17** `tests/e2e/test_sieve.py` › test_sieve_max_script_size_enforced — `SIEVE_MAX_SCRIPT_SIZE` is enforced: an oversized upload is refused, a small one on the same service passes.

## Migration / schema tests

- **F15** `tests/e2e/test_maildir_layout.py` › test_maildir_uses_domain_localpart_layout — the on-disk mailbox layout stays `domain/localpart` (a layout change across upgrades would orphan every existing mailbox).
- **F19** `tests/e2e/test_schema_upgrade.py` › test_schema_upgrade_via_setup — a REAL PostfixAdmin 3.2.4 schema (generated by the old release itself) is migrated by opening setup.php; the previously failing admin pages work afterwards.

## Image / compose contract tests

- **F4, F15** `tests/queue-persistence.sh` — an accepted-but-undelivered mail survives the DESTRUCTION and recreation of its container (named spool volume) and is delivered afterwards — the «250 means never lost» migration guarantee, proven end-to-end.
- **F15** `tests/compose-contract.sh` — the production compose keeps `/var/spool/postfix` of every postfix service and `/var/lib/mysql` of the database on NAMED volumes (plus a self-test of the detection).
- **F11** `tests/compose-contract.sh` — the plain-HTTP admin UI is published on loopback only.
- **F18** `tests/image-contract.sh` — every shipped image is headless: no sh, no bash, no busybox, no perl (checked from outside, against the production images and every e2e-built image).
- **F9, F18** `tests/snappymail-gnupg.sh` — the SnappyMail image ships the php-gnupg extension and a runnable gpg binary.
- *(guard)* `tests/coverage-guard.sh` — FEATURES.md ↔ TESTS.md consistency: unique feature numbers, every feature tested, no dangling references.

## Security tests (effectiveness, not existence)

The security-relevant invariants are pinned by the tests already listed
above; the most important ones, by promise:

- Passwords never travel unencrypted (F3): the four cleartext-refusal
  tests (IMAP, POP3, ManageSieve, SMTP AUTH) all run WITH valid
  credentials — they measure the protection layer, not a password
  mismatch; `test_smtp_auth_disabled_without_cert` pins the certless
  branch server-side.
- Our verdict headers cannot be forged (F6, F8):
  `test_transport_security_header_not_forgeable` and
  `test_forged_spam_headers_stripped_on_ingress`.
- No open relay (F12): `test_smtp_relay_rejected_for_external`,
  `test_mailforward_rejects_unmapped_recipient`.
- Hardened, shell-free images (F18): `tests/image-contract.sh`.
- Environment validation (F18, F21, F22) is pinned per image in the
  submodule suites (`postfix/tests/config-validation.sh`,
  `dovecot/tests/config-validation.sh`,
  `rspamd/tests/config-validation.sh`,
  `smtp-relay/tests/config-validation.sh`,
  `mailforward/tests/config-validation.sh` — run via each submodule's
  `npm test`): every documented env knob has a reject case (malformed /
  injection value refused with `invalid <VAR>`) and an accept case.
- Tuning knobs whose values the e2e stack actively depends on are
  thereby effectiveness-tested on every run:
  `RSPAMD_GREYLIST_TIMEOUT`/`EXPIRE` (the greylist retry tests fit the
  pytest budget only because of them), `RSPAMD_REJECT_SCORE` (GTUBE
  rejects), `RSPAMD_LOCAL_ADDRS`/`RSPAMD_SIGN_NETWORKS` (the verify
  paths only run because the runner counts as external yet gets
  signed), `SETUP_PASSWORD`/`DATABASE_*`/`EMAILCHECK_RESOLVE_DOMAIN`
  (provisioning), `MESSAGE_SIZE_LIMIT` and `SMTP_HARD_ERROR_LIMIT`
  (validated; the 100-GiB default cannot be exercised with real mail —
  documented technical limit).
