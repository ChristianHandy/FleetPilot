import tempfile
from pathlib import Path

import two_factor


def test_webauthn_registration_options_and_credential_metadata():
    original_db = two_factor.TFA_DB
    try:
        with tempfile.TemporaryDirectory() as temporary:
            two_factor.TFA_DB = Path(temporary) / "2fa.db"
            two_factor.init_db()
            if not two_factor.WEBAUTHN_AVAILABLE:
                raise AssertionError("The declared WebAuthn dependency must be importable in the build environment.")

            registration = two_factor.generate_webauthn_registration(
                42, "admin", "fleetpilot.example.test"
            )
            public_key = registration["options"]
            assert registration["challenge"]
            assert public_key["rp"]["id"] == "fleetpilot.example.test"
            assert public_key["user"]["name"] == "admin"

            with two_factor.get_db() as db:
                db.execute(
                    """
                    INSERT INTO webauthn_credentials(user_id, credential_id, public_key, sign_count, label)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (42, "credential-test", "public-key-test", 0, "Test security key"),
                )

            methods = two_factor.get_2fa_methods(42)
            credentials = two_factor.get_webauthn_credentials(42)
            assert methods["webauthn"] == 1
            assert credentials[0]["label"] == "Test security key"
            assert two_factor.delete_webauthn_credential(42, credentials[0]["id"])
            assert two_factor.get_2fa_methods(42)["webauthn"] == 0
    finally:
        two_factor.TFA_DB = original_db


if __name__ == "__main__":
    test_webauthn_registration_options_and_credential_metadata()
    print("WebAuthn support tests: OK")
