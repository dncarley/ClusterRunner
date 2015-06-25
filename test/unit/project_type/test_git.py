from subprocess import Popen
from unittest.mock import ANY, call, MagicMock, Mock

from genty import genty, genty_dataset
import re

from app.project_type.git import Git
from app.util.conf.configuration import Configuration
from test.framework.base_unit_test_case import BaseUnitTestCase
from test.framework.comparators import AnyStringMatching


@genty
class TestGit(BaseUnitTestCase):

    def setUp(self):
        super().setUp()
        self.patch('app.project_type.git.fs.create_dir')
        self.patch('os.unlink')
        self.patch('os.symlink')

        self.os_path_exists_mock = self.patch('app.project_type.git.os.path.exists')
        self.os_path_exists_mock.return_value = False
        self.os_path_isfile_mock = self.patch('app.project_type.git.os.path.isfile')
        self.os_path_isfile_mock.return_value = False

    def test_timing_file_path_happy_path(self):
        git_env = Git("ssh://scm.dev.box.net/box/www/current", 'origin', 'refs/changes/78/151978/27')
        timing_file = git_env.timing_file_path('QUnit')
        self.assertEquals(
            Configuration['base_directory'] +
            '/timings/master/scm.dev.box.net/box/www/current/QUnit.timing.json',
            timing_file
        )

    def test_execute_command_in_project_specifies_cwd_if_exists(self):
        self.os_path_exists_mock.return_value = True
        project_type_popen_patch = self._patch_popen()

        git_env = Git("ssh://scm.dev.box.net/box/www/current", 'origin', 'refs/changes/78/151978/27')
        git_env.project_directory = 'proj_dir'
        git_env.execute_command_in_project('some_command')
        project_type_popen_patch.assert_called_once_with(
            'export PROJECT_DIR="proj_dir"; some_command',
            cwd='proj_dir',
            shell=ANY,
            stdout=ANY,
            stderr=ANY,
            start_new_session=ANY,
        )

    def test_execute_command_in_project_type_specifies_cwd_if_doesnt_exist(self):
        project_type_popen_patch = self._patch_popen()

        git_env = Git("ssh://scm.dev.box.net/box/www/current", 'origin', 'refs/changes/78/151978/27')
        git_env.project_directory = 'proj_dir'
        git_env.execute_command_in_project('some_command')
        project_type_popen_patch.assert_called_once_with(
            'export PROJECT_DIR="proj_dir"; some_command',
            cwd=None,
            shell=ANY,
            stdout=ANY,
            stderr=ANY,
            start_new_session=ANY,
        )

    def test_get_full_repo_directory(self):
        Configuration['repo_directory'] = '/home/cr_user/.clusterrunner/repos/master'
        url = 'http://scm.example.com/path/to/project'

        repo_path = Git.get_full_repo_directory(url)

        self.assertEqual(repo_path, '/home/cr_user/.clusterrunner/repos/master/scm.example.com/path/to/project')

    def test_get_timing_file_directory(self):
        Configuration['timings_directory'] = '/home/cr_user/.clusterrunner/timing'
        url = 'http://scm.example.com/path/to/project'

        timings_path = Git.get_timing_file_directory(url)

        self.assertEqual(timings_path, '/home/cr_user/.clusterrunner/timing/scm.example.com/path/to/project')

    def test_get_repo_directory_removes_colon_from_directory_if_exists(self):
        Configuration['repo_directory'] = '/tmp/repos'
        git = Git("some_remote_value", 'origin', 'ref/to/some/branch')

        repo_directory = git.get_full_repo_directory('ssh://source_control.cr.com:1234/master')

        self.assertEqual(repo_directory, '/tmp/repos/source_control.cr.com1234/master')

    def test_get_timing_file_directory_removes_colon_from_directory_if_exists(self):
        Configuration['timings_directory'] = '/tmp/timings'
        git = Git("some_remote_value", 'origin', 'ref/to/some/branch')

        repo_directory = git.get_timing_file_directory('ssh://source_control.cr.com:1234/master')

        self.assertEqual(repo_directory, '/tmp/timings/source_control.cr.com1234/master')

    def test_fetch_project_when_existing_repo_is_shallow_deletes_repo(self):
        self.os_path_isfile_mock.return_value = True
        self.os_path_exists_mock.return_value = True
        mock_fs = self.patch('app.project_type.git.fs')
        mock_rmtree = self.patch('shutil.rmtree')

        git = Git('url')
        git._repo_directory = 'fake/repo_path'
        git._execute_and_raise_on_failure = MagicMock()
        git.execute_command_in_project = Mock(return_value=('', 0))

        mock_fs.create_dir.call_count = 0  # only measure calls made in _fetch_project
        mock_rmtree.call_count = 0

        git._fetch_project()

        mock_rmtree.assert_called_once_with('fake/repo_path')
        mock_fs.create_dir.assert_called_once_with('fake/repo_path', Git.DIRECTORY_PERMISSIONS)

    @genty_dataset(
        failed_rev_parse=(1, True),
        successful_rev_parse=(0, False),
    )
    def test_repo_is_cloned_if_and_only_if_rev_parse_fails(self, rev_parse_return_code, expect_git_clone_call):
        mock_popen = self._patch_popen({
            'git rev-parse$': _FakePopenResult(return_code=rev_parse_return_code)
        })
        Configuration['repo_directory'] = '/repo-directory'

        git = Git(url='http://original-user-specified-url.test/repo-path/repo-name')
        git.fetch_project()

        git_clone_call = call(AnyStringMatching('git clone'), start_new_session=ANY,
                              stdout=ANY, stderr=ANY, cwd=ANY, shell=ANY)
        if expect_git_clone_call:
            self.assertIn(git_clone_call, mock_popen.call_args_list, 'If "git rev-parse" returns a failing exit code, '
                                                                     '"git clone" should be called.')
        else:
            self.assertNotIn(git_clone_call, mock_popen.call_args_list, 'If "git rev-parse" returns a successful exit '
                                                                        'code, "git clone" should not be called.')

    @genty_dataset(
        strict_host_checking_is_on=(True,),
        strict_host_checking_is_off=(False,),
    )
    def test_execute_git_command_auto_sets_strict_host_option_correctly(self, strict_host_check_setting):
        Configuration['git_strict_host_key_checking'] = strict_host_check_setting
        popen_mock = self._patch_popen()

        git = Git(url='http://some-user-url.com/repo-path/repo-name')
        git._execute_git_command_in_repo_and_raise_on_failure('fakecmd')

        if strict_host_check_setting:
            expected_ssh_arg = '-o StrictHostKeyChecking=yes'
        else:
            expected_ssh_arg = '-o StrictHostKeyChecking=no'

        expected_call = call(AnyStringMatching(expected_ssh_arg),
                             start_new_session=ANY, stdout=ANY, stderr=ANY, cwd=ANY, shell=ANY)
        self.assertIn(expected_call, popen_mock.call_args_list, 'Executed git command should include the correct '
                                                                'option for StrictHostKeyChecking.')

    def test_slave_param_overrides_returns_expected(self):
        self._patch_popen({
            'git rev-parse FETCH_HEAD': _FakePopenResult(stdout='deadbee123\n')
        })
        Configuration['repo_directory'] = '/repo-directory'

        git = Git(url='http://original-user-specified-url.test/repo-path/repo-name')
        git.fetch_project()
        actual_overrides = git.slave_param_overrides()

        expected_overrides = {
            'url': 'ssh://fake_hostname/repodirectory/originaluserspecifiedurl.test/repopath/reponame',
            'branch': 'refs/clusterrunner/deadbee123',
        }
        self.assertEqual(expected_overrides, actual_overrides, 'Slave param overrides from Git object should match'
                                                               'expected.')

    def _patch_popen(self, command_to_result_map=None):
        """
        Mock out calls to Popen to inject fake results for specific command strings.

        :param command_to_result_map: A dict that maps a command string regex to a _FakePopenResult object
        :type command_to_result_map: dict[str, _FakePopenResult]
        :return: The patched popen constructor mock
        :rtype: MagicMock
        """
        command_to_result_map = command_to_result_map or {}
        self.patch('app.project_type.project_type.TemporaryFile', new=lambda: Mock())
        project_type_popen_patch = self.patch('app.project_type.project_type.Popen_with_delayed_expansion')

        def fake_popen_constructor(command, stdout, stderr, *args, **kwargs):
            fake_result = _FakePopenResult()  # default value
            for command_regex in command_to_result_map:
                if re.search(command_regex, command):
                    fake_result = command_to_result_map[command_regex]
                    break
            stdout.read.return_value = fake_result.stdout.encode()
            stderr.read.return_value = fake_result.stderr.encode()
            return Mock(spec=Popen, returncode=fake_result.return_code)

        project_type_popen_patch.side_effect = fake_popen_constructor
        return project_type_popen_patch


class _FakePopenResult:
    def __init__(self, return_code=0, stdout='', stderr=''):
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr
