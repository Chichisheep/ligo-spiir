#
# Copyright (C) 2010
# Chad Hanna <chad.hanna@ligo.org>
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

try:
	import sqlite3
except ImportError:
        # pre 2.5.x
	from pysqlite2 import dbapi2 as sqlite3

from glue import segments
from glue import segmentsUtils
from glue.ligolw import ligolw
from glue.ligolw import lsctables
from glue.ligolw import utils
from glue.ligolw.utils import process as ligolw_process
from pylal.datatypes import LIGOTimeGPS


#
# open ligolw_xml file containing sim_inspiral and create a segment list
#

def sim_inspiral_to_segment_list(fname, pad=1, verbose=False):

	# initialization

	seglist = segments.segmentlist()
	padtime = LIGOTimeGPS(pad)

	# Parse the XML file

	xmldoc=utils.load_filename(fname, gz=fname.endswith(".gz"), verbose=verbose)

	# extract the padded geocentric end times into segment lists
	
	sim_inspiral_table=lsctables.table.get_table(xmldoc, lsctables.SimInspiralTable.tableName)
	for row in sim_inspiral_table:
		t = row.get_time_geocent()
		seglist.append((t-padtime, t+padtime))

	return seglist


