# Copyright (C) 2010  Leo Singer
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
"""

Plotting tools, mostly for inspiral searches.

"""
__author__       = "Leo Singer <leo.singer@ligo.org>"
__organization__ = ["LIGO", "California Institute of Technology"]
__copyright__    = "Copyright 2010, Leo Singer"


import gstlal.pipeutil # FIXME: needed because we have GStreamer stuff mixed in where it shouldn't be
import pylab

"""Dictionary of strings for useful units."""
units = {
	'msun': r"$M_\odot$",
}


"""Dictionary of strings for useful plot labels.  Keys are generallly named the
same as a matching ligolw column."""
labels = {
	'mtotal': r"total mass, $M$ (%s)" % units['msun'],
	'mchirp': r"chirp mass, $\mathcal{M}$ (%s)" % units['msun'],
	'mass1': r"component mass 1, $M_1$ (%s)" % units['msun'],
	'mass2': r"component mass 2, $M_2$ (%s)" % units['msun'],
	'snr': r"SNR $\rho$",
	'eff_snr': r"effective SNR $\rho_\mathrm{eff}$",
	'combined_snr': r"combined SNR, $\sqrt{\sum\rho^2}$",
	'combined_eff_snr': r"combined effective SNR, $\sqrt{\sum\rho_\mathrm{eff}^2}$",
	'chisq': r"$\chi^2$",
	'tau0': r"chirp time $\tau0$",
	'tau3': r"chirp time $\tau3$",
}


def plotbank(in_filename, out_filename=None, column1='mchirp', column2='mtotal'):
	"""Plot template bank parameters from a file generated by lalapps_tmpltbank."""
	from glue.ligolw import utils, lsctables
	table = lsctables.table.get_table(
		utils.load_filename(in_filename, gz=in_filename.endswith('gz')),
		lsctables.SnglInspiralTable.tableName
	)
	pylab.figure()
	pylab.title('%s: placement of %d templates' % (in_filename, len(table)))
	pylab.plot(table.get_column(column1), table.get_column(column2), ',')
	pylab.xlabel(labels[column1])
	pylab.ylabel(labels[column2])
	pylab.grid()
	if out_filename is None:
		pylab.show()
	else:
		pylab.savefig(out_filename)
	pylab.close()


def plotsvd(in_filename, out_filename=None):
	"""Plot heatmap of orthogonal template components."""
	from gstlal.gstlal_svd_bank import read_bank
	bank = read_bank(in_filename)
	ntemplates = 0
	for bf in bank.bank_fragments:
		next_ntemplates = ntemplates + bf.orthogonal_template_bank.shape[0]
		pylab.imshow(
			pylab.log10(abs(bf.orthogonal_template_bank[::-1,:])),
			extent = (bf.end, bf.start, ntemplates, next_ntemplates),
			hold=True, aspect='auto'
		)
		pylab.text(bf.end + bank.filter_length / 30, ntemplates + 0.5 * bf.orthogonal_template_bank.shape[0], '%d Hz' % bf.rate, size='x-small')
		ntemplates = next_ntemplates

	pylab.xlim(0, 1.15*bank.filter_length)
	pylab.ylim(0, 1.05*ntemplates)
	pylab.colorbar().set_label('$\mathrm{log}_{10} |u_{i}(t)|$')
	pylab.xlabel(r"Time $t$ until coalescence (seconds)")
	pylab.ylabel(r"Basis index $i$")
	pylab.title(r"Orthonormal basis templates $u_{i}(t)$")
	if out_filename is None:
		pylab.show()
	else:
		pylab.savefig(out_filename)
	pylab.close()


def plotskymap(fig, theta, phi, logp, gpstime, arrival_times=None, inj_lon_lat=None):
	"""Draw a skymap as produced by the lal_skymap element.
	arrival_times should be a dictionary with keys being IFO names
	(e.g. 'H1', 'L1', 'V1', ...) and values being double precision GPS arrival
	at each IFO.

	If inj_lon_at is set to a celestial Dec/RA tuple in radians, then the
	injection point of origin will be marked with a cross.

	Currently, lal_skymap generates a grid of 450x900 points, and this code
	relies on that.  It could be generalized to handle any rectangular grid,
	but the pcolormesh method that is used here is really only finally tuned for
	quadrilateral meshes.
	"""


	# Some imports that are only useful for this function

	from math import atan2, acos, asin, degrees, sqrt, pi
	from mpl_toolkits.basemap import Basemap, shiftgrid
	import numpy as np
	from pylal.xlal import constants
	from pylal.xlal import tools
	from pylal.datatypes import LIGOTimeGPS
	from pylal.date import XLALGreenwichMeanSiderealTime
	from glue.iterutils import choices


	# Some useful functions

	def location_for_site(prefix):
		"""Get the Cartesian (WGS84) coordinates of a site, given its prefix
		(h for Hanford, l for Livingston...)."""
		# Dictionary mapping detector site prefixes to nick names
		matching_detectors = [x for x in tools.cached_detector.values() if x.prefix.startswith(prefix)]
		if len(matching_detectors) > 1:
			raise ValueError("Found more than one matching detector: %s" % prefix)
		if len(matching_detectors) == 0:
			raise ValueError("Found no matching detectors: %s" % prefix)
		return matching_detectors[0].location

	def cart2spherical(cart):
		"""Convert a Cartesian vector to spherical polar azimuth (phi) and elevation (theta) in radians."""
		return atan2(cart[1], cart[0]), acos(cart[2] / sqrt(np.dot(cart, cart)))


	def spherical2latlon(spherical):
		"""Converts spherical polar coordinates in radians to latitude, longitude in degrees."""
		return degrees(spherical[0]), 90 - degrees(spherical[1])


	# Get figure axes.
	ax = fig.gca()

	# Initialize map; draw gridlines and map boundary.
	m = Basemap(projection='moll', lon_0=0, lat_0=0, ax=ax)
	m.drawparallels(np.arange(-45,46,45), linewidth=0.5, labels=[1, 0, 0, 0], labelstyle="+/-")
	m.drawmeridians(np.arange(-180,180,90), linewidth=0.5)
	m.drawmapboundary()

	# lal_skymap outputs geographic coordinates; convert to celestial here.
	sidereal_time = np.mod(XLALGreenwichMeanSiderealTime(LIGOTimeGPS(gpstime)) * constants.LAL_180_PI, 360)
	lons_grid = sidereal_time + phi.reshape(450, 900) * constants.LAL_180_PI
	lats_grid = 90 - theta.reshape(450, 900) * constants.LAL_180_PI
	logp_grid = logp.reshape(450, 900)

	# Rotate the coordinate grid; Basemap is too stupid to correctly handle a
	# scalar field that must wrap around the edge of the map.
	# FIXME: Find a mapping library that isn't a toy.
	gridshift = round(sidereal_time / 360) * 360 + 180
	lats_grid, dummy = shiftgrid(gridshift, lats_grid, lons_grid[0,:], start=False)
	logp_grid, dummy = shiftgrid(gridshift, logp_grid, lons_grid[0,:], start=False)
	lons_grid, dummy = shiftgrid(gridshift, lons_grid, lons_grid[0,:], start=False)

	# Transform from longitude/latitude to selected projection.
	x, y = m(lons_grid, lats_grid)

	# Draw log probability distribution
	pc = m.pcolormesh(x, y, logp_grid, vmin=logp[np.isfinite(logp)].min())
	cb = fig.colorbar(pc, shrink=0.5)
	cb.set_label('log relative probability')
	cb.cmap.set_under('1.0', alpha=1.0)
	cb.cmap.set_bad('1.0', alpha=1.0)

	# Draw mode of probability distribution
	maxidx = logp_grid.flatten().argmax()
	m.plot(x.flatten()[maxidx], y.flatten()[maxidx], '*', markerfacecolor='white', markersize=10)

	# Draw time delay loci, if arrival times were provided.
	if arrival_times is not None:
		for sites in choices(arrival_times.keys(), 2):
			site0_location = location_for_site(sites[0])
			site1_location = location_for_site(sites[1])
			site_separation = site0_location - site1_location
			site_distance_seconds = sqrt(np.dot(site_separation, site_separation)) / constants.LAL_C_SI
			lon, lat = spherical2latlon(cart2spherical(site_separation))
			site0_toa = arrival_times[sites[0]]
			site1_toa = arrival_times[sites[1]]
			radius = acos((site1_toa - site0_toa) / site_distance_seconds) * 180 / pi
			# Sigh.  Basemap is too stupid to be able to draw circles that wrap around
			# the dateline.  We'll just grab the points it generated, and plot it as
			# a dense scatter point series.
			poly = m.tissot(lon + sidereal_time, lat, radius, 1000, facecolor='none')
			poly.remove()
			x, y = zip(*poly.xy)
			m.plot(x, y, ',k')

	# Draw injection point, if provided
	if inj_lon_lat is not None:
		inj_x, inj_y = m(degrees(inj_lon_lat[0]), degrees(inj_lon_lat[1]))
		m.plot(inj_x, inj_y, '+k', markersize=20, markeredgewidth=1)

	# Add labels
	ax.set_title('Candidate log probability distribution')
	ax.set_xlabel('RA/dec, J2000.  White star marks the mode of the PDF.\nBlack lines represent time delay solution loci for each pair of detectors.', fontsize=10)
