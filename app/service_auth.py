"""Short-lived identity bound to one internal HTTP method, path and JSON body."""
import hashlib
import json
import os
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


def signer():
    secret = os.getenv('INTERNAL_TOKEN', '')
    if not secret:
        raise RuntimeError('INTERNAL_TOKEN is required')
    return URLSafeTimedSerializer(secret, salt='kostcycle-reservation-v1',
                                  signer_kwargs={'digest_method': hashlib.sha256})


def body_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def sign_identity(user_id, method, path, payload):
    return signer().dumps({'uid': user_id, 'method': method, 'path': path, 'body': body_hash(payload)})


def verify_identity(token, method, path, payload):
    try:
        data = signer().loads(token, max_age=30)
        uid = data.get('uid')
        if (type(uid) is int and uid > 0 and data.get('method') == method
                and data.get('path') == path and data.get('body') == body_hash(payload)):
            return uid
    except (BadSignature, SignatureExpired, ValueError, TypeError, AttributeError):
        pass
    return None
