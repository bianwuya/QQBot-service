"""Read-only NapCat QR diagnosis, optional refresh while waiting. Never prints credentials/QR URLs."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import requests

ROOT = Path(__file__).resolve().parents[1]
NAP = ROOT.parent / 'NapCat-runtime'


def inspect_login(refresh=False):
    cfg = json.loads((NAP / 'napcat/config/webui.json').read_text('utf-8-sig'))
    if cfg.get('host') != '127.0.0.1' or not 1 <= int(cfg['port']) <= 65535:
        raise RuntimeError('Unexpected WebUI address')
    base = 'http://127.0.0.1:' + str(int(cfg['port']))
    session = requests.Session()
    session.trust_env = False
    try:
        hashed = hashlib.sha256((cfg['token'] + '.napcat').encode()).hexdigest()
        r = session.post(base + '/api/auth/login', json={'hash': hashed}, timeout=(3, 8))
        r.raise_for_status()
        login = r.json()
        credential = (login.get('data') or {}).get('Credential')
        if login.get('code') != 0 or not credential:
            raise RuntimeError('NapCat WebUI authentication failed; verify local token/2FA configuration')
        session.headers['Authorization'] = 'Bearer ' + credential

        def api(action, timeout=8):
            response = session.post(base + '/api/QQLogin/' + action, json={}, timeout=(3, timeout))
            response.raise_for_status()
            body = response.json()
            if body.get('code') != 0:
                # Do not print raw responses, login errors, or user/account details.
                raise RuntimeError('NapCat ' + action + ' returned an error')
            return body.get('data') or {}

        status = api('CheckLoginStatus')
        phase = status.get('loginPhase')
        online = bool(status.get('isLogin'))
        scan_accepted = bool(status.get('qrLoginAccepted')) or phase in ('qrcode_scanned', 'initializing')
        refreshed = False
        if not online and not scan_accepted and refresh and phase not in ('reconnecting', 'generating_qrcode'):
            api('RefreshQRcode', timeout=25)
            refreshed = True
            status = api('CheckLoginStatus')
            phase = status.get('loginPhase')
            online = bool(status.get('isLogin'))
            scan_accepted = bool(status.get('qrLoginAccepted')) or phase in ('qrcode_scanned', 'initializing')
        qr_available = False
        if not online and not scan_accepted:
            qr_available = bool(api('GetQQLoginQrcode').get('qrcode'))
        return {'webui_authenticated': True, 'qq_online': online, 'login_phase': phase,
                'scan_accepted': scan_accepted, 'qr_available': qr_available, 'qr_refreshed': refreshed,
                'needs_user_scan': not online and not scan_accepted and qr_available}
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    try:
        result = inspect_login(args.refresh)
        print(json.dumps(result, ensure_ascii=True))
        if not any(result[k] for k in ('qq_online', 'scan_accepted', 'qr_available')):
            return 2
        return 0
    except requests.RequestException:
        print('NapCat WebUI is unavailable or request timed out.', file=sys.stderr)
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        # Our RuntimeError messages are intentionally safe; other exceptions may contain paths.
        print(str(error) if isinstance(error, RuntimeError) else 'Local login configuration could not be read.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
