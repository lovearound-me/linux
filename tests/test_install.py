import os
import shutil
import subprocess
import sys
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


def run_install(*args, cwd=None, **env):
    return subprocess.run(["bash", os.path.join(ROOT, "install.sh"), *args],
                          capture_output=True, text=True, cwd=cwd, env=dict(os.environ, **env))


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
            with open(os.path.join(fake, "cryptography.py"), "w") as f:
                f.write("raise ImportError(\"No module named 'cryptography'\")\n")
            refused = run_install("--user", PYTHONPATH=fake, **env)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("cryptography", refused.stderr)
            self.assertTrue(os.path.exists(os.path.join(local, "lib", "lovearound", "lovearound", "app.py")))

            again = run_install("--user", **env)
            self.assertEqual(again.returncode, 0, again.stderr)
            gone = run_install("--user", "--uninstall", **env)
            self.assertEqual(gone.returncode, 0, gone.stderr)
            shutil.rmtree(fake)
            self.assertEqual(files_mentioning(home, "lovearound"), [])

    def test_a_relative_destdir_is_the_callers(self):
        with tempfile.TemporaryDirectory() as work:
            try:
                done = run_install("--prefix", "/usr", "--destdir", "stage-under-test", cwd=work)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertTrue(os.path.exists(os.path.join(work, "stage-under-test", "usr", "bin", "lovearound")))
            finally:
                shutil.rmtree(os.path.join(ROOT, "stage-under-test"), ignore_errors=True)
