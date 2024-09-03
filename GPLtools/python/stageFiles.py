#  stageFiles.py
"""@brief Manage staging of files to/from machine-local disk.
$Id$
@author W. Focke <focke@slac.stanford.edu>

refactored: T.Glanzman 2/22/2007
"""

## Preliminaries
import os
import re
import sys
import shutil
import time

import fileOps
import runner

## Set up message logging
import logging
log = logging.getLogger("gplLong")

filterAfs = '^/afs/'
filterAll = '.*'
filterNone = None
defaultStrictSetup = False

class StageSet:

    """@brief Manage staging of files to/from machine-local disk.

    simple example:
    > stagedStuff = StageSet()
    > sIn = stagedStuff.stageIn(inFile)
    > sOut = stagedStuff.stageOut(outFile)
    > os.system('do_something < %s > %s' % (sIn, sOut))
    > stagedStuff.finish()
    instead of:
    > os.system('do_something < %s > %s' % (inFile, outFile))

    The values returned by stageIn and stageOut may be the same as
    their inputs if staging is not possible.

    @todo Write out a persistent representation so that multiple processes
    could use the same staging set, and only the last one to run would
    call finish().  Or maybe have some way that processes could register
    a "hold" on the set, and calls to finish would have no effect until all
    holds had been released.

    @todo Allow user to write out "junk" files to the staging area and
    not needing or wanting to copy them back, and also for copying back
    any files that are found in the staging area at "finish" time.

    @todo Allow for the use of subdirectories of files in the staging
    area (e.g. the various Pulsar files that get produced by Gleam MC)



    
    """


    def __init__(self, stageName=None, stageArea=None, excludeIn=filterAfs,
                 excludeOut=filterNone, autoStart=True, strictSetup=None):
        """@brief Initialize the staging system
        @param [stageName] Name of directory where staged copies are kept.
        @param [stageArea] Parent of directory where staged copies are kept.
        @param [exculde] Regular expresion for file names which should not be staged.
        """

        if strictSetup is None: strictSetup = defaultStrictSetup

        log.debug("Entering stageFiles constructor...")
        self.setupFlag = 0
        self.setupOK = 0

        self.excludeIn = excludeIn
        self.excludeOut = excludeOut
        self.autoStart = autoStart
        
        ##
        ## defaultStateAreas defines all possible machine-local stage
        ## directories/partitions:
        ##
        ## S3DF machines all have local /lscratch for this purpose
        ## The shared scratch space is located at /sdf/scratch/fermi 
        ## Funally, interactive machines have scratch space at /tmp
        
        
        defaultStageAreas=["/lscratch/glastraw","/sdf/scratch/fermi","/tmp"]

        ##
        ## Construct path to staging area
        ## Priorities:
        ##  1     $GPL_STAGEROOTDEV (if defined)
        ##  2     Constructor argument
        ##  3     $GPL_STAGEROOT (if defined)
        ##  4     Selection from hard-wired default list
        try:
            envvarStageAreaDev = os.environ['GPL_STAGEROOTDEV']
            stageArea = envvarStageAreaDev
            log.debug('stageArea defined from $GPL_STAGEROOTDEV: '+stageArea)
        except KeyError:
            if stageArea is None:
                try:
                    envvarStageArea = os.environ['GPL_STAGEROOT']
                    stageArea = envvarStageArea
                    log.debug('stageArea defined from $GPL_STAGEROOT: '+stageArea)
                except KeyError:
                    for x in defaultStageAreas:
                        if os.access(x,os.W_OK):        # Does stageArea already exist?
                            log.debug("Successful access of "+x)
                            stageArea=x
                            log.debug('stageArea defined from default list: '+stageArea)
                            break
                        
                        else:                           # Try to create stageArea
                            try:
                                rc = fileOps.makedirs(x)
                                stageArea=x
                                log.debug("Successful creation of "+x)
                                log.debug('stageArea defined from default list: '+stageArea)
                                break
                            except:                     # No luck, revert to $PWD
                                log.warning("Staging cannot use "+x)
                                stageArea=os.environ['PWD']
                                pass
                            pass
                        pass
                    pass
                pass
            
            else:
                log.debug('stageArea defined by constructor argument: '+stageArea)
                pass
                    
        log.debug("Selected staging root directory = "+stageArea)

        if stageName is None:
            stageName = `os.getpid()`    # aim for something unique if not specified
            pass
 
        self.stageDir = os.path.join(stageArea, stageName)
        log.debug('Targeted staging directory = '+self.stageDir)
        self.setup()

        if strictSetup and not self.setupOK:
            raise OSError, "Couldn't setup staging!"

        return


    def setup(self):
        """@brief Create a staging area directory (intended as a private function)"""

        log.debug("Entering stage setup...")

        stageExists = os.access(self.stageDir,os.F_OK)
        log.debug("os.access = "+`stageExists`)

        ## Check if requested staging directory already exists and, if
        ## not, try to create it
        if stageExists:
            log.info("Requested stage directory already exists: "+self.stageDir)
            self.setupOK=1
            self.listStageDir()
        else:
            try:
                rc = fileOps.makedirs(self.stageDir)
                self.setupOK=1
                log.debug("Successful creation of "+self.stageDir)
            except OSError:
                log.warning('Staging disabled: error from makedirs: '+self.stageDir)
                self.stageDir=""
                self.setupOK=0
                pass
            pass
        
        log.debug("os.access = "+`os.access(self.stageDir,os.F_OK)`)
            
        ## Initialize file staging bookkeeping
        self.reset()
        self.setupFlag = 1
        return


    def reset(self):
        """@brief Initialize internal dictionaries/lists/counters
        (intended as a private function)"""
        self.stagedFiles = []
        self.numIn=0
        self.numOut=0
        self.numMod=0
        self.xrootdIgnoreErrors = False

    def xrootdIgnore(self,flag):
        log.info("Setting xrootdIgnoreErrors to "+str(flag))
        self.xrootdIgnoreErrors = flag

    def stageIn(self, inFile):
        """@brief Stage an input file.
        @param inFile real name of the input file
        @return name of the staged file
        """
        if self.setupFlag <> 1: self.setup()

        if self.setupOK <> 1:
            log.warning("Stage IN not available for: "+inFile)
            return inFile
        elif self.excludeIn and re.search(self.excludeIn, inFile):
            log.info("Staging disabled for file '%s' by pattern '%s'." %
                     (inFile, self.excludeIn))
            return inFile
        else:
            cleanup = True
            stageName = self.stagedName(inFile)
            pass
        
        log.info("\nstageIn for: "+inFile)

        inStage = StagedFile(stageName, source=inFile,
                             cleanup=cleanup, autoStart=self.autoStart)

        self.numIn=self.numIn+1
        self.stagedFiles.append(inStage)

        return stageName

    
    def stageOut(self, *args):
        """@brief Stage an output file.
        @param outFile [...] = real name(s) of the output file(s)
        @return name of the staged file
        """
        if self.setupFlag <> 1: setup()

## Build stage file map even if staging is disabled - so that copying
## to possible 2nd target (e.g., xrootd) will still take place
        
        if not args:
            log.error("Primary stage file not specified")
            return ""
        
        outFile = args[0]
        destinations = args

        if self.setupOK <> 1:
            log.warning("Stage OUT not available for "+outFile)
            stageName = outFile
            cleanup = False
        elif self.excludeOut and re.search(self.excludeOut, outFile):
            log.info("Staging disabled for file '%s' by pattern '%s'." %
                     (outFile, self.excludeOut))
            stageName = outFile
            cleanup = False
        else:
            stageName = self.stagedName(outFile)
            log.info("\nstageOut for: "+outFile)
            cleanup = True
            pass

        outStage = StagedFile(
            stageName, destinations=destinations, cleanup=cleanup)
        self.stagedFiles.append(outStage)

        self.numOut=self.numOut+1

        return stageName








    def stageMod(self, modFile):
        """@brief Stage a in a file to be modified and then staged out
        @param modFile real name of the target file
        @return name of the staged file
        """
        if self.setupFlag <> 1: self.setup()

        if self.setupOK <> 1:
            log.warning("Stage MOD not available for: "+modFile)
            return modFile
        elif self.excludeIn and re.search(self.excludeIn, modFile):
            log.info("Staging disabled for file '%s' by pattern '%s'." %
                     (modFile, self.excludeIn))
            return modFile
        else:
            cleanup = True
            stageName = self.stagedName(modFile)
            pass
        
        log.info("\nstageMod for: "+modFile)

        modStage = StagedFile(stageName, source=modFile, destinations=[modFile],
                             cleanup=cleanup, autoStart=self.autoStart)

        self.numMod += 1
        self.stagedFiles.append(modStage)

        return stageName

    









    def start(self):
        rc = 0
        for stagee in self.stagedFiles:
            rc |= stagee.start()
            continue
        return rc
    


    def finish(self,option=""):
        """@brief Delete staged inputs, move outputs to final destination.
        option: additional functions
        keep    - no additional function (in anticipation of further file use)
        clean   - +move/delete all staged files (in anticipation of further directory use)
        <null>  - +remove stage directories (full cleanup)
        wipe    - remove stage directories WITHOUT copying staged files to destination
        """
        log.debug('Entering stage.finish('+option+')')
        rc = 0     # overall

        keep = False
        
        ## bail out if no staging was done
        if self.setupOK == 0:
            log.warning("Staging disabled: look only if secondary target needs to receive produced file(s).")
        log.debug("*******************************************")

        if option == 'wipe':
            log.info(
                'Deleting staging directory without retrieving output files.')
            if self.setupOK <> 0:
                return self._removeDir()
            pass
        elif option == 'keep':
            keep = True
            pass

        # copy stageOut files to their final destinations
        for stagee in self.stagedFiles:
            rc |= stagee.finish(keep)
            continue
    
        if option == "keep": return rc              # Early return #1

        # Initialize stage data structures
        log.info("Initializing internal staging structures")
        self.reset()

        if option == "clean": return rc           # Early return #2
                            
        # remove stage directory (unless staging is disabled)
        if self.setupOK <> 0:
            rc |= self._removeDir()
            pass
        
        self.setupFlag=0
        self.setupOK=0
        self.reset()
 
        return rc


    def _removeDir(self):

        rc = 0

        # remove stage directory (unless staging is disabled)
        if self.setupOK <> 0:
            try:
                fileOps.rmdir(self.stageDir)
                log.info("Removed staging directory "+str(self.stageDir))
                rc = 0
            except:
                log.warning("Staging directory not empty after cleanup!!")
                log.warning("Content of staging directory "+self.stageDir)
                os.system('ls -l '+self.stageDir)
                log.warning("*** All files & directories will be deleted! ***")
                try:
                    fileOps.rmtree(self.stageDir)
                    rc = 0
                except:
                    log.error("Could not remove stage directory, "+self.stageDir)
                    rc = 2
                    pass
                pass
            pass
 
    
        self.setupFlag=0
        self.setupOK=0
        self.reset()
 
        return rc



    def stagedName(self, fileName):
        """@brief Generate names of staged files.
        @param fileName Real name of file.
        @return Name of staged file.
        """
        base = os.path.basename(fileName)
        stageName = os.path.join(self.stageDir, base)
        return stageName



### Utilities:  General information about staging and its files


    def getChecksums(self,printflag=None):
        """@brief Return a dictionary of: [stagedOut file name,[length,checksum] ].  Call this after creating file(s), but before finish(), if at all.  If the printflag is set to 1, a brief report will be sent to stdout."""
        cksums = {}
        # Compute checksums for all stagedOut files
        log.info("Calculating 32-bit CRC checksums for stagedOut files")
        for stagee in self.stagedFiles:
            if len(stagee.destinations) != 0:
                file = stagee.location
                if os.access(file,os.R_OK):
                    cksum = "cksum "+file
                    fd = os.popen(cksum,'r')    # Capture output from unix command
                    foo = fd.read()             # Calculate checksum
                    rc = fd.close()
                    if rc != None:
                        log.warning("Checksum error: return code =  "+str(rc)+" for file "+file)
                    else:
                        cksumout = foo.split()
                        cksums[cksumout[2]] = [cksumout[0],cksumout[1]]
                        pass
                else:
                    log.warning("Checksum error: file does not exist, "+file)
                    pass
                pass
            continue
# Print report, if requested
        if int(printflag) == 1:
            log.info("Checksum report")
            print "\n"
            for cksum in cksums:
                print "Checksum report for file: ",cksum," checksum=",cksums[cksum][0]," bytes=",cksums[cksum][1]
                pass
            print "\n"
            pass
        return cksums



    def getStageDir(self):
        """@brief Return the name of the stage directory being used"""
        if self.setupOK == 0: return ""
        return self.stageDir



    def listStageDir(self):
        """@brief List contents of current staging directory"""
        if self.setupOK == 0: return
        log.info("\nContents of stage directory \n ls -laF "+self.stageDir)
        dirlist = os.system('ls -laF '+self.stageDir)
        return


    def getStageStatus(self):
        """@brief Return status of file staging
        0 = staging not in operation
        1 = staging initialized and in operation
        """
        return self.setupOK



    def dumpStagedFiles(self):
        """@brief Dump names of staged files to stdout"""
        log.info('\n\n\tStatus of File Staging System')
        log.info('setupFlag= '+str(self.setupFlag)+', setupOK= '+str(self.setupOK)+', stageDirectory= '+str(self.stageDir)+'\n')
        log.info(str(self.numIn)+" files being staged in")
        log.info(str(self.numOut)+" files being staged out")
        log.info(str(self.numMod)+" files being staged in/out for modification\n")

        # copy stageOut files to their final destinations
        for stagee in self.stagedFiles:
            stagee.dumpState()
            continue
        return

    def dumpFileList(self, mylist):
        """@brief Dummy for backward compatibility"""
        print "Entering dumpFileList (dummy method)"
        return




class StagedFile(object):

    def __init__(self, location, source=None, destinations=[],
                 cleanup=False, autoStart=True):
        self.source = source                   # (stageIn) original file location
        self.location = location               # temporary file location during job
        self.destinations = list(destinations) # (stageOut) list of final destinations for file
        self.cleanup = cleanup                 # cleanup=>remove file at finish()
        self.started = False                   # (stageIn) file has been copied to scratch area
        if location in self.destinations:      # prevent shooting self in foot
            self.destinations.remove(location)
            self.cleanup = False
            pass
        if autoStart:                          # cause files to be stagedIn
            self.start()
            pass
        self.dumpState()
        return

    def dumpState(self):
        log.info('StagedFile 0x%x' % id(self))
        log.info('source: %s' % self.source)
        log.info('location: %s' % self.location)
        log.info('destinations: %s' % self.destinations)
        log.info('cleanup: %s' % self.cleanup)
        log.info('started: %s' % self.started)
        return

    def start(self):                   # copy stagedIn file to temporary working area
        self.dumpState()
        rc = 0
        if self.source and self.location != self.source and not self.started:
            rc = fileOps.copy(self.source, self.location)
            pass
        if rc:
            raise IOError, "Can't stage in %s" % self.source
        self.started = True
        return rc

    def finish(self, keep=False):      # copy stagedOut file to final destination(s) & cleanup
        self.dumpState()
        rc = 0
        if not 'SCRATCH' in self.destinations:
            for dest in self.destinations:
                rc |= fileOps.copy(self.location, dest)
                continue
            pass
        else:
            log.info('File declared scratch, not copying to destination: '+self.destinations[0])
            pass
        
        if not keep and self.cleanup and os.access(self.location, os.W_OK):
            log.info('Nuking %s' % self.location)
            fileOps.remove(self.location)
        else:
            log.info('Not nuking %s' % self.location)
            pass
        return rc
    pass

