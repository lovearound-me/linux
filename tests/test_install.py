import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock

from lovearound import presenting, update
from tests import until

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LauncherTest(unittest.TestCase):
    def test_runs_the_code_installed_beside_it(self):
        with tempfile.TemporaryDirectory() as prefix:
            os.makedirs(os.path.join(prefix, "bin"))
            shutil.copy(os.path.join(ROOT, "bin", "lovearound"), os.path.join(prefix, "bin"))
            package = os.path.join(prefix, "lib", "lovearound", "lovearound")
            os.makedirs(package)
            open(os.path.join(package, "__init__.py"), "w").close()
            with open(os.path.join(package, "app.py"), "w") as f:
                f.write("def main():\n    print('installed copy')\n    return 0\n")
            out = subprocess.run([sys.executable, os.path.join(prefix, "bin", "lovearound")],
                                 capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), "installed copy", out.stderr)


class KWinScriptTest(unittest.TestCase):
    def test_found_in_the_checkout(self):
        self.assertEqual(presenting.kwin_script_path(), os.path.join(ROOT, "kwin", "fullscreen.js"))


class LauncherPathTest(unittest.TestCase):
    def test_a_checkout_autostarts_by_name(self):
        from lovearound import config
        self.assertEqual(config.launcher(), "lovearound")

    def test_a_checkout_does_not_update_itself(self):
        self.assertIsNone(update.installed_get_sh())


def run_install(*args, tree=ROOT, cwd=None, **env):
    return subprocess.run(["bash", os.path.join(tree, "install.sh"), *args],
                          capture_output=True, text=True, cwd=cwd, env=dict(os.environ, **env))


def missing_module(directory, name):
    with open(os.path.join(directory, name + ".py"), "w") as f:
        f.write("raise ImportError(\"No module named '%s'\")\n" % name)
    return directory


def files_mentioning(root, word):
    found = []
    for d, _, files in os.walk(root):
        for f in files:
            path = os.path.join(d, f)
            with open(path, errors="replace") as text:
                if word in os.path.relpath(path, root).lower() or "me." + word in text.read():
                    found.append(path)
    return found


class InstallScriptTest(unittest.TestCase):
    def test_user_install_and_uninstall(self):
        with tempfile.TemporaryDirectory() as home:
            env = {"HOME": home, "XDG_DATA_HOME": os.path.join(home, "data"),
                   "XDG_CONFIG_HOME": os.path.join(home, "config")}
            done = run_install("--user", **env)
            self.assertEqual(done.returncode, 0, done.stderr)
            local, data = os.path.join(home, ".local"), os.path.join(home, "data")
            self.assertIn("installed to " + local, done.stdout)
            self.assertIn("Add %s/bin to PATH" % local, done.stdout)
            for path in ("bin/lovearound", "lib/lovearound/lovearound/app.py", "lib/lovearound/lovearound/VERSION",
                         "lib/lovearound/get.sh"):
                self.assertTrue(os.path.exists(os.path.join(local, path)), path)
            for path in ("applications/me.lovearound.LoveAround.desktop",
                         "gnome-shell/extensions/lovearound@lovearound.me/metadata.json",
                         "icons/hicolor/48x48/apps/me.lovearound.LoveAround.png"):
                self.assertTrue(os.path.exists(os.path.join(data, path)), path)
            self.assertTrue(os.access(os.path.join(local, "bin", "lovearound"), os.X_OK))
            with open(os.path.join(data, "applications", "me.lovearound.LoveAround.desktop")) as f:
                self.assertIn("\nExec=%s/bin/lovearound %%u\n" % local, f.read())

            def installed(module, expression):
                done = subprocess.run(
                    [sys.executable, "-c", "from lovearound import %s; print(%s)" % (module, expression)],
                    capture_output=True, text=True, cwd=home,
                    env=dict(os.environ, PYTHONPATH=os.path.join(local, "lib", "lovearound")))
                self.assertEqual(done.returncode, 0, done.stderr)
                return done.stdout.strip()
            self.assertEqual(installed("config", "config.launcher()"), os.path.join(local, "bin", "lovearound"))
            self.assertEqual(installed("presenting", "presenting.kwin_script_path()"),
                             os.path.join(local, "lib", "lovearound", "kwin", "fullscreen.js"))
            self.assertEqual(installed("update", "update.installed_get_sh()"),
                             os.path.join(local, "lib", "lovearound", "get.sh"))

            fake = os.path.join(home, "fake")
            os.makedirs(fake)
            refused = run_install("--user", PYTHONPATH=missing_module(fake, "cryptography"), **env)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("cryptography", refused.stderr)
            self.assertTrue(os.path.exists(os.path.join(local, "lib", "lovearound", "lovearound", "app.py")))

            again = run_install("--user", "--as-version", "0.2.99", **env)
            self.assertEqual(again.returncode, 0, again.stderr)
            with open(os.path.join(local, "lib", "lovearound", "lovearound", "VERSION")) as f:
                self.assertEqual(f.read().strip(), "0.2.99")
            # What the app writes on its first launch.
            autostart = os.path.join(home, "config", "autostart", "me.lovearound.LoveAround.desktop")
            os.makedirs(os.path.dirname(autostart))
            with open(autostart, "w") as f:
                f.write("[Desktop Entry]\nExec=%s/bin/lovearound --background\nIcon=me.lovearound.LoveAround\n" % local)
            gone = run_install("--user", "--uninstall", **env)
            self.assertEqual(gone.returncode, 0, gone.stderr)
            shutil.rmtree(fake)
            self.assertEqual(files_mentioning(home, "lovearound"), [])

    def test_only_a_user_install_or_a_package_stage_is_accepted(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as prefix:
            env = {"HOME": home, "XDG_DATA_HOME": os.path.join(home, "data")}
            stage = os.path.join(prefix, "stage")
            for args in ((), ("--prefix", prefix), ("--destdir", stage), ("--user", "--destdir", stage),
                         ("--user", "--prefix", prefix), ("--prefix", prefix, "--destdir", stage, "--user"),
                         ("--prefix", prefix, "--destdir", stage, "--uninstall")):
                done = run_install(*args, **env)
                self.assertEqual(done.returncode, 2, args)
                self.assertIn("--user", done.stderr)
            self.assertEqual(files_mentioning(home, "lovearound"), [])
            self.assertEqual(os.listdir(prefix), [])

    def assert_refused(self, tree, home):
        done = run_install("--user", tree=tree, HOME=home, XDG_DATA_HOME=os.path.join(home, "data"))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("git history", done.stderr)
        self.assertEqual(files_mentioning(home, "lovearound"), [])

    def test_a_tree_without_git_is_refused(self):
        with tempfile.TemporaryDirectory() as tree, tempfile.TemporaryDirectory() as home:
            shutil.copy2(os.path.join(ROOT, "install.sh"), tree)
            self.assert_refused(tree, home)

    def test_a_shallow_clone_is_refused(self):
        with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as home:
            tree = os.path.join(work, "clone")
            subprocess.run(["git", "clone", "-q", "--depth", "1", "--no-checkout", "file://" + ROOT, tree], check=True)
            shutil.copy2(os.path.join(ROOT, "install.sh"), tree)
            self.assert_refused(tree, home)

    def test_a_destdir_run_names_a_missing_dependency(self):
        with tempfile.TemporaryDirectory() as work:
            done = run_install("--prefix", "/usr", "--destdir", os.path.join(work, "stage"),
                               PYTHONPATH=missing_module(work, "cryptography"))
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("cryptography", done.stderr)
            self.assertFalse(os.path.exists(os.path.join(work, "stage")))

    def test_a_relative_destdir_is_the_callers(self):
        with tempfile.TemporaryDirectory() as work:
            try:
                done = run_install("--prefix", "/usr", "--destdir", "stage-under-test", cwd=work)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertTrue(os.path.exists(os.path.join(work, "stage-under-test", "usr", "bin", "lovearound")))
                self.assertFalse(os.path.exists(os.path.join(work, "stage-under-test", "usr", "lib", "lovearound",
                                                             "get.sh")))
            finally:
                shutil.rmtree(os.path.join(ROOT, "stage-under-test"), ignore_errors=True)


def run_get(home, tag, files, *args):
    tarball = os.path.join(home, "release.tar.gz")
    with tarfile.open(tarball, "w:gz") as tar:
        for path, text in files.items():
            data = text.encode()
            entry = tarfile.TarInfo("source/" + path)
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
    stub = os.path.join(home, "stub")
    os.makedirs(stub)
    with open(os.path.join(stub, "curl"), "w") as f:
        f.write('#!/bin/sh\necho "$@" >> "$HOME/curl-log"\nwhile [ "$1" != -o ]; do shift; done\n'
                'cp "%s" "$2"\necho "/%s"\n' % (tarball, tag))
    os.chmod(os.path.join(stub, "curl"), 0o755)
    return subprocess.run(["sh", os.path.join(ROOT, "tools", "get.sh"), *args], capture_output=True, text=True,
                          env=dict(os.environ, HOME=home, PATH=stub + os.pathsep + os.environ["PATH"]))


class GetScriptTest(unittest.TestCase):
    RECORD_ARGS = {"install.sh": 'echo "$@" > "$HOME/args"\n'}

    def test_latest_prints_the_version_and_installs_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            done = run_get(home, "v0.2.99", self.RECORD_ARGS, "--latest")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout, "0.2.99\n")
            self.assertFalse(os.path.exists(os.path.join(home, "args")))
            with open(os.path.join(home, "curl-log")) as f:
                self.assertNotIn("archive", f.read())

    def test_version_installs_that_release(self):
        with tempfile.TemporaryDirectory() as home:
            done = run_get(home, "v0.2.99", self.RECORD_ARGS, "--version", "0.2.50")
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(os.path.join(home, "args")) as f:
                self.assertEqual(f.read().strip(), "--user --as-version 0.2.50")
            with open(os.path.join(home, "curl-log")) as f:
                log = f.read()
            self.assertIn("/archive/refs/tags/v0.2.50.tar.gz", log)
            self.assertNotIn("releases/latest", log)

    def test_an_unknown_option_is_refused(self):
        for args in (("--prefix", "/usr"), ("--version",), ("--latest", "extra")):
            with tempfile.TemporaryDirectory() as home:
                done = run_get(home, "v0.2.99", self.RECORD_ARGS, *args)
                self.assertEqual(done.returncode, 2, args)
                self.assertFalse(os.path.exists(os.path.join(home, "curl-log")), args)

    def test_runs_the_release_install_sh_for_the_user_with_its_version(self):
        with tempfile.TemporaryDirectory() as home:
            done = run_get(home, "v0.2.99", self.RECORD_ARGS)
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(os.path.join(home, "args")) as f:
                self.assertEqual(f.read().strip(), "--user --as-version 0.2.99")

    def test_a_release_without_install_sh_is_refused(self):
        with tempfile.TemporaryDirectory() as home:
            done = run_get(home, "v0.2.4", {"README.md": "old release\n"})
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("v0.2.4", done.stderr)
            self.assertEqual(files_mentioning(home, "lovearound"), [])

    def test_a_truncated_download_runs_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            stub = os.path.join(home, "stub")
            os.makedirs(stub)
            with open(os.path.join(stub, "curl"), "w") as f:
                f.write('#!/bin/sh\ntouch "$HOME/curl-ran"\n')
            os.chmod(os.path.join(stub, "curl"), 0o755)
            with open(os.path.join(ROOT, "tools", "get.sh")) as f:
                script = f.read()
            subprocess.run(["sh"], input=script[:len(script) * 4 // 5], capture_output=True, text=True,
                           env=dict(os.environ, HOME=home, PATH=stub + os.pathsep + os.environ["PATH"]))
            self.assertFalse(os.path.exists(os.path.join(home, "curl-ran")))


def write_get_sh(folder, body):
    path = os.path.join(folder, "get.sh")
    with open(path, "w") as f:
        f.write(body)
    return path


class UpdateScriptTest(unittest.TestCase):
    def test_latest_is_what_get_sh_prints(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(update.latest(write_get_sh(folder, 'echo 0.2.10\n')), "0.2.10")

    def test_a_failed_or_garbled_check_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            for body in ('exit 1\n', 'echo "<html>"\n'):
                with self.assertRaises(update.Failed):
                    update.latest(write_get_sh(folder, body))

    def test_install_passes_the_version_and_raises_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            update.install(write_get_sh(folder, 'echo "$@" > "%s/args"\n' % folder), "0.2.10")
            with open(os.path.join(folder, "args")) as f:
                self.assertEqual(f.read().strip(), "--version 0.2.10")
            with self.assertRaises(update.Failed):
                update.install(write_get_sh(folder, 'exit 1\n'), "0.2.10")


    def test_a_timeout_stops_what_get_sh_started(self):
        with tempfile.TemporaryDirectory() as folder:
            finished = os.path.join(folder, "finished")
            path = write_get_sh(folder, "sh -c 'sleep 1; touch \"%s\"'\n" % finished)
            with mock.patch.object(update, "INSTALL_TIMEOUT", 0.2):
                with self.assertRaises(update.Failed):
                    update.install(path, "0.2.10")
            time.sleep(1.5)
            self.assertFalse(os.path.exists(finished))


class UpdaterTest(unittest.TestCase):
    def updater(self, folder, body):
        return update.Updater(write_get_sh(folder, body), "0.2.9", lambda: None, lambda: None)

    def settle(self, updater):
        self.assertTrue(until(lambda: not updater.busy, 10))

    def test_closing_clears_the_answer_to_a_check(self):
        with tempfile.TemporaryDirectory() as folder:
            for body, shown in (('echo 0.2.9\n', "latest"), ('exit 1\n', "check-failed")):
                updater = self.updater(folder, body)
                updater.check(asked=True)
                self.settle(updater)
                self.assertEqual(updater.state, shown)
                updater.dismiss()
                self.assertEqual((updater.state, updater.version), ("idle", None))

    def test_closing_turns_a_failed_update_back_into_the_offer(self):
        with tempfile.TemporaryDirectory() as folder:
            updater = self.updater(folder, 'case "$1" in --latest) echo 0.2.10 ;; *) exit 1 ;; esac\n')
            updater.check(asked=True)
            self.settle(updater)
            updater.dismiss()
            self.assertEqual((updater.state, updater.version), ("available", "0.2.10"))
            updater.install()
            self.settle(updater)
            self.assertEqual(updater.state, "install-failed")
            updater.dismiss()
            self.assertEqual((updater.state, updater.version), ("available", "0.2.10"))

    def test_closing_during_a_check_drops_its_answer_but_not_a_release(self):
        with tempfile.TemporaryDirectory() as folder:
            for body, shown in (('sleep 0.3; echo 0.2.9\n', ("idle", None)),
                                ('sleep 0.3; exit 1\n', ("idle", None)),
                                ('sleep 0.3; echo 0.2.10\n', ("available", "0.2.10"))):
                updater = self.updater(folder, body)
                updater.check(asked=True)
                updater.dismiss()
                self.assertEqual(updater.state, "idle")
                self.settle(updater)
                self.assertEqual((updater.state, updater.version), shown, body)

    def test_a_day_between_checks_is_counted_on_the_wall_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            ran = os.path.join(folder, "ran")
            updater = self.updater(folder, 'touch "%s"; echo 0.2.9\n' % ran)
            updater.checked_at = time.time() - update.CHECK_EVERY_SECONDS + 60
            self.assertTrue(updater._look())
            self.assertFalse(updater.busy)
            updater.checked_at = time.time() - update.CHECK_EVERY_SECONDS - 1
            self.assertTrue(updater._look())
            self.settle(updater)
            self.assertTrue(os.path.exists(ran))
            self.assertAlmostEqual(updater.checked_at, time.time(), delta=5)

    def test_asking_during_a_scheduled_check_reports_its_answer(self):
        with tempfile.TemporaryDirectory() as folder:
            updater = self.updater(folder, 'sleep 0.3; echo 0.2.9\n')
            updater.check(asked=False)
            updater.check(asked=True)
            self.assertEqual(updater.state, "checking")
            self.settle(updater)
            self.assertEqual(updater.state, "latest")
