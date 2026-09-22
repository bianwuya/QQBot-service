"""Explicit one-time migration; no credential values are printed."""
from pathlib import Path
import datetime, hashlib, json, os, shutil, subprocess
ROOT = Path('F:/Apps')
DST = ROOT / 'QQBot-service'
STAMP = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
ARCHIVE = ROOT / 'backups' / ('qqbot-legacy-' + STAMP)
PS = 'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'

def main():
    if (DST / 'config.json').exists():
        raise RuntimeError('Migration already configured; refusing overwrite')
    old = json.loads((ROOT/'QQ-OpenAI-Bridge/bridge.config.json').read_text('utf-8-sig'))
    admins = [str(x) for x in old['auth']['admins']]
    if not admins or any(not x.isdigit() for x in admins):
        raise RuntimeError('Invalid admin allowlist')
    runtime = json.loads((ROOT/'LLBot-runtime/bin/llbot/default_config.json').read_text('utf-8-sig'))
    http = next(x for x in runtime['ob11']['connect'] if x['type']=='http')
    if not http.get('token') or http.get('host')!='127.0.0.1':
        raise RuntimeError('OneBot HTTP must be loopback and authenticated')
    cfg = {
        'admins':admins, 'onebot':{'base_url':'http://127.0.0.1:3000','token':http['token']},
        'llm':{'base_url':'http://127.0.0.1:7866/v1','key_file':'F:/Apps/Sub2API/native/.gwkey-current',
               'default_model':'deepseek-v4-flash','timeout':120,'max_tokens':4096},
        'runtime':'F:/Apps/LLBot-runtime','health_port':3002,
        'limits':{'max_pending':40,'max_pending_per_user':3,'cooldown_seconds':3,'max_input_chars':12000,
                  'file_bytes':30*1024*1024,'video_bytes':150*1024*1024,'video_seconds':1200,
                  'extract_chars':40000,'daily_requests_per_user':100,'work_retention_hours':24},
        'group_require_at':True,'video_auto':True,'file_auto':True,'cookie_files':{},
        'notes':'Only explicit admins can manage this Bot. No shell/Agent tools are exposed to any model.'
    }
    ARCHIVE.mkdir(parents=True,exist_ok=False)
    shutil.copy2(ROOT/'LLBot-runtime/bin/llbot/default_config.json',ARCHIVE/'runtime-default-config.before.json')
    # Export disabled legacy task before removing its registration; never touch unrelated tasks.
    ps = "$t=Get-ScheduledTask -TaskName 'QQBridgeWatchdog' -ErrorAction SilentlyContinue; if($t){ if($t.State -eq 'Running'){throw 'Legacy watchdog is running'}; Export-ScheduledTask -TaskName 'QQBridgeWatchdog' | Out-File -Encoding utf8 '"+str(ARCHIVE/'QQBridgeWatchdog.xml')+"' }"
    r=subprocess.run([PS,'-NoProfile','-Command',ps],capture_output=True)
    if r.returncode: raise RuntimeError('Cannot safely export legacy task')
    manifest=[]
    for name in ['LLBot','QQ-OpenAI-Bridge']:
        p=ROOT/name
        for f in p.rglob('*'):
            if f.is_file():
                manifest.append({'path':str(f.relative_to(ROOT)).replace('\\','/'),'size':f.stat().st_size,
                                 'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
    (ARCHIVE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Windows may hold a directory as another terminal's cwd. Copy+verify first;
    # never kill unrelated processes merely to rename that directory.
    for name in ['LLBot','QQ-OpenAI-Bridge']:
        shutil.copytree(ROOT/name,ARCHIVE/name)
    for row in manifest:
        f=ARCHIVE/row['path']
        if hashlib.sha256(f.read_bytes()).hexdigest()!=row['sha256']: raise RuntimeError('Archive verification failed')
    for row in manifest:
        f=ROOT/row['path']
        if hashlib.sha256(f.read_bytes()).hexdigest()!=row['sha256']: raise RuntimeError('Source changed during backup; cleanup aborted')
    leftovers=[]
    for row in manifest:
        try: (ROOT/row['path']).unlink()
        except OSError: leftovers.append(row['path'])
    for name in ['LLBot','QQ-OpenAI-Bridge']:
        p=ROOT/name
        for d in sorted([d for d in p.rglob('*') if d.is_dir()],key=lambda d:len(d.parts),reverse=True)+[p]:
            try:d.rmdir()
            except OSError:pass
    if leftovers: print('locked_legacy_files',len(leftovers))
    # Config is new, written exclusively. Old API keys remain only in the archive, not in this app.
    with (DST/'config.json').open('x',encoding='utf-8',newline='\n') as f: json.dump(cfg,f,ensure_ascii=False,indent=2);f.write('\n')
    r=subprocess.run([PS,'-NoProfile','-Command',"$t=Get-ScheduledTask -TaskName 'QQBridgeWatchdog' -ErrorAction SilentlyContinue; if($t){ Unregister-ScheduledTask -TaskName 'QQBridgeWatchdog' -Confirm:$false }"],capture_output=True)
    print(json.dumps({'archive':str(ARCHIVE),'verified_files':len(manifest),'admins_migrated':len(admins),
                      'config_written':True,'legacy_task_removed':r.returncode==0},ensure_ascii=False))
    (DST/'state/migration.json').write_text(json.dumps({'archive':str(ARCHIVE),'timestamp':STAMP},ensure_ascii=False)+'\n',encoding='utf-8')

if __name__=='__main__':main()
