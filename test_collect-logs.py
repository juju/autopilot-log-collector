# Copyright 2016 Canonical Limited.  All rights reserved.

# To run: "python -m unittest test_collect-logs"

import errno
from fixtures import EnvironmentVariableFixture, TestWithFixtures
import os
import os.path
import shutil
import subprocess
import sys
import tempfile
from unittest import TestCase

import mock


__file__ = os.path.abspath(__file__)

script = type(sys)("collect-logs")
script.__file__ = os.path.abspath("collect-logs")
execfile("collect-logs", script.__dict__)


class FakeError(Exception):
    """A specific error for which to check."""


def _create_file(filename, data=None):
    """Create (or re-create) the identified file.

    If data is provided, it is written to the file.  Otherwise it
    will be empty.

    The file's directory is created if necessary.
    """
    dirname = os.path.dirname(os.path.abspath(filename))
    try:
        os.makedirs(dirname)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

    with open(filename, "w") as file:
        if data:
            file.write()


class _BaseTestCase(TestCase):

    MOCKED = None

    def setUp(self):
        super(_BaseTestCase, self).setUp()

        self.orig_cwd = os.getcwd()
        self.cwd = tempfile.mkdtemp()
        os.chdir(self.cwd)

        self.tempdir = os.path.join(self.cwd, "tempdir")
        os.mkdir(self.tempdir)

        self.orig = {}
        for attr in self.MOCKED or ():
            self.orig[attr] = getattr(script, attr)
            setattr(script, attr, mock.Mock())

        self.juju = script.Juju()

    def tearDown(self):
        for attr in self.MOCKED or ():
            setattr(script, attr, self.orig[attr])

        shutil.rmtree(self.cwd)
        os.chdir(self.orig_cwd)

        super(_BaseTestCase, self).tearDown()

    def _create_tempfile(self, filename, data=None):
        """Create a file at the identified path, but rooted at the temp dir."""
        _create_file(os.path.join(self.tempdir, filename), data)

    def assert_cwd(self, dirname):
        """Ensure that the CWD matches the given directory."""
        cwd = os.getcwd()
        self.assertEqual(cwd, dirname)


class GetUnitsTests(TestCase):

    def test_get_units_returns_juju_units_with_name_and_ip(self):
        """get_units returns a list of JujuUnits with names and ips."""
        status = {
            "applications": {
                "ubuntu": {
                    "units": {"ubuntu/1" : {"public-address": "1.2.3.4"}}},
                "ntp": {
                    "units": {"ntp/1" : {"public-address": "1.2.3.5"}}}}
        }
        expected = [
            script.JujuUnit("ubuntu/1", "1.2.3.4"), 
            script.JujuUnit("ntp/1", "1.2.3.5")]
        self.assertItemsEqual(
            expected, script.get_units(juju=None, status=status))

    def test_get_units_marks_units_with_no_public_address(self):
        """
        get_units sets ip to NO_PUBLIC_ADDRESS for JujuUnits which do not
        report a public-address key.
        """
        status = {
            "applications": {
                "ubuntu": {
                    "units": {"ubuntu/1" : {"public-address": "1.2.3.4"}}},
                "ntp": {
                    "units": {"ntp/1" : {}}}}
        }
        expected = [
            script.JujuUnit("ubuntu/1", "1.2.3.4"), 
            script.JujuUnit("ntp/1", script.NO_PUBLIC_ADDRESS)]
        self.assertItemsEqual(
            expected, script.get_units(juju=None, status=status))

    def test_get_units_ignores_subordinate_applications(self):
        """get_units ignores subordinate units."""
        status = {
            "applications": {
                "ubuntu": {
                    "units": {"ubuntu/1" : {"public-address": "1.2.3.4"}}},
                "landscape-client": {
                    "subordinate-to": ["ubuntu"],
                    "units": {
                        "ceilometer-agent/1" : {"public-address": "1.2.3.5"}}}}
        }
        expected = [
            script.JujuUnit("ubuntu/1", "1.2.3.4")]
        self.assertItemsEqual(
            expected, script.get_units(juju=None, status=status))


class GetJujuTests(TestWithFixtures):

    def test_juju1_outer(self):
        """
        get_juju() returns a Juju prepped for a Juju 1 outer model.
        """
        juju = script.get_juju(script.JUJU1, inner=False)

        expected = script.Juju("juju", model=None)
        self.assertEqual(juju, expected)

    def test_juju1_inner(self):
        """
        get_juju() returns a Juju prepped for a Juju 1 inner model.
        """
        cfgdir = "/var/lib/landscape/juju-homes/0"

        juju = script.get_juju(script.JUJU1, model=None, cfgdir=cfgdir,
            inner=True)

        expected = script.Juju("juju", cfgdir=cfgdir)
        self.assertEqual(juju, expected)

    def test_juju2_outer(self):
        """
        get_juju() returns a Juju prepped for a Juju 2 outer model.
        """
        juju = script.get_juju(script.JUJU2, inner=False)

        expected = script.Juju("juju-2.1", model=None)
        self.assertEqual(juju, expected)

    def test_get_args_without_ssh_uses_ip_address(self):
        """
        When juju_ssh is False, get_juju returns direct ssh commands from
        Juju.ssh_args using using the unit's IP address instead of hostname.
        """
        self.useFixture(
            EnvironmentVariableFixture("JUJU_DATA", "some-dir"))
        juju = script.get_juju(script.JUJU2, inner=False, juju_ssh=False)
        expected = [
            "/usr/bin/ssh", "-o", "StrictHostKeyChecking=no",
            "-i", "some-dir/ssh/juju_id_rsa",
            "ubuntu@10.1.1.1", "ls tmp"]
        self.assertFalse(juju.juju_ssh)
        unit = script.JujuUnit("ubuntu/0", "10.1.1.1")
        self.assertEqual(expected, juju.ssh_args(unit,"ls tmp"))

    def test_get_args_without_ssh_missing_public_address_uses_juju_ssh(self):
        """
        When juju_ssh is False, but juju status doesn't report public-address
        for a unit, ssh_args falls back to using 'juju ssh'.
        """
        self.useFixture(
            EnvironmentVariableFixture("JUJU_DATA", "some-dir"))
        juju = script.get_juju(script.JUJU2, inner=False, juju_ssh=False)
        expected = ["juju-2.1", "ssh", "ubuntu/0", "ls tmp"]
        self.assertFalse(juju.juju_ssh)
        unit = script.JujuUnit("ubuntu/0", script.NO_PUBLIC_ADDRESS)
        self.assertEqual(expected, juju.ssh_args(unit,"ls tmp"))

    def test_pull_args_without_ssh_uses_ip_address(self):
        """
        When juju_ssh is False, get_juju returns direct ssh commands from
        Juju.pull_args using using the unit's IP address instead of hostname.
        """
        self.useFixture(
            EnvironmentVariableFixture("JUJU_DATA", "some-dir"))
        juju = script.get_juju(script.JUJU2, inner=False, juju_ssh=False)
        expected = [
            "/usr/bin/scp", "-o", "StrictHostKeyChecking=no",
            "-i", "some-dir/ssh/juju_id_rsa",
            "ubuntu@10.1.1.1:file1", "."]
        unit = script.JujuUnit("ubuntu/0", "10.1.1.1")
        self.assertEqual(expected, juju.pull_args(unit, "file1"))

    def test_pull_args_without_ssh_missing_public_address_uses_juju_ssh(self):
        """
        When juju_ssh is False, but juju status doesn't report public-address
        for a unit, Juju.pull_args falls back to using 'juju ssh'.
        """
        self.useFixture(
            EnvironmentVariableFixture("JUJU_DATA", "some-dir"))
        juju = script.get_juju(script.JUJU2, inner=False, juju_ssh=False)
        expected = ["juju-2.1", "scp", "ubuntu/0:file1", "."]
        unit = script.JujuUnit("ubuntu/0", script.NO_PUBLIC_ADDRESS)
        self.assertEqual(expected, juju.pull_args(unit, "file1"))

    def test_push_args_without_ssh_uses_ip_address(self):
        """
        When juju_ssh is False, get_juju returns direct ssh commands from
        Juju.push_args using using the unit's IP address instead of hostname.
        """
        self.useFixture(
            EnvironmentVariableFixture("JUJU_DATA", "some-dir"))
        juju = script.get_juju(script.JUJU2, inner=False, juju_ssh=False)
        expected = [
            "/usr/bin/scp", "-o", "StrictHostKeyChecking=no",
            "-i", "some-dir/ssh/juju_id_rsa",
            "file1", "ubuntu@10.1.1.1:/tmp/blah"]
        unit = script.JujuUnit("ubuntu/0", "10.1.1.1")
        self.assertEqual(expected, juju.push_args(unit, "file1", "/tmp/blah"))

    def test_push_args_without_ssh_missing_public_address_uses_juju_ssh(self):
        """
        When juju_ssh is False, but juju status doesn't report public-address
        for a unit, Juju.push_args falls back to using 'juju ssh'.
        """
        self.useFixture(
            EnvironmentVariableFixture("JUJU_DATA", "some-dir"))
        juju = script.get_juju(script.JUJU2, inner=False, juju_ssh=False)
        expected = ["juju-2.1", "scp", "file1", "ubuntu/0:/tmp/blah"]
        unit = script.JujuUnit("ubuntu/0", script.NO_PUBLIC_ADDRESS)
        self.assertEqual(expected, juju.push_args(unit, "file1", "/tmp/blah"))

    def test_juju2_inner(self):
        """
        get_juju() returns a Juju prepped for a Juju 2 inner model.
        """
        cfgdir = "/var/lib/landscape/juju-homes/0"

        juju = script.get_juju(script.JUJU2, cfgdir=cfgdir, inner=True)

        expected = script.Juju("juju-2.1", model="controller", cfgdir=cfgdir)
        self.assertEqual(juju, expected)


class MainTestCase(_BaseTestCase):

    MOCKED = ("collect_logs", "collect_inner_logs", "bundle_logs")

    def setUp(self):
        super(MainTestCase, self).setUp()

        self.orig_mkdtemp = script.mkdtemp
        script.mkdtemp = lambda: self.tempdir

    def tearDown(self):
        script.mkdtemp = self.orig_mkdtemp

        super(MainTestCase, self).tearDown()

    def test_success(self):
        """
        main() calls collect_logs(), collect_inner_logs(), and bundle_logs().
        """
        tarfile = "/tmp/logs.tgz"
        extrafiles = ["spam.py"]

        script.main(tarfile, extrafiles, juju=self.juju)

        script.collect_logs.assert_called_once_with(self.juju)
        script.collect_inner_logs.assert_called_once_with(
            self.juju, script.DEFAULT_MODEL)
        script.bundle_logs.assert_called_once_with(
            self.tempdir, tarfile, extrafiles)
        self.assertFalse(os.path.exists(self.tempdir))

    def test_in_correct_directories(self):
        """
        main() calls its dependencies while in specific directories.
        """
        script.collect_logs.side_effect = (
            lambda _: self.assert_cwd(self.tempdir))
        script.collect_inner_logs.side_effect = (
            lambda _: self.assert_cwd(self.tempdir))
        script.bundle_logs.side_effect = lambda *a: self.assert_cwd(self.cwd)
        tarfile = "/tmp/logs.tgz"
        extrafiles = ["spam.py"]

        script.main(tarfile, extrafiles, juju=self.juju)

    def test_no_script_recursion_for_inner_model(self):
        """
        main() will not call collect_inner_logs() if --inner is True.
        """
        tarfile = "/tmp/logs.tgz"
        extrafiles = ["spam.py"]
        cfgdir = "/var/lib/landscape/juju-homes/0"
        juju = script.get_juju(script.JUJU2, cfgdir)

        script.main(tarfile, extrafiles, juju=juju, inner=True)

        script.collect_logs.assert_called_once_with(juju)
        script.collect_inner_logs.assert_not_called()
        script.bundle_logs.assert_called_once_with(
            self.tempdir, tarfile, extrafiles)
        self.assertFalse(os.path.exists(self.tempdir))

    def test_cleanup(self):
        """
        main() cleans up the temp dir it creates.
        """
        tarfile = "/tmp/logs.tgz"
        extrafiles = ["spam.py"]

        script.main(tarfile, extrafiles, juju=self.juju)

        self.assertFalse(os.path.exists(self.tempdir))

    def test_collect_logs_error(self):
        """
        main() doesn't handle the error when collect_logs() fails.

        It still cleans up the temp dir.
        """
        tarfile = "/tmp/logs.tgz"
        extrafiles = ["spam.py"]
        script.collect_logs.side_effect = FakeError()

        with self.assertRaises(FakeError):
            script.main(tarfile, extrafiles, juju=self.juju)

        script.collect_logs.assert_called_once_with(self.juju)
        script.collect_inner_logs.assert_not_called()
        script.bundle_logs.assert_not_called()
        self.assertFalse(os.path.exists(self.tempdir))

    def test_collect_inner_logs_error(self):
        """
        main() ignores the error when collect_inner_logs() fails.

        It still cleans up the temp dir.
        """
        tarfile = "/tmp/logs.tgz"
        extrafiles = ["spam.py"]
        script.collect_inner_logs.side_effect = FakeError()

        script.main(tarfile, extrafiles, juju=self.juju)

        script.collect_logs.assert_called_once_with(self.juju)
        script.collect_inner_logs.assert_called_once_with(
            self.juju, script.DEFAULT_MODEL)
        script.bundle_logs.assert_called_once_with(
            self.tempdir, tarfile, extrafiles)
        self.assertFalse(os.path.exists(self.tempdir))

    def test_bundle_logs_error(self):
        """
        main() doesn't handle the error when bundle_logs() fails.

        It still cleans up the temp dir.
        """
        tarfile = "/tmp/logs.tgz"
        extrafiles = ["spam.py"]
        script.bundle_logs.side_effect = FakeError()

        with self.assertRaises(FakeError):
            script.main(tarfile, extrafiles, juju=self.juju)

        script.collect_logs.assert_called_once_with(self.juju)
        script.collect_inner_logs.assert_called_once_with(
            self.juju, script.DEFAULT_MODEL)
        script.bundle_logs.assert_called_once_with(
            self.tempdir, tarfile, extrafiles)
        self.assertFalse(os.path.exists(self.tempdir))


class CreateOutputFilesTestCase(_BaseTestCase):

    MOCKED = ("call", "check_output", "get_units", "get_hosts", "mkdtemp")

    def setUp(self):
        super(CreateOutputFilesTestCase, self).setUp()
        self.hosts = [
            script.JujuHost("0", "1.2.3.8"),
        ]
        script.get_hosts.return_value = self.hosts[:]
        self.tmpdir = tempfile.mkdtemp()
        script.mkdtemp.return_value = self.tmpdir

    def tearDown(self):
        if os.path.exists(self.tmpdir):
            # self.tmpdir is returned by the mocked tempfile.mkdtemp()
            # Normally, this won't exist as collect-logs should remove it.
            shutil.rmtree(self.tmpdir)
        super(CreateOutputFilesTestCase, self).tearDown()

    def test_get_ps_mem_with_git_clone(self):
        """
        Clone the ps_mem repo when there is no local copy.
        """
        ps_mem_file = os.path.join(self.tmpdir, "ps_mem.py")
        repo_path = os.path.join(self.tmpdir, "ps_mem")
        script._get_ps_mem(ps_mem_file, script.PS_MEM_REPO, repo_path)
        expected = [
            mock.call(["git", "clone", script.PS_MEM_REPO, repo_path],
            stderr=subprocess.STDOUT),
        ]
        self.assertEqual(expected, script.check_output.call_args_list)

    def test_get_ps_mem_local(self):
        """
        Don't clone the ps_mem repo when there is a local copy.
        """
        ps_mem_file = os.path.join(self.tmpdir, "ps_mem.py")
        with open(ps_mem_file, 'w') as outfile:
            outfile.write("# This is a fake ps_mem.py")
        repo_path = os.path.join(self.tmpdir, "ps_mem")
        result = script._get_ps_mem(ps_mem_file, script.PS_MEM_REPO, repo_path)
        self.assertEqual(ps_mem_file, result)
        script.check_output.assert_not_called()

    def test_upload_ps_mem(self):
        """
        Verify that the repo is cloned and file uploaded.
        """
        script.upload_ps_mem(self.juju, self.hosts[0])
        repo_path = os.path.join(self.tmpdir, "ps_mem")
        expected = [
            mock.call(["git", "clone", script.PS_MEM_REPO, repo_path],
            stderr=subprocess.STDOUT),
        ]
        self.assertEqual(expected, script.check_output.call_args_list)
        source = os.path.join(repo_path, "ps_mem.py")
        target = "{}:/tmp/ps_mem.py".format(self.hosts[0].name)
        expected = [
            mock.call(["juju", "scp", source, target],
                      env=None),
        ]
        self.assertEqual(expected, script.call.call_args_list)

    def test_create_ps_mem_output_file(self):
        """
        Verify expected commands when creating the ps_mem output.
        """
        script._create_ps_mem_output_file(self.juju, self.hosts[0])
        repo_path = os.path.join(self.tmpdir, "ps_mem")
        expected = [
            mock.call([
                "juju", "ssh", "0",
                "if ! python -V; then sudo apt-get install -y python; fi"],
            env=None, stderr=subprocess.STDOUT),
            mock.call([
                "juju", "ssh", "0",
                "sudo /tmp/ps_mem.py -S | sudo tee /var/log/ps_mem.txt"],
            env=None, stderr=subprocess.STDOUT),
        ]
        self.assertEqual(expected, script.check_output.call_args_list)


class CollectLogsTestCase(_BaseTestCase):

    MOCKED = ("get_units", "get_bootstrap_ip", "check_output", "call",
              "get_hosts", "upload_ps_mem", "_create_ps_mem_output_file")

    def setUp(self):
        super(CollectLogsTestCase, self).setUp()

        self.units = [
            script.JujuUnit("landscape-server/0", "1.2.3.4"),
            script.JujuUnit("postgresql/0", "1.2.3.5"),
            script.JujuUnit("rabbitmq-server/0", "1.2.3.6"),
            script.JujuUnit("haproxy/0", "1.2.3.7"),
            ]
        script.get_units.return_value = self.units[:]
        script.get_bootstrap_ip.return_value = self.units[0].ip
        self.hosts = [
            script.JujuHost("0", "1.2.3.8"),
        ]
        script.get_hosts.return_value = self.hosts[:]

        self.mp_map_orig = script._mp_map
        script._mp_map = lambda f, a: map(f, a)

        os.chdir(self.tempdir)

    def tearDown(self):
        script._mp_map = self.mp_map_orig

        super(CollectLogsTestCase, self).tearDown()

    def _call_side_effect(self, cmd, env=None):
        """Perform the side effect of calling the mocked-out call()."""
        if cmd[0] == "tar":
            self.assertTrue(os.path.exists(cmd[-1]))
            return
        self.assertEqual(env, self.juju.env)
        self.assertEqual(cmd[0], self.juju.binary_path)
        _create_file(os.path.basename(cmd[2]))

    def test_success(self):
        """
        collect_logs() gathers "ps" output and logs from each unit.
        """
        script.call.side_effect = self._call_side_effect

        script.collect_logs(self.juju)

        script.get_units.assert_called_once_with(self.juju)
        expected = []
        units = self.units + [script.JujuUnit("0", "1.2.3.3")]
        # for _create_ps_output_file()
        for unit in units:
            cmd = "ps fauxww | sudo tee /var/log/ps-fauxww.txt"
            expected.append(mock.call(["juju", "ssh", unit.name, cmd],
                                      stderr=subprocess.STDOUT,
                                      env=None,
                                      ))
        # for _create_log_tarball()
        for unit in units:
            tarfile = "/tmp/logs_{}.tar".format(unit.name.replace("/", "-")
                                                if unit.name != "0"
                                                else "bootstrap")
            cmd = ("sudo tar --ignore-failed-read"
                   " --exclude=/var/lib/landscape/client/package/hash-id"
                   " --exclude=/var/lib/juju/containers/juju-*-lxc-template"
                   " -cf {}"
                   " $(sudo sh -c \"ls -1d {} 2>/dev/null\")"
                   ).format(
                       tarfile,
                       " ".join(["/var/log",
                                 "/etc/hosts",
                                 "/etc/network",
                                 "/var/crash",
                                 "/var/lib/landscape/client",
                                 "/etc/apache2",
                                 "/etc/haproxy",
                                 "/var/lib/lxc/*/rootfs/var/log",
                                 "/var/lib/juju/containers",
                                 "/etc/nova",
                                 "/etc/swift",
                                 "/etc/neutron",
                                 "/etc/ceph",
                                 "/etc/glance",
                                 ]),
                       )
            expected.append(mock.call(["juju", "ssh", unit.name, cmd],
                                      stderr=subprocess.STDOUT,
                                      env=None,
                                      ))
            expected.append(mock.call(["juju", "ssh", unit.name,
                                       "sudo gzip -f {}".format(tarfile)],
                                      stderr=subprocess.STDOUT,
                                      env=None,
                                      ))
        self.assertEqual(script.check_output.call_count, len(expected))
        script.check_output.assert_has_calls(expected, any_order=True)
        # for _create_ps_mem_output_file
        script._create_ps_mem_output_file.assert_has_calls([
            mock.call(self.juju, self.hosts[0]),
        ])
        # for download_log_from_unit()
        expected = []
        for unit in units:
            if unit.name != "0":
                name = unit.name.replace("/", "-")
            else:
                name = "bootstrap"
            filename = "logs_{}.tar.gz".format(name)
            source = "{}:/tmp/{}".format(unit.name, filename)
            expected.append(mock.call(["juju", "scp", source, "."], env=None))
            expected.append(mock.call(["tar", "-C", name, "-xzf", filename]))
            self.assertFalse(os.path.exists(filename))
        self.assertEqual(script.call.call_count, len(expected))
        script.call.assert_has_calls(expected, any_order=True)

    def test_inner(self):
        """
        collect_logs() gathers "ps" output and logs from each unit.
        Running in the inner model produces different commands.
        """
        cfgdir = "/var/lib/landscape/juju-homes/0"
        juju = script.Juju("juju-2.1", model="controller", cfgdir=cfgdir)
        self.juju = juju
        script.call.side_effect = self._call_side_effect

        script.collect_logs(juju)

        script.get_units.assert_called_once_with(juju)
        expected = []
        units = self.units + [script.JujuUnit("0", "1.2.3.3")]
        # for _create_ps_output_file()
        for unit in units:
            cmd = "ps fauxww | sudo tee /var/log/ps-fauxww.txt"
            expected.append(mock.call(["juju-2.1", "ssh",
                                       "-m", "controller", unit.name, cmd],
                                      stderr=subprocess.STDOUT,
                                      env=juju.env,
                                      ))
        # for _create_log_tarball()
        for unit in units:
            tarfile = "/tmp/logs_{}.tar".format(unit.name.replace("/", "-")
                                                if unit.name != "0"
                                                else "bootstrap")
            cmd = ("sudo tar --ignore-failed-read"
                   " --exclude=/var/lib/landscape/client/package/hash-id"
                   " --exclude=/var/lib/juju/containers/juju-*-lxc-template"
                   " -cf {}"
                   " $(sudo sh -c \"ls -1d {} 2>/dev/null\")"
                   ).format(
                       tarfile,
                       " ".join(["/var/log",
                                 "/etc/hosts",
                                 "/etc/network",
                                 "/var/crash",
                                 "/var/lib/landscape/client",
                                 "/etc/apache2",
                                 "/etc/haproxy",
                                 "/var/lib/lxc/*/rootfs/var/log",
                                 "/var/lib/juju/containers",
                                 "/etc/nova",
                                 "/etc/swift",
                                 "/etc/neutron",
                                 "/etc/ceph",
                                 "/etc/glance",
                                 ]),
                       )
            expected.append(mock.call(
                ["juju-2.1", "ssh", "-m", "controller", unit.name, cmd],
                stderr=subprocess.STDOUT,
                env=juju.env,
                ))
            expected.append(mock.call(
                ["juju-2.1", "ssh", "-m", "controller", unit.name,
                 "sudo gzip -f {}".format(tarfile)],
                 stderr=subprocess.STDOUT,
                 env=juju.env,
                 ))
        self.assertEqual(script.check_output.call_count, len(expected))
        script.check_output.assert_has_calls(expected, any_order=True)
        # for _create_ps_mem_output_file
        script._create_ps_mem_output_file.assert_has_calls([
            mock.call(self.juju, self.hosts[0]),
        ])
        # for download_log_from_unit()
        expected = []
        for unit in units:
            if unit.name != "0":
                name = unit.name.replace("/", "-")
            else:
                name = "bootstrap"
            filename = "logs_{}.tar.gz".format(name)
            source = "{}:/tmp/{}".format(unit.name, filename)
            expected.append(mock.call(
                ["juju-2.1", "scp", "-m", "controller", source, "."],
                env=juju.env))
            expected.append(mock.call(["tar", "-C", name, "-xzf", filename]))
            self.assertFalse(os.path.exists(filename))
        self.assertEqual(script.call.call_count, len(expected))
        script.call.assert_has_calls(expected, any_order=True)

    def test_get_units_failure(self):
        """
        collect_logs() does not handle errors from get_units().
        """
        script.get_units.side_effect = FakeError()

        with self.assertRaises(FakeError):
            script.collect_logs(self.juju)

        script.get_units.assert_called_once_with(self.juju)
        script.check_output.assert_not_called()
        script.call.assert_not_called()

    def test_get_hosts_failure(self):
        """
        collect_logs() does not handle errors from get_hosts().
        """
        script.get_hosts.side_effect = FakeError()

        with self.assertRaises(FakeError):
            script.collect_logs(self.juju)

        script.get_hosts.assert_called_once_with(self.juju)
        self.assertEqual(script.check_output.call_count, 5)
        script.call.assert_not_called()

    def test_check_output_failure(self):
        """
        collect_logs() does not handle errors from check_output().
        """
        script.check_output.side_effect = [mock.DEFAULT,
                                           FakeError(),
                                           ]

        with self.assertRaises(FakeError):
            script.collect_logs(self.juju)

        script.get_units.assert_called_once_with(self.juju)
        self.assertEqual(script.check_output.call_count, 2)
        script.call.assert_not_called()

    def test_call_failure(self):
        """
        collect_logs() does not handle errors from call().
        """
        def call_side_effect(cmd, env=None):
            # second use of call() for landscape-server/0
            if script.call.call_count == 2:
                raise FakeError()
            # first use of call() for postgresql/0
            if script.call.call_count == 3:
                raise FakeError()
            # all other uses of call() default to the normal side effect.
            return self._call_side_effect(cmd, env=env)
        script.call.side_effect = call_side_effect

        script.collect_logs(self.juju)

        script.get_units.assert_called_once_with(self.juju)
        units = self.units + [script.JujuUnit("0", "1.2.3.3")]
        self.assertEqual(script.check_output.call_count, len(units) * 3)
        self.assertEqual(script.call.call_count, len(units) * 2 - 1)
        for unit in units:
            if unit.name != "0":
                name = unit.name.replace("/", "-")
            else:
                name = "bootstrap"
            if unit == self.units[1]:
                self.assertFalse(os.path.exists(name))
            else:
                self.assertTrue(os.path.exists(name))
            filename = "logs_{}.tar.gz".format(name)
            self.assertFalse(os.path.exists(filename))


class CollectInnerLogsTestCase(_BaseTestCase):

    MOCKED = ("get_units", "check_output", "call", "check_call",
              "upload_ps_mem")

    def setUp(self):
        super(CollectInnerLogsTestCase, self).setUp()

        self.units = [
            script.JujuUnit("landscape-server/0" , "1.2.3.4"),
            script.JujuUnit("postgresql/0", "1.2.3.5"),
            script.JujuUnit("rabbitmq-server/0", "1.2.3.6"),
            script.JujuUnit("haproxy/0", "1.2.3.7"),
            ]
        script.get_units.return_value = self.units[:]
        script.check_output.return_value = "0\n"
        script.call.return_value = 0

        os.chdir(self.tempdir)

    def assert_clean(self):
        """Ensure that collect_inner_logs cleaned up after itself."""
        self.assert_cwd(self.tempdir)
        self.assertFalse(os.path.exists("inner-logs.tar.gz"))

    def test_juju_2(self):
        """
        collect_inner_logs() finds the inner model and runs collect-logs
        inside it.  The resulting tarball is downloaded, extracted, and
        deleted.
        """
        def check_call_side_effect(cmd, env=None):
            self.assertEqual(env, self.juju.env)
            if script.check_call.call_count == 4:
                self.assert_cwd(self.tempdir)
                self._create_tempfile("inner-logs.tar.gz")
            elif script.check_call.call_count == 5:
                cwd = os.path.join(self.tempdir, "landscape-0-inner-logs")
                self.assert_cwd(cwd)
            return None
        script.check_call.side_effect = check_call_side_effect

        script.collect_inner_logs(self.juju)

        # Check get_units() calls.
        script.get_units.assert_called_once_with(self.juju)
        # Check check_output() calls.
        expected = []
        cmd = ("sudo JUJU_DATA=/var/lib/landscape/juju-homes/"
               "`sudo ls -rt /var/lib/landscape/juju-homes/ | tail -1`"
               " juju-2.1 model-config -m controller proxy-ssh=false")
        expected.append(mock.call(["juju", "ssh", "landscape-server/0", cmd],
                                  stderr=subprocess.STDOUT,
                                  env=self.juju.env))
        expected.append(mock.call(
            ["juju", "ssh", "landscape-server/0",
             "sudo ls -rt /var/lib/landscape/juju-homes/"],
            env=self.juju.env))
        self.assertEqual(script.check_output.call_count, len(expected))
        script.check_output.assert_has_calls(expected, any_order=True)
        # Check call() calls.
        expected = [
            mock.call(["juju", "ssh", "landscape-server/0",
                       ("sudo JUJU_DATA=/var/lib/landscape/juju-homes/0 "
                        "juju-2.1 status -m controller --format=yaml"),
                       ], env=self.juju.env),
            mock.call(["juju", "scp",
                       os.path.join(os.path.dirname(__file__), "collect-logs"),
                       "landscape-server/0:/tmp/collect-logs",
                       ], env=self.juju.env),
            mock.call(["juju", "ssh",
                       "landscape-server/0",
                       "sudo rm -rf /tmp/inner-logs.tar.gz",
                       ], env=self.juju.env),
            ]
        self.assertEqual(script.call.call_count, len(expected))
        script.call.assert_has_calls(expected, any_order=True)
        # Check check_call() calls.
        cmd = ("sudo"
               " JUJU_DATA=/var/lib/landscape/juju-homes/0"
               " /tmp/collect-logs --inner --juju juju-2.1"
               " --model controller"
               " --cfgdir /var/lib/landscape/juju-homes/0"
               " /tmp/inner-logs.tar.gz")
        expected = [
            mock.call(["juju", "ssh", "landscape-server/0", cmd],
                      env=self.juju.env),
            mock.call(["juju", "scp",
                       "landscape-server/0:/tmp/inner-logs.tar.gz",
                       os.path.join(self.tempdir, "inner-logs.tar.gz"),
                       ], env=self.juju.env),
            mock.call(["tar", "-zxf", self.tempdir + "/inner-logs.tar.gz"]),
            ]
        self.assertEqual(script.check_call.call_count, len(expected))
        script.check_call.assert_has_calls(expected, any_order=True)
        self.assert_clean()

    def test_juju_1(self):
        """
        collect_inner_logs() finds the inner model and runs collect-logs
        inside it.  The resulting tarball is downloaded, extracted, and
        deleted.
        """
        def check_call_side_effect(cmd, env=None):
            self.assertEqual(env, self.juju.env)
            if script.check_call.call_count == 4:
                self.assert_cwd(self.tempdir)
                self._create_tempfile("inner-logs.tar.gz")
            elif script.check_call.call_count == 5:
                cwd = os.path.join(self.tempdir, "landscape-0-inner-logs")
                self.assert_cwd(cwd)
            return None
        script.check_call.side_effect = check_call_side_effect
        script.call.side_effect = [1, 0, 0, 0]
        err = subprocess.CalledProcessError(1, "...", "<output>")
        script.check_output.side_effect = [err,
                                           mock.DEFAULT,
                                           mock.DEFAULT,
                                           ]

        script.collect_inner_logs(self.juju)

        # Check get_units() calls.
        script.get_units.assert_called_once_with(self.juju)
        # Check check_output() calls.
        expected = []
        cmd = ("sudo JUJU_DATA=/var/lib/landscape/juju-homes/"
               "`sudo ls -rt /var/lib/landscape/juju-homes/ | tail -1`"
               " juju-2.1 model-config -m controller proxy-ssh=false")
        expected.append(mock.call(["juju", "ssh", "landscape-server/0", cmd],
                                  stderr=subprocess.STDOUT,
                                  env=None))
        cmd = ("sudo JUJU_HOME=/var/lib/landscape/juju-homes/"
               "`sudo ls -rt /var/lib/landscape/juju-homes/ | tail -1`"
               " juju set-env proxy-ssh=false")
        expected.append(mock.call(["juju", "ssh", "landscape-server/0", cmd],
                                  stderr=subprocess.STDOUT,
                                  env=None))
        expected.append(mock.call(
            ["juju", "ssh", "landscape-server/0",
             "sudo ls -rt /var/lib/landscape/juju-homes/"],
            env=None))
        self.assertEqual(script.check_output.call_count, len(expected))
        script.check_output.assert_has_calls(expected, any_order=True)
        # Check call() calls.
        expected = [
            mock.call(["juju", "ssh", "landscape-server/0",
                       ("sudo JUJU_DATA=/var/lib/landscape/juju-homes/0 "
                        "juju-2.1 status -m controller --format=yaml"),
                       ], env=None),
            mock.call(["juju", "ssh", "landscape-server/0",
                       ("sudo -u landscape "
                        "JUJU_HOME=/var/lib/landscape/juju-homes/0 "
                        "juju status --format=yaml"),
                       ], env=None),
            mock.call(["juju", "scp",
                       os.path.join(os.path.dirname(__file__), "collect-logs"),
                       "landscape-server/0:/tmp/collect-logs",
                       ], env=None),
            mock.call(["juju", "ssh",
                       "landscape-server/0",
                       "sudo rm -rf /tmp/inner-logs.tar.gz",
                       ], env=None),
            ]
        self.assertEqual(script.call.call_count, len(expected))
        script.call.assert_has_calls(expected, any_order=True)
        # Check check_call() calls.
        cmd = ("sudo -u landscape"
               " JUJU_HOME=/var/lib/landscape/juju-homes/0"
               " /tmp/collect-logs --inner --juju juju"
               " --cfgdir /var/lib/landscape/juju-homes/0"
               " /tmp/inner-logs.tar.gz")
        expected = [
            mock.call(["juju", "ssh", "landscape-server/0", cmd], env=None),
            mock.call(["juju", "scp",
                       "landscape-server/0:/tmp/inner-logs.tar.gz",
                       os.path.join(self.tempdir, "inner-logs.tar.gz"),
                       ], env=None),
            mock.call(["tar", "-zxf", self.tempdir + "/inner-logs.tar.gz"]),
            ]
        self.assertEqual(script.check_call.call_count, len(expected))
        script.check_call.assert_has_calls(expected, any_order=True)
        self.assert_clean()

    def test_with_legacy_landscape_unit(self):
        """
        collect_inner_logs() correctly supports legacy landscape installations.
        """
        self.units[0] = script.JujuUnit("landscape/0", "1.2.3.4")
        script.get_units.return_value = self.units[:]
        err = subprocess.CalledProcessError(1, "...", "<output>")
        script.check_output.side_effect = [err,
                                           mock.DEFAULT,
                                           mock.DEFAULT,
                                           ]

        script.collect_inner_logs(self.juju)

        expected = []
        cmd = ("sudo JUJU_DATA=/var/lib/landscape/juju-homes/"
               "`sudo ls -rt /var/lib/landscape/juju-homes/ | tail -1`"
               " juju-2.1 model-config -m controller proxy-ssh=false")
        expected.append(mock.call(["juju", "ssh", "landscape/0", cmd],
                                  stderr=subprocess.STDOUT,
                                  env=None))
        cmd = ("sudo JUJU_HOME=/var/lib/landscape/juju-homes/"
               "`sudo ls -rt /var/lib/landscape/juju-homes/ | tail -1`"
               " juju set-env proxy-ssh=false")
        expected.append(mock.call(["juju", "ssh", "landscape/0", cmd],
                                  stderr=subprocess.STDOUT,
                                  env=None))
        expected.append(mock.call(
            ["juju", "ssh", "landscape/0",
             "sudo ls -rt /var/lib/landscape/juju-homes/"],
            env=None))
        self.assertEqual(script.check_output.call_count, len(expected))
        script.check_output.assert_has_calls(expected, any_order=True)
        self.assert_clean()

    def test_no_units(self):
        """
        collect_inner_logs() is a noop if no units are found.
        """
        script.get_units.return_value = []

        script.collect_inner_logs(self.juju)

        script.get_units.assert_called_once_with(self.juju)
        script.check_output.assert_not_called()
        script.call.assert_not_called()
        script.check_call.assert_not_called()
        self.assert_clean()

    def test_no_landscape_server_unit(self):
        """
        collect_inner_logs() is a noop if the landscape unit isn't found.
        """
        del self.units[0]
        script.get_units.return_value = self.units[:]

        script.collect_inner_logs(self.juju)

        script.get_units.assert_called_once_with(self.juju)
        script.check_output.assert_not_called()
        script.call.assert_not_called()
        script.check_call.assert_not_called()
        self.assert_clean()

    def test_no_juju_homes(self):
        script.get_units.return_value = []
        script.check_output.return_value = ""

        script.collect_inner_logs(self.juju)

        script.get_units.assert_called_once_with(self.juju)

        script.get_units.assert_called_once_with(self.juju)
        script.check_output.assert_not_called()
        script.call.assert_not_called()
        script.check_call.assert_not_called()
        self.assert_clean()

    def test_get_units_failure(self):
        """
        collect_inner_logs() does not handle errors from get_units().
        """
        script.get_units.side_effect = FakeError()

        with self.assertRaises(FakeError):
            script.collect_inner_logs(self.juju)

        self.assertEqual(script.get_units.call_count, 1)
        script.check_output.assert_not_called()
        script.call.assert_not_called()
        script.check_call.assert_not_called()
        self.assert_cwd(self.tempdir)
        self.assert_clean()

    def test_check_output_failure_1(self):
        """
        collect_inner_logs() does not handle non-CalledProcessError
        errors when disabling the SSH proxy.
        """
        script.check_output.side_effect = FakeError()

        with self.assertRaises(FakeError):
            script.collect_inner_logs(self.juju)

        self.assertEqual(script.get_units.call_count, 1)
        self.assertEqual(script.check_output.call_count, 1)
        script.call.assert_not_called()
        script.check_call.assert_not_called()
        self.assert_cwd(self.tempdir)
        self.assert_clean()

    def test_check_output_failure_2(self):
        """
        collect_inner_logs() does not handle non-CalledProcessError
        errors when verifying the inner model is bootstrapped.
        """
        script.check_output.side_effect = [None,
                                           FakeError(),
                                           ]

        with self.assertRaises(FakeError):
            script.collect_inner_logs(self.juju)

        self.assertEqual(script.get_units.call_count, 1)
        self.assertEqual(script.check_output.call_count, 2)
        script.call.assert_not_called()
        script.check_call.assert_not_called()
        self.assert_cwd(self.tempdir)
        self.assert_clean()

    def test_call_juju2_failure(self):
        """
        collect_inner_logs() does not handle errors from call().
        """
        script.call.side_effect = FakeError()

        with self.assertRaises(FakeError):
            script.collect_inner_logs(self.juju)

        self.assertEqual(script.get_units.call_count, 1)
        self.assertEqual(script.check_output.call_count, 2)
        self.assertEqual(script.call.call_count, 1)
        script.check_call.assert_not_called()
        self.assert_cwd(self.tempdir)
        self.assert_clean()

    def test_call_juju1_failure(self):
        """
        collect_inner_logs() does not handle errors from call().
        """
        script.call.side_effect = [1,
                                   FakeError(),
                                   ]

        with self.assertRaises(FakeError):
            script.collect_inner_logs(self.juju)

        self.assertEqual(script.get_units.call_count, 1)
        self.assertEqual(script.check_output.call_count, 2)
        self.assertEqual(script.call.call_count, 2)
        script.check_call.assert_not_called()
        self.assert_cwd(self.tempdir)
        self.assert_clean()

    def test_call_juju2_nonzero_return(self):
        """
        When no Juju 2 model is detected, Juju 1 is tried.
        """
        script.call.side_effect = [1,
                                   mock.DEFAULT,
                                   mock.DEFAULT,
                                   mock.DEFAULT,
                                   ]

        script.collect_inner_logs(self.juju)

        self.assertEqual(script.get_units.call_count, 1)
        self.assertEqual(script.check_output.call_count, 2)
        self.assertEqual(script.call.call_count, 4)
        self.assertEqual(script.check_call.call_count, 3)
        self.assert_clean()

    def test_call_juju1_nonzero_return(self):
        """
        When no Juju 2 model is detected, Juju 1 is tried. When that
        is not detected, no inner logs are collected.
        """
        script.call.side_effect = [1,
                                   1,
                                   ]

        script.collect_inner_logs(self.juju)

        self.assertEqual(script.get_units.call_count, 1)
        self.assertEqual(script.check_output.call_count, 2)
        self.assertEqual(script.call.call_count, 2)
        script.check_call.assert_not_called()
        self.assert_clean()

    def test_call_all_nonzero_return(self):
        """
        When no Juju 2 model is detected, Juju 1 is tried. When that
        is not detected, no inner logs are collected.
        """
        script.call.return_value = 1

        script.collect_inner_logs(self.juju)

        self.assertEqual(script.get_units.call_count, 1)
        self.assertEqual(script.check_output.call_count, 2)
        self.assertEqual(script.call.call_count, 2)
        script.check_call.assert_not_called()
        self.assert_clean()

    def test_check_call_failure_1(self):
        """
        collect_inner_logs() does not handle errors when running
        collect-logs in the inner model.
        """
        script.check_call.side_effect = FakeError()

        with self.assertRaises(FakeError):
            script.collect_inner_logs(self.juju)

        self.assertEqual(script.get_units.call_count, 1)
        self.assertEqual(script.check_output.call_count, 2)
        self.assertEqual(script.call.call_count, 3)
        self.assertEqual(script.check_call.call_count, 1)
        self.assert_clean()

    def test_check_call_failure_2(self):
        """
        collect_inner_logs() does not handle errors downloading the
        collected logs from the inner model.

        It does clean up, however.
        """
        script.check_call.side_effect = [None,
                                         FakeError(),
                                         ]

        with self.assertRaises(FakeError):
            script.collect_inner_logs(self.juju)

        self.assertEqual(script.get_units.call_count, 1)
        self.assertEqual(script.check_output.call_count, 2)
        self.assertEqual(script.call.call_count, 3)
        self.assertEqual(script.check_call.call_count, 2)
        self.assert_clean()

    def test_check_call_failure_3(self):
        def check_call_side_effect(cmd, env=None):
            self.assertEqual(env, self.juju.env)
            if script.check_call.call_count == 3:
                raise FakeError()
            if script.check_call.call_count == 2:
                self._create_tempfile("inner-logs.tar.gz")
            return None
        script.check_call.side_effect = check_call_side_effect

        with self.assertRaises(FakeError):
            script.collect_inner_logs(self.juju)

        self.assertEqual(script.get_units.call_count, 1)
        self.assertEqual(script.check_output.call_count, 2)
        self.assertEqual(script.call.call_count, 3)
        self.assertEqual(script.check_call.call_count, 3)
        self.assert_clean()


class BundleLogsTestCase(_BaseTestCase):

    MOCKED = ("call",)

    def setUp(self):
        """
        bundle_logs() creates a tarball holding the files in the tempdir.
        """
        super(BundleLogsTestCase, self).setUp()

        os.chdir(self.tempdir)

        self._create_tempfile("bootstrap/var/log/syslog")
        self._create_tempfile("bootstrap/var/log/juju/all-machines.log")
        self._create_tempfile(
            "bootstrap/var/lib/lxc/deadbeef/rootfs/var/log/syslog")
        self._create_tempfile("bootstrap/var/lib/juju/containers")
        self._create_tempfile("landscape-server-0/var/log/syslog")
        self._create_tempfile("postgresql-0/var/log/syslog")
        self._create_tempfile("rabbitmq-server-0/var/log/syslog")
        self._create_tempfile("haproxy-0/var/log/syslog")
        self._create_tempfile(
            "landscape-0-inner-logs/bootstrap/var/log/syslog")

        self.extrafile = os.path.join(self.cwd, "spam.txt")
        _create_file(self.extrafile)

    def test_success_with_extra(self):
        """
        bundle_logs() works if extra files are included.
        """
        tarfile = "/tmp/logs.tgz"
        extrafiles = [self.extrafile]

        script.bundle_logs(self.tempdir, tarfile, extrafiles)

        script.call.assert_called_once_with(
            ["tar",
             "czf", tarfile,
             "--transform", "s,{}/,,".format(self.tempdir[1:]),
             os.path.join(self.tempdir, "bootstrap"),
             os.path.join(self.tempdir, "haproxy-0"),
             os.path.join(self.tempdir, "landscape-0-inner-logs"),
             os.path.join(self.tempdir, "landscape-server-0"),
             os.path.join(self.tempdir, "postgresql-0"),
             os.path.join(self.tempdir, "rabbitmq-server-0"),
             self.extrafile,
             ],
            )

    def test_success_without_extra(self):
        """
        bundle_logs() works if there aren't any extra files.
        """
        tarfile = "/tmp/logs.tgz"

        script.bundle_logs(self.tempdir, tarfile)

        script.call.assert_called_once_with(
            ["tar",
             "czf", tarfile,
             "--transform", "s,{}/,,".format(self.tempdir[1:]),
             os.path.join(self.tempdir, "bootstrap"),
             os.path.join(self.tempdir, "haproxy-0"),
             os.path.join(self.tempdir, "landscape-0-inner-logs"),
             os.path.join(self.tempdir, "landscape-server-0"),
             os.path.join(self.tempdir, "postgresql-0"),
             os.path.join(self.tempdir, "rabbitmq-server-0"),
             ],
            )

    def test_success_no_files(self):
        """
        bundle_logs() works even when the temp dir is empty.
        """
        for filename in os.listdir(self.tempdir):
            shutil.rmtree(os.path.join(self.tempdir, filename))
        tarfile = "/tmp/logs.tgz"

        script.bundle_logs(self.tempdir, tarfile)

        script.call.assert_called_once_with(
            ["tar",
             "czf", tarfile,
             "--transform", "s,{}/,,".format(self.tempdir[1:]),
             ],
            )

    def test_call_failure(self):
        """
        bundle_logs() does not handle errors when creating the tarball.
        """
        script.call.side_effect = FakeError()
        tarfile = "/tmp/logs.tgz"

        with self.assertRaises(FakeError):
            script.bundle_logs(self.tempdir, tarfile)

        script.call.assert_called_once_with(
            ["tar",
             "czf", tarfile,
             "--transform", "s,{}/,,".format(self.tempdir[1:]),
             os.path.join(self.tempdir, "bootstrap"),
             os.path.join(self.tempdir, "haproxy-0"),
             os.path.join(self.tempdir, "landscape-0-inner-logs"),
             os.path.join(self.tempdir, "landscape-server-0"),
             os.path.join(self.tempdir, "postgresql-0"),
             os.path.join(self.tempdir, "rabbitmq-server-0"),
             ],
            )
