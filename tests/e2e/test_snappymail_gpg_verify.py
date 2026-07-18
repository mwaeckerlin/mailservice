"""SnappyMail release-signature verification — machinery test.

The production `rainloop/Dockerfile.php-fpm` refuses to build a
SnappyMail tarball whose OpenPGP signature does not verify against
the key pinned in `rainloop/snappymail-signing-key.asc`. The e2e
`snappymail` service in `tests/e2e/docker-compose.yml` explicitly
sets the escape hatch `SKIP_GPG_VERIFY=1` so CI can build with the
shipped placeholder in place.

This test suite exercises the *machinery* itself, without going
through docker build, by using gpg directly in the test-runner
container:

  - positive case: a fresh throw-away signing key signs a tarball;
    `gpg --verify` accepts.
  - negative case: the same signature paired with a tampered tarball
    is rejected (`gpg --verify` exits non-zero).

If either case regresses, the SnappyMail Dockerfile's verify step
does not protect us against the class of tampering it claims to.
"""
import os
import shutil
import subprocess
import tempfile

import pytest


def _run(cmd: list[str], check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, check=check, capture_output=True, text=True, **kw
    )


@pytest.fixture
def gnupg_home():
    """Fresh throw-away GNUPGHOME so tests do not interfere with each
    other and no state escapes into the container filesystem."""
    home = tempfile.mkdtemp(prefix="gnupg-e2e-")
    os.chmod(home, 0o700)
    yield home
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture
def test_keyring(gnupg_home):
    """Generate a throw-away signing key inside `gnupg_home`."""
    # gnupg is installed by tests/e2e/Dockerfile.playwright — a missing
    # gpg means the runner image is broken, which must fail, not skip.
    assert shutil.which("gpg") is not None, (
        "gpg is not installed in the test-runner image — "
        "tests/e2e/Dockerfile.playwright must install gnupg"
    )

    batch = (
        "%no-protection\n"
        "Key-Type: RSA\n"
        "Key-Length: 2048\n"
        "Name-Real: E2E Test Signer\n"
        "Name-Email: e2e@test.local\n"
        "Expire-Date: 0\n"
        "%commit\n"
    )
    _run(
        ["gpg", "--batch", "--generate-key"],
        env={**os.environ, "GNUPGHOME": gnupg_home},
        input=batch,
    )
    return gnupg_home


def _sign(gnupg_home: str, tarball: str, sig_out: str) -> None:
    _run(
        ["gpg", "--batch", "--yes", "--armor", "--detach-sign",
         "--output", sig_out, tarball],
        env={**os.environ, "GNUPGHOME": gnupg_home},
    )


def _verify(gnupg_home: str, tarball: str, sig: str) -> bool:
    r = _run(
        ["gpg", "--batch", "--verify", sig, tarball],
        check=False,
        env={**os.environ, "GNUPGHOME": gnupg_home},
    )
    return r.returncode == 0


def test_signed_tarball_verifies(test_keyring, tmp_path):
    """Positive case: a signature made with our test key over our
    tarball verifies cleanly. If this fails, gpg is unhealthy or
    the Dockerfile's happy-path can never fire either."""
    tar  = tmp_path / "release.tar.gz"
    tar.write_bytes(b"synthetic snappymail release payload\n" * 100)
    sig  = tmp_path / "release.tar.gz.asc"
    _sign(test_keyring, str(tar), str(sig))
    assert _verify(test_keyring, str(tar), str(sig)), (
        "Signed tarball did not verify — gpg toolchain is broken or "
        "the Dockerfile's `gpg --verify` step would silently accept a "
        "bad build."
    )


def test_tampered_tarball_is_rejected(test_keyring, tmp_path):
    """Negative case: a signature made over tarball A must fail
    verification against a byte-tampered tarball A'. This is the
    exact attack the Dockerfile's verify step exists to catch —
    a poisoned download served by a MITM'd mirror. If this test
    passes, the machinery does not protect us."""
    tar     = tmp_path / "release.tar.gz"
    payload = b"synthetic snappymail release payload\n" * 100
    tar.write_bytes(payload)
    sig = tmp_path / "release.tar.gz.asc"
    _sign(test_keyring, str(tar), str(sig))

    # tamper: flip a byte in the middle of the tarball
    tampered = bytearray(payload)
    tampered[len(tampered) // 2] ^= 0xFF
    tar.write_bytes(bytes(tampered))

    assert not _verify(test_keyring, str(tar), str(sig)), (
        "gpg accepted a signature over a tampered tarball — the "
        "verify machinery does not actually catch tampering. This "
        "voids the SnappyMail supply-chain guarantee."
    )


def test_signature_from_unknown_key_is_rejected(test_keyring, gnupg_home, tmp_path):
    """Negative case: a signature from a DIFFERENT signer's key must
    fail verification, even if the tarball itself is untouched. This
    guards against a MITM that swaps in a valid signature of their
    own instead of tampering with the tarball."""
    tar = tmp_path / "release.tar.gz"
    tar.write_bytes(b"payload\n" * 100)

    # sign with a completely separate keyring
    intruder_home = tempfile.mkdtemp(prefix="gnupg-intruder-")
    os.chmod(intruder_home, 0o700)
    try:
        _run(
            ["gpg", "--batch", "--generate-key"],
            env={**os.environ, "GNUPGHOME": intruder_home},
            input=(
                "%no-protection\n"
                "Key-Type: RSA\n"
                "Key-Length: 2048\n"
                "Name-Real: Intruder\n"
                "Name-Email: intruder@evil.local\n"
                "Expire-Date: 0\n"
                "%commit\n"
            ),
        )
        sig = tmp_path / "release.tar.gz.asc"
        _sign(intruder_home, str(tar), str(sig))

        # verify against the LEGITIMATE keyring — must fail
        assert not _verify(test_keyring, str(tar), str(sig)), (
            "gpg accepted an unknown-key signature — the pinned-key "
            "guarantee is broken."
        )
    finally:
        shutil.rmtree(intruder_home, ignore_errors=True)
