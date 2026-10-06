#!/bin/env python3
"""
Program to manage and run ATS regression tests.

With inspiration, and in some places just stolen, from Ben Andre's
PFloTran regression test suite.

Author: Ethan Coon (ecoon@lanl.gov)
"""

import argparse
import sys,os
import textwrap
import time

def commandline_options():
    """
    Process the command line arguments and return them as a dict.
    """
    parser = argparse.ArgumentParser(description='Run an ATS regression '
                                     'tests or suite of tests.')
    parser.add_argument('--ats', default=None,
                        help='Path to ATS source directory')
    
    parser.add_argument('--backtrace', action='store_true',
                        help='show exception backtraces as extra debugging '
                        'output')

    parser.add_argument('--check-only', action='store_true', default=False,
                        help="diff the existing regression files without "
                        "running ATS again.")

    parser.add_argument('--check-performance', action='store_true', default=False,
                        help="include the performance metrics ('SOLUTION' blocks) "
                        "in regression checks.")

    parser.add_argument('--debug', action='store_true',
                        help='extra debugging output')

    parser.add_argument('-d', '--dry-run',
                        default=False, action='store_true',
                        help='perform a dry run, setup the test commands but '
                        'don\'t run them')

    parser.add_argument('-e', '--executable', default=None,
                        help='path to executable to use for testing')

    parser.add_argument('--list-available-suites', default=False, action='store_true',
                        help='print the list of test suites from the config '
                        'file and exit')

    parser.add_argument('--list-available-tests', default=False, action='store_true',
                        help='print the list of tests from the config file '
                        'and exit')

    parser.add_argument('--list-tests', default=False, action='store_true',
                        help='print the list of selected tests from the config '
                        'file and exit')

    parser.add_argument('-m', '--mpiexec', default=None,
                        help="path to the executable for mpiexec (mpirun, etc)"
                        "on the current machine.")

    parser.add_argument('--mpiexec-global-args', default=None,
                        help="arguments that must be provided to mpiexec executable")

    parser.add_argument('--mpiexec-numprocs-flag', default='-n',
                        help="mpiexec flag to set number of MPI ranks")

    parser.add_argument('--always-mpiexec', default=False, action='store_true',
                        help="use mpiexec to launch all tests")

    parser.add_argument('-n', '--new-tests', default=False, action="store_true",
                        help="Indicate that there are new tests being run. "
                        "Skips the output check and creates a new gold file.")

    parser.add_argument('-r', '--rerun-failed', default=None, nargs='?', const=True,
                        help="Rerun only failed tests from a previous logfile.  If "
                        "a value is provided, it is the path to the logfile.  If no "
                        "value is provided, will search for the last logfile. "
                        "Note that a config file (or '.') must still be provided -- "
                        "only failed tests in the provided config files will be run.")
    
    parser.add_argument('--save-dt-history', default=False, action="store_true",
                        help="When used with --new-tests, does an additional run "
                        "to get the timestep history for more accurate comparison.")

    parser.add_argument('-s', '--suites', nargs="+", default=[],
                        help='space separated list of test suite names')

    parser.add_argument('-t', '--tests', nargs="+", default=[],
                        help='space separated list of test names')

    parser.add_argument('--exclude', nargs="+", default=[],
                        help='space separated list of test names to exclude')

    parser.add_argument('--timeout', nargs=1, default=None,
                        help="test timeout (for assuming a job has hung and "
                        "needs to be killed)")

    parser.add_argument('-u', '--update',
                        action="store_true", default=False,
                        help='update the tests listed by the "--tests" '
                        'option, with the current output becoming the new '
                        'gold standard')

    parser.add_argument('configs', metavar='CONFIG_LOCATION', type=str,
                        nargs='+', help='list of directories and/or configuration '
                        'files to parse for suites and tests')
    
    options = parser.parse_args()
    return options


def main(options):
    txtwrap = textwrap.TextWrapper(width=78, subsequent_indent=4*" ")
    root_dir = os.getcwd()

    # find and import test_manager
    if options.ats is not None:
        sys.path.append(os.path.join(options.ats, 'tools', 'testing'))
    if 'ATS_SRC_DIR' in os.environ:
        sys.path.append(os.path.join(os.environ['ATS_SRC_DIR'], 'tools', 'testing'))
    import test_manager

    # silent here means limited stdout for use by cmake or simple list calls
    silent = options.list_tests or options.list_available_suites or options.list_available_tests

    # create the logfile
    testlog = test_manager.setup_testlog(txtwrap, silent)

    test_manager.check_options(options)

    # if using rerun-failed option, parse logfile for failed tests
    if options.rerun_failed:
        if isinstance(options.rerun_failed, bool):
            options.rerun_failed = test_manager.find_last_logfile()
        options.tests = test_manager.find_failed(options.rerun_failed)

        # need to short-circuit return here, because empty test list
        # will be interpreted as running all tests
        if len(options.tests) == 0:
            return 0

    # find executable and mpi
    if silent:
        executable = None
        mpiexec = None
    else:
        executable = test_manager.check_for_executable(options, testlog)
        mpiexec = test_manager.check_for_mpiexec(options, testlog)

    config_file_list = test_manager.generate_config_file_list(options)

    if not silent:
        print("Running ATS regression tests :")

    # loop through config files, cd into the appropriate directory,
    # read the appropriate config file and run the various tests.
    start = time.time()
    report = {}
    for config_file in config_file_list:
        print(80 * '=', file=testlog)
        print(f'Running {config_file}', file=testlog)
        header = os.path.split(config_file)[-1]
        if len(header) > 20:
            header = header[:20]
        else:
            header = header + ' '*(20-len(header))

        if not silent:
            print(f'{header} | ', end='', file=sys.stdout)

        # get the absolute path of the directory
        test_dir = os.path.dirname(config_file)
        # cd into the test directory so that the relative paths in
        # test files are correct
        os.chdir(test_dir)
        if options.debug:
            print("Changed to working directory: {0}".format(test_dir))

        tm = test_manager.RegressionTestManager(executable, mpiexec)

        if options.debug:
            tm.debug(True)

        # get the relative file name
        filename = os.path.basename(config_file)

        tm.generate_tests(filename,
                          options.suites,
                          options.tests,
                          options.exclude,
                          options.timeout,
                          options.check_performance,
                          testlog)

        if options.debug:
            print(70 * '-')
            print(tm)

        if options.list_available_suites:
            tm.display_available_suites()

        if options.list_available_tests:
            tm.display_available_tests()

        if options.list_tests:
            tm.display_selected_tests()

        if not silent:
            tm.run_tests(options.dry_run,
                         options.update,
                         options.new_tests,
                         options.check_only,
                         False,
                         testlog,
                         options.save_dt_history)

            report[filename] = tm.run_status()

            # Not sure why this is needed to get proper printing when there are no tests...
            if tm.num_tests() == 0:
                print('', file=sys.stdout)
        
        os.chdir(root_dir)
            
    stop = time.time()
    status = 0
    if not options.dry_run and not options.update and not options.list_tests:
        print("")
        run_time = stop - start
        test_manager.summary_report_by_file(report, testlog)
        test_manager.summary_report(run_time, report, testlog)
        status = test_manager.summary_report(run_time, report, sys.stdout)

    if options.update:
        message = txtwrap.fill(
            "Test results were updated! Please document why you modified the "
            "gold standard test results in your revision control commit message!\n")
        print(''.join(['\n', message, '\n']))

    testlog.close()

    return status

if __name__ == "__main__":
    cmdl_options = commandline_options()
    suite_status = main(cmdl_options)
    sys.exit(suite_status)

