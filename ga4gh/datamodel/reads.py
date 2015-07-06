"""
Module responsible for translating read data into GA4GH native
objects.
"""
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import datetime
import os

import pysam

import ga4gh.protocol as protocol
import ga4gh.datamodel as datamodel
import ga4gh.exceptions as exceptions


class SamCigar(object):
    """
    Utility class for working with SAM CIGAR strings
    """
    # see http://pysam.readthedocs.org/en/latest/api.html
    # #pysam.AlignedSegment.cigartuples
    cigarStrings = [
        protocol.CigarOperation.ALIGNMENT_MATCH,
        protocol.CigarOperation.INSERT,
        protocol.CigarOperation.DELETE,
        protocol.CigarOperation.SKIP,
        protocol.CigarOperation.CLIP_SOFT,
        protocol.CigarOperation.CLIP_HARD,
        protocol.CigarOperation.PAD,
        protocol.CigarOperation.SEQUENCE_MATCH,
        protocol.CigarOperation.SEQUENCE_MISMATCH,
    ]

    @classmethod
    def ga2int(cls, value):
        for i, cigarString in enumerate(cls.cigarStrings):
            if value == cigarString:
                return i

    @classmethod
    def int2ga(cls, value):
        return cls.cigarStrings[value]


class SamFlags(object):
    """
    Utility class for working with SAM flags
    """
    NUMBER_READS = 0x1
    PROPER_PLACEMENT = 0x2
    READ_NUMBER_ONE = 0x40
    READ_NUMBER_TWO = 0x80
    SECONDARY_ALIGNMENT = 0x100
    FAILED_VENDOR_QUALITY_CHECKS = 0x200
    DUPLICATE_FRAGMENT = 0x400
    SUPPLEMENTARY_ALIGNMENT = 0x800

    @staticmethod
    def isFlagSet(flagAttr, flag):
        return flagAttr & flag == flag

    @staticmethod
    def setFlag(flagAttr, flag):
        flagAttr |= flag


class AbstractReadGroupSet(datamodel.DatamodelObject):
    """
    The base class of a read group set
    """
    def __init__(self, id_):
        self._id = id_
        self._readGroups = []

    def getId(self):
        # TODO move into the superclass
        return self._id

    def getReadGroups(self):
        """
        Returns the read groups in this read group set
        """
        return self._readGroups

    def toProtocolElement(self):
        """
        Returns the GA4GH protocol representation of this ReadGroupSet.
        """
        readGroupSet = protocol.ReadGroupSet()
        readGroupSet.id = self._id
        readGroupSet.readGroups = [
            readGroup.toProtocolElement() for readGroup in self._readGroups]
        readGroupSet.name = None
        readGroupSet.datasetId = None
        return readGroupSet


class SimulatedReadGroupSet(AbstractReadGroupSet):
    """
    A simulated read group set
    """
    def __init__(self, id_, numAlignments=2):
        super(SimulatedReadGroupSet, self).__init__(id_)
        readGroupId = "{}:one".format(id_)
        readGroup = SimulatedReadGroup(readGroupId, numAlignments)
        self._readGroups.append(readGroup)


class HtslibReadGroupSet(datamodel.PysamDatamodelMixin, AbstractReadGroupSet):
    """
    Class representing a logical collection ReadGroups.
    """
    def __init__(self, id_, dataDir):
        super(HtslibReadGroupSet, self).__init__(id_)
        self._dataDir = dataDir
        self._readGroups = []
        self._setAccessTimes(dataDir)
        self._scanDataFiles(dataDir, ["*.bam"])

    def _addDataFile(self, path):
        filename = os.path.split(path)[1]
        localId = os.path.splitext(filename)[0]
        readGroupId = "{}:{}".format(self._id, localId)
        readGroup = HtslibReadGroup(readGroupId, path)
        self._readGroups.append(readGroup)


class AbstractReadGroup(object):
    """
    Class representing a ReadGroup. A ReadGroup is all the data that's
    processed the same way by the sequencer.  There are typically 1-10
    ReadGroups in a ReadGroupSet.
    """
    def __init__(self, id_):
        self._id = id_
        now = protocol.convertDatetime(datetime.datetime.now())
        self._creationTime = now
        self._updateTime = now

    def getId(self):
        """
        Returns the id of the read group
        """
        return self._id

    def toProtocolElement(self):
        """
        Returns the GA4GH protocol representation of this ReadGroup.
        """
        # TODO this is very incomplete, but we don't have the
        # implementation to fill out the rest of the fields currently
        readGroup = protocol.ReadGroup()
        readGroup.id = self._id
        readGroup.created = self._creationTime
        readGroup.updated = self._updateTime
        readGroup.datasetId = None
        readGroup.description = None
        readGroup.experiment = None
        readGroup.info = {}
        readGroup.name = readGroup.id
        readGroup.predictedInsertSize = None
        readGroup.programs = []
        readGroup.referenceSetId = None
        readGroup.sampleId = None
        return readGroup


class SimulatedReadGroup(AbstractReadGroup):
    """
    A simulated readgroup
    """
    def __init__(self, id_, numAlignments=2):
        super(SimulatedReadGroup, self).__init__(id_)
        self._numAlignments = numAlignments

    def getReadAlignments(self, referenceId=None, start=None, end=None):
        for i in range(self._numAlignments):
            alignment = self._createReadAlignment(i)
            yield alignment

    def _createReadAlignment(self, i):
        # TODO fill out a bit more
        id_ = "{}:simulated{}".format(self._id, i)
        alignment = protocol.ReadAlignment()
        alignment.alignedQuality = [1, 2, 3]
        alignment.alignedSequence = "ACT"
        gaPosition = protocol.Position()
        gaPosition.position = 0
        gaPosition.referenceName = "whatevs"
        gaPosition.strand = protocol.Strand.POS_STRAND
        gaLinearAlignment = protocol.LinearAlignment()
        gaLinearAlignment.position = gaPosition
        alignment.alignment = gaLinearAlignment
        alignment.duplicateFragment = False
        alignment.failedVendorQualityChecks = False
        alignment.fragmentLength = 3
        alignment.fragmentName = id_
        alignment.id = id_
        alignment.info = {}
        alignment.nextMatePosition = None
        alignment.numberReads = None
        alignment.properPlacement = False
        alignment.readGroupId = self._id
        alignment.readNumber = None
        alignment.secondaryAlignment = False
        alignment.supplementaryAlignment = False
        return alignment


class HtslibReadGroup(datamodel.PysamDatamodelMixin, AbstractReadGroup):
    """
    A readgroup based on htslib's reading of a given file
    """
    def __init__(self, id_, dataFile):
        super(HtslibReadGroup, self).__init__(id_)
        self._samFilePath = dataFile
        try:
            self._samFile = pysam.AlignmentFile(dataFile)
        except ValueError:
            raise exceptions.FileOpenFailedException(dataFile)

    def getSamFilePath(self):
        """
        Returns the file path of the sam file
        """
        return self._samFilePath

    def getReadAlignments(self, referenceId=None, start=None, end=None):
        """
        Returns an iterator over the specified reads
        """
        # TODO If referenceId is None, return against all references,
        # including unmapped reads.
        referenceName = ""
        if referenceId is not None:
            self.sanitizeGetRName(referenceId)
            referenceName = self._samFile.getrname(referenceId)
        referenceName, start, end = self.sanitizeAlignmentFileFetch(
            referenceName, start, end)
        # TODO deal with errors from htslib
        readAlignments = self._samFile.fetch(referenceName, start, end)
        for readAlignment in readAlignments:
            yield self.convertReadAlignment(readAlignment)

    def convertReadAlignment(self, read):
        """
        Convert a pysam ReadAlignment to a GA4GH ReadAlignment
        """
        # TODO fill out remaining fields
        # TODO refine in tandem with code in converters module
        ret = protocol.ReadAlignment()
        ret.alignedQuality = list(read.query_qualities)
        ret.alignedSequence = read.query_sequence
        ret.alignment = protocol.LinearAlignment()
        ret.alignment.mappingQuality = read.mapping_quality
        ret.alignment.position = protocol.Position()
        self.sanitizeGetRName(read.reference_id)
        ret.alignment.position.referenceName = self._samFile.getrname(
            read.reference_id)
        ret.alignment.position.position = read.reference_start
        ret.alignment.position.strand = \
            protocol.Strand.POS_STRAND  # TODO fix this!
        ret.alignment.cigar = []
        for operation, length in read.cigar:
            gaCigarUnit = protocol.CigarUnit()
            gaCigarUnit.operation = SamCigar.int2ga(operation)
            gaCigarUnit.operationLength = length
            gaCigarUnit.referenceSequence = None  # TODO fix this!
            ret.alignment.cigar.append(gaCigarUnit)
        ret.duplicateFragment = SamFlags.isFlagSet(
            read.flag, SamFlags.DUPLICATE_FRAGMENT)
        ret.failedVendorQualityChecks = SamFlags.isFlagSet(
            read.flag, SamFlags.FAILED_VENDOR_QUALITY_CHECKS)
        ret.fragmentLength = read.template_length
        ret.fragmentName = read.query_name
        ret.id = "{}:{}".format(self._id, read.query_name)
        ret.info = {key: [str(value)] for key, value in read.tags}
        ret.nextMatePosition = None
        if read.next_reference_id != -1:
            ret.nextMatePosition = protocol.Position()
            self.sanitizeGetRName(read.next_reference_id)
            ret.nextMatePosition.referenceName = self._samFile.getrname(
                read.next_reference_id)
            ret.nextMatePosition.position = read.next_reference_start
            ret.nextMatePosition.strand = \
                protocol.Strand.POS_STRAND  # TODO fix this!
        # TODO Is this the correct mapping between numberReads and
        # sam flag 0x1? What about the mapping between numberReads
        # and 0x40 and 0x80?
        ret.numberReads = None
        ret.readNumber = None
        if SamFlags.isFlagSet(read.flag, SamFlags.NUMBER_READS):
            ret.numberReads = 2
            if SamFlags.isFlagSet(read.flag, SamFlags.READ_NUMBER_ONE):
                ret.readNumber = 0
            elif SamFlags.isFlagSet(read.flag, SamFlags.READ_NUMBER_TWO):
                ret.readNumber = 1
        ret.properPlacement = SamFlags.isFlagSet(
            read.flag, SamFlags.PROPER_PLACEMENT)
        ret.readGroupId = self._id
        ret.secondaryAlignment = SamFlags.isFlagSet(
            read.flag, SamFlags.SECONDARY_ALIGNMENT)
        ret.supplementaryAlignment = SamFlags.isFlagSet(
            read.flag, SamFlags.SUPPLEMENTARY_ALIGNMENT)
        return ret
