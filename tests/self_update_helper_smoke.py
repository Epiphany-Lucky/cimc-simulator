"""Run the real Windows update helper against an isolated executable fixture.

The fixture writes witnesses and copies itself as the restart target. It owns no
installer identity, registry entry, shortcuts or production application files.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'engine'))
from self_update import SelfUpdater


def main():
    if sys.platform != 'win32':
        raise SystemExit('This acceptance runs on Windows.')
    shell = str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
    output = ROOT/'artifacts'/'self-update-helper-smoke.json'
    output.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='CIMC update 中文 ') as temporary:
        directory = Path(temporary)
        fixture = directory/'fixture.exe'
        compile_script = directory/'compile.ps1'
        compile_script.write_text(r'''param([string]$Destination)
$ErrorActionPreference = 'Stop'
Add-Type -OutputAssembly $Destination -OutputType ConsoleApplication -TypeDefinition @'
using System;
using System.IO;
using System.Diagnostics;
public static class Fixture {
    public static int Main(string[] args) {
        string witness = Environment.GetEnvironmentVariable("CIMC_UPDATE_WITNESS");
        string own = Process.GetCurrentProcess().MainModule.FileName;
        if (Path.GetFileName(own) == "CIMC-Studio.exe") {
            File.WriteAllText(witness, "restarted");
            return 0;
        }
        File.WriteAllLines(witness + ".arguments", args);
        foreach (string arg in args) {
            if (arg.StartsWith("/DIR=")) {
                string destination = arg.Substring(5).Trim('"');
                Directory.CreateDirectory(destination);
                File.Copy(own, Path.Combine(destination, "CIMC-Studio.exe"));
                File.WriteAllText(witness + ".installed", "installed");
                return 0;
            }
        }
        return 1;
    }
}
'@
''', encoding='utf-8-sig')
        subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(compile_script),
                        '-Destination', str(fixture)], check=True, capture_output=True, timeout=30)
        payload = fixture.read_bytes()
        asset = {'name': 'CIMC-Studio-9.0.0-Setup-x64.exe',
                 'url': 'https://github.com/Epiphany-Lucky/cimc-simulator/releases/download/v9.0.0/CIMC-Studio-9.0.0-Setup-x64.exe',
                 'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
        checker = Mock()
        checker.check.return_value = {'status': 'ok', 'available': True, 'latestVersion': '9.0.0',
                                     'assetDetails': {'windowsInstaller': asset}}
        updater = SelfUpdater(checker, directory, cache_root=directory/'cache',
                              opener=lambda *_args, **_kwargs: io.BytesIO(payload))
        updater.start('9.0.0')
        updater.thread.join(5)
        assert updater.state()['status'] == 'ready', updater.state()
        updater.destination = directory/'安装文件夹 with spaces'
        witness = directory/'restart-witness.txt'
        waiter = subprocess.Popen([shell, '-NoProfile', '-Command', 'Start-Sleep -Seconds 3'],
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        helper = None
        try:
            with patch.dict(os.environ, {'CIMC_DESKTOP_PID': str(waiter.pid), 'CIMC_UPDATE_WITNESS': str(witness)}):
                command = updater._installer_command()
            # This test process remains alive to inspect the helper, so the fake
            # engine and desktop ownership both use our bounded waiter process.
            command[command.index('-EngineProcessId')+1] = str(waiter.pid)
            env = dict(os.environ, CIMC_UPDATE_WITNESS=str(witness))
            helper = subprocess.Popen(command, env=env, creationflags=subprocess.CREATE_NO_WINDOW,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(.8)
            assert not Path(str(witness)+'.installed').exists(), 'Installed before the application exited'
            waiter.wait(timeout=10)
            stdout, stderr = helper.communicate(timeout=30)
            helper_log = updater.download.parent/'update-helper.log'
            log_text = helper_log.read_text(encoding='utf-8-sig') if helper_log.exists() else ''
            assert helper.returncode == 0, (stdout, stderr, log_text)
            deadline = time.monotonic()+10
            while not witness.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            assert witness.read_text(encoding='utf-8') == 'restarted'
            arguments = Path(str(witness)+'.arguments').read_text(encoding='utf-8').splitlines()
            assert '/DIR='+str(updater.destination) in arguments, arguments
            assert '/VERYSILENT' in arguments
            report = {'passed': True, 'waitedForApplicationExit': True, 'installerDigestVerified': True,
                      'customChineseSpacedPathPreserved': True, 'installerExitCodeChecked': True,
                      'restartedApplication': True, 'productionInstallationTouched': False,
                      'helperLog': (updater.download.parent/'update-helper.log').read_text(encoding='utf-8').strip()}
            output.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        finally:
            if waiter.poll() is None:
                waiter.terminate()
                waiter.wait(5)
            if helper and helper.poll() is None:
                helper.terminate()
                helper.wait(5)
    print('PASS: real Windows helper waits, verifies, installs into a spaced Chinese path and restarts the executable fixture')


if __name__ == '__main__':
    main()
