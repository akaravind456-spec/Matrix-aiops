"""Ed25519 signatures (RFC 8032) in plain Python, so the Lambda needs no extra package.

Used for the signed licence key: the VENDOR signs with a private key that is never shipped; the product only holds the public key and can
verify but not create a key. Slow (milliseconds to a few tens of milliseconds) but only run at start-up and when the licence card loads.
"""
import hashlib

P = 2 ** 255 - 19
Q = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _sha512(s):
    return hashlib.sha512(s).digest()


def _inv(x):
    return pow(x, P - 2, P)


def _add(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % P
    B = (a[1] + a[0]) * (b[1] + b[0]) % P
    C = 2 * a[3] * b[3] * D % P
    DD = 2 * a[2] * b[2] % P
    E, F, G, H = B - A, DD - C, DD + C, B + A
    return (E * F % P, G * H % P, F * G % P, E * H % P)


def _mul(s, pt):
    r = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            r = _add(r, pt)
        pt = _add(pt, pt)
        s >>= 1
    return r


def _equal(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_GY = 4 * _inv(5) % P
_GX = _recover_x(_GY, 0)
BASE = (_GX, _GY, 1, _GX * _GY % P)


def _compress(pt):
    zinv = _inv(pt[2])
    x, y = pt[0] * zinv % P, pt[1] * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, 'little')


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, 'little')
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def _expand(secret):
    h = _sha512(secret)
    a = int.from_bytes(h[:32], 'little')
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _h(s):
    return int.from_bytes(_sha512(s), 'little') % Q


def public_key(secret):
    a, _ = _expand(secret)
    return _compress(_mul(a, BASE))


def sign(secret, msg):
    """Vendor side only. secret is 32 bytes."""
    a, prefix = _expand(secret)
    A = _compress(_mul(a, BASE))
    r = _h(prefix + msg)
    Rs = _compress(_mul(r, BASE))
    s = (r + _h(Rs + A + msg) * a) % Q
    return Rs + int.to_bytes(s, 32, 'little')


def verify(public, msg, signature):
    """True only if signature is valid for msg under public (32 bytes). Never raises."""
    try:
        if len(public) != 32 or len(signature) != 64:
            return False
        A = _decompress(public)
        R = _decompress(signature[:32])
        if A is None or R is None:
            return False
        s = int.from_bytes(signature[32:], 'little')
        if s >= Q:
            return False
        h = _h(signature[:32] + public + msg)
        return _equal(_mul(s, BASE), _add(R, _mul(h, A)))
    except Exception:
        return False
