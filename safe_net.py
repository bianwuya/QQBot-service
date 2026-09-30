"""Public-only, DNS-pinned downloads. No proxy, cookies or LAN access for arbitrary URLs."""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from pathlib import Path
from urllib.parse import urlsplit, urljoin, unquote, quote

class Rejected(ValueError):
    pass

def safe_name(value, default='文件'):
    value = str(value).replace('\\', '/').split('/')[-1]
    value = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', value).strip(' .')[:90]
    if not value or value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{x}' for x in range(10)],*[f'LPT{x}' for x in range(10)]}:
        value = default
    return value

# Public DoH resolvers used only when system DNS answers non-global addresses
# (e.g. proxy fake-IP/TUN mode). They are reached by literal global IPs, so they
# work without trusting the local resolver; returned answers are still fully
# validated before any connection is made.
_DOH_ENDPOINTS = (
    ('1.1.1.1', 'cloudflare-dns.com', '/dns-query'),
    ('223.5.5.5', 'alidns.com', '/resolve'),
)


def _global_ip(value):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    if not ip.is_global or (getattr(ip, 'ipv4_mapped', None) and not ip.ipv4_mapped.is_global):
        return None
    return str(ip)


def _doh_addresses(host, resolver_ip_timeout=6):
    """Resolve host via public DNS-over-HTTPS; literal-IP endpoints, JSON answers."""
    for ip_addr, name, path in _DOH_ENDPOINTS:
        conn = None
        try:
            conn = PinnedHTTPS(name, 443, ip_addr)
            conn.request('GET', path + '?name=' + quote(host) + '&type=A',
                         headers={'Host': name, 'Accept': 'application/dns-json',
                                  'User-Agent': 'Mozilla/5.0 QQBot/1.0'})
            resp = conn.getresponse()
            body = resp.read(65536)
            conn.close(); conn = None
            if resp.status != 200:
                continue
            answers = json.loads(body.decode('utf-8', 'replace')).get('Answer') or []
            out = []
            for answer in answers:
                value = str(answer.get('data') or '').strip()
                if answer.get('type') == 1 and _global_ip(value):
                    out.append(value)
            if out:
                return out
        except Exception:
            if conn is not None:
                try: conn.close()
                except Exception: pass
            continue
    return []


def public_target(url, resolver=socket.getaddrinfo, high_ports=False, doh=None):
    try:
        u = urlsplit(url)
        if u.scheme not in ('https','http') or not u.hostname or u.username or u.password:
            raise Rejected('仅支持无凭据的公开 HTTP/HTTPS 链接')
        if u.port not in (None,80,443) and not (high_ports and u.port is not None and 1024<=u.port<=65535):
            raise Rejected('不允许非标准网络端口')
        host = u.hostname.encode('idna').decode('ascii')
        port = u.port or (443 if u.scheme=='https' else 80)
        if '%' in host: raise Rejected('无效地址')
        addresses = list(dict.fromkeys(x[4][0] for x in resolver(host,port,type=socket.SOCK_STREAM)))
        if not addresses: raise Rejected('无法解析地址')
        checked = [_global_ip(a) for a in addresses]
        if None in checked:
            # Anti-rebinding: mixed global+reserved answers always block. DoH
            # rescue only when every system answer is non-global (proxy
            # fake-IP/TUN mode) and the host is a name, never an IP literal.
            rescued = []
            if all(v is None for v in checked) and resolver is socket.getaddrinfo:
                try: ipaddress.ip_address(host)
                except ValueError:
                    rescued = (_doh_addresses if doh is None else doh)(host)
            rescued = [g for g in (_global_ip(a) for a in rescued) if g]
            if not rescued: raise Rejected('禁止访问本机、内网、保留地址或云元数据')
            addresses = rescued
        return u, host, port, addresses[0]
    except (ValueError, UnicodeError, socket.gaierror) as e:
        if isinstance(e,Rejected):raise
        raise Rejected('链接地址无效或无法解析') from None

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip):
        super().__init__(host,port,timeout=20,context=ssl.create_default_context())
        self.ip = ip
    def connect(self):
        self.sock = self._context.wrap_socket(socket.create_connection((self.ip,self.port),self.timeout),server_hostname=self.host)

class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip):
        super().__init__(host,port,timeout=20);self.ip=ip
    def connect(self):
        self.sock=socket.create_connection((self.ip,self.port),self.timeout)

def open_public(url, headers=None, host_guard=None, high_ports=False):
    for _ in range(6):
        u,host,port,ip=public_target(url,high_ports=high_ports)
        if host_guard and not host_guard(host):raise Rejected('跳转到不支持的视频平台')
        conn=(PinnedHTTPS if u.scheme=='https' else PinnedHTTP)(host,port,ip)
        h={'User-Agent':'Mozilla/5.0 QQBot/1.0','Accept-Encoding':'identity'}
        # Never forward Cookie / Authorization to a redirect target.
        for k,v in (headers or {}).items():
            if k.lower() in ('user-agent','referer','accept') and '\n' not in str(v) and '\r' not in str(v):h[k]=str(v)
        conn.request('GET',(u.path or '/')+('?' + u.query if u.query else ''),headers=h)
        response=conn.getresponse()
        if response.status in (301,302,303,307,308):
            loc=response.getheader('Location');conn.close()
            if not loc:raise Rejected('跳转缺少目标')
            url=urljoin(url,loc);continue
        if response.status!=200:
            conn.close();raise Rejected('下载源拒绝访问，HTTP '+str(response.status))
        return url,conn,response
    raise Rejected('链接跳转过多')

def resolve_public(url, host_guard):
    final,conn,resp=open_public(url,host_guard=host_guard)
    conn.close();return final

def download(url, destination, limit, headers=None, total_timeout=180, high_ports=False):
    final,conn,resp=open_public(url,headers,high_ports=high_ports)
    dest=Path(destination)
    try:
        declared=resp.getheader('Content-Length')
        if declared and int(declared)>limit:raise Rejected('文件超过大小限制')
        suggested=safe_name(unquote(urlsplit(final).path.split('/')[-1]),'下载文件.bin')
        disposition=resp.getheader('Content-Disposition','')
        m=re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)",disposition,re.I)
        if m:suggested=safe_name(unquote(m.group(1) or m.group(2)))
        start=time.monotonic();size=0
        with dest.open('xb') as f:
            while True:
                chunk=resp.read(65536)
                if not chunk:break
                size+=len(chunk)
                if size>limit or time.monotonic()-start>total_timeout:raise Rejected('下载超限或超时')
                f.write(chunk)
        if not size:raise Rejected('下载内容为空')
        return suggested,size
    except Exception:
        dest.unlink(missing_ok=True);raise
    finally:conn.close()
