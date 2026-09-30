"""Local-operator configured scripts only; no model supplied paths or argv."""
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
import requests


class AppFailure(RuntimeError):
    pass


def script_command(method):
    if not isinstance(method, dict) or method.get('kind') != 'script':
        raise AppFailure('invalid_method')
    script=Path(method.get('script',''))
    if not script.is_absolute() or script.suffix.lower()!='.ps1' or not script.is_file() or script.is_symlink():
        raise AppFailure('invalid_script')
    host=method.get('host','powershell')
    if host=='powershell':
        exe=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    elif host=='pwsh':
        exe=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'PowerShell/7/pwsh.exe'
    else:raise AppFailure('invalid_host')
    args=method.get('args',[])
    if not isinstance(args,list) or len(args)>12 or not all(isinstance(a,str) and len(a)<=200 and '\x00' not in a for a in args):
        raise AppFailure('invalid_arguments')
    if not exe.is_file():raise AppFailure('host_unavailable')
    return [str(exe),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script.resolve()),*args]


class Executor:
    def status(self, app):
        method=app['status_method'];timeout=min(5,app['timeout'])
        if isinstance(method,dict) and method.get('kind')=='http':
            url=method.get('url','');p=urlsplit(url)
            if p.scheme!='http' or p.hostname!='127.0.0.1' or p.username or p.password or p.fragment:
                raise AppFailure('invalid_status_endpoint')
            session=requests.Session();session.trust_env=False
            try:
                with session.get(url,timeout=(2,timeout),allow_redirects=False,stream=True) as response:
                    return {'online':response.status_code==200}
            except requests.RequestException:return {'online':False}
            finally:session.close()
        try:
            result=subprocess.run(script_command(method),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL,timeout=timeout,shell=False)
            return {'online':result.returncode==0}
        except subprocess.TimeoutExpired:raise AppFailure('timeout') from None

    def execute(self, app, action, detach=False):
        method=app[action+'_method'];command=script_command(method)
        if detach:
            if os.name!='nt':raise AppFailure('unsupported_platform')
            subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             shell=False,close_fds=True,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
            return {'state':'scheduled','verify_after_restart':True}
        try:
            result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                  shell=False,timeout=app['timeout'])
        except subprocess.TimeoutExpired:
            # Killing the launcher cannot roll back already accepted application work.
            raise AppFailure('timeout_unknown') from None
        if result.returncode:raise AppFailure('application_failed')
        return {'state':'command_completed','status':self.status(app)}
