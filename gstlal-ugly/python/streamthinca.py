# Copyright (C) 2011  Kipp Cannon, Chad Hanna, Drew Keppel
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


from glue import iterutils
from glue import segments
from glue.ligolw import lsctables
from pylal import ligolw_burca2
from pylal import ligolw_thinca
from pylal.date import XLALUTCToGPS
import time


#
# =============================================================================
#
#                              Pipeline Elements
#
# =============================================================================
#


#
# sngl_inspiral<-->sngl_inspiral comparison function
#


def event_comparefunc(event_a, offset_a, event_b, offset_b, light_travel_time, delta_t):
	return (event_a.mass1 != event_b.mass1) or (event_a.mass2 != event_b.mass2) or (event_a.chi != event_b.chi) or (float(abs(event_a.get_end() + offset_a - event_b.get_end() - offset_b)) > light_travel_time + delta_t)


#
# allowed instrument combinations (yes, hard-coded, just take off, eh)
#


allowed_instrument_combos = (frozenset(("H1", "H2", "L1")), frozenset(("H1", "L1", "V1")), frozenset(("H1", "L1")), frozenset(("H1", "V1")), frozenset(("L1", "V1")))


#
# gstlal_inspiral's triggers cause a divide-by-zero error in the effective
# SNR method attached to the triggers, so we replace it with one that works
# for the duration of the ligolw_thinca() call.  this is the function with
# which we replace it
#


def get_effective_snr(self, fac):
	return self.snr


#
# on-the-fly thinca implementation
#


class StreamThinca(object):
	def __init__(self, xmldoc, process_id, coincidence_threshold, thinca_interval = 50.0, coinc_params_distributions = None, likelihood_params_func = None):
		self.xmldoc = xmldoc
		self.process_id = process_id
		self.thinca_interval = thinca_interval
		self.set_likelihood_data(coinc_params_distributions, likelihood_params_func)
		self.last_coincs = None

		# when using the normal coincidence function from
		# ligolw_thinca this is the e-thinca parameter.  when using
		# a \Delta t only coincidence test it's the \Delta t window
		# not including the light travel time
		self.coincidence_threshold = coincidence_threshold

		# we need our own copy of the sngl_inspiral table because
		# we need a place for all the triggers to be held while we
		# run coincidence on them.  we need our own copies of the
		# other tables because sometimes ligolw_thinca wants to
		# modify the attributes of a row object after appending it
		# to a table, which isn't possible if the tables are
		# SQL-based.  also, when making these, we can't use
		# table.new_from_template() because we need to ensure we
		# have a Table subclass, not a DBTable subclass
		self.sngl_inspiral_table = lsctables.New(lsctables.SnglInspiralTable, lsctables.table.get_table(self.xmldoc, lsctables.SnglInspiralTable.tableName).columnnames)
		self.coinc_event_map_table = lsctables.New(lsctables.CoincMapTable)
		self.coinc_event_table = lsctables.New(lsctables.CoincTable)
		self.coinc_inspiral_table = lsctables.New(lsctables.CoincInspiralTable)

		# upper boundary of interval spanned by last invocation
		self.last_boundary = -segments.infinity()

		# stay this far away from the boundaries of the available
		# triggers
		self.coincidence_back_off = max(abs(offset) for offset in lsctables.table.get_table(self.xmldoc, lsctables.TimeSlideTable.tableName).getColumnByName("offset"))

		# set of the event ids of triggers currently in ram that
		# have already been used in coincidences
		self.ids = set()

		# the start time
		self.start_time = time.time()

	def set_likelihood_data(self, coinc_params_distributions, likelihood_params_func):
		if coinc_params_distributions is not None:
			assert likelihood_params_func is not None
			self.likelihood_func = ligolw_burca2.LikelihoodRatio(coinc_params_distributions)
		else:
			assert likelihood_params_func is None
			self.likelihood_func = None
		self.likelihood_params_func = likelihood_params_func


	def add_events(self, events, boundary, FAP = None):
		# invalidate the coinc extractor
		self.last_coincs = None

		# no-op if no new events
		if not events:
			return []

		# convert the new row objects to the type required by
		# ligolw_thinca(), and append to our sngl_inspiral table
		for old_event in events:
			new_event = ligolw_thinca.SnglInspiral()
			for col in self.sngl_inspiral_table.columnnames:
				setattr(new_event, col, getattr(old_event, col))
			self.sngl_inspiral_table.append(new_event)

		# run coincidence, return non-coincident sngls
		return self.run_coincidence(boundary, FAP)


	def run_coincidence(self, boundary, FAP = None):
		# check that we've accumulated thinca_interval seconds
		if  self.last_boundary + self.thinca_interval > boundary - self.coincidence_back_off:
			return []

		# remove triggers that are too old to be useful from our
		# internal sngl_inspiral table.  save any that were never
		# used in coincidences
		discard_boundary = self.last_boundary - self.coincidence_back_off
		noncoinc_sngls = [row for row in self.sngl_inspiral_table if row.get_end() < discard_boundary and row.event_id not in self.ids]
		iterutils.inplace_filter(lambda row: row.get_end() >= discard_boundary, self.sngl_inspiral_table)

		# clear our other internal tables
		del self.coinc_event_map_table[:]
		del self.coinc_event_table[:]
		del self.coinc_inspiral_table[:]

		# replace tables with our versions
		orig_sngl_inspiral_table = lsctables.table.get_table(self.xmldoc, lsctables.SnglInspiralTable.tableName)
		self.xmldoc.childNodes[-1].replaceChild(self.sngl_inspiral_table, orig_sngl_inspiral_table)
		orig_coinc_event_map_table = lsctables.table.get_table(self.xmldoc, lsctables.CoincMapTable.tableName)
		self.xmldoc.childNodes[-1].replaceChild(self.coinc_event_map_table, orig_coinc_event_map_table)
		orig_coinc_event_table = lsctables.table.get_table(self.xmldoc, lsctables.CoincTable.tableName)
		self.xmldoc.childNodes[-1].replaceChild(self.coinc_event_table, orig_coinc_event_table)
		orig_coinc_inspiral_table = lsctables.table.get_table(self.xmldoc, lsctables.CoincInspiralTable.tableName)
		self.xmldoc.childNodes[-1].replaceChild(self.coinc_inspiral_table, orig_coinc_inspiral_table)

		# define once-off ntuple_comparefunc() so we can pass the
		# coincidence segment in as a default value for the seg
		# keyword argument
		def ntuple_comparefunc(events, offset_vector, seg = segments.segment(self.last_boundary, boundary)):
			return frozenset(event.ifo for event in events) not in allowed_instrument_combos or ligolw_thinca.coinc_inspiral_end_time(events, offset_vector) not in seg

		# swap .get_effective_snr() method on trigger class
		orig_get_effective_snr, ligolw_thinca.SnglInspiral.get_effective_snr = ligolw_thinca.SnglInspiral.get_effective_snr, get_effective_snr

		# find coincs
		ligolw_thinca.ligolw_thinca(
			self.xmldoc,
			process_id = self.process_id,
			coinc_definer_row = ligolw_thinca.InspiralCoincDef,
			event_comparefunc = event_comparefunc,
			thresholds = self.coincidence_threshold,
			ntuple_comparefunc = ntuple_comparefunc,
			likelihood_func = self.likelihood_func,
			likelihood_params_func = self.likelihood_params_func
		)

		# restore .get_effective_snr() method on trigger class
		ligolw_thinca.SnglInspiral.get_effective_snr = orig_get_effective_snr

		# Assign FAPs if requested
		if FAP is not None:
			# set the live time
			FAP.livetime = time.time() - self.start_time
			coinc_event_index = dict((row.coinc_event_id, row) for row in self.coinc_event_table)
			ref_time = XLALUTCToGPS(time.gmtime())
			for coinc_inspiral_row in self.coinc_inspiral_table:
				coinc_event_row = coinc_event_index[coinc_inspiral_row.coinc_event_id]
				# Assign the FAP
				coinc_inspiral_row.false_alarm_rate = FAP.fap_from_rank(coinc_event_row.likelihood, coinc_inspiral_row.ifos, coinc_event_row.time_slide_id)
				# increment the trials table
				FAP.trials_table[(coinc_inspiral_row.ifos, coinc_event_row.time_slide_id)] += 1
				# assume each event is "loudest" so n = 1 by default, not the same as required for an IFAR plot
				coinc_inspiral_row.combined_far = FAP.compute_far(coinc_inspiral_row.false_alarm_rate)
				# populate a column with latency
				coinc_inspiral_row.minimum_duration = float(coinc_inspiral_row.get_end() - ref_time)

		# construct a coinc extractor from the XML document while
		# the tree still contains our internal table objects
		self.last_coincs = ligolw_thinca.sngl_inspiral_coincs(self.xmldoc)

		# put the original table objects back
		self.xmldoc.childNodes[-1].replaceChild(orig_sngl_inspiral_table, self.sngl_inspiral_table)
		self.xmldoc.childNodes[-1].replaceChild(orig_coinc_event_map_table, self.coinc_event_map_table)
		self.xmldoc.childNodes[-1].replaceChild(orig_coinc_event_table, self.coinc_event_table)
		self.xmldoc.childNodes[-1].replaceChild(orig_coinc_inspiral_table, self.coinc_inspiral_table)

		# copy triggers into real output document
		self.copy_results_to_output()

		# record boundary
		self.last_boundary = boundary

		# return non-coincident sngls
		return noncoinc_sngls


	def copy_results_to_output(self):
		"""
		Copy rows into real output document.  FOR INTERNAL USE ONLY.
		"""
		if self.coinc_event_map_table:
			# retrieve the target tables
			real_sngl_inspiral_table = lsctables.table.get_table(self.xmldoc, lsctables.SnglInspiralTable.tableName)
			real_coinc_event_map_table = lsctables.table.get_table(self.xmldoc, lsctables.CoincMapTable.tableName)
			real_coinc_event_table = lsctables.table.get_table(self.xmldoc, lsctables.CoincTable.tableName)
			real_coinc_inspiral_table = lsctables.table.get_table(self.xmldoc, lsctables.CoincInspiralTable.tableName)

			# figure out the IDs of triggers that have been
			# used in coincs for the first time, and update the
			# set of IDs of all triggers that have been used in
			# coincs
			index = dict((row.event_id, row) for row in self.sngl_inspiral_table)
			self.ids &= set(index)
			newids = set(self.coinc_event_map_table.getColumnByName("event_id")) - self.ids
			self.ids |= newids

			# copy rows into target tables.
			for id in newids:
				real_sngl_inspiral_table.append(index[id])
			map(real_coinc_event_map_table.append, self.coinc_event_map_table)
			map(real_coinc_event_table.append, self.coinc_event_table)
			map(real_coinc_inspiral_table.append, self.coinc_inspiral_table)


	def flush(self):
		# invalidate the coinc extractor
		self.last_coincs = None

		# coincidence
		noncoinc_sngls = self.run_coincidence(segments.infinity())

		# save all remaining triggers that weren't used in coincs
		noncoinc_sngls.extend(row for row in self.sngl_inspiral_table if row.event_id not in self.ids)

		# return non-coincident sngls
		return noncoinc_sngls
