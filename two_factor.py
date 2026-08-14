"""
Two-Factor Authentication Module for FleetPilot
Supports:
  - TOTP (Time-based One-Time Password) — Google Authenticator, Authy, etc.
  - YubiKey OTP (Yubico OTP validation via Yubico API)
  - YubiKey FIDO2/WebAuthn (hardware key challenge-response)
"""
import sqlite3
import os
import base64
import hashlib
import hmac
import struct
import time
import secrets
import json
import re
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta

# ── Optional imports ──────────────────────────────────────────────────────────
try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False

try:
    import qrcode
    import io
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

try:
    from webauthn import (
        generate_registration_options,
        verify_registration_response,
        generate_authentication_options,
        verify_authentication_response,
        options_to_json,
    )
    from webauthn.helpers.structs import (
        AuthenticatorAttachment,
        AuthenticatorSelectionCriteria,
        UserVerificationRequirement,
        ResidentKeyRequirement,
        PublicKeyCredentialDescriptor,
        PublicKeyCredentialType,
    )
    WEBAUTHN_AVAILABLE = True
except ImportError:
    WEBAUTHN_AVAILABLE = False

# ── Database ──────────────────────────────────────────────────────────────────
def _get_data_dir():
    app_dir = Path(__file__).parent
    data_dir = Path(os.environ.get('FLEETPILOT_DATA_DIR', str(app_dir / 'data')))
    data_dir.mkdir(exist_ok=True)
    return data_dir

TFA_DB = _get_data_dir() / '2fa.db'

def get_db():
    conn = sqlite3.connect(str(TFA_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """Initialize 2FA database tables."""
    with get_db() as db:
        db.executescript("""
        -- TOTP secrets per user
        CREATE TABLE IF NOT EXISTS totp_secrets (
            user_id     INTEGER PRIMARY KEY,
            secret      TEXT NOT NULL,
            enabled     INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified_at TIMESTAMP
        );

        -- Backup codes (one-time use)
        CREATE TABLE IF NOT EXISTS backup_codes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            code_hash   TEXT NOT NULL,
            used        INTEGER DEFAULT 0,
            used_at     TIMESTAMP,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- YubiKey registrations
        CREATE TABLE IF NOT EXISTS yubikeys (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            key_id      TEXT NOT NULL,       -- first 12 chars of OTP (modhex public ID)
            label       TEXT DEFAULT 'YubiKey',
            enabled     INTEGER DEFAULT 1,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used   TIMESTAMP,
            UNIQUE(user_id, key_id)
        );

        -- WebAuthn credentials (FIDO2)
        CREATE TABLE IF NOT EXISTS webauthn_credentials (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            credential_id   TEXT NOT NULL UNIQUE,
            public_key      TEXT NOT NULL,
            sign_count      INTEGER DEFAULT 0,
            label           TEXT DEFAULT 'Security Key',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used       TIMESTAMP
        );

        -- WebAuthn challenges (temporary, expire after 5 min)
        CREATE TABLE IF NOT EXISTS webauthn_challenges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            challenge   TEXT NOT NULL UNIQUE,
            type        TEXT NOT NULL,   -- 'register' or 'authenticate'
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 2FA audit log
        CREATE TABLE IF NOT EXISTS tfa_audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            username    TEXT,
            method      TEXT,           -- 'totp', 'yubikey', 'webauthn', 'backup_code'
            success     INTEGER,
            ip          TEXT,
            reason      TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_totp_user ON totp_secrets(user_id);
        CREATE INDEX IF NOT EXISTS idx_yubikey_user ON yubikeys(user_id);
        CREATE INDEX IF NOT EXISTS idx_webauthn_user ON webauthn_credentials(user_id);
        CREATE INDEX IF NOT EXISTS idx_backup_user ON backup_codes(user_id);
        CREATE INDEX IF NOT EXISTS idx_challenge_user ON webauthn_challenges(user_id);
        """)

# ── TOTP ──────────────────────────────────────────────────────────────────────

def _totp_fallback(secret: str, digits: int = 6, period: int = 30) -> str:
    """Pure-Python TOTP implementation (RFC 6238) as fallback if pyotp not available."""
    key = base64.b32decode(secret.upper().replace(' ', ''))
    counter = int(time.time()) // period
    msg = struct.pack('>Q', counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()  # SHA1 required by RFC 6238 TOTP/HOTP standard
    offset = h[-1] & 0x0F
    code = struct.unpack('>I', h[offset:offset+4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)

def generate_totp_secret() -> str:
    """Generate a new TOTP secret."""
    if PYOTP_AVAILABLE:
        return pyotp.random_base32()
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')

def get_totp_uri(secret: str, username: str, issuer: str = 'FleetPilot') -> str:
    """Get otpauth:// URI for QR code generation."""
    if PYOTP_AVAILABLE:
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=username, issuer_name=issuer)
    params = urllib.parse.urlencode({
        'secret': secret,
        'issuer': issuer,
        'algorithm': 'SHA1',
        'digits': '6',
        'period': '30',
    })
    return f"otpauth://totp/{urllib.parse.quote(issuer)}:{urllib.parse.quote(username)}?{params}"

def get_totp_qr_base64(secret: str, username: str) -> str:
    """Generate QR code as base64 PNG."""
    uri = get_totp_uri(secret, username)
    if QRCODE_AVAILABLE:
        qr = qrcode.QRCode(version=1, box_size=6, border=4)
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return base64.b64encode(buf.getvalue()).decode()
    # Fallback: return URI as text (user can use any QR generator)
    return base64.b64encode(uri.encode()).decode()

def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    """Verify a TOTP code with ±window periods tolerance."""
    code = code.replace(' ', '').strip()
    if not code.isdigit() or len(code) != 6:
        return False
    if PYOTP_AVAILABLE:
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=window)
    # Fallback: check current and adjacent windows
    period = 30
    for offset in range(-window, window + 1):
        counter = int(time.time()) // period + offset
        key = base64.b32decode(secret.upper().replace(' ', ''))
        msg = struct.pack('>Q', counter)
        h = hmac.new(key, msg, hashlib.sha1).digest()  # SHA1 required by RFC 6238 TOTP/HOTP standard
        off = h[-1] & 0x0F
        expected = str(struct.unpack('>I', h[off:off+4])[0] & 0x7FFFFFFF % 1000000).zfill(6)
        if hmac.compare_digest(code, expected):
            return True
    return False

def setup_totp(user_id: int) -> dict:
    """Generate a new TOTP secret for a user (not yet enabled)."""
    secret = generate_totp_secret()
    with get_db() as db:
        db.execute("""
            INSERT OR REPLACE INTO totp_secrets(user_id, secret, enabled)
            VALUES (?, ?, 0)
        """, (user_id, secret))
    return {'secret': secret}

def enable_totp(user_id: int, code: str) -> bool:
    """Enable TOTP after verifying the first code."""
    with get_db() as db:
        row = db.execute("SELECT secret FROM totp_secrets WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return False
        if verify_totp(row['secret'], code):
            db.execute("""
                UPDATE totp_secrets SET enabled=1, verified_at=CURRENT_TIMESTAMP
                WHERE user_id=?
            """, (user_id,))
            # Generate backup codes
            _generate_backup_codes(user_id, db)
            return True
    return False

def disable_totp(user_id: int):
    """Disable TOTP for a user."""
    with get_db() as db:
        db.execute("UPDATE totp_secrets SET enabled=0 WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM backup_codes WHERE user_id=?", (user_id,))

def get_totp_status(user_id: int) -> dict:
    """Get TOTP status for a user."""
    with get_db() as db:
        row = db.execute("SELECT * FROM totp_secrets WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {'enabled': False, 'secret': None}
        return {
            'enabled': bool(row['enabled']),
            'secret': row['secret'] if not row['enabled'] else None,
            'verified_at': row['verified_at'],
        }

# ── Backup Codes ──────────────────────────────────────────────────────────────

def _generate_backup_codes(user_id: int, db) -> list:
    """Generate 10 backup codes for a user."""
    db.execute("DELETE FROM backup_codes WHERE user_id=?", (user_id,))
    codes = []
    for _ in range(10):
        code = secrets.token_hex(4).upper()  # 8-char hex code
        code_formatted = f"{code[:4]}-{code[4:]}"
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        db.execute("""
            INSERT INTO backup_codes(user_id, code_hash) VALUES (?, ?)
        """, (user_id, code_hash))
        codes.append(code_formatted)
    return codes

def get_backup_codes(user_id: int) -> list:
    """Get unused backup codes count."""
    with get_db() as db:
        rows = db.execute("""
            SELECT COUNT(*) as cnt FROM backup_codes
            WHERE user_id=? AND used=0
        """, (user_id,)).fetchone()
        return rows['cnt'] if rows else 0

def verify_backup_code(user_id: int, code: str) -> bool:
    """Verify and consume a backup code."""
    code = code.replace('-', '').replace(' ', '').upper()
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    with get_db() as db:
        row = db.execute("""
            SELECT id FROM backup_codes
            WHERE user_id=? AND code_hash=? AND used=0
        """, (user_id, code_hash)).fetchone()
        if row:
            db.execute("""
                UPDATE backup_codes SET used=1, used_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (row['id'],))
            return True
    return False

def regenerate_backup_codes(user_id: int) -> list:
    """Regenerate backup codes for a user."""
    with get_db() as db:
        return _generate_backup_codes(user_id, db)

# ── YubiKey OTP ───────────────────────────────────────────────────────────────

YUBICLOUD_SERVERS = [
    'https://api.yubico.com/wsapi/2.0/verify',
    'https://api2.yubico.com/wsapi/2.0/verify',
    'https://api3.yubico.com/wsapi/2.0/verify',
    'https://api4.yubico.com/wsapi/2.0/verify',
    'https://api5.yubico.com/wsapi/2.0/verify',
]

def _extract_yubikey_id(otp: str) -> str:
    """Extract the 12-character public ID from a YubiKey OTP."""
    # YubiKey OTP is 44 chars modhex: first 12 = device ID, last 32 = encrypted payload
    if len(otp) < 32:
        return ''
    return otp[:-32]

def validate_yubikey_otp(otp: str, client_id: str = '1', secret_key: str = '') -> dict:
    """
    Validate a YubiKey OTP against the Yubico API.
    For production use, register at https://upgrade.yubico.com/getapikey/
    Default client_id=1 works for testing but has no HMAC verification.
    """
    otp = otp.strip()
    if not re.match(r'^[cbdefghijklnrtuv]{32,48}$', otp):
        return {'valid': False, 'reason': 'Invalid OTP format'}

    nonce = secrets.token_hex(16)
    params = {
        'id': client_id,
        'otp': otp,
        'nonce': nonce,
        'sl': '50',  # 50% of servers must agree
        'timeout': '10',
    }

    for server in YUBICLOUD_SERVERS:
        try:
            url = f"{server}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'FleetPilot/2.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode()
            result = {}
            for line in body.strip().split('\n'):
                if '=' in line:
                    k, v = line.split('=', 1)
                    result[k.strip()] = v.strip()

            status = result.get('status', 'UNKNOWN')
            if status == 'OK':
                if result.get('nonce') != nonce:
                    return {'valid': False, 'reason': 'Nonce mismatch (replay attack?)'}
                return {'valid': True, 'key_id': _extract_yubikey_id(otp), 'status': status}
            elif status in ('REPLAYED_OTP', 'REPLAYED_REQUEST'):
                return {'valid': False, 'reason': 'Replayed OTP — possible replay attack'}
            else:
                return {'valid': False, 'reason': f'Yubico API: {status}'}
        except Exception as e:
            continue  # Try next server

    return {'valid': False, 'reason': 'All Yubico API servers unreachable'}

def register_yubikey(user_id: int, otp: str, label: str = 'YubiKey',
                     client_id: str = '1', secret_key: str = '') -> dict:
    """Register a YubiKey for a user by validating an OTP."""
    result = validate_yubikey_otp(otp, client_id, secret_key)
    if not result['valid']:
        return {'success': False, 'error': result.get('reason', 'Invalid OTP')}

    key_id = result['key_id']
    with get_db() as db:
        try:
            db.execute("""
                INSERT INTO yubikeys(user_id, key_id, label)
                VALUES (?, ?, ?)
            """, (user_id, key_id, label))
            return {'success': True, 'key_id': key_id}
        except sqlite3.IntegrityError:
            return {'success': False, 'error': 'YubiKey already registered'}

def verify_yubikey(user_id: int, otp: str,
                   client_id: str = '1', secret_key: str = '') -> bool:
    """Verify a YubiKey OTP for a registered user."""
    key_id = _extract_yubikey_id(otp.strip())
    with get_db() as db:
        row = db.execute("""
            SELECT id FROM yubikeys
            WHERE user_id=? AND key_id=? AND enabled=1
        """, (user_id, key_id)).fetchone()
        if not row:
            return False

    result = validate_yubikey_otp(otp, client_id, secret_key)
    if result['valid']:
        with get_db() as db:
            db.execute("UPDATE yubikeys SET last_used=CURRENT_TIMESTAMP WHERE id=?",
                       (row['id'],))
        return True
    return False

def get_yubikeys(user_id: int) -> list:
    """Get all registered YubiKeys for a user."""
    with get_db() as db:
        rows = db.execute("""
            SELECT id, key_id, label, enabled, created_at, last_used
            FROM yubikeys WHERE user_id=?
            ORDER BY created_at DESC
        """, (user_id,)).fetchall()
        return [dict(r) for r in rows]

def delete_yubikey(user_id: int, key_db_id: int) -> bool:
    """Delete a registered YubiKey."""
    with get_db() as db:
        cur = db.execute("DELETE FROM yubikeys WHERE id=? AND user_id=?",
                         (key_db_id, user_id))
        return cur.rowcount > 0

# ── WebAuthn / FIDO2 Security Keys ─────────────────────────────────────────────

def _bytes_to_b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _b64url_to_bytes(value: str) -> bytes:
    value = str(value or '').strip()
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def get_webauthn_credentials(user_id: int) -> list:
    """Return public security-key metadata only; private credential material never leaves the database."""
    with get_db() as db:
        rows = db.execute("""
            SELECT id, credential_id, label, sign_count, created_at, last_used
            FROM webauthn_credentials WHERE user_id=? ORDER BY created_at DESC
        """, (user_id,)).fetchall()
        return [dict(row) for row in rows]


def delete_webauthn_credential(user_id: int, credential_db_id: int) -> bool:
    with get_db() as db:
        cursor = db.execute(
            "DELETE FROM webauthn_credentials WHERE id=? AND user_id=?",
            (credential_db_id, user_id),
        )
        return cursor.rowcount > 0


def generate_webauthn_registration(user_id: int, username: str, rp_id: str,
                                    rp_name: str = 'FleetPilot') -> dict:
    """Create browser registration options for an external FIDO2/WebAuthn key."""
    if not WEBAUTHN_AVAILABLE:
        raise RuntimeError('WebAuthn support is not installed on this FleetPilot server.')
    credentials = get_webauthn_credentials(user_id)
    exclude = [
        PublicKeyCredentialDescriptor(
            id=_b64url_to_bytes(item['credential_id']),
            type=PublicKeyCredentialType.PUBLIC_KEY,
        )
        for item in credentials
    ]
    selection = AuthenticatorSelectionCriteria(
        authenticator_attachment=AuthenticatorAttachment.CROSS_PLATFORM,
        resident_key=ResidentKeyRequirement.PREFERRED,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=str(user_id).encode('utf-8'),
        user_name=username,
        user_display_name=username,
        authenticator_selection=selection,
        exclude_credentials=exclude or None,
    )
    return {
        'options': json.loads(options_to_json(options)),
        'challenge': _bytes_to_b64url(options.challenge),
    }


def verify_webauthn_registration(user_id: int, credential: dict, challenge: str,
                                  rp_id: str, origin: str, label: str) -> dict:
    """Validate an attestation response and persist only its public verification data."""
    if not WEBAUTHN_AVAILABLE:
        return {'success': False, 'error': 'WebAuthn support is unavailable.'}
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=_b64url_to_bytes(challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_presence=True,
            require_user_verification=False,
        )
        credential_id = _bytes_to_b64url(verified.credential_id)
        public_key = _bytes_to_b64url(verified.credential_public_key)
        with get_db() as db:
            db.execute("""
                INSERT INTO webauthn_credentials(user_id, credential_id, public_key, sign_count, label)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, credential_id, public_key, verified.sign_count, label or 'Security Key'))
        _log_2fa(user_id, 'webauthn_register', True)
        return {'success': True, 'credential_id': credential_id}
    except sqlite3.IntegrityError:
        return {'success': False, 'error': 'This security key is already registered.'}
    except Exception:
        _log_2fa(user_id, 'webauthn_register', False, 'Registration verification failed')
        return {'success': False, 'error': 'Security-key registration could not be verified.'}


def generate_webauthn_authentication(user_id: int, rp_id: str) -> dict:
    """Create a challenge tied to the pending user and that user’s registered credentials."""
    if not WEBAUTHN_AVAILABLE:
        raise RuntimeError('WebAuthn support is not installed on this FleetPilot server.')
    credentials = get_webauthn_credentials(user_id)
    if not credentials:
        raise RuntimeError('No security key is registered for this account.')
    allow = [
        PublicKeyCredentialDescriptor(
            id=_b64url_to_bytes(item['credential_id']),
            type=PublicKeyCredentialType.PUBLIC_KEY,
        )
        for item in credentials
    ]
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return {
        'options': json.loads(options_to_json(options)),
        'challenge': _bytes_to_b64url(options.challenge),
    }


def verify_webauthn_authentication(user_id: int, credential: dict, challenge: str,
                                    rp_id: str, origin: str) -> dict:
    """Verify a signed assertion and rotate the stored authenticator counter safely."""
    if not WEBAUTHN_AVAILABLE:
        return {'success': False, 'error': 'WebAuthn support is unavailable.'}
    credential_id = credential.get('id') or credential.get('rawId')
    if not credential_id:
        return {'success': False, 'error': 'The browser did not return a credential identifier.'}
    with get_db() as db:
        row = db.execute("""
            SELECT id, credential_id, public_key, sign_count FROM webauthn_credentials
            WHERE user_id=? AND credential_id=?
        """, (user_id, str(credential_id))).fetchone()
    if not row:
        _log_2fa(user_id, 'webauthn', False, 'Unknown credential')
        return {'success': False, 'error': 'This security key is not registered for the account.'}
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=_b64url_to_bytes(challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=_b64url_to_bytes(row['public_key']),
            credential_current_sign_count=int(row['sign_count'] or 0),
            require_user_verification=False,
        )
        with get_db() as db:
            db.execute("""
                UPDATE webauthn_credentials SET sign_count=?, last_used=CURRENT_TIMESTAMP WHERE id=?
            """, (verified.new_sign_count, row['id']))
        _log_2fa(user_id, 'webauthn', True)
        return {'success': True, 'method': 'Security key'}
    except Exception:
        _log_2fa(user_id, 'webauthn', False, 'Authentication verification failed')
        return {'success': False, 'error': 'Security-key authentication could not be verified.'}


# ── 2FA Status ────────────────────────────────────────────────────────────────

def user_has_2fa(user_id: int) -> bool:
    """Check if a user has any 2FA method enabled."""
    with get_db() as db:
        totp = db.execute("""
            SELECT 1 FROM totp_secrets WHERE user_id=? AND enabled=1
        """, (user_id,)).fetchone()
        if totp:
            return True
        yubikey = db.execute("""
            SELECT 1 FROM yubikeys WHERE user_id=? AND enabled=1
        """, (user_id,)).fetchone()
        if yubikey:
            return True
        webauthn = db.execute("""
            SELECT 1 FROM webauthn_credentials WHERE user_id=?
        """, (user_id,)).fetchone()
        if webauthn:
            return True
    return False

def get_2fa_methods(user_id: int) -> dict:
    """Get all 2FA methods for a user."""
    with get_db() as db:
        totp = db.execute("""
            SELECT enabled FROM totp_secrets WHERE user_id=?
        """, (user_id,)).fetchone()
        yubikeys = db.execute("""
            SELECT COUNT(*) as cnt FROM yubikeys WHERE user_id=? AND enabled=1
        """, (user_id,)).fetchone()
        webauthn = db.execute("""
            SELECT COUNT(*) as cnt FROM webauthn_credentials WHERE user_id=?
        """, (user_id,)).fetchone()
        backup = db.execute("""
            SELECT COUNT(*) as cnt FROM backup_codes WHERE user_id=? AND used=0
        """, (user_id,)).fetchone()
    return {
        'totp': bool(totp and totp['enabled']),
        'yubikeys': yubikeys['cnt'] if yubikeys else 0,
        'webauthn': webauthn['cnt'] if webauthn else 0,
        'backup_codes': backup['cnt'] if backup else 0,
    }

def verify_2fa(user_id: int, code: str, method: str = 'auto',
               client_id: str = '1', secret_key: str = '') -> dict:
    """
    Verify a 2FA code for a user.
    method: 'auto' (detect), 'totp', 'yubikey', 'backup_code'
    """
    code = code.strip()

    # Auto-detect method
    if method == 'auto':
        if len(code) >= 32 and re.match(r'^[cbdefghijklnrtuv]+$', code):
            method = 'yubikey'
        elif re.match(r'^[0-9A-F]{4}-[0-9A-F]{4}$', code.upper()) or \
             re.match(r'^[0-9A-F]{8}$', code.upper()):
            method = 'backup_code'
        else:
            method = 'totp'

    if method == 'totp':
        with get_db() as db:
            row = db.execute("""
                SELECT secret FROM totp_secrets WHERE user_id=? AND enabled=1
            """, (user_id,)).fetchone()
            if row and verify_totp(row['secret'], code):
                _log_2fa(user_id, 'totp', True)
                return {'success': True, 'method': 'totp'}
            _log_2fa(user_id, 'totp', False, 'Invalid TOTP code')
            return {'success': False, 'method': 'totp', 'reason': 'Invalid code'}

    elif method == 'yubikey':
        if verify_yubikey(user_id, code, client_id, secret_key):
            _log_2fa(user_id, 'yubikey', True)
            return {'success': True, 'method': 'yubikey'}
        _log_2fa(user_id, 'yubikey', False, 'Invalid YubiKey OTP')
        return {'success': False, 'method': 'yubikey', 'reason': 'Invalid YubiKey OTP'}

    elif method == 'backup_code':
        if verify_backup_code(user_id, code):
            _log_2fa(user_id, 'backup_code', True)
            return {'success': True, 'method': 'backup_code'}
        _log_2fa(user_id, 'backup_code', False, 'Invalid backup code')
        return {'success': False, 'method': 'backup_code', 'reason': 'Invalid backup code'}

    return {'success': False, 'reason': 'Unknown method'}

def _log_2fa(user_id: int, method: str, success: bool, reason: str = None):
    """Log a 2FA attempt."""
    try:
        with get_db() as db:
            db.execute("""
                INSERT INTO tfa_audit_log(user_id, method, success, reason)
                VALUES (?, ?, ?, ?)
            """, (user_id, method, int(success), reason))
    except Exception:
        pass

# ── Cleanup ───────────────────────────────────────────────────────────────────

def cleanup_expired_challenges():
    """Remove expired WebAuthn challenges (older than 5 minutes)."""
    with get_db() as db:
        db.execute("""
            DELETE FROM webauthn_challenges
            WHERE created_at < datetime('now', '-5 minutes')
        """)

# Initialize on import
try:
    init_db()
except Exception as e:
    print(f"[2FA] DB init error: {e}")
