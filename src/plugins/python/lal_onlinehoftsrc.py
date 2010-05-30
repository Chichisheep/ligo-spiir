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

Online calibrated h(t) source, implementing the S6 specification described on 
<https://www.lsc-group.phys.uwm.edu/daswg/wiki/S6OnlineGroup/CalibratedData>.

The environment variable ONLINEHOFT must be set and must point to the online
frames directory, which has subfolders for H1, H2, L1, V1, ... .

Online frames are 16 seconds in duration, and start on 16 second boundaries.
They contain up to three channels:
 - IFO:DMT-STRAIN (16384 Hz), online calibrated h(t)
 - IFO:DMT-STATE_VECTOR (16 Hz), state vector
 - IFO:DMT-DATA_QUALITY_VECTOR (1 Hz), data quality flags

This element features user-programmable data vetos at 1 second resolution.
Gaps (GStreamer buffers marked as containing neutral data) will be created
whenever the state vector mask and data quality mask flag properties are
not met.

Gaps will also be created whenever an anticipated frame file is missing.

"""
__author__ = "Leo Singer <leo.singer@ligo.org>"
__version__ = "FIXME"
__date__ = "FIXME"
__all__ = ("lal_onlinehoftsrc", "directory_poller")


import errno
import os
import os.path
import sys
import time
import bisect
from _onlinehoftsrc import *
try:
	from collections import namedtuple
except:
	# Pre-Python 2.6 compatibility.
	from gstlal.namedtuple import namedtuple
from gstlal.pipeutil import *
from gst.extend.pygobject import gproperty, with_construct_properties


def gps_now():
	import pylal.xlal.date
	return int(pylal.xlal.date.XLALUTCToGPS(time.gmtime()))


def safe_getvect(filename, channel, start, duration, fs):
	"""Ultra-paranoid frame reading function."""
	from pylal.Fr import frgetvect1d
	vect_data, vect_start, vect_x0, vect_df, vect_unit_x, vect_unit_y = frgetvect1d(filename, channel, start, duration)
	if vect_start != start:
		raise ValueError, "channel %s: expected start time %d, but got %f" % (channel, start, vec_start)
	if vect_x0 != 0:
		raise ValueError, "channel %s: expected offset 0, but got %f" % (channel, vect_x0)
	if vect_df != 1.0 / fs:
		raise ValueError, "channel %s: expected sample rate %d, but got %f" % (channel, fs, 1.0 / vect_df)
	if len(vect_data) != duration * fs:
		raise ValueError, "channel %s: expected %d samples, but got %d" % (channel, duration * fs, len(vect_data))
	return vect_data


class dir_cache(object):
	def __init__(self, path, expires):
		self.path = path
		self.expires = expires
		self.mtime = 0
		self.refresh()
	def refresh(self):
		old_mtime = self.mtime
		self.mtime = os.stat(self.path)[8]
		if self.path is None or self.mtime != old_mtime:
			self.items = self.decorate(os.listdir(self.path))


class dir_cache_top(dir_cache):
	def __init__(self, top, nameprefix):
		self.nameprefix = nameprefix
		super(dir_cache_top, self).__init__(top, 0)
	def decorate(self, filenames):
		items = []
		for filename in filenames:
			if filename != 'latest':
				if filename.startswith(self.nameprefix):
					try:
						item = int(filename[len(self.nameprefix):])
					except:
						print >>sys.stderr, "lal_onlinehoftsrc: %s: invalid epoch name" % filename
					else:
						items.append(item)
				else:
					print >>sys.stderr, "lal_onlinehoftsrc: %s: invalid epoch name" % filename
		return sorted(items)


class dir_cache_epoch(dir_cache):
	def __init__(self, top, nameprefix, namesuffix, epoch):
		self.nameprefix = nameprefix
		self.namesuffix = namesuffix
		path = os.path.join(top, "%s%u" % (nameprefix, epoch))
		super(dir_cache_epoch, self).__init__(path, epoch * 100000)
	def decorate(self, filenames):
		items = []
		for filename in filenames:
			if filename.startswith(self.nameprefix) and filename.endswith(self.namesuffix):
				try:
					item = int(filename[len(self.nameprefix):-len(self.namesuffix)])
				except:
					print >>sys.stderr, "lal_onlinehoftsrc: %s: invalid file name" % filename
				else:
					items.append(item)
			else:
				print >>sys.stderr, "lal_onlinehoftsrc: %s: invalid file name" % filename
		return sorted(items)


class directory_poller(object):
	"""Iterate over file descriptors from a directory tree of GPS-timestamped
	files, like the $ONLINEHOFT or $ONLINEDQ directories on LSC clusters.
	"""

	def __init__(self, top, nameprefix, namesuffix):
		self.top = top
		self.nameprefix = nameprefix
		self.namesuffix = namesuffix
		self.__time = 0
		self.stride = 16
		self.latency = 60
		self.timeout = 1
		self.top_cache = None
		self.epoch_caches = {}


	def get_time(self):
		return self.__time
	def set_time(self, time):
		for key in self.epoch_caches.keys():
			if self.epoch_caches[key].expires < time:
				del self.epoch_caches[key]
		self.__time = time
	time = property(get_time, set_time)


	def __iter__(self):
		return self


	def next(self):
		fd = None
		while fd is None:
			epoch = self.time / 100000
			epoch_path = os.path.join(self.top, "%s%u" % (self.nameprefix, epoch))
			filename = "%s%d%s" % (self.nameprefix, self.time, self.namesuffix)
			filepath = os.path.join(epoch_path, filename)

			try:
				# Attempt to open the file.
				fd = os.open(filepath, os.O_RDONLY)
			except OSError as (err, strerror):
				# Opening the file failed.
				if err == errno.ENOENT:
					# Opening the file failed because it did not exist.
					if gps_now() - self.time < self.latency:
						# The requested time is too recent, so just wait
						# a bit and then try again.
						print >>sys.stderr, "lal_onlinehoftsrc: sleeping because requested time is too new"
						time.sleep(self.timeout)
						continue
					else:
						# The requested time is old enough that it is possible that
						# there is a missing file.  Look through the directory tree
						# to find the next available file.

						print >>sys.stderr, "lal_onlinehoftsrc: %s: late or missing file suspected" % filepath
						if self.top_cache is None:
							self.top_cache = dir_cache_top(self.top, self.nameprefix)
							
							try:
								cache = dir_cache_top(self.top, self.nameprefix)
							except OSError as (err, strerror):
								print >>sys.stderr, "lal_onlinehoftsrc: %s: %s" % (self.top, strerror)
								time.sleep(self.timeout)
								continue
							else:
								self.top_cache = cache
						else:
							self.top_cache.refresh()

						new_file_found = False
						for other_epoch in self.top_cache.items[bisect.bisect_left(self.top_cache.items, epoch):]:
							if other_epoch not in self.epoch_caches.keys():
								try:
									cache = dir_cache_epoch(self.top, self.nameprefix, self.namesuffix, other_epoch)
								except OSError:
									continue
								else:
									self.epoch_caches[other_epoch] = cache
							else:
								cache = self.epoch_caches[other_epoch]
							idx = bisect.bisect_left(cache.items, self.time)
							if idx >= len(cache.items):
								continue
							else:
								if self.time != cache.items[idx]:
									print >>sys.stderr, "lal_onlinehoftsrc: files skipped" 
									self.time = cache.items[idx]
								new_file_found = True
								break

						if not new_file_found:
							time.sleep(self.timeout)
						continue
				else:
					# Opening file failed for some reason *other* than that it did
					# not exist, so we assume that we will never be able to open it.
					# Print an error message and try the next file.
					self.time += self.stride
					print >>sys.stderr, "lal_onlinehoftsrc: %s: %s" % (filepath, strerror)
					continue
			else:
				# Opening the file succeeded, so return the new file descriptor.
				self.time += self.stride
		return ((self.time - self.stride), fd)


ifodesc = namedtuple("ifodesc", "ifo nameprefix namesuffix channelname state_channelname dq_channelname")

ifodescs = {
	"H1": ifodesc("H1", "H-H1_DMT_C00_L2-", "-16.gwf", "H1:DMT-STRAIN", "H1:DMT-STATE_VECTOR", "H1:DMT-DATA_QUALITY_VECTOR"),
	"H2": ifodesc("H2", "H-H2_DMT_C00_L2-", "-16.gwf", "H2:DMT-STRAIN", "H2:DMT-STATE_VECTOR", "H2:DMT-DATA_QUALITY_VECTOR"),
	"H3": ifodesc("L1", "L-L1_DMT_C00_L2-", "-16.gwf", "L1:DMT-STRAIN", "L1:DMT-STATE_VECTOR", "L1:DMT-DATA_QUALITY_VECTOR")
}


class lal_onlinehoftsrc(gst.BaseSrc):

	__gstdetails__ = (
		"Online h(t) Source",
		"Source",
		__doc__,
		__author__
	)
	gproperty(
		gobject.TYPE_STRING,
		"instrument",
		'Instrument name (e.g., "H1")',
		None,
		construct=True
	)
	gproperty(
		StateFlags,
		"state-require",
		"State vector flags that must be TRUE",
		STATE_SCI | STATE_CON | STATE_UP | STATE_EXC,
		construct=True
	)
	gproperty(
		StateFlags,
		"state-deny",
		"State vector flags that must be FALSE",
		0,
		construct=True
	)
	gproperty(
		DQFlags,
		"data-quality-require",
		"Data quality flags that must be TRUE",
		DQ_SCIENCE | DQ_UP | DQ_CALIBRATED | DQ_LIGHT,
		construct=True
	)
	gproperty(
		DQFlags,
		"data-quality-deny",
		"Data quality flags that must be FALSE",
		DQ_BADGAMMA,
		construct=True
	)
	__gsttemplates__ = (
		gst.PadTemplate("src",
			gst.PAD_SRC, gst.PAD_ALWAYS,
			gst.caps_from_string("""
				audio/x-raw-float,
				channels = (int) 1,
				endianness = (int) BYTE_ORDER,
				width = (int) 64,
				rate = (int) 16384
			""")
		),
	)


	@with_construct_properties
	def __init__(self):
		super(lal_onlinehoftsrc, self).__init__()
		self.set_property('blocksize', 16384 * 16 * 8)
		self.set_do_timestamp(False)
		self.set_format(gst.FORMAT_TIME)
		self.src_pads().next().use_fixed_caps()


	def do_start(self):
		"""GstBaseSrc->start virtual method"""
		self.__needs_seek = False
		instrument = self.get_property('instrument')
		if instrument not in ifodescs:
			self.error("unknown instrument: %s" % instrument)
			return False
		self.__ifodesc = ifodescs[instrument]
		self.__poller = directory_poller(
			os.path.join(os.getenv('ONLINEHOFT'), instrument),
			self.__ifodesc.nameprefix, self.__ifodesc.namesuffix
		)
		self.__last_successful_gps_end = None
		return True


	def do_stop(self):
		"""GstBaseSrc->stop virtual method"""
		self.__ifodesc = None
		self.__poller = None
		return True


	def do_check_get_range(self):
		"""GstBaseSrc->check_get_range virtual method"""
		return True


	def do_is_seekable(self):
		"""GstBaseSrc->is_seekable virtual method"""
		return True


	def do_do_seek(self, segment):
		"""GstBaseSrc->do_seek virtual method"""
		if segment.flags & gst.SEEK_FLAG_KEY_UNIT:
			# If necessary, extend the segment to the nearest "key frame",
			# playback can only start or stop on boundaries of 16 seconds.
			print segment.start, segment.stop
			if segment.start == -1:
				start = -1
				start_seek_type = gst.SEEK_TYPE_NONE
			else:
				start = gst.util_uint64_scale(gst.util_uint64_scale(segment.start, 1, 16 * gst.SECOND), 16 * gst.SECOND, 1)
				start_seek_type = gst.SEEK_TYPE_SET
			if segment.stop == -1:
				stop = -1
				stop_seek_type = gst.SEEK_TYPE_NONE
			else:
				stop = gst.util_uint64_scale_ceil(gst.util_uint64_scale_ceil(segment.stop, 1, 16 * gst.SECOND), 16 * gst.SECOND, 1)
				stop_seek_type = gst.SEEK_TYPE_SET
			print start, stop
			segment.set_seek(segment.rate, segment.format, segment.flags, start_seek_type, start, stop_seek_type, stop)
		self.__seek_time = (segment.start / gst.SECOND / 16) * 16
		self.__needs_seek = True
		return True


	def do_create(self, offset, size):
		"""GstBaseSrc->create virtual method"""

		# Seek if needed.
		if self.__needs_seek:
			self.__poller.time = self.__seek_time
			self.__needs_seek = False
			self.__last_successful_gps_end = None

		# Loop over available buffers until we reach one that is not corrupted.
		for (gps_start, fd) in self.__poller:
			try:
				filename = "/dev/fd/%d" % fd
				hoft_array = safe_getvect(filename, self.__ifodesc.channelname, gps_start, 16, 16384)
				os.lseek(fd, 0, os.SEEK_SET)
				state_array = safe_getvect(filename, self.__ifodesc.state_channelname, gps_start, 16, 16)
				os.lseek(fd, 0, os.SEEK_SET)
				dq_array = safe_getvect(filename, self.__ifodesc.dq_channelname, gps_start, 16, 1)
			except Exception as e:
				self.warning(str(e))
			else:
				break
			finally:
				os.close(fd)

		# Look up our src pad and its caps.
		pad = self.src_pads().next()
		caps = pad.get_property('caps')

		# Compute "good data" segment mask.
		dq_require = int(self.get_property('data-quality-require'))
		dq_deny = int(self.get_property('data-quality-deny'))
		state_require = int(self.get_property('state-require'))
		state_deny = int(self.get_property('state-deny'))
		state_array = state_array.astype(int).reshape((16, 16))
		segment_mask = (
			(state_array & state_require == state_require).all(1) &
			(~state_array & state_deny == state_deny).all(1) &
			(dq_array & dq_require == dq_require) & 
			(~dq_array & dq_deny == dq_deny)
		)
		self.info('good data mask is ' + ''.join([str(x) for x in segment_mask.astype('int')]))

		# If necessary, create gap for skipped frames.
		if self.__last_successful_gps_end is not None and self.__last_successful_gps_end != gps_start:
			offset = 16384 * self.__last_successful_gps_end
			print gps_start, self.__last_successful_gps_end, (gps_start - self.__last_successful_gps_end)
			size = 16384 * (gps_start - self.__last_successful_gps_end) * 8
			(retval, buf) = pad.alloc_buffer(offset, size, caps)
			if retval != gst.FLOW_OK:
				return (retval, None)
			buf.offset = offset
			buf.offset_end = 16384 * gps_start
			buf.duration = gst.SECOND * (gps_start - self.__last_successful_gps_end)
			buf.timestamp = gst.SECOND * self.__last_successful_gps_end
			buf.flag_set(gst.BUFFER_FLAG_GAP)
			self.warning("pushing buffer spanning [%u, %u) (nongap=1, SKIPPED frames)"
				% (self.__last_successful_gps_end, gps_start))
			result = pad.push(buf)
			if result != gst.FLOW_OK:
				return (retval, None)
		self.__last_successful_gps_end = gps_start + 16
			
		# Loop over 1-second chunks in current buffer, and push extra buffers
		# as needed when a transition betwen gap and nongap has to occur.
		was_nongap = segment_mask[0]
		last_segment_num = 0
		for segment_num, is_nongap in enumerate(segment_mask):
			if is_nongap ^ was_nongap:
				offset = 16384 * (gps_start + last_segment_num)
				size = 16384 * (segment_num - last_segment_num) * 8
				(retval, buf) = pad.alloc_buffer(offset, size, caps)
				if retval != gst.FLOW_OK:
					return (retval, None)
				buf[0:size] = hoft_array[(16384*last_segment_num):(16384*segment_num)].data
				buf.offset = offset
				buf.offset_end = 16384 * (gps_start + segment_num)
				buf.duration = gst.SECOND * (segment_num - last_segment_num)
				buf.timestamp = gst.SECOND * (gps_start + last_segment_num)
				if not was_nongap:
					buf.flag_set(gst.BUFFER_FLAG_GAP)
				self.info("pushing buffer spanning [%u, %u) (nongap=%d, extra frame)"
					% (gps_start + last_segment_num, gps_start + segment_num, was_nongap))
				result = pad.push(buf)
				if result != gst.FLOW_OK:
					return (retval, None)
				last_segment_num = segment_num
			was_nongap = is_nongap

		# Finish off current frame.
		segment_num = 16
		offset = 16384 * (gps_start + last_segment_num)
		size = 16384 * (segment_num - last_segment_num) * 8
		(retval, buf) = pad.alloc_buffer(offset, size, caps)
		if retval != gst.FLOW_OK:
			return (retval, None)
		buf[0:size] = hoft_array[(16384*last_segment_num):(16384*segment_num)].data
		buf.offset = offset
		buf.offset_end = 16384 * (gps_start + segment_num)
		buf.duration = gst.SECOND * (segment_num - last_segment_num)
		buf.timestamp = gst.SECOND * (gps_start + last_segment_num)
		if not was_nongap:
			buf.flag_set(gst.BUFFER_FLAG_GAP)
		self.info("pushing buffer spanning [%u, %u) (nongap=%d)"
			% (gps_start + last_segment_num, gps_start + segment_num, was_nongap))

		# Don't need to push this buffer, just return it.
		return (gst.FLOW_OK, buf)


# Register element class
gstlal_element_register(lal_onlinehoftsrc)


if __name__ == '__main__':
	# Pipeline to demonstrate a veto kicking in.
	# Conlog says:
	#
	# H1-1792  19771 s    959175240- 959195011   2010 05/29 13:33:45 - 05/29 19:03:16 utc
	# H1-1793  13342 s    959196562- 959209904   2010 05/29 19:29:07 - 05/29 23:11:29 utc
	#
	# so after a few frames you'll see gaps start appearing, then about a hundred
	# frames later you'll see data again.
	#
	pipeline = gst.Pipeline("lal_onlinehoftsrc_example")
	elems = mkelems_in_bin(pipeline,
		("lal_onlinehoftsrc", {"instrument":"H1"}),
		("progressreport",),
		("fakesink",)
	)
	print elems[0].set_state(gst.STATE_READY)
	if not elems[0].seek(1.0, gst.FORMAT_TIME, gst.SEEK_FLAG_KEY_UNIT,
		gst.SEEK_TYPE_SET, (959195011 - 16*3)*gst.SECOND, gst.SEEK_TYPE_NONE, -1):
		raise RuntimeError, "Seek failed"
	print pipeline.set_state(gst.STATE_PLAYING)
	mainloop = gobject.MainLoop()
	mainloop.run()
