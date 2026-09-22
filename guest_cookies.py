"""Anonymous guest cookies for public video pages. No login state, no paywall bypass.

Douyin risk control demands fresh cookies for anonymous parsing; yt-dlp's own error
text says "Fresh cookies (not necessarily logged in) are needed". This module only
registers a guest ttwid from the public registration endpoint and locally generates
s_v_web_id in the frontend format. Reference implementation: F:/万能视频下载器
downloader/auto_cookies.py (same anonymous-guest approach).
"""
import random
import re
import string
import time
import requests

TTWID_REGISTER_URL = 'https://ttwid.bytedance.com/ttwid/union/register/'
TTWID_REGISTER_BODY = {'region': 'cn', 'aid': 1768, 'needFid': False, 'service': 'www.ixigua.com',
                       'migrate_info': {'ticket': '', 'source': 'node'}, 'cbUrlProtocol': 'https', 'union': True}
DOUYIN_HOMEPAGE = 'https://www.douyin.com/'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0')
_CACHE = {'at': 0.0, 'header': '', 'ua': USER_AGENT}
_TTL = 300.0


def _random_chars(n):
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def generate_s_v_web_id():
    # verify_<13-digit-ms>_<8>_<4>_<4>_<4>_<12>, same shape as the frontend-generated value.
    return f"verify_{int(time.time() * 1000)}_{_random_chars(8)}_{_random_chars(4)}_{_random_chars(4)}_{_random_chars(4)}_{_random_chars(12)}"


def build_douyin_guest_cookies():
    session = requests.Session()
    session.trust_env = False
    session.headers['User-Agent'] = USER_AGENT
    response = session.post(TTWID_REGISTER_URL, json=TTWID_REGISTER_BODY, timeout=15)
    response.raise_for_status()
    ttwid = response.cookies.get('ttwid') or ''
    if not ttwid:
        for chunk in response.headers.get('Set-Cookie', '').split(';'):
            chunk = chunk.strip()
            if chunk.startswith('ttwid='):
                ttwid = chunk[len('ttwid='):].strip()
                break
    if not ttwid:
        raise RuntimeError('ttwid 注册接口未返回游客凭证')
    cookies = {'ttwid': ttwid, 's_v_web_id': generate_s_v_web_id()}
    try:
        session.get(DOUYIN_HOMEPAGE, cookies=cookies, timeout=15)
        for name, value in session.cookies.items():
            if name and value and name not in cookies:
                cookies[name] = value
    except requests.RequestException:
        pass
    return {'header': '; '.join(f'{k}={v}' for k, v in cookies.items() if v), 'ua': USER_AGENT}


def douyin_cookie_header(force_refresh=False):
    """Return an anonymous guest cookie header for douyin, cached for 5 minutes."""
    now = time.time()
    if not force_refresh and _CACHE['header'] and now - _CACHE['at'] <= _TTL:
        return _CACHE['header']
    built = build_douyin_guest_cookies()
    _CACHE.update(at=now, header=built['header'], ua=built['ua'])
    return _CACHE['header']


def write_netscape_cookiefile(header, path, ua=USER_AGENT, domains=('douyin.com', 'iesdouyin.com')):
    """Write a Netscape-format cookies.txt for yt-dlp --cookies."""
    lines = ['# Netscape HTTP Cookie File']
    for part in header.split(';'):
        name, _, value = part.strip().partition('=')
        if not name or not value:
            continue
        value = value.strip()
        for domain in domains:
            lines.append(f'.{domain}\tTRUE\t/\tTRUE\t{int(time.time()) + 86400}\t{name}\t{value}')
    text = '\n'.join(lines) + '\n'
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    return path
