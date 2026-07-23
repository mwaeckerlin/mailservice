"""Webmail OpenPGP end-to-end (SnappyMail + the shipped php-gnupg
backend).

The real user path through the real UI:

  1. Key generation through the SnappyMail dialog (browser-side
     OpenPGP.js keys — the dialog the user actually sees).
  2. Key import through the SnappyMail dialog into the SERVER-side
     GnuPG store (the php-gnupg extension the image ships — pinned so
     the extension is not merely present but actually working).
  3. The full crypto roundtrip: alice signs + encrypts a mail to bob in
     the compose window; the wire copy (raw IMAP) is a real PGP MESSAGE
     that does not leak the plaintext; bob decrypts in his webmail and
     sees the plaintext and a valid signature.

  4. The same roundtrip with a passphrase-PROTECTED private key
     (charlie) — signing and decrypting hand the passphrase to the
     php-gnupg backend through the dialog; this is the exact concern
     upstream disabled the backend over (fixed in extension >= 1.5 via
     loopback pinentry, which this image pins).

Key material comes from a real `gpg` (test-runner), imported through
the real UI — alice/bob passphrase-less (deterministic base case),
charlie passphrase-protected.
"""
import os
import subprocess
import time
import uuid

import pytest
from playwright.sync_api import Browser, Page, expect

from conftest import (
    ALICE, ALICE_PW, BOB, BOB_PW, CHARLIE, CHARLIE_PW, DOMAIN, SM_URL,
    imap_starttls,
)

CHARLIE_PP = "Charliepp123"     # passphrase protecting charlie's key


# ------------------------------------------------------------ key helpers ---

def _gpg(env: dict, *args: str) -> str:
    res = subprocess.run(["gpg", *args], capture_output=True, text=True,
                         env=env, timeout=60)
    assert res.returncode == 0, f"gpg {args} failed: {res.stderr}"
    return res.stdout


@pytest.fixture(scope="module")
def pgp_keys(tmp_path_factory):
    """Real keypairs from a real gpg: passphrase-less for alice and bob
    (deterministic roundtrip), passphrase-PROTECTED for charlie (the
    case the php-gnupg backend must handle via loopback pinentry)."""
    home = tmp_path_factory.mktemp("gnupg")
    home.chmod(0o700)
    env = {**os.environ, "GNUPGHOME": str(home)}
    for uid in (f"Alice Test <{ALICE}>", f"Bob Test <{BOB}>"):
        _gpg(env, "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
             "--quick-generate-key", uid, "default", "default", "never")
    _gpg(env, "--batch", "--pinentry-mode", "loopback",
         "--passphrase", CHARLIE_PP,
         "--quick-generate-key", f"Charlie Test <{CHARLIE}>",
         "default", "default", "never")
    return {
        "alice_priv":   _gpg(env, "--armor", "--pinentry-mode", "loopback",
                             "--passphrase", "", "--export-secret-keys", ALICE),
        "alice_pub":    _gpg(env, "--armor", "--export", ALICE),
        "bob_priv":     _gpg(env, "--armor", "--pinentry-mode", "loopback",
                             "--passphrase", "", "--export-secret-keys", BOB),
        "bob_pub":      _gpg(env, "--armor", "--export", BOB),
        "charlie_priv": _gpg(env, "--armor", "--pinentry-mode", "loopback",
                             "--passphrase", CHARLIE_PP,
                             "--export-secret-keys", CHARLIE),
        "charlie_pub":  _gpg(env, "--armor", "--export", CHARLIE),
    }


# ------------------------------------------------------------- UI helpers ---

def _login(page: Page, user: str, password: str) -> None:
    page.goto(SM_URL, timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=20_000)
    page.get_by_placeholder("Email", exact=False).fill(user)
    page.locator("input[type=password]").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_load_state("networkidle", timeout=20_000)
    _dismiss_identity_dialog(page)


def _dismiss_identity_dialog(page: Page) -> None:
    """SnappyMail opens an «Edit Identity» popup shortly after login when
    the account has no saved identity yet — it overlays everything."""
    dialog = page.locator("dialog#V-PopupsIdentity")
    try:
        dialog.wait_for(state="visible", timeout=8_000)
        dialog.locator("input[name='Name']").fill("Test")
        dialog.locator("button.buttonAddIdentity").click()
        dialog.wait_for(state="hidden", timeout=8_000)
    except Exception:
        pass


def _confirm_passphrase_if_asked(page: Page, passphrase: str = "") -> None:
    """Fill SnappyMail's ask-passphrase dialog if it appears (it may be
    skipped for passphrase-less keys or a cached passphrase)."""
    try:
        pw = page.locator("dialog[open] input[type=password]").first
        pw.wait_for(state="visible", timeout=3_000)
        pw.fill(passphrase)
        pw.press("Enter")
    except Exception:
        pass


def _compose_and_send(page: Page, to: str, subject: str, body: str,
                      passphrase: str = "") -> None:
    """Compose a signed + encrypted mail and send it, handling the
    passphrase dialog and the first-send system-folder picker."""
    page.goto(SM_URL, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.locator("a.buttonCompose").first.click()
    page.wait_for_timeout(1_000)

    to_input = page.locator("ul.emailaddresses input").first
    to_input.click()
    to_input.type(to)
    to_input.press("Enter")
    page.locator("input[name='subject']").fill(subject)

    body_area = page.locator(".textAreaParent > .squire-wysiwyg")
    body_area.wait_for(state="attached", timeout=10_000)
    body_area.evaluate("el => el.focus()")
    page.keyboard.type(body)

    sign = page.locator("a[data-bind*='doSign']").first
    expect(sign).to_be_visible(timeout=10_000)
    sign.click()
    encrypt = page.locator("a[data-bind*='doEncrypt']").first
    expect(encrypt).to_be_visible(timeout=10_000)
    encrypt.click()

    page.locator("a[data-bind*='sendCommand']").first.click()
    _confirm_passphrase_if_asked(page, passphrase)

    # first-send system-folder picker (no Sent folder yet): set «do not
    # use» and resend — same known quirk as in test_webui.py
    folder_picker = page.locator("dialog#V-PopupsFolderSystem")
    try:
        folder_picker.wait_for(state="visible", timeout=5_000)
        folder_picker.locator("select").first.select_option("__UNUSE__")
        page.wait_for_timeout(500)
        folder_picker.locator("a.close").click()
        folder_picker.wait_for(state="hidden", timeout=5_000)
        page.locator("a[data-bind*='sendCommand']").first.click()
        _confirm_passphrase_if_asked(page, passphrase)
    except Exception:
        pass

    page.locator("dialog#V-PopupsCompose").wait_for(state="hidden",
                                                    timeout=30_000)


def _fetch_raw(user: str, password: str, subject: str,
               timeout: int = 30) -> str:
    """Poll the user's INBOX via IMAP and return the raw RFC822 text of
    the mail with `subject`, or '' if it never arrives."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with imap_starttls() as conn:
            conn.login(user, password)
            conn.select("INBOX")
            _, data = conn.search(None, f'SUBJECT "{subject}"')
            if data[0]:
                _, fetched = conn.fetch(data[0].split()[0], "(RFC822)")
                return fetched[0][1].decode(errors="replace")
        time.sleep(2)
    return ""


def _open_openpgp_settings(page: Page) -> None:
    page.goto(f"{SM_URL}/#/settings/security", timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    expect(page.locator("[data-bind*='addOpenPgpKey']").first).to_be_visible(
        timeout=15_000)


def _import_key_to_gnupg(page: Page, armored: str) -> None:
    """Import an armored key through the SnappyMail dialog into the
    server-side GnuPG store (the shipped php-gnupg backend)."""
    page.locator("[data-bind*='addOpenPgpKey']").first.click()
    dialog = page.locator("dialog#V-PopupsOpenPgpImport")
    dialog.wait_for(state="visible", timeout=10_000)
    dialog.locator("textarea").fill(armored)
    # «store in GnuPG» (saveGnuPG) defaults to TRUE in the dialog's view
    # model (dev/View/Popup/OpenPgpImport.js) — leave it untouched, a
    # click would deactivate the server-side backend under test.
    # A server-side failure only surfaces as a JS alert (auto-dismissed
    # in headless runs), so pin the actual PgpImportKey response.
    with page.expect_response(
        lambda r: "PgpImportKey" in (r.request.post_data or ""),
        timeout=20_000,
    ) as resp_info:
        dialog.locator("button[form='openpgp-import']").click()
    resp = resp_info.value
    body = resp.text().replace(" ", "")
    assert resp.ok and '"gnuPG":true' in body, (
        f"server-side GnuPG import failed (the php-gnupg backend must "
        f"really store the key): HTTP {resp.status} {body[:800]}"
    )
    dialog.wait_for(state="hidden", timeout=20_000)
    page.wait_for_timeout(500)


# ------------------------------------------------------------------ tests ---

def test_openpgp_generate_key_in_ui(browser: Browser, sm_domain_ready):
    """The generate dialog produces a usable key pair: after generation
    alice's private-key list is no longer empty."""
    page = browser.new_page()
    _login(page, ALICE, ALICE_PW)
    _open_openpgp_settings(page)

    page.locator("[data-bind*='generateOpenPgpKey']").first.click()
    dialog = page.locator("dialog#V-PopupsOpenPgpGenerate")
    dialog.wait_for(state="visible", timeout=10_000)
    dialog.locator("input[type=text]").first.fill("Alice Test")
    email = dialog.locator("input[type=email]").first
    if not email.input_value():
        email.fill(ALICE)
    # the first input[type=password] is a hidden anti-autofill dummy —
    # the real field is the one marked autocomplete='new-password'
    dialog.locator("input[autocomplete='new-password']").fill("Genpass123")
    dialog.locator("button[form='openpgp-generate']").click()
    dialog.wait_for(state="hidden", timeout=60_000)

    # the generated key shows up in a private-key list (OpenPGP.js or
    # GnuPG, depending on the dialog's storage default); the lists sit
    # in collapsed <details> groups, so assert presence, not visibility
    expect(page.locator(
        "tbody[data-bind*='openpgpkeysPrivate'] tr, "
        "tbody[data-bind*='gnupgPrivateKeys'] tr"
    ).first).to_be_attached(timeout=30_000)
    page.close()


def test_openpgp_signed_encrypted_roundtrip(browser: Browser,
                                            sm_domain_ready, pgp_keys):
    """Sign + encrypt in alice's compose window, decrypt + verify in
    bob's webmail; the wire copy is ciphertext only."""
    subject = f"PGP-{uuid.uuid4().hex[:8]}"
    secret = f"the secret payload {uuid.uuid4().hex}"

    # alice: her private key + bob's public key into the GnuPG store
    page = browser.new_page()
    _login(page, ALICE, ALICE_PW)
    _open_openpgp_settings(page)
    _import_key_to_gnupg(page, pgp_keys["alice_priv"])
    _import_key_to_gnupg(page, pgp_keys["bob_pub"])
    page.reload()
    page.wait_for_load_state("networkidle", timeout=15_000)
    # collapsed <details> group — assert presence, not visibility
    expect(page.locator("tbody[data-bind*='gnupgPrivateKeys'] tr").first
           ).to_be_attached(timeout=15_000)

    # compose to bob with sign + encrypt enabled
    _compose_and_send(page, BOB, subject, secret)
    page.close()

    # the wire copy: a real PGP message, plaintext not leaked
    raw = _fetch_raw(BOB, BOB_PW, subject)
    assert raw, f"encrypted mail '{subject}' never delivered to bob"
    assert "BEGIN PGP MESSAGE" in raw, (
        "mail was not PGP-encrypted on the wire despite doEncrypt"
    )
    assert secret not in raw, "plaintext leaked into the wire copy"

    # bob: import his private key + alice's public key, open, decrypt,
    # verify
    page = browser.new_page()
    _login(page, BOB, BOB_PW)
    _open_openpgp_settings(page)
    _import_key_to_gnupg(page, pgp_keys["bob_priv"])
    _import_key_to_gnupg(page, pgp_keys["alice_pub"])

    _open_decrypt_verify(page, subject, secret)
    page.close()


def _open_decrypt_verify(page: Page, subject: str, secret: str,
                         passphrase: str = "") -> None:
    """Open the mail with `subject`, decrypt it (handling the passphrase
    dialog) and assert the plaintext appears and the signature verifies."""
    page.goto(SM_URL, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.get_by_text(subject, exact=False).first.click()
    page.wait_for_timeout(1_000)

    decrypt = page.locator("button[data-bind*='pgpDecrypt']").first
    expect(decrypt).to_be_visible(timeout=15_000)
    decrypt.click()
    _confirm_passphrase_if_asked(page, passphrase)

    expect(page.get_by_text(secret, exact=False).first).to_be_visible(
        timeout=20_000)

    # the signature made in the sender's compose window verifies here
    signed_ok = page.locator(".crypto-control.signed.success")
    try:
        expect(signed_ok.first).to_be_visible(timeout=5_000)
    except AssertionError:
        verify = page.locator("button[data-bind*='pgpVerify']").first
        expect(verify).to_be_visible(timeout=5_000)
        verify.click()
        _confirm_passphrase_if_asked(page, passphrase)
        expect(signed_ok.first).to_be_visible(timeout=15_000)


def test_openpgp_passphrase_protected_key_roundtrip(browser: Browser,
                                                    sm_domain_ready,
                                                    pgp_keys):
    """The php-gnupg backend with a passphrase-PROTECTED private key —
    the exact concern upstream disabled the backend over (pre-1.5
    extension versions could not hand the passphrase to gpg; 1.5+ uses
    loopback pinentry). charlie's key is protected:

      1. charlie SIGNS + encrypts to alice, entering his passphrase in
         the dialog — pins signing with a protected key,
      2. alice decrypts (her key is passphrase-less) and charlie's
         signature verifies,
      3. alice signs + encrypts back to charlie,
      4. charlie DECRYPTS with his passphrase — pins decryption with a
         protected key."""
    subject_out = f"PGP-PP-{uuid.uuid4().hex[:8]}"
    secret_out = f"protected-key payload {uuid.uuid4().hex}"
    subject_back = f"PGP-PP-RE-{uuid.uuid4().hex[:8]}"
    secret_back = f"protected-key reply {uuid.uuid4().hex}"

    # charlie: protected private key + alice's public key
    page = browser.new_page()
    _login(page, CHARLIE, CHARLIE_PW)
    _open_openpgp_settings(page)
    _import_key_to_gnupg(page, pgp_keys["charlie_priv"])
    _import_key_to_gnupg(page, pgp_keys["alice_pub"])
    # 1. sign (passphrase dialog) + encrypt to alice
    _compose_and_send(page, ALICE, subject_out, secret_out,
                      passphrase=CHARLIE_PP)
    page.close()

    raw = _fetch_raw(ALICE, ALICE_PW, subject_out)
    assert raw, f"mail '{subject_out}' never delivered to alice"
    assert "BEGIN PGP MESSAGE" in raw and secret_out not in raw, (
        "mail from the protected key was not ciphertext-only on the wire"
    )

    # 2. alice decrypts and sees charlie's signature verify; her own key
    # is passphrase-less (imported by the previous roundtrip — imports
    # are idempotent, so make it explicit and order-independent)
    page = browser.new_page()
    _login(page, ALICE, ALICE_PW)
    _open_openpgp_settings(page)
    _import_key_to_gnupg(page, pgp_keys["alice_priv"])
    _import_key_to_gnupg(page, pgp_keys["charlie_pub"])
    _open_decrypt_verify(page, subject_out, secret_out)
    # 3. alice answers signed + encrypted to charlie
    _compose_and_send(page, CHARLIE, subject_back, secret_back)
    page.close()

    raw = _fetch_raw(CHARLIE, CHARLIE_PW, subject_back)
    assert raw, f"mail '{subject_back}' never delivered to charlie"
    assert "BEGIN PGP MESSAGE" in raw and secret_back not in raw, (
        "reply was not ciphertext-only on the wire"
    )

    # 4. charlie decrypts WITH his passphrase
    page = browser.new_page()
    _login(page, CHARLIE, CHARLIE_PW)
    _open_decrypt_verify(page, subject_back, secret_back,
                         passphrase=CHARLIE_PP)
    page.close()
