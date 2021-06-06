#!/usr/bin/env python


""""
Enhance.py

Run engine bench command and return nodes.

format:
    bench <hash> <threads> <limitvalue> <fenfile | default>
          <limittype [depth(default), perft, nodes, movetime]> <evaltype [mixed(default), classical, NNUE]>

bench 128 1 4 file.epd depth mixed
"""


__author__ = 'fsmosca'
__script_name__ = 'Enhance'
__version__ = 'v0.1.0'
__credits__ = ['musketeerchess']


from pathlib import Path
import subprocess
import argparse
import time
import random
import concurrent.futures
from concurrent.futures import ProcessPoolExecutor
import logging
from statistics import mean
from typing import List
import multiprocessing
from datetime import datetime


logging.basicConfig(
    filename='enhance_log.txt', filemode='w',
    level=logging.DEBUG,
    format='%(asctime)s - pid%(process)5d - %(levelname)5s - %(message)s')


class Enhance:
    def __init__(self, engineinfo, hashmb=64, threads=1, limitvalue=15,
                 fenfile='default', limittype='depth', evaltype='mixed',
                 concurrency=1):
        self.engineinfo = engineinfo
        self.hashmb = hashmb
        self.threads = threads
        self.limitvalue = limitvalue
        self.fenfile=fenfile
        self.limittype=limittype
        self.evaltype=evaltype
        self.concurrency = concurrency

        self.nodes = None  # objective value

    def send(self, p, command):
        """ Send msg to engine """
        p.stdin.write('%s\n' % command)
        logging.debug('>> %s' % command)
        
    def read_engine_reply(self, p, command):
        """ Read reply from engine """
        self.nodes = None
        for eline in iter(p.stdout.readline, ''):
            line = eline.strip()
            logging.debug('<< %s' % line)
            if command == 'uci' and 'uciok' in line:
                break
            if command == 'isready' and 'readyok' in line:
                break
            # Nodes searched  : 3766422
            if command == 'bench' and 'nodes searched' in line.lower():
                self.nodes = int(line.split(': ')[1])
            elif command == 'bench' and 'Nodes/second' in line:
                break

    def match(self, fenfn) -> int:
        """
        Run the engine, send a bench command and return the nodes searched.
        """
        folder = Path(self.engineinfo['cmd']).parent
        print(self.engineinfo['cmd'])

        # Start the engine.
        proc = subprocess.Popen(self.engineinfo['cmd'], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, bufsize=1, cwd=folder)

        self.send(proc, 'uci')
        self.read_engine_reply(proc, 'uci')

        self.send(proc, 'isready')
        self.read_engine_reply(proc, 'isready')

        # Set param values to be optimized.
        for k, v in self.engineinfo['opt'].items():
            self.send(proc, f'setoption name {k} value {v}')

        self.send(proc, f'bench {self.hashmb} {self.threads} {self.limitvalue} {fenfn} {self.limittype} {self.evaltype}')
        # self.send(proc, f'bench')
        self.read_engine_reply(proc, 'bench')

        # Quit the engine.
        self.send(proc, 'quit')

        return self.nodes

    def generate_files(self, posperfile, randomsort=True):
        """
        Read fen file and split it into different files by the number of workers.
        """
        fenlist, filelist = [], []

        fen_file = Path(self.fenfile)
        if not fen_file.is_file():
            return filelist

        with open(self.fenfile) as f:
            for lines in f:
                fen = lines.rstrip()
                fenlist.append(fen)

        # sort if required
        if randomsort:
            random.shuffle(fenlist)

        for i in range(self.concurrency):
            start = i * posperfile
            end = (i+1) * posperfile

            fens = fenlist[start:end]
            fn = f'file{i}.fen'

            with open(fn, 'a') as f:
                for fen in fens:
                    f.write(f'{fen}\n')

            filelist.append(fn)

        logging.debug(f'filelist: {filelist}')

        return filelist

    def run(self):
        """Run the engine to get the objective value."""
        objectivelist, joblist = [], []
        posperfile, israndom = 24, False

        fenfiles = self.generate_files(posperfile, israndom)
        print(f'fenfiles: {fenfiles}')

        # Use Python 3.8 or higher.
        with ProcessPoolExecutor(max_workers=self.concurrency) as executor:
            if len(fenfiles) == 0:
                job = executor.submit(self.match, 'default')
                joblist.append(job)
            else:
                for fn in fenfiles:
                    job = executor.submit(self.match, fn)
                    joblist.append(job)

            for future in concurrent.futures.as_completed(joblist):
                try:
                    nodes_searched = future.result()
                    print(f'nodes_searched {nodes_searched}')
                    objectivelist.append(nodes_searched)
                except concurrent.futures.process.BrokenProcessPool as ex:
                    print(f'exception: {ex}')

        # This is used by optimizer to signal that the job is done.
        print(f'nodes searched: {int(mean(objectivelist))}')
        print('Finished match')


def define_engine(engine_option_value):
    """
    Define engine files, and options.
    """
    optdict = {}
    engineinfo = {'cmd': None, 'opt': optdict}

    for eng_opt_val in engine_option_value:
        for value in eng_opt_val:
            if 'cmd=' in value:
                engineinfo.update({'cmd': value.split('=')[1]})
            elif 'option.' in value:
                # option.QueenValueOpening=1000
                optn = value.split('option.')[1].split('=')[0]
                optv = int(value.split('option.')[1].split('=')[1])
                optdict.update({optn: optv})
                engineinfo.update({'opt': optdict})

    return engineinfo


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        prog='%s %s' % (__script_name__, __version__),
        description='Run bench command.',
        epilog='%(prog)s')
    parser.add_argument('-engine', nargs='*', action='append', required=True,
                        metavar=('cmd=', 'option.<optionname>=value'),
                        help='Define engine filename and option, required=True. Example:\n'
                        '-engine cmd=eng.exe option.FutilityMargin=120 option.MoveCount=1000')
    parser.add_argument('-concurrency', required=False,
                        help='The number of process to run in parallel, default=1',
                        type=int, default=1)
    parser.add_argument('-hashmb', required=False, help='memory value in mb, default=64',
                        type=int, default=64)
    parser.add_argument('-threads', required=False, help='number of threads, default=1',
                        type=int, default=1)
    parser.add_argument('-limitvalue', required=False,
                        help='a number that limits the engine search, default=15',
                        type=int, default=15)
    parser.add_argument('-fenfile', required=False,
                        help='Filename of FEN file.',
                        default='default')
    parser.add_argument('-limittype', required=False,
                        help='the type of limit can be depth, perft, nodes and movetime, default=depth',
                        type=str,
                        default='depth')
    parser.add_argument('-evaltype', required=False,
                        help='the type of eval to use can be mixed, classical or NNUE, default=mixed',
                        type=str, default='mixed')
    parser.add_argument('-v', '--version', action='version', version=f'{__version__}')

    args = parser.parse_args()

    # Define engine files, name and options.
    engineinfo = define_engine(args.engine)

    # Exit if engine file is not defined.
    if engineinfo['cmd'] is None:
        print('Error, engines are not properly defined!')
        return

    duel = Enhance(engineinfo, hashmb=args.hashmb, threads=args.threads,
                   limitvalue=args.limitvalue, fenfile=args.fenfile,
                   limittype=args.limittype, evaltype=args.evaltype,
                   concurrency=args.concurrency)
    duel.run()


if __name__ == '__main__':
    main()
