import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

from lovearound import presenting

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
            env = {"HOME": home, "XDG_DATA_HOME": os.path.join(home, "data")}
            done = run_install("--user", **env)
            self.assertEqual(done.returncode, 0, done.stderr)
            local, data = os.path.join(home, ".local"), os.path.join(home, "data")
            self.assertIn("installed to " + local, done.stdout)
            self.assertIn("Add %s/bin to PATH" % local, done.stdout)
            for path in ("bin/lovearound", "lib/lovearound/lovearound/app.py", "lib/lovearound/lovearound/VERSION"):
                self.assertTrue(os.path.exists(os.path.join(local, path)), path)
            for path in ("applications/me.lovearound.LoveAround.desktop",
                         "gnome-shell/extensions/lovearound@lovearound.me/metadata.json",
                         "icons/hicolor/48x48/apps/me.lovearound.LoveAround.png"):
                self.assertTrue(os.path.exists(os.path.join(data, path)), path)
            self.assertTrue(os.access(os.path.join(local, "bin", "lovearound"), os.X_OK))
            kwin = subprocess.run(
                [sys.executable, "-c", "from lovearound import presenting; print(presenting.kwin_script_path())"],
                capture_output=True, text=True, cwd=home,
                env=dict(os.environ, PYTHONPATH=os.path.join(local, "lib", "lovearound")))
            self.assertEqual(kwin.stdout.strip(), os.path.join(local, "lib", "lovearound", "kwin", "fullscreen.js"),
                             kwin.stderr)

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
            gone = run_install("--user", "--uninstall", **env)
            self.assertEqual(gone.returncode, 0, gone.stderr)
            shutil.rmtree(fake)
            self.assertEqual(files_mentioning(home, "lovearound"), [])

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
            finally:
                shutil.rmtree(os.path.join(ROOT, "stage-under-test"), ignore_errors=True)


def run_get(home, tag, files):
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
        f.write('#!/bin/sh\nwhile [ "$1" != -o ]; do shift; done\ncp "%s" "$2"\necho "/%s"\n' % (tarball, tag))
    os.chmod(os.path.join(stub, "curl"), 0o755)
    return subprocess.run(["sh", os.path.join(ROOT, "tools", "get.sh")], capture_output=True, text=True,
                          env=dict(os.environ, HOME=home, PATH=stub + os.pathsep + os.environ["PATH"]))


class GetScriptTest(unittest.TestCase):
    def test_runs_the_release_install_sh_for_the_user_with_its_version(self):
        with tempfile.TemporaryDirectory() as home:
            done = run_get(home, "v0.2.99", {"install.sh": 'echo "$@" > "$HOME/args"\n'})
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
