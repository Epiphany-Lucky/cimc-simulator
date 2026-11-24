"""Isolated Windows install/reinstall/uninstall acceptance, not unittest discovery.

Run: python tests/windows_installer_smoke.py PACKAGE_DIRECTORY [--skip-desktop]
Every installation identity, shortcut and directory belongs to this test only.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import winreg

ROOT=Path(__file__).resolve().parents[1]


def run(command,timeout=240):
    result=subprocess.run([str(x) for x in command],cwd=ROOT,timeout=timeout,
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
    if result.returncode:raise RuntimeError(f'Command exited {result.returncode}: {command[0]}\n{result.stdout}')
    return result.stdout


def registry_entry(key_name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key_name,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
            return {name:winreg.QueryValueEx(key,name)[0] for name in ('DisplayName','DisplayVersion','InstallLocation','UninstallString')}
    except FileNotFoundError:return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path)
    parser.add_argument('--version',default='0.8.0')
    parser.add_argument('--skip-desktop',action='store_true',help='For CI runners without an interactive WebView2 desktop')
    args=parser.parse_args()
    if os.name!='nt':parser.error('This acceptance test requires Windows')
    package=args.package.resolve()
    if not (package/'CIMC-Studio.exe').is_file():parser.error('Pass a complete Windows release directory')
    shell=shutil.which('pwsh') or shutil.which('powershell')
    if not shell:raise RuntimeError('PowerShell is required to build the isolated test installer')
    identity=uuid.uuid4().hex[:12]
    test_root=(ROOT/'artifacts'/f'installer-smoke-{identity}').resolve()
    assert test_root.is_relative_to((ROOT/'artifacts').resolve())
    test_root.mkdir()
    installed=test_root/'application'
    display=f'CIMC Studio Test {identity}'
    registry_key=rf'Software\Microsoft\Windows\CurrentVersion\Uninstall\CIMCStudio.InstallerTest.{identity}_is1'
    assert registry_entry(registry_key) is None,'Random test installation identity already exists'
    locations={}
    for name,csidl in (('desktop',0x0010),('programs',0x0002)):
        buffer=ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None,csidl,None,0,buffer)!=0:
            raise RuntimeError(f'Cannot locate the current user {name} folder')
        locations[name]=buffer.value
    group=Path(locations['programs'])/display
    shortcut=Path(locations['desktop'])/(display+'.lnk')
    assert not group.exists() and not shortcut.exists(),'Random test shortcuts already exist'
    report={'testId':identity,'package':str(package),'installDirectory':str(installed),'desktopTest':not args.skip_desktop,'passed':False}
    report_path=test_root/'result.json'
    sentinel=installed/'my-exported-wiring.json'
    sentinel_text='{"keep":"user export must survive uninstall"}'
    uninstaller=installed/'unins000.exe'
    failure=None
    try:
        output=run([shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',ROOT/'scripts/build-windows-installer.ps1',
                    '-Version',args.version,'-PackageDirectory',package,'-OutputDirectory',test_root,'-TestId',identity],timeout=600)
        (test_root/'compile.log').write_text(output,encoding='utf-8')
        setup=test_root/f'CIMC-Studio-{args.version}-Test-{identity}-Setup-x64.exe'
        assert setup.is_file(),output
        install_args=['/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/LANG=chinesesimplified',
                      f'/DIR={installed}','/TASKS=desktopicon']
        run([setup,*install_args,f'/LOG={test_root / "install.log"}'])
        entry=registry_entry(registry_key)
        assert entry and entry['DisplayName']==display and entry['DisplayVersion']==args.version,entry
        assert Path(entry['InstallLocation']).resolve()==installed,entry
        assert (group/(display+'.lnk')).is_file() and (group/(display+' - Web.lnk')).is_file()
        assert shortcut.is_file() and uninstaller.is_file()
        for name in ('CIMC-Studio.exe','CIMC-Engine.exe','web/assets/schematics/GD32F470-V1.0-schematic.pdf'):
            assert hashlib.sha256((installed/name).read_bytes()).digest()==hashlib.sha256((package/name).read_bytes()).digest(),name
        sentinel.write_text(sentinel_text,encoding='utf-8')
        report['registeredInstallation']=entry
        report['packageExecution']=run([sys.executable,'-X','utf8',ROOT/'tests/package_smoke.py',installed],timeout=900).strip()
        if not args.skip_desktop:
            report['desktopExecution']=run([sys.executable,'-X','utf8',ROOT/'tests/desktop_smoke.py',installed/'CIMC-Studio.exe',
                                            '--output',test_root/'installed-desktop'],timeout=180).strip()
        run([setup,*install_args,f'/LOG={test_root / "reinstall.log"}'])
        assert registry_entry(registry_key)['InstallLocation']==entry['InstallLocation']
        assert len(list(installed.glob('unins*.exe')))==1
        assert sentinel.read_text(encoding='utf-8')==sentinel_text
        report['reinstallPassed']=True
        run([uninstaller,'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',f'/LOG={test_root / "uninstall.log"}'])
        # The uninstaller may finish removal from its temporary copy just after exit.
        deadline=time.monotonic()+10
        while uninstaller.exists() and time.monotonic()<deadline:time.sleep(.1)
        assert registry_entry(registry_key) is None
        assert not (installed/'CIMC-Studio.exe').exists() and not (installed/'CIMC-Engine.exe').exists()
        assert not group.exists() and not shortcut.exists()
        assert sentinel.read_text(encoding='utf-8')==sentinel_text
        report['uninstallPreservedUserFile']=True
        report['passed']=True
    except BaseException as error:
        failure=error;report['error']=repr(error)
    finally:
        # Never recursively remove a directory or touch a production installation.
        if uninstaller.is_file():
            try:run([uninstaller,'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',f'/LOG={test_root / "cleanup.log"}'])
            except Exception as error:report['cleanupError']=repr(error)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if failure:raise failure
    print('PASS: isolated current-user install, shortcuts/HKCU entry, installed firmware execution, reinstall, uninstall and user-file retention')
    print(report_path)


if __name__=='__main__':main()
