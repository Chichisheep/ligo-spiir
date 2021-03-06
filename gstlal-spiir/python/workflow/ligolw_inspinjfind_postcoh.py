# Copyright (C) 2006--2011,2013,2014,2016  Kipp Cannon
# 2017 Qi Chu adapted from glue ligolw_inspinjfind
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

#
# =============================================================================
#
#                                   Preamble
#
# =============================================================================
#
"""
Inspiral injection identification library.  Contains code providing the
capacity to search a list of sngl_inspiral candidates for events
matching entries in a sim_inspiral list of software injections, recording the
matches as inspiral <--> injection coincidences using the standard coincidence
infrastructure.  Also, any pre-recorded inspiral <--> inspiral coincidences are
checked for cases where all the inspiral events in a coincidence match an
injection, and these are recorded as coinc <--> injection coincidences,
again using the standard coincidence infrastructure.
"""

import bisect
import sys
import pdb

from glue import iterutils
from glue.ligolw import ligolw
from glue.ligolw import lsctables
from glue.text_progress_bar import ProgressBar

from gstlal.pipemodules.postcohtable import postcoh_table_def
from glue.ligolw import ilwd

__author__ = "Kipp Cannon <kipp.cannon@ligo.org>"
#__version__ = "git id %s" % git_version.id
#__date__ = git_version.date

#
# =============================================================================
#
#                               Content Handler
#
# =============================================================================
#


class PostcohInspiral(postcoh_table_def.PostcohInspiral):
    """
	Version of lsctables.SnglInspiral who's .__cmp__() method compares
	this object's .end value directly to the value of other.  Allows a
	list of instances of this class sorted by .end to be bisection
	searched for a LIGOTimeGPS end time.
	"""
    __slots__ = ()

    def __cmp__(self, other):
        return cmp(self.end, other)


@postcoh_table_def.use_in
@lsctables.use_in
class LIGOLWContentHandler(ligolw.LIGOLWContentHandler):
    pass


#
# =============================================================================
#
#                              Document Interface
#
# =============================================================================
#


class DocContents(object):
    """
	A wrapper interface to the XML document.
	"""
    def __init__(self, xmldoc, process, end_time_bisect_window):
        #
        # store the process row
        #

        self.process = process

        #
        # locate the postcoh and sim_inspiral tables
        #

        self.postcohinspiraltable = postcoh_table_def.PostcohInspiralTable.get_table(
            xmldoc)
        self.siminspiraltable = lsctables.SimInspiralTable.get_table(xmldoc)

        #
        # get coinc_map table, create one if needed
        #

        try:
            self.coincmaptable = lsctables.CoincMapTable.get_table(xmldoc)
        except ValueError:
            self.coincmaptable = lsctables.New(lsctables.CoincMapTable)
            xmldoc.childNodes[0].appendChild(self.coincmaptable)

        #
        #

        self.postcohinspiraltable.sort(key=lambda row: row.end)

        #
        # set the window for inspirals_near_endtime().  this window
        # is the amount of time such that if an injection's end
        # time and a inspiral event's end time differ by more than
        # this it is *impossible* for them to match one another.
        #
        self.end_time_bisect_window = lsctables.LIGOTimeGPS(
            end_time_bisect_window)

    def postcoh_inspirals_near_endtime(self, t):
        """
		Return a list of the inspiral events whose end times are
		within self.end_time_bisect_window of t.
		"""
        return self.postcohinspiraltable[
            bisect.bisect_left(self.postcohinspiraltable, t -
                               self.end_time_bisect_window):bisect.
            bisect_right(self.postcohinspiraltable, t +
                         self.end_time_bisect_window)]

    def sort_triggers_by_id(self):
        """
		Sort the sngl_inspiral table's rows by ID (tidy-up document
		for output).
		"""
        self.postcohinspiraltable.sort(key=lambda row: row.event_id)

    def new_coinc(self, coinc_def_id):
        """
		Construct a new coinc_event row attached to the given
		process, and belonging to the set of coincidences defined
		by the given coinc_def_id.
		"""
        coinc = lsctables.Coinc()
        # FIXME: revert when register_to_xml works in bin/ligolw_inspinjfind_postcoh
        #coinc.process_id = self.process.process_id
        ilwd_process_id = ilwd.get_ilwdchar_class("process", "process")
        coinc.process_id = ilwd_process_id(10)
        coinc.coinc_def_id = coinc_def_id
        coinc.coinc_event_id = self.coinctable.get_next_id()
        coinc.time_slide_id = self.tisi_id
        coinc.set_instruments(None)
        coinc.nevents = 0
        coinc.likelihood = None
        self.coinctable.append(coinc)
        return coinc


#
# =============================================================================
#
#                 Build sim_inspiral <--> postcoh Coincidences
#
# =============================================================================
#


def add_sim_postcoh_coinc(contents, sim, event_ids):
    """
	Create a coinc_event in the coinc table, and add arcs in the
	coinc_event_map table linking the sim_inspiral row and the list of
	postcoh rows to the new coinc_event row.
	"""

    ilwd_postcoh_id = ilwd.get_ilwdchar_class("postcoh", "event_id")
    for one_event_id in event_ids:
        coincmap = lsctables.CoincMap()
        coincmap.coinc_event_id = one_event_id
        # FIXME: this does not work due to load xmldoc problem in
        # bin/ligolw_inspinjfind_postcoh, related to the last FIXME
        # coincmap.table_name = sim.simulation_id.table_name
        coincmap.table_name = sim.simulation_id.split(':')[0]
        coincmap.event_id = sim.simulation_id
        contents.coincmaptable.append(coincmap)


#
# =============================================================================
#
#                                 Library API
#
# =============================================================================
#


# FIXME: exact trigger time matches the sim geocent time, need to conside
# 1) should we use a more accurate time than geocent time ?
# 2) any one of the single triggers matches the sim time.
def find_exact_postcoh_matches(contents, t):
    """
	Return a set of the postcoh_id of the inspiral<-->postcoh
	coincs in which all inspiral events match sim.
	"""
    # comparefunc is True --> inspiral does not match sim
    # any(...) --> at least one inspiral does not match sim
    # not any(...) --> all inspirals match sim
    #
    postcohs = contents.postcoh_inspirals_near_endtime(t)

    return set(one_postcoh.event_id for one_postcoh in postcohs)


def injfind(xmldoc,
            process,
            search,
            end_time_bisect_window=1.0,
            verbose=False):
    #
    # Analyze the document's contents.
    #

    if verbose:
        print >> sys.stderr, "indexing ..."

    contents = DocContents(xmldoc=xmldoc,
                           process=process,
                           end_time_bisect_window=end_time_bisect_window)
    #
    # Find sim_inspiral <--> coinc_event coincidences.
    #

    progressbar = ProgressBar(max=len(contents.siminspiraltable),
                              textwidth=35,
                              text="injfind") if verbose else None

    for sim in contents.siminspiraltable:
        if progressbar is not None:
            progressbar.increment()
        exact_postcoh_event_ids = find_exact_postcoh_matches(
            contents, sim.time_geocent)
        if exact_postcoh_event_ids:
            add_sim_postcoh_coinc(contents, sim, exact_postcoh_event_ids)
    del progressbar

    #
    # Restore the original event order.
    #

    if verbose:
        print >> sys.stderr, "finishing ..."

    #
    # Done.
    #

    return xmldoc
