"""Game-free final persistence regressions for hs-run.sh (stdlib unittest).

Run directly or with unittest discovery; no private environment is required.
The fixture copies the real naming helpers and regression reader. Its only
launcher adaptation is literal /home/mooki relocation to an owned temporary
HOME. Explicit synthetic gate receipts replace gate/workload execution, and
journalctl is a no-host-journal double. tee is the real system executable.
These tests do not establish game, GPU, journal-service or Windows behaviour.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('bash'),
                     'hs-run.sh requires Linux and bash')
class FinalIOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hs-final-io-')
        self.root = Path(self.temp.name)
        self.addCleanup(self.cleanup)
        self.home = self.root / 'home'
        self.harness = self.home / 'Games/.hookshot-harness'
        self.harness.mkdir(parents=True)
        self.copy = self.home / 'Games/.hookshot-h-SYNTHETIC'
        self.copy.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.denied = self.root / 'DENIED'
        deny = '#!/bin/sh\nprintf "%s\\n" "$0" >> ' + shlex.quote(str(self.denied)) + '\nexit 99\n'
        for name in ('systemd-run', 'systemctl', 'service', 'busctl', 'sudo',
                     'ssh', 'scp', 'sftp', 'curl', 'wget', 'gh', 'git', 'hyprctl',
                     'nvidia-smi', 'glxinfo', 'vulkaninfo', 'magick', 'make',
                     'cmake', 'ninja', 'cc', 'c++', 'gcc', 'g++', 'clang',
                     'clang++', 'timeout', 'hookshot', 'longshot'):
            self.executable(self.bin / name, deny)
        self.executable(self.copy / 'hookshot', deny)
        self.executable(self.home / 'Games/hs-intel-slot', deny)
        self.executable(self.home / 'Games/hs-build-slot', deny)
        self.executable(self.home / 'Games/hs-gpu-slot', deny)
        (self.copy / 'image.bin').touch()  # Empty identity marker, not game data.
        (self.copy / 'romfs').mkdir()
        self.executable(self.bin / 'journalctl', '#!/bin/sh\nprintf "%s\\n" "$@" > '
                        + shlex.quote(str(self.root / 'journal-argv')) + '\nexit 0\n')
        for name in ('hs-names.sh', 'hs_names.py'):
            shutil.copy2(SOURCE / 'harness' / name, self.harness / name)
        (self.harness / 'regress').mkdir()
        shutil.copy2(SOURCE / 'regress/run_case.py', self.harness / 'regress/run_case.py')
        self.wrapper = self.harness / 'hs-run.sh'
        text = (SOURCE / 'harness/hs-run.sh').read_text()
        self.wrapper.write_text(text.replace('/home/mooki', shlex.quote(str(self.home))))
        self.wrapper.chmod(0o755)
        self.env = {'PATH': str(self.bin) + ':/usr/bin:/bin', 'HOME': str(self.home),
                    'LC_ALL': 'C', 'LANG': 'C', 'PYTHONDONTWRITEBYTECODE': '1'}
        for key, folder in (('TMPDIR', 'tmp'), ('TMP', 'tmp'), ('TEMP', 'tmp'),
                            ('XDG_CACHE_HOME', 'cache'), ('XDG_CONFIG_HOME', 'config'),
                            ('XDG_DATA_HOME', 'data'), ('XDG_RUNTIME_DIR', 'runtime')):
            path = self.root / folder
            path.mkdir(exist_ok=True)
            self.env[key] = str(path)
        self.assertEqual(shutil.which('tee', path=self.env['PATH']), '/usr/bin/tee')
        self.assertEqual(shutil.which('systemd-run', path=self.env['PATH']), str(self.bin / 'systemd-run'))
        self.journal = self.harness / 'runs.log'
        self.sentinel = b'previous synthetic run\n'
        self.journal.write_bytes(self.sentinel)

    def cleanup(self):
        root = self.root
        self.temp.cleanup()
        self.assertFalse(root.exists())
        print('FINAL_IO_CLEANUP ' + json.dumps({'method': self._testMethodName, 'root': str(root), 'absent': True}), flush=True)

    @staticmethod
    def executable(path, text):
        path.write_text(text)
        path.chmod(0o755)

    def gate(self, summary_directory=False):
        # Synthetic reporting boundary only: never invokes --inner or any workload.
        body = '''#!/bin/bash
set -eu
R=${@: -1}
[ ! -s "$R/memmax" ] || exit 98
printf '124\\n' > "$R/exit.txt"
printf '2026-01-01 00:00:00\\n' > "$R/start.txt"
printf '2026-01-01 00:00:01\\n' > "$R/end.txt"
printf '0.0\\n' > "$R/wall.txt"
printf '0 0 0\\n' > "$R/load-before.txt"
printf '0 0 0\\n' > "$R/load-after.txt"
printf 'SYNTHETIC receipt; no game or GPU\\n' > "$R/hookshot_log.txt"
'''
        if summary_directory:
            body += 'mkdir "$R/summary.txt"\n'
        self.executable(self.home / 'Games/hs-gpu-slot', body)

    def run_wrapper(self):
        run = self.copy / 'runs/final-io'
        argv = [str(self.wrapper), str(self.copy), 'final-io', '2']
        process = subprocess.Popen(argv, env=self.env, cwd=self.root, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            print('FINAL_IO_TIMEOUT ' + json.dumps({'stdout': stdout, 'stderr': stderr}), flush=True)
            self.fail('synthetic wrapper exceeded deadline')
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            pass
        else:
            os.killpg(process.pid, signal.SIGKILL)
            self.fail('wrapper left a process group alive')
        summary = run / 'summary.txt'
        observed = {'method': self._testMethodName, 'argv': argv, 'environment': self.env,
                    'pid_pgid': process.pid, 'wrapper_exit': process.returncode,
                    'stdout': stdout, 'stderr': stderr, 'memmax_bytes': (run / 'memmax').stat().st_size,
                    'receipt': (run / 'exit.txt').read_text(),
                    'summary_type': 'directory' if summary.is_dir() else 'file' if summary.is_file() else 'absent',
                    'summary': summary.read_text() if summary.is_file() else None,
                    'journal_type': 'directory' if self.journal.is_dir() else 'file',
                    'journal': self.journal.read_text() if self.journal.is_file() else None,
                    'kernel_status': json.loads((run / 'kernel-status.json').read_text()),
                    'journal_argv': (self.root / 'journal-argv').read_text(),
                    'denied': self.denied.read_text() if self.denied.exists() else '',
                    'process_group_absent': True}
        print('FINAL_IO_OBSERVATION ' + json.dumps(observed, sort_keys=True), flush=True)
        self.assertEqual(observed['memmax_bytes'], 0)
        self.assertEqual(observed['denied'], '')
        self.assertEqual(observed['receipt'], '124\n')
        self.assertEqual(observed['kernel_status']['journal_exit'], 0)
        self.assertIn('exit=124', stdout)
        return process.returncode, stdout, stderr, run

    def test_summary_write_failure_is_not_success_or_appended(self):
        self.gate(summary_directory=True)
        code, stdout, stderr, run = self.run_wrapper()
        self.assertIn('Is a directory', stderr)
        self.assertTrue((run / 'summary.txt').is_dir())
        self.assertEqual(code, 1, 'summary write failure was hidden')
        self.assertEqual(self.journal.read_bytes(), self.sentinel, 'failed summary was appended')

    def test_log_append_failure_is_not_wrapper_success(self):
        self.gate()
        self.journal.unlink()
        self.journal.mkdir()
        code, stdout, stderr, run = self.run_wrapper()
        self.assertIn('Is a directory', stderr)
        self.assertTrue(self.journal.is_dir())
        self.assertEqual((run / 'summary.txt').read_text(), stdout)
        self.assertEqual(code, 1, 'log append failure was hidden')

    def test_wrapper_zero_preserves_receipt_124_and_persists_summary(self):
        # Compatibility, not a new defect: run_case.py requires wrapper0 + receipt124.
        self.gate()
        code, stdout, stderr, run = self.run_wrapper()
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr, '')
        self.assertEqual((run / 'summary.txt').read_text(), stdout)
        self.assertEqual(self.journal.read_bytes(), self.sentinel
                         + ('2026-01-01 00:00:00 ' + stdout).encode())


if __name__ == '__main__':
    unittest.main(verbosity=2)
