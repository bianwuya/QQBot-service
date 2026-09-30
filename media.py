"""Supported video shares -> bounded local MP4. No shell command interpolation."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin,urlsplit,urlunsplit
from safe_net import PinnedHTTPS, Rejected, download, public_target, resolve_public, safe_name

PLATFORMS={'bilibili':('bilibili.com','b23.tv'),'douyin':('douyin.com','iesdouyin.com'),'xiaohongshu':('xiaohongshu.com','xhslink.com')}
DOUYIN_SHARE_UA=('Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 '
                 '(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1')

def platform_of(url):
    try:
        u=urlsplit(url);host=(u.hostname or '').lower()
        if u.scheme not in ('http','https') or u.username or u.password or u.port not in (None,80,443):return None
        for platform,domains in PLATFORMS.items():
            if any(host==d or host.endswith('.'+d) for d in domains):return platform
    except ValueError:pass
    return None

def video_identity(url):
    """Resolve allowed short links; store a digest, never the URL, in dedupe claims."""
    platform=platform_of(url)
    if not platform:raise Rejected('不支持的视频平台')
    final=resolve_public(url,lambda host:any(host==d or host.endswith('.'+d) for d in PLATFORMS[platform]))
    split=urlsplit(final);path=split.path.rstrip('/')
    patterns={'bilibili':r'/video/(BV[a-zA-Z0-9]+|av\d+)',
              'douyin':r'/video/(\d+)',
              'xiaohongshu':r'/(?:explore|discovery/item)/(\w+)'}
    found=re.search(patterns[platform],path,re.I)
    # Unknown URL forms keep their query: it can contain the actual media ID.
    canonical=(found.group(1) if found else urlunsplit(('',split.hostname or '',path,split.query,'')))
    digest=hashlib.sha256((platform+':'+canonical).encode()).hexdigest()
    return platform,digest

def share_urls(segments):
    values=[]
    def walk(obj,depth=0):
        if depth>10:return
        if isinstance(obj,str):values.append(obj.replace('\\/','/'))
        elif isinstance(obj,dict):
            for v in obj.values():walk(v,depth+1)
        elif isinstance(obj,list):
            for v in obj[:100]:walk(v,depth+1)
    for seg in segments:
        if seg.get('type')=='text':walk(seg.get('data',{}).get('text',''))
        elif seg.get('type')=='json':
            raw=seg.get('data',{}).get('data','')
            if len(str(raw))>100000:continue
            try:walk(json.loads(raw) if isinstance(raw,str) else raw)
            except (ValueError,TypeError):pass
    urls=[]
    for value in values:
        for url in re.findall(r'https?://[^\s<>"\x00-\x20]+',value):
            url=url.rstrip("。，、！？）)]}'；;")
            if platform_of(url) and url not in urls:urls.append(url)
    return urls[:3]

def run_bounded(args,directory,timeout=90,max_output=8*1024*1024,ok_codes=(0,)):
    """Use temporary files, not unbounded PIPE capture; no secrets are logged."""
    import time
    directory=Path(directory)
    output=directory/'child-output.tmp';err=directory/'child-error.tmp'
    with output.open('wb') as out,err.open('wb') as stderr:
        child=subprocess.Popen(args,stdout=out,stderr=stderr,stdin=subprocess.DEVNULL,shell=False,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        from process_limits import attach_job
        close_job=attach_job(child)
        start=time.monotonic()
        try:
            while child.poll() is None:
                if time.monotonic()-start>timeout or output.stat().st_size+err.stat().st_size>max_output:
                    raise Rejected('处理超时或输出超限')
                time.sleep(.1)
        finally:
            if child.poll() is None:child.kill()
            child.wait()
            if close_job:close_job()
    content=output.read_bytes();output.unlink(missing_ok=True);err.unlink(missing_ok=True)
    if child.returncode not in ok_codes:raise Rejected('视频暂无法解析：可能需要登录 Cookie、链接已失效或平台限制；未绕过付费/权限限制。')
    return content

def _ytdlp_source(final,directory,cfg,p):
    """Metadata + direct media download via yt-dlp. Returns (video_path,audio_path,title,duration)."""
    limit=cfg['limits']['video_bytes']
    args=[sys.executable,'-X','utf8','-m','yt_dlp','--ignore-config','--no-playlist','--skip-download','--dump-single-json',
          '--no-cache-dir','--no-warnings','--socket-timeout','15','--retries','1',
          '--extractor-retries','1','--use-extractors','BiliBili,Douyin,XiaoHongShu,generic']
    cookie=cfg.get('cookie_files',{}).get(p)
    if cookie:
        if not Path(cookie).is_file():raise Rejected('已配置的平台 Cookie 文件不存在')
        args+=['--cookies',cookie]
    elif p=='douyin':
        # Anonymous guest cookies only: public ttwid registration + local fingerprint id.
        # No browser/login state is read; failures fall back to a cookie-less attempt.
        try:
            from guest_cookies import douyin_cookie_header, write_netscape_cookiefile, USER_AGENT
            cookie_path=write_netscape_cookiefile(douyin_cookie_header(),directory/'guest-cookies.txt')
            args+=['--cookies',str(cookie_path),'--user-agent',USER_AGENT,'--impersonate','chrome']
        except Exception:pass
    args+=['--',final]
    # yt-dlp exits 101 (DownloadCancelled) after --max-downloads 1 completes; JSON output is still valid.
    try:data=json.loads(run_bounded(args,directory,timeout=90,ok_codes=(0,101)))
    except ValueError:raise Rejected('视频暂无法解析：可能需要登录 Cookie、链接已失效或平台限制；未绕过付费/权限限制。')
    if data.get('is_live') or data.get('_type') in ('playlist','multi_video'):
        raise Rejected('不下载直播或整个合集，请提供单个视频')
    if (data.get('duration') or 0)>cfg['limits']['video_seconds']:raise Rejected('视频时长超过限制')
    formats=data.get('formats') or [data]
    # Only direct HTTP(S) media. HLS/DASH manifests are not delegated to ffmpeg.
    usable=[f for f in formats if f.get('url','').startswith(('http://','https://'))
            and f.get('protocol','https') in ('http','https')
            and not f.get('has_drm') and (f.get('filesize') or 0)<=limit]
    videos=[f for f in usable if f.get('vcodec') not in (None,'none') and (f.get('height') or 0)<=1080]
    if not videos:raise Rejected('未找到可直接下载的公开视频流（仅图文/需登录/加密流不转换）')
    video=max(videos,key=lambda f:(min(f.get('height') or 0,720),f.get('acodec') not in (None,'none'),f.get('tbr') or 0))
    vpath=directory/'source-video.bin'
    # Platform CDN stream URLs (extractor-provided): allow unprivileged high ports; public-IP checks stay.
    _,size=download(video['url'],vpath,limit,video.get('http_headers') or data.get('http_headers'),high_ports=True)
    audio=None
    if video.get('acodec') in (None,'none'):
        audios=[f for f in usable if f.get('vcodec')=='none' and f.get('acodec') not in (None,'none')]
        if audios:
            af=max(audios,key=lambda f:f.get('abr') or 0);audio=directory/'source-audio.bin'
            download(af['url'],audio,limit-size,af.get('http_headers') or data.get('http_headers'),high_ports=True)
    return vpath,audio,data.get('title','视频'),data.get('duration') or 0

def _douyin_aweme_id(url):
    for pattern in (r'/video/(\d+)',r'/share/video/(\d+)',r'/note/(\d+)',r'modal_id=(\d+)'):
        m=re.search(pattern,url)
        if m:return m.group(1)
    return None

def _douyin_guard(host):
    return any(host==d or host.endswith('.'+d) for d in PLATFORMS['douyin'])

def _douyin_share_source(url,directory,cfg):
    """Fallback for Douyin: parse the public mobile share page (anonymous guest only).

    No signature reverse-engineering and no login state; guest cookies come from the
    public ttwid registration endpoint. Returns (video_path,None,title,duration).
    """
    from guest_cookies import douyin_cookie_header
    aweme=_douyin_aweme_id(url)
    if not aweme:
        final=resolve_public(url,_douyin_guard)
        aweme=_douyin_aweme_id(final)
    if not aweme:raise Rejected('无法从抖音链接中识别视频编号')
    share='https://www.iesdouyin.com/share/video/'+aweme
    cookie=douyin_cookie_header()
    current=share;body=None
    for _ in range(6):
        u,host,port,ip=public_target(current)
        if not _douyin_guard(host):raise Rejected('跳转到不支持的视频平台')
        conn=PinnedHTTPS(host,port,ip)
        headers={'User-Agent':DOUYIN_SHARE_UA,'Accept':'text/html','Accept-Language':'zh-CN,zh;q=0.9',
                 'Referer':'https://www.douyin.com/'}
        # Cookies are attached only to whitelisted Douyin hosts, never to redirect targets elsewhere.
        if cookie:headers['Cookie']=cookie
        try:
            conn.request('GET',(u.path or '/')+('?' + u.query if u.query else ''),headers=headers)
            resp=conn.getresponse()
            if resp.status in (301,302,303,307,308):
                loc=resp.getheader('Location');conn.close()
                if not loc:raise Rejected('跳转缺少目标')
                current=urljoin(current,loc);continue
            if resp.status!=200:raise Rejected('抖音分享页拒绝访问，HTTP '+str(resp.status))
            data=resp.read(512*1024)
            if len(data)>=512*1024:raise Rejected('抖音分享页响应超限')
            body=data.decode('utf-8',errors='replace')
        finally:conn.close()
        break
    if body is None:raise Rejected('抖音分享页跳转过多')
    m=re.search(r'window\._ROUTER_DATA\s*=\s*(\{.*?\})</script>',body,re.S)
    if not m:raise Rejected('抖音分享页未返回可解析数据（可能需要验证或链接已失效）')
    try:router=json.loads(m.group(1))
    except ValueError:raise Rejected('抖音分享页数据格式异常')
    def find_items(obj,depth=0):
        if depth>12:return
        if isinstance(obj,dict):
            if 'play_addr' in obj and isinstance(obj.get('play_addr'),dict):yield obj
            for v in obj.values():yield from find_items(v,depth+1)
        elif isinstance(obj,list):
            for v in obj[:20]:yield from find_items(v,depth+1)
    item=next(find_items(router),None)
    if not item:raise Rejected('抖音分享页未包含视频流（可能是图文或已删除）')
    duration_ms=item.get('video',{}).get('duration') or item.get('duration') or 0
    duration=float(duration_ms)/1000 if duration_ms>2000 else float(duration_ms)
    if duration>cfg['limits']['video_seconds']:raise Rejected('视频时长超过限制')
    urls=[str(x) for x in item['play_addr'].get('url_list',[]) if str(x).startswith('https://')]
    if not urls:raise Rejected('抖音未返回可下载的公开视频流')
    play=urls[0].replace('/playwm/','/play/')
    vpath=directory/'source-video.bin'
    download(play,vpath,cfg['limits']['video_bytes'],{'User-Agent':DOUYIN_SHARE_UA,'Referer':share},high_ports=True)
    return vpath,None,item.get('desc','') or '视频',duration

def get_video(url,directory,cfg):
    p=platform_of(url)
    if not p:raise Rejected('目前只支持 B站、抖音和小红书视频链接')
    final=resolve_public(url,lambda host:any(host==d or host.endswith('.'+d) for d in PLATFORMS[p]))
    if final.rstrip('/')==url.rstrip('/'):final=url
    directory=Path(directory);limit=cfg['limits']['video_bytes']
    try:
        vpath,audio,title,declared=_ytdlp_source(final,directory,cfg,p)
    except Rejected:
        if p!='douyin':raise
        vpath,audio,title,declared=_douyin_share_source(final,directory,cfg)
    probe=Path(cfg['ffmpeg_dir'])/'ffprobe.exe'
    source_meta=json.loads(run_bounded([str(probe),'-v','error','-protocol_whitelist','file,pipe','-show_entries','format=duration','-of','json',str(vpath)],directory,timeout=20))
    source_duration=float(source_meta.get('format',{}).get('duration') or declared or 0)
    if source_duration<=0 or source_duration>cfg['limits']['video_seconds']:
        raise Rejected('无法确认视频时长或时长超过限制，未截断发送')
    ff=Path(cfg['ffmpeg_dir'])/'ffmpeg.exe'
    output=directory/(safe_name(title)[:65]+'.mp4')
    args=[str(ff),'-hide_banner','-loglevel','error','-nostdin','-protocol_whitelist','file,pipe','-i',str(vpath)]
    if audio:args+=['-protocol_whitelist','file,pipe','-i',str(audio),'-map','0:v:0','-map','1:a:0']
    else:args+=['-map','0:v:0','-map','0:a:0?']
    # Produce H.264/AAC MP4 for in-QQ playback, limited threads, duration and file size.
    args+=['-c:v','libx264','-preset','veryfast','-crf','25','-threads','2','-vf',"scale='trunc(min(1280,iw)/2)*2':-2",'-pix_fmt','yuv420p',
           '-c:a','aac','-b:a','128k','-t',str(cfg['limits']['video_seconds']),'-fs',str(limit),'-movflags','+faststart','-y',str(output)]
    run_bounded(args,directory,timeout=240)
    if not output.exists() or not 0<output.stat().st_size<limit:raise Rejected('视频转码超过大小限制')
    meta=json.loads(run_bounded([str(probe),'-v','error','-protocol_whitelist','file,pipe','-show_entries','format=duration:stream=codec_type,codec_name','-of','json',str(output)],directory,timeout=20))
    if not any(s.get('codec_name')=='h264' for s in meta.get('streams',[])):raise Rejected('输出视频校验失败')
    actual=float(meta.get('format',{}).get('duration',0))
    if source_duration and actual<source_duration-3:raise Rejected('视频未完整转码，拒绝发送截断内容')
    return output
