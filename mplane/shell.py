# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
##
# mPlane Software Development Kit for Python 3
# Utility classes for asynchronous command-line clients
#
# (c) 2016 MAMI Project (https://www.mami-project.eu)
#               Author: Brian Trammell <brian@trammell.ch>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser
# General Public License for more details. You should have received a copy
# of the GNU General Public License along with this program.  If not, see
# <http://www.gnu.org/licenses/>.


from prompt_toolkit.shortcuts import prompt_async
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.completion import Completer
from prompt_toolkit.completion import Completion

import sys
import asyncio
import traceback
import logging

# make prompt_toolkit look like cmd, asynchronously

class AsyncPromptShell:
    """
    Utility class for building a Cmd-like 
    asynchronous command-line shell atop prompt_toolkit

    Inherit from this class and create cmd_ functions to handle commands
    """
    def __init__(self, prompt_text, completer=None, loop=None):
        self.prompt_text = prompt_text
        self.completer = completer
        self._traceback_mode = False

        self.history = InMemoryHistory()

        self.quit = asyncio.Event()

        if loop:
            self.loop = loop
        else:
            self.loop = asyncio.get_event_loop()

    async def next_command(self, text=None):
        # display a prompt and get input
        if not text:
            try:
                text = await prompt_async(self.prompt_text, 
                                          history=self.history, 
                                          completer=self.completer)
            except EOFError:
                return self.cmd_quit()

        # shortcut blank lines and comments
        if not len(text.lstrip()) or text.lstrip().startswith("#")
            return

        # split into command and args
        (cmd, *args) = text.split()

        # dot means source
        if cmd == ".":
            cmd = "source"

        try:
            fn_name = "cmd_"+cmd.lower()
            print("trying to get "+fn_name+" on "+repr(self))
            fn = getattr(self, fn_name)
            print("got "+repr(fn))
            return fn(*args)
        except AttributeError as ae:
            print(str(ae))
            print("I don't know how to "+cmd+". Available commands:")
            print(self._summary())
        except TypeError as te:
            print(str(te))
        except Exception as e:
            if self._traceback_mode:
                traceback.print_tb(sys.exc_info()[2])
            else:
                print("failed: "+str(e))

    async def command_loop(self):
        while not self.quit.is_set():
            await self.next_command()

    def _summary(self):
        out = ""
        for cmd in map(lambda x: str(x).partition("_")[2],
                       filter(lambda x: str(x).startswith("cmd_"), dir(self))):
            cmd_info = self._describe(cmd)
            out += ("  %12s :  %60s\n" % (cmd.rjust(12), cmd_info.ljust(60)))
        return out

    def _describe(self, cmd_name):
        try:
            ds = getattr(self, "cmd_"+cmd_name).__doc__
            if not ds:
                return ""
            return ds.split("\n")[1].lstrip()
        except AttributeError as ae:
            return ""

    def _help(self, cmd_name):
        try:
            ds = getattr(self, "cmd_"+cmd_name).__doc__
            if not ds:
                return ""
            return "\n".join(map(lambda x: x.lstrip(), ds.split("\n")[1:]))
        except AttributeError as ae:
            return ""

    def cmd_traceback(self, *args):
        """
        Set traceback mode

        When traceback mode is enabled, full tracebacks will be printed for
        each exception occuring in the shell. Otherwise, only a brief error
        message will be printed.

        """
        if (len(args) > 0) and (args[0].startswith("0") or
                                args[0].startswith("n")):
            self._traceback_mode = False
            print("traceback disabled")
        else:
            self._traceback_mode = True
            print("traceback enabled")

    def cmd_help(self, *args):
        """
        Get help on a command, or list available

        If called with a command name (e.g. help traceback), print full
        documentation for that command. Otherwise, list commands with 
        summary documentation for each.

        """
        if len(args) > 0:
            hs = self._help(args[0])
            if hs:
                print(hs)
            else:
                "no help available"
        else:
            print(self._summary())

    def cmd_source(self, filename, *ignored):
        with open(filename) as script:
            for line in script:
                self.loop.run_until_complete(next_command(line))

    def cmd_quit(self, *ignored):
        """
        Quit. (Ctrl-D/EOF also works)

        """
        print("Exiting. Ciao!")
        self.quit.set()

    def go(self):
        self.loop.run_until_complete(self.command_loop())
