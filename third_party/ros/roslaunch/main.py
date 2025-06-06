# Software License Agreement (BSD License)
#
# Copyright (c) 2008, Willow Garage, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# Revision $Id$
# pylint: disable=bare-except,broad-except
# pylint: disable=line-too-long
# pylint: disable=deprecated-module,consider-using-f-string,unspecified-encoding
import logging
import os
import socket
import sys
import traceback
from optparse import OptionParser

import rosgraph.roslogging
import rospkg
from rosmaster import DEFAULT_MASTER_PORT
from rosmaster.master_api import NUM_WORKERS

from third_party.ros.roslaunch import arg_dump
from third_party.ros.roslaunch import child
from third_party.ros.roslaunch import core
from third_party.ros.roslaunch import node_args
from third_party.ros.roslaunch import param_dump
from third_party.ros.roslaunch import parent
from third_party.ros.roslaunch import rlutil
from third_party.ros.roslaunch.core import RLException
from third_party.ros.roslaunch.nodeprocess import DEFAULT_TIMEOUT_SIGINT
from third_party.ros.roslaunch.nodeprocess import DEFAULT_TIMEOUT_SIGTERM

NAME = 'roslaunch'


def configure_logging(uuid):
    """
    scripts using roslaunch MUST call configure_logging
    """
    try:
        logfile_basename = os.path.join(
            uuid, '%s-%s-%s.log' % (NAME, socket.gethostname(), os.getpid()))
        # additional: names of python packages we depend on that may also be logging
        logfile_name = rosgraph.roslogging.configure_logging(
            NAME, filename=logfile_basename)
        if logfile_name:
            print('... logging to %s' % logfile_name)

        # add logger to internal roslaunch logging infrastructure
        logger = logging.getLogger('roslaunch')
        core.add_printlog_handler(logger.info)
        core.add_printerrlog_handler(logger.error)
    except:
        print(
            'WARNING: unable to configure logging. No log files will be generated',
            file=sys.stderr)


def write_pid_file(options_pid_fn, options_core, port):
    if options_pid_fn or options_core:
        # #2987
        ros_home = rospkg.get_ros_home()
        if options_pid_fn:
            pid_fn = os.path.expanduser(options_pid_fn)
            if os.path.dirname(
                    pid_fn) == ros_home and not os.path.exists(ros_home):
                os.makedirs(ros_home)
        else:
            # NOTE: this assumption is not 100% valid until work on #3097 is complete
            if port is None:
                port = DEFAULT_MASTER_PORT
            pid_fn = os.path.join(ros_home, 'roscore-%s.pid' % (port))
            # #3828
            if not os.path.exists(ros_home):
                os.makedirs(ros_home)

        with open(pid_fn, 'w') as f:
            f.write(str(os.getpid()))


def _get_optparse():
    usage = 'usage: %prog [options] [package] <filename> [arg_name:=value...]\n'
    usage += '       %prog [options] <filename> [<filename>...] [arg_name:=value...]\n\n'
    usage += "If <filename> is a single dash ('-'), launch XML is read from standard input."
    parser = OptionParser(usage=usage, prog=NAME)
    parser.add_option(
        '--files',
        dest='file_list',
        default=False,
        action='store_true',
        help=
        'Print list files loaded by launch file, including launch file itself')
    parser.add_option('--args',
                      dest='node_args',
                      default=None,
                      help='Print command-line arguments for node',
                      metavar='NODE_NAME')
    parser.add_option('--nodes',
                      dest='node_list',
                      default=False,
                      action='store_true',
                      help='Print list of node names in launch file')
    parser.add_option('--find-node',
                      dest='find_node',
                      default=None,
                      help='Find launch file that node is defined in',
                      metavar='NODE_NAME')
    parser.add_option('-c',
                      '--child',
                      dest='child_name',
                      default=None,
                      help="Run as child service 'NAME'. Required with -u",
                      metavar='NAME')
    parser.add_option('--local',
                      dest='local_only',
                      default=False,
                      action='store_true',
                      help='Do not launch remote nodes')
    # #2370
    parser.add_option('--screen',
                      dest='force_screen',
                      default=False,
                      action='store_true',
                      help='Force output of all local nodes to screen')
    parser.add_option('--required',
                      dest='force_required',
                      default=False,
                      action='store_true',
                      help='Force all nodes to be required')
    parser.add_option('--log',
                      dest='force_log',
                      default=False,
                      action='store_true',
                      help='Force output of all local nodes to log')
    parser.add_option('-u',
                      '--server_uri',
                      dest='server_uri',
                      default=None,
                      help='URI of server. Required with -c',
                      metavar='URI')
    parser.add_option('--run_id',
                      dest='run_id',
                      default=None,
                      help='run_id of session. Required with -c',
                      metavar='RUN_ID')
    # #1254: wait until master comes online before starting
    parser.add_option('--wait',
                      action='store_true',
                      dest='wait_for_master',
                      default=False,
                      help='wait for master to start before launching')
    parser.add_option('-p',
                      '--port',
                      dest='port',
                      default=None,
                      help='master port. Only valid if master is launched',
                      metavar='PORT')
    parser.add_option('--core',
                      action='store_true',
                      dest='core',
                      default=False,
                      help='Launch core services only')
    parser.add_option('--pid',
                      dest='pid_fn',
                      default='',
                      help='write the roslaunch pid to filename')
    parser.add_option('-v',
                      action='store_true',
                      dest='verbose',
                      default=False,
                      help='verbose printing')
    parser.add_option('--no-summary',
                      action='store_true',
                      dest='no_summary',
                      default=False,
                      help='hide summary printing')
    # 2685 - Dump parameters of launch files
    parser.add_option('--dump-params',
                      default=False,
                      action='store_true',
                      dest='dump_params',
                      help='Dump parameters of all roslaunch files to stdout')
    parser.add_option('--skip-log-check',
                      default=False,
                      action='store_true',
                      dest='skip_log_check',
                      help='skip check size of log folder')
    parser.add_option(
        '--ros-args',
        default=False,
        action='store_true',
        dest='ros_args',
        help='Display command-line arguments for this launch file')
    parser.add_option('--disable-title',
                      default=False,
                      action='store_true',
                      dest='disable_title',
                      help='Disable setting of terminal title')
    parser.add_option(
        '-w',
        '--numworkers',
        dest='num_workers',
        default=NUM_WORKERS,
        type=int,
        help='override number of worker threads. Only valid for core services.',
        metavar='NUM_WORKERS')
    parser.add_option(
        '-t',
        '--timeout',
        dest='timeout',
        help=
        'override the socket connection timeout (in seconds). Only valid for core services.',
        metavar='TIMEOUT')
    parser.add_option(
        '--master-logger-level',
        dest='master_logger_level',
        default=False,
        type=str,
        help=
        "set rosmaster.master logger level ('debug', 'info', 'warn', 'error', 'fatal')"
    )
    parser.add_option(
        '--sigint-timeout',
        dest='sigint_timeout',
        default=DEFAULT_TIMEOUT_SIGINT,
        type=float,
        help='the SIGINT timeout used when killing nodes (in seconds).',
        metavar='SIGINT_TIMEOUT')
    parser.add_option(
        '--sigterm-timeout',
        dest='sigterm_timeout',
        default=DEFAULT_TIMEOUT_SIGTERM,
        type=float,
        help=
        'the SIGTERM timeout used when killing nodes if SIGINT does not stop the node (in seconds).',
        metavar='SIGTERM_TIMEOUT')

    return parser


def _validate_args(parser, options, args):
    # validate args first so we don't spin up any resources
    if options.child_name:
        if not options.server_uri:
            parser.error(
                '--child option requires --server_uri to be set as well')
        if not options.run_id:
            parser.error('--child option requires --run_id to be set as well')
        if options.port:
            parser.error('port option cannot be used with roslaunch child mode')
        if args:
            parser.error('Input files are not allowed when run in child mode')
    elif options.core:
        if options.run_id:
            parser.error(
                '--run_id should only be set for child roslaunches (-c)')

        # we don't actually do anything special for core as the roscore.xml file
        # is an implicit include for any roslaunch

    elif len(args) == 0:
        parser.error('you must specify at least one input file')
    else:
        missing_files = [f for f in args if not (f == '-' or os.path.exists(f))]
        if missing_files:
            parser.error('The following input files do not exist: %s' %
                         ', '.join(missing_files))

    if args.count('-') > 1:
        parser.error(
            "Only a single instance of the dash ('-') may be specified.")

    if len([
            x for x in [
                options.node_list, options.find_node, options.node_args,
                options.ros_args
            ] if x
    ]) > 1:
        parser.error(
            'only one of [--nodes, --find-node, --args --ros-args] may be specified'
        )


def handle_exception(roslaunch_core, logger, msg, e):
    roslaunch_core.printerrlog(msg + str(e))
    roslaunch_core.printerrlog(
        'The traceback for the exception was written to the log file')
    if logger:
        logger.error(traceback.format_exc())
    sys.exit(1)


def main(argv):
    options = None
    logger = None
    exit_code = 0
    try:
        parser = _get_optparse()

        (options, args) = parser.parse_args(argv[1:])
        args = rlutil.resolve_launch_arguments(args)
        _validate_args(parser, options, args)

        # node args doesn't require any roslaunch infrastructure, so process it first
        if any([
                options.node_args, options.node_list, options.find_node,
                options.dump_params, options.file_list, options.ros_args
        ]):
            if options.node_args and not args:
                parser.error('please specify a launch file')

            if options.node_args:
                node_args.print_node_args(options.node_args, args)
            elif options.find_node:
                node_args.print_node_filename(options.find_node, args)
            # Dump parameters, #2685
            elif options.dump_params:
                param_dump.dump_params(args)
            elif options.file_list:
                rlutil.print_file_list(args)
            elif options.ros_args:
                arg_dump.dump_args(args)
            else:
                node_args.print_node_list(args)
            return

        # we have to wait for the master here because we don't have the run_id yet
        if options.wait_for_master:
            if options.core:
                parser.error('--wait cannot be used with roscore')
            rlutil.wait_for_master()

        # write the pid to a file
        write_pid_file(options.pid_fn, options.core, options.port)

        # spin up the logging infrastructure. have to wait until we can read options.run_id
        uuid = rlutil.get_or_generate_uuid(options.run_id,
                                           options.wait_for_master)
        configure_logging(uuid)

        # #3088: don't check disk usage on remote machines
        if not options.child_name and not options.skip_log_check:
            # #2761
            rlutil.check_log_disk_usage()

        logger = logging.getLogger('roslaunch')
        logger.info('roslaunch starting with args %s', str(argv))
        logger.info('roslaunch env is %s', os.environ)

        if options.child_name:
            logger.info('starting %s in child mode', options.child_name)

            # This is a roslaunch child, spin up client server.
            # client spins up an XML-RPC server that waits for
            # commands and configuration from the server.
            c = child.ROSLaunchChild(uuid,
                                     options.child_name,
                                     options.server_uri,
                                     sigint_timeout=options.sigint_timeout,
                                     sigterm_timeout=options.sigterm_timeout)
            c.run()
            exit_code = c.exit_code
            logger.debug('child node %s done %d', options.child_name, exit_code)
        else:
            logger.info('starting in server mode')

            # #1491 change terminal name
            if not options.disable_title:
                rlutil.change_terminal_name(args, options.core)

            # Read roslaunch string from stdin when - is passed as launch filename.
            roslaunch_strs = []
            if '-' in args:
                core.printlog(
                    "Passed '-' as file argument, attempting to read roslaunch XML from stdin."
                )
                roslaunch_strs.append(sys.stdin.read())
                core.printlog('... %d bytes read successfully.\n' %
                              len(roslaunch_strs[-1]))
                args.remove('-')

            # This is a roslaunch parent, spin up parent server and launch processes.
            # args are the roslaunch files to load
            # force a port binding spec if we are running a core
            if options.core:
                options.port = options.port or DEFAULT_MASTER_PORT
            p = parent.ROSLaunchParent(
                uuid,
                args,
                roslaunch_strs=roslaunch_strs,
                is_core=options.core,
                port=options.port,
                local_only=options.local_only,
                verbose=options.verbose,
                force_screen=options.force_screen,
                force_log=options.force_log,
                num_workers=options.num_workers,
                timeout=options.timeout,
                master_logger_level=options.master_logger_level,
                show_summary=not options.no_summary,
                force_required=options.force_required,
                sigint_timeout=options.sigint_timeout,
                sigterm_timeout=options.sigterm_timeout)
            p.start()
            p.spin()
            exit_code = p.exit_code

    except RLException as e:
        handle_exception(core, logger, 'RLException: ', e)
    except ValueError as e:
        # TODO: need to trap better than this high-level trap
        handle_exception(core, logger, 'Value error: ', e)
    except rospkg.ResourceNotFound as e:
        handle_exception(core, logger, 'Resource not found: ', e)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    finally:
        # remove the pid file
        if options is not None and options.pid_fn:
            try:
                os.unlink(options.pid_fn)
            except os.error:
                pass

    sys.exit(exit_code)


if __name__ == '__main__':
    main(sys.argv)
