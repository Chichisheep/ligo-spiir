
# Copyright (C) 2009--2013  Kipp Cannon, Chad Hanna, Drew Keppel
# Copyright (C) 2013, 2014  Qi Chu
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
#
# =============================================================================
#
#                                   Preamble
#
# =============================================================================
#


import math
import sys
import numpy as np
import warnings
import StringIO
from gstlal.pipeio import repack_complex_array_to_real 


# The following snippet is taken from http://gstreamer.freedesktop.org/wiki/FAQ#Mypygstprogramismysteriouslycoredumping.2Chowtofixthis.3F
import pygtk
pygtk.require("2.0")
import gobject
gobject.threads_init()
import pygst
pygst.require('0.10')
import gst


from glue import iterutils
from glue import segments
from glue.ligolw import ligolw
from glue.ligolw import lsctables
from glue.ligolw import utils as ligolw_utils
from glue.ligolw.utils import segments as ligolw_segments
from glue.ligolw.utils import process as ligolw_process
from gstlal import bottle
from gstlal import datasource
from gstlal import multirate_datasource
from gstlal import pipeio
from gstlal import pipeparts
from gstlal import simplehandler
from gstlal import simulation
from pylal.datatypes import LIGOTimeGPS

from gstlal import uni_datasource
import pdb
from gstlal import cbc_template_iir

#
# SPIIR many instruments, many template banks
#

def mkitac_spearman(pipeline, src, n, bank, autocorrelation_matrix = None, mask_matrix = None, snr_thresh = 0, sigmasq = None):
	properties = {
		"n": n,
		"bank_filename": bank,
		"snr_thresh": snr_thresh
	}
	if autocorrelation_matrix is not None:
		properties["autocorrelation_matrix"] = pipeio.repack_complex_array_to_real(autocorrelation_matrix)
	if mask_matrix is not None:
		properties["autocorrelation_mask"] = mask_matrix
	if sigmasq is not None:
		properties["sigmasq"] = sigmasq
	return pipeparts.mkgeneric(pipeline, src, "lal_itac_spearman", **properties)

def mkcudapostcoh(pipeline, snr, instrument, detrsp_fname, autocorrelation_fname, hist_trials = 1, snglsnr_thresh = 4.0, output_skymap = 0, trial_interval = 0.1, stream_id = 0):

	properties = dict((name, value) for name, value in zip(("detrsp-fname", "autocorrelation-fname", "hist-trials", "snglsnr-thresh", "output-skymap", "trial-interval", "stream_id"), (detrsp_fname, autocorrelation_fname, hist_trials, snglsnr_thresh, output_skymap, trial_interval, stream_id)))
	if "name" in properties:
		elem = gst.element_factory_make("cuda_postcoh", properties.pop("name"))
	else:
		elem = gst.element_factory_make("cuda_postcoh")
	# make sure stream_id go first
	for name, value in properties.items():
		if name == "stream_id":
			elem.set_property(name.replace("_", "-"), value)
	for name, value in properties.items():
		if name != "stream_id":
			elem.set_property(name.replace("_", "-"), value)

	pipeline.add(elem)
	snr.link_pads(None, elem, instrument)
	return elem


def mkcohfar_accumbackground(pipeline, src, ifos= "H1L1", update_interval =  0, history_fname = None,output_fname = None):
	properties = {
		"ifos": ifos,
		"update_interval": update_interval
	}
	if history_fname is not None:
		properties["history_fname"] = history_fname
	if output_fname is not None:
		properties["output_fname"] = output_fname

	if "name" in properties:
		elem = gst.element_factory_make("cohfar_accumbackground", properties.pop("name"))
	else:
		elem = gst.element_factory_make("cohfar_accumbackground")
	# make sure ifos go first
	for name, value in properties.items():
		if name == "ifos":
			elem.set_property(name.replace("_", "-"), value)
	for name, value in properties.items():
		if name != "ifos":
			elem.set_property(name.replace("_", "-"), value)

	pipeline.add(elem)
	if isinstance(src, gst.Pad):
		src.get_parent_element().link_pads(src, elem, None)
	elif src is not None:
		src.link(elem)
	return elem

def mkSPIIRmulti(pipeline, detectors, banks, psd, psd_fft_length = 8, ht_gate_threshold = None, veto_segments = None, verbose = False, nxydump_segment = None, chisq_type = 'autochisq', track_psd = False, block_duration = gst.SECOND, blind_injections = None, peak_thresh = 4):
	#
	# check for recognized value of chisq_type
	#

	if chisq_type not in ['autochisq' or 'autochisq_spearman']:
		raise ValueError("chisq_type must be either 'autochisq' or 'autochisq_spearman', given %s" % chisq_type)

	#
	# extract segments from the injection file for selected reconstruction
	#

	if detectors.injection_filename is not None:
		inj_seg_list = simulation.sim_inspiral_to_segment_list(detectors.injection_filename)
	else:
		inj_seg_list = None
		#
		# Check to see if we are specifying blind injections now that we know
		# we don't want real injections. Setting this
		# detectors.injection_filename will ensure that injections are added
		# but won't only reconstruct injection segments.
		#
		detectors.injection_filename = blind_injections

	#
	# construct dictionaries of whitened, conditioned, down-sampled
	# h(t) streams
	#

	hoftdicts = {}
	for instrument in detectors.channel_dict:
		rates = set(rate for bank in banks[instrument] for rate in bank.get_rates()) # FIXME what happens if the rates are not the same?
		src = datasource.mkbasicsrc(pipeline, detectors, instrument, verbose)
		if veto_segments is not None:
			hoftdicts[instrument] = multirate_datasource.mkwhitened_multirate_src(pipeline, src, rates, instrument, psd = psd[instrument], psd_fft_length = psd_fft_length, ht_gate_threshold = ht_gate_threshold, veto_segments = veto_segments[instrument], seekevent = detectors.seekevent, nxydump_segment = nxydump_segment, track_psd = track_psd, zero_pad = 0, width = 32)
		else:
			hoftdicts[instrument] = multirate_datasource.mkwhitened_multirate_src(pipeline, src, rates, instrument, psd = psd[instrument], psd_fft_length = psd_fft_length, ht_gate_threshold = ht_gate_threshold, veto_segments = None, seekevent = detectors.seekevent, nxydump_segment = nxydump_segment, track_psd = track_psd, zero_pad = 0, width = 32)

	#
	# construct trigger generators
	#
	# format of banklist : {'H1': <H1Bank0>, <H1Bank1>..;
	#			'L1': <L1Bank0>, <L1Bank1>..;..}
	# format of bank: <H1bank0>


	triggersrcs = dict((instrument, set()) for instrument in hoftdicts)

	for instrument, bank in [(instrument, bank) for instrument, banklist in banks.items() for bank in banklist]:
		suffix = "%s%s" % (instrument, (bank.logname and "_%s" % bank.logname or ""))
		snr = mkSPIIRhoftToSnrSlices(
			pipeline,
			hoftdicts[instrument],
			bank,
			instrument,
			verbose = verbose,
			nxydump_segment = nxydump_segment,
			quality = 1
		)
		snr = pipeparts.mkchecktimestamps(pipeline, snr, "timestamps_%s_snr" % suffix)

		snr = pipeparts.mktogglecomplex(pipeline, snr)
		snr = pipeparts.mktee(pipeline, snr)
		# FIXME you get a different trigger generator depending on the chisq calculation :/
		if chisq_type == 'autochisq':
			# FIXME don't hardcode
			# peak finding window (n) in samples is one second at max rate, ie max(rates)
			# FIXME: bank.snr_thresh is removed, use peak_thresh instead
			head = pipeparts.mkitac(pipeline, snr, max(rates), bank.template_bank_filename, autocorrelation_matrix = bank.autocorrelation_bank, mask_matrix = bank.autocorrelation_mask, snr_thresh = peak_thresh, sigmasq = bank.sigmasq)
			if verbose:
				head = pipeparts.mkprogressreport(pipeline, head, "progress_xml_%s" % suffix)
			triggersrcs[instrument].add(head)
		elif chisq_type == 'autochisq_spearman':
			# FIXME don't hardcode
			# peak finding window (n) in samples is one second at max rate, ie max(rates)
			# FIXME: bank.snr_thresh is removed, use peak_thresh instead
			head = mkitac_spearman(pipeline, snr, max(rates), bank.template_bank_filename, autocorrelation_matrix = bank.autocorrelation_bank, mask_matrix = bank.autocorrelation_mask, snr_thresh = peak_thresh, sigmasq = bank.sigmasq)
			if verbose:
				head = pipeparts.mkprogressreport(pipeline, head, "progress_xml_%s" % suffix)
			triggersrcs[instrument].add(head)

		# FIXME:  find a way to use less memory without this hack
		del bank.autocorrelation_bank
		if nxydump_segment is not None:
			pipeparts.mknxydumpsink(pipeline, pipeparts.mktogglecomplex(pipeline, pipeparts.mkqueue(pipeline, snr)), "snr_cpu_%d_%s.dump" % (nxydump_segment[0], suffix), segment = nxydump_segment)
		#pipeparts.mkogmvideosink(pipeline, pipeparts.mkcapsfilter(pipeline, pipeparts.mkchannelgram(pipeline, pipeparts.mkqueue(pipeline, snr), plot_width = .125), "video/x-raw-rgb, width=640, height=480, framerate=64/1"), "snr_channelgram_%s.ogv" % suffix, audiosrc = pipeparts.mkaudioamplify(pipeline, pipeparts.mkqueue(pipeline, hoftdict[max(bank.get_rates())], max_size_time = 2 * int(math.ceil(bank.filter_length)) * gst.SECOND), 0.125), verbose = True)

	#
	# done
	#

	assert any(triggersrcs.values())
	return triggersrcs


def mkSPIIRhoftToSnrSlices(pipeline, src, bank, instrument, verbose = None, nxydump_segment = None, quality = 4, sample_rates = None, max_rate = None):
	if sample_rates is None:
		sample_rates = sorted(bank.get_rates())
	else:
		sample_rates = sorted(sample_rates)
	#FIXME don't upsample everything to a common rate
	if max_rate is None:
		max_rate = max(sample_rates)
	prehead = None

	for sr in sample_rates:
		head = pipeparts.mkqueue(pipeline, src[sr], max_size_time=gst.SECOND * 10, max_size_buffers=0, max_size_bytes=0)
		head = pipeparts.mkreblock(pipeline, head)
		head = pipeparts.mkiirbank(pipeline, head, a1 = bank.A[sr], b0 = bank.B[sr], delay = bank.D[sr], name = "gstlaliirbank_%d_%s_%s" % (sr, instrument, bank.logname))

		head = pipeparts.mkqueue(pipeline, head, max_size_time=gst.SECOND * 10, max_size_buffers=0, max_size_bytes=0)
		if prehead is not None:
			adder = gst.element_factory_make("lal_adder")
			adder.set_property("sync", True)
			pipeline.add(adder)
			head.link(adder)
			prehead.link(adder)
			head = adder
		#	head = pipeparts.mkadder(pipeline, (head, prehead))
		# FIXME:  this should get a nofakedisconts after it until the resampler is patched
		head = pipeparts.mkresample(pipeline, head, quality = 1)
		if sr == max_rate:
			head = pipeparts.mkcapsfilter(pipeline, head, "audio/x-raw-float, rate=%d" % max_rate)
		else:
			head = pipeparts.mkcapsfilter(pipeline, head, "audio/x-raw-float, rate=%d" % (2 * sr))
		prehead = head

	return head

def mkBuildBossSPIIR(pipeline, detectors, banks, psd, psd_fft_length = 8, ht_gate_threshold = None, veto_segments = None, verbose = False, nxydump_segment = None, chisq_type = 'autochisq', track_psd = False, block_duration = gst.SECOND, blind_injections = None, peak_thresh = 4):
	#
	# check for recognized value of chisq_type
	#

	if chisq_type not in ['autochisq', 'autochisq_spearman']:
		raise ValueError("chisq_type must be either 'autochisq' or 'autochisq_spearman', given %s" % chisq_type)

	#
	# extract segments from the injection file for selected reconstruction
	#

	if detectors.injection_filename is not None:
		inj_seg_list = simulation.sim_inspiral_to_segment_list(detectors.injection_filename)
	else:
		inj_seg_list = None
		#
		# Check to see if we are specifying blind injections now that we know
		# we don't want real injections. Setting this
		# detectors.injection_filename will ensure that injections are added
		# but won't only reconstruct injection segments.
		#
		detectors.injection_filename = blind_injections

	#
	# construct dictionaries of whitened, conditioned, down-sampled
	# h(t) streams
	#

	hoftdicts = {}
	max_instru_rates = {} 
	sngl_max_rate = 0
	for instrument in detectors.channel_dict:
		for bank_name in banks[instrument]:
			sngl_max_rate = max(cbc_template_iir.get_maxrate_from_xml(bank_name), sngl_max_rate)
		max_instru_rates[instrument] = sngl_max_rate
		src = datasource.mkbasicsrc(pipeline, detectors, instrument, verbose)
		if veto_segments is not None:		
			hoftdicts[instrument] = uni_datasource.mkwhitened_src(pipeline, src, sngl_max_rate, instrument, psd = psd[instrument], psd_fft_length = psd_fft_length, ht_gate_threshold = ht_gate_threshold, veto_segments = veto_segments[instrument], seekevent = detectors.seekevent, nxydump_segment = nxydump_segment, track_psd = track_psd, zero_pad = 0, width = 32)
		else:
			hoftdicts[instrument] = uni_datasource.mkwhitened_src(pipeline, src, sngl_max_rate, instrument, psd = psd[instrument], psd_fft_length = psd_fft_length, ht_gate_threshold = ht_gate_threshold, veto_segments = None, seekevent = detectors.seekevent, nxydump_segment = nxydump_segment, track_psd = track_psd, zero_pad = 0, width = 32)

	#
	# construct trigger generators
	#

	triggersrcs = dict((instrument, set()) for instrument in hoftdicts)
	# format of banklist : {'H1': <H1Bank0>, <H1Bank1>..;
	#			'L1': <L1Bank0>, <L1Bank1>..;..}
	# format of bank: <H1bank0>

#	pdb.set_trace()
	bank_count = 0
	for instrument, bank_name in [(instrument, bank_name) for instrument, banklist in banks.items() for bank_name in banklist]:
		suffix = "%s%s" % (instrument,  "_%d" % bank_count)
		head = pipeparts.mkqueue(pipeline, hoftdicts[instrument], max_size_time=gst.SECOND * 10, max_size_buffers=0, max_size_bytes=0)
		max_bank_rate = cbc_template_iir.get_maxrate_from_xml(bank_name)
		if max_bank_rate < max_instru_rates[instrument]:
			head = pipeparts.mkcapsfilter(pipeline, pipeparts.mkresample(pipeline, head, quality = 9), "audio/x-raw-float, rate=%d" % max_bank_rate)
		snr = pipeparts.mkreblock(pipeline, head)

#		bank_struct = build_bank_struct(bank, max_rates[instrument])
		snr = pipeparts.mkcudamultiratespiir(pipeline, snr, bank_name, gap_handle = 0, stream_id = bank_count) # treat gap as zeros

		snr = pipeparts.mktogglecomplex(pipeline, snr)
		snr = pipeparts.mktee(pipeline, snr)
		# FIXME you get a different trigger generator depending on the chisq calculation :/
		bank_struct = cbc_template_iir.Bank()
		bank_struct.read_from_xml(bank_name)
		if chisq_type == 'autochisq':
			# FIXME don't hardcode
			# peak finding window (n) in samples is one second at max rate, ie max(rates)
			head = pipeparts.mkqueue(pipeline, snr, max_size_buffers=1)
			head = pipeparts.mkitac(pipeline, head, max_bank_rate, bank_struct.template_bank_filename, autocorrelation_matrix = bank_struct.autocorrelation_bank, mask_matrix = bank_struct.autocorrelation_mask, snr_thresh = peak_thresh, sigmasq = bank_struct.sigmasq)
			if verbose:
				head = pipeparts.mkprogressreport(pipeline, head, "progress_xml_%s" % suffix)
			triggersrcs[instrument].add(head)
		elif chisq_type == 'autochisq_spearman':
			# FIXME don't hardcode
			# peak finding window (n) in samples is one second at max rate, ie max(rates)
			head = pipeparts.mkqueue(pipeline, snr, max_size_buffers=1)
			head = mkitac_spearman(pipeline, head, max_bank_rate, bank_struct.template_bank_filename, autocorrelation_matrix = bank_struct.autocorrelation_bank, mask_matrix = bank_struct.autocorrelation_mask, snr_thresh = peak_thresh, sigmasq = bank_struct.sigmasq)
			if verbose:
				head = pipeparts.mkprogressreport(pipeline, head, "progress_xml_spearman_%s" % suffix)
			triggersrcs[instrument].add(head)
		# FIXME:  find a way to use less memory without this hack
		del bank_struct.autocorrelation_bank
		bank_count = bank_count + 1
		if nxydump_segment is not None:
			pipeparts.mknxydumpsink(pipeline, pipeparts.mktogglecomplex(pipeline, pipeparts.mkqueue(pipeline, snr)), "snr_gpu_%d_%s.dump" % (nxydump_segment[0], suffix), segment = nxydump_segment)
		#pipeparts.mkogmvideosink(pipeline, pipeparts.mkcapsfilter(pipeline, pipeparts.mkchannelgram(pipeline, pipeparts.mkqueue(pipeline, snr), plot_width = .125), "video/x-raw-rgb, width=640, height=480, framerate=64/1"), "snr_channelgram_%s.ogv" % suffix, audiosrc = pipeparts.mkaudioamplify(pipeline, pipeparts.mkqueue(pipeline, hoftdict[max(bank.get_rates())], max_size_time = 2 * int(math.ceil(bank.filter_length)) * gst.SECOND), 0.125), verbose = True)

	#
	# done
	#

	assert any(triggersrcs.values())
	return triggersrcs
def mkpostcohfilesink(pipeline, postcoh, location = ".", compression = 1, snapshot_interval = 0):
	properties = dict((name, value) for name, value in zip(("location", "compression", "snapshot-interval", "sync", "async"), (location, compression, snapshot_interval, False, False)))
	if "name" in properties:
		elem = gst.element_factory_make("postcoh_filesink", properties.pop("name"))
	else:
		elem = gst.element_factory_make("postcoh_filesink")
	for name, value in properties.items():
		elem.set_property(name.replace("_", "-"), value)
	pipeline.add(elem)
	postcoh.link(elem)
	return elem


def mkPostcohSPIIR(pipeline, detectors, banks, psd, psd_fft_length = 8, ht_gate_threshold = None, veto_segments = None, verbose = False, nxydump_segment = None, chisq_type = 'autochisq', track_psd = False, block_duration = gst.SECOND, blind_injections = None, peak_thresh = 4, detrsp_fname = None, hist_trials = 1, output_prefix = None, output_skymap = 0):
#	pdb.set_trace()
	#
	# check for recognized value of chisq_type
	#

	if chisq_type not in ['autochisq']:
		raise ValueError("chisq_type must be either 'autochisq', given %s" % chisq_type)

	#
	# extract segments from the injection file for selected reconstruction
	#

	if detectors.injection_filename is not None:
		inj_seg_list = simulation.sim_inspiral_to_segment_list(detectors.injection_filename)
	else:
		inj_seg_list = None
		#
		# Check to see if we are specifying blind injections now that we know
		# we don't want real injections. Setting this
		# detectors.injection_filename will ensure that injections are added
		# but won't only reconstruct injection segments.
		#
		detectors.injection_filename = blind_injections

	#
	# construct dictionaries of whitened, conditioned, down-sampled
	# h(t) streams

	#
	#

	hoftdicts = {}
	max_instru_rates = {} 
	sngl_max_rate = 0
	for instrument in detectors.channel_dict:
		for instrument_from_bank, bank_list in [(instrument_from_bank, bank_list) for bank_dict in banks for instrument_from_bank, bank_list in bank_dict.items()]:
			if instrument_from_bank == instrument:
				sngl_max_rate = max(cbc_template_iir.get_maxrate_from_xml(bank_list[0]), sngl_max_rate)
		max_instru_rates[instrument] = sngl_max_rate
		src = datasource.mkbasicsrc(pipeline, detectors, instrument, verbose)
		if veto_segments is not None:		
			hoftdicts[instrument] = uni_datasource.mkwhitened_src(pipeline, src, sngl_max_rate, instrument, psd = psd[instrument], psd_fft_length = psd_fft_length, ht_gate_threshold = ht_gate_threshold, veto_segments = veto_segments[instrument], seekevent = detectors.seekevent, nxydump_segment = nxydump_segment, track_psd = track_psd, zero_pad = 0, width = 32)
		else:
			hoftdicts[instrument] = uni_datasource.mkwhitened_src(pipeline, src, sngl_max_rate, instrument, psd = psd[instrument], psd_fft_length = psd_fft_length, ht_gate_threshold = ht_gate_threshold, veto_segments = None, seekevent = detectors.seekevent, nxydump_segment = nxydump_segment, track_psd = track_psd, zero_pad = 0, width = 32)

	#
	# construct trigger generators
	#
	triggersrcs = []

	# format of banks :	[{'H1': <H1Bank0>; 'L1': <L1Bank0>..;}
	#			 {'H1': <H1Bank1>; 'L1': <L1Bank1>..;}
	#			 ...]
	# format of bank_dict: {'H1': <H1Bank1>; 'L1': <L1Bank1>..;}
	bank_count = 0
	postcoh_count = 0
	autocorrelation_fname_list = []
	for bank_dict in banks:
		autocorrelation_fname = ""
		for instrument, bank_list in bank_dict.items():
			autocorrelation_fname += str(instrument)
			autocorrelation_fname += ":"
			autocorrelation_fname += str(bank_list[0])
			autocorrelation_fname += "," 
			if len(bank_list) != 1:
				raise ValueError("%s instrument: number of banks is not equal to 1, can not do coherent analysis" % instrument)
		autocorrelation_fname = autocorrelation_fname.rstrip(',')
		print autocorrelation_fname
		autocorrelation_fname_list.append(autocorrelation_fname)

	for instrument in banks[0].keys():
		hoftdicts[instrument] = pipeparts.mktee(pipeline, hoftdicts[instrument])

	for i_dict, bank_dict in enumerate(banks):
		postcoh = None
		head = None

		for instrument, bank_list in bank_dict.items():
			max_bank_rate = cbc_template_iir.get_maxrate_from_xml(bank_list[0])
			head = pipeparts.mkqueue(pipeline, hoftdicts[instrument], max_size_time=gst.SECOND * 10, max_size_buffers=0, max_size_bytes=0)
			if max_bank_rate < max_instru_rates[instrument]:
				head = pipeparts.mkcapsfilter(pipeline, pipeparts.mkresample(pipeline, head, quality = 9), "audio/x-raw-float, rate=%d" % max_bank_rate)
			suffix = "%s%s" % (instrument,  "_stream%d" % bank_count)
	
			head = pipeparts.mkreblock(pipeline, head)
			snr = pipeparts.mkcudamultiratespiir(pipeline, head, bank_list[0], gap_handle = 0, stream_id = bank_count) # treat gap as zeros
			if verbose:
				snr = pipeparts.mkprogressreport(pipeline, snr, "progress_done_gpu_filtering_%s" % suffix)

			if postcoh is None:
				postcoh = mkcudapostcoh(pipeline, snr, instrument, detrsp_fname, autocorrelation_fname_list[i_dict], hist_trials = hist_trials, snglsnr_thresh = peak_thresh, output_skymap = output_skymap, stream_id = postcoh_count)
				postcoh_count += 1
			else:
				snr.link_pads(None, postcoh, instrument)
			bank_count += 1

		# FIXME: hard-coded to do compression
		if verbose:
			postcoh = pipeparts.mkprogressreport(pipeline, postcoh, "progress_xml_dump_bank_stream%d" % i_dict)
		head = mkpostcohfilesink(pipeline, postcoh, location = output_prefix, compression = 1, snapshot_interval = 0)
		triggersrcs.append(head)
	return triggersrcs

def mkPostcohSPIIROnline(pipeline, detectors, banks, psd, psd_fft_length = 8, ht_gate_threshold = None, veto_segments = None, verbose = False, nxydump_segment = None, chisq_type = 'autochisq', track_psd = False, block_duration = gst.SECOND, blind_injections = None, peak_thresh = 4, detrsp_fname = None, hist_trials = 1, output_stats_prefix = None, output_skymap = 0, stats_update_interval = 14400, k10_gpu_start_id = 0, num_k10_gpu = 4):
#	pdb.set_trace()
	#
	# check for recognized value of chisq_type
	#

	if chisq_type not in ['autochisq']:
		raise ValueError("chisq_type must be either 'autochisq', given %s" % chisq_type)

	#
	# extract segments from the injection file for selected reconstruction
	#

	if detectors.injection_filename is not None:
		inj_seg_list = simulation.sim_inspiral_to_segment_list(detectors.injection_filename)
	else:
		inj_seg_list = None
		#
		# Check to see if we are specifying blind injections now that we know
		# we don't want real injections. Setting this
		# detectors.injection_filename will ensure that injections are added
		# but won't only reconstruct injection segments.
		#
		detectors.injection_filename = blind_injections

	#
	# construct dictionaries of whitened, conditioned, down-sampled
	# h(t) streams

	#
	#

	hoftdicts = {}
	max_instru_rates = {} 
	sngl_max_rate = 0
	for instrument in detectors.channel_dict:
		for instrument_from_bank, bank_list in [(instrument_from_bank, bank_list) for bank_dict in banks for instrument_from_bank, bank_list in bank_dict.items()]:
			if instrument_from_bank == instrument:
				sngl_max_rate = max(cbc_template_iir.get_maxrate_from_xml(bank_list[0]), sngl_max_rate)
		max_instru_rates[instrument] = sngl_max_rate
		src = datasource.mkbasicsrc(pipeline, detectors, instrument, verbose)
		if veto_segments is not None:		
			hoftdicts[instrument] = uni_datasource.mkwhitened_src(pipeline, src, sngl_max_rate, instrument, psd = psd[instrument], psd_fft_length = psd_fft_length, ht_gate_threshold = ht_gate_threshold, veto_segments = veto_segments[instrument], seekevent = detectors.seekevent, nxydump_segment = nxydump_segment, track_psd = track_psd, zero_pad = 0, width = 32)
		else:
			hoftdicts[instrument] = uni_datasource.mkwhitened_src(pipeline, src, sngl_max_rate, instrument, psd = psd[instrument], psd_fft_length = psd_fft_length, ht_gate_threshold = ht_gate_threshold, veto_segments = None, seekevent = detectors.seekevent, nxydump_segment = nxydump_segment, track_psd = track_psd, zero_pad = 0, width = 32)

	#
	# construct trigger generators
	#
	triggersrcs = []
	ifos = ""
	for instrument in banks[0].keys():
		ifos += str(instrument)

	# format of banks :	[{'H1': <H1Bank0>; 'L1': <L1Bank0>..;}
	#			 {'H1': <H1Bank1>; 'L1': <L1Bank1>..;}
	#			 ...]
	# format of bank_dict: {'H1': <H1Bank1>; 'L1': <L1Bank1>..;}
	bank_count = 0
	postcoh_count = 0
	gtx750_list = range(0, 6)
	k10_list = range(k10_gpu_start_id, k10_gpu_start_id + num_k10_gpu)
	for ele in k10_list:
		gtx750_list.remove(ele)
	autocorrelation_fname_list = []
	for bank_dict in banks:
		autocorrelation_fname = ""
		for instrument, bank_list in bank_dict.items():
			autocorrelation_fname += str(instrument)
			autocorrelation_fname += ":"
			autocorrelation_fname += str(bank_list[0])
			autocorrelation_fname += "," 
			if len(bank_list) != 1:
				raise ValueError("%s instrument: number of banks is not equal to other banks, can not do coherent analysis" % instrument)
		autocorrelation_fname = autocorrelation_fname.rstrip(',')
		print autocorrelation_fname
		autocorrelation_fname_list.append(autocorrelation_fname)

	for instrument in banks[0].keys():
		hoftdicts[instrument] = pipeparts.mktee(pipeline, hoftdicts[instrument])

	for i_dict, bank_dict in enumerate(banks):
		postcoh = None
		head = None
		output_stats_fname = "%s_stats.xml.gz" % output_stats_prefix[i_dict]

		for instrument, bank_list in bank_dict.items():
			max_bank_rate = cbc_template_iir.get_maxrate_from_xml(bank_list[0])
			head = pipeparts.mkqueue(pipeline, hoftdicts[instrument], max_size_time=gst.SECOND * 10, max_size_buffers=0, max_size_bytes=0)
			if max_bank_rate < max_instru_rates[instrument]:
				head = pipeparts.mkcapsfilter(pipeline, pipeparts.mkresample(pipeline, head, quality = 9), "audio/x-raw-float, rate=%d" % max_bank_rate)
			suffix = "%s%s" % (instrument,  "_stream%d" % bank_count)
	
			head = pipeparts.mkreblock(pipeline, head)
			snr = pipeparts.mkcudamultiratespiir(pipeline, head, bank_list[0], gap_handle = 0, stream_id = bank_count) # treat gap as zeros
			if verbose:
				snr = pipeparts.mkprogressreport(pipeline, snr, "progress_done_gpu_filtering_%s" % suffix)

			if postcoh is None:
				# make a queue for postcoh, otherwise it will be in the same thread with the first bank	
				snr = pipeparts.mkqueue(pipeline, snr, max_size_time=gst.SECOND * 10, max_size_buffers=0, max_size_bytes=0)
				# FIXME: hard-coded to set 2 postcoh process to 2 gtx750 cards
				if bank_count > 23:
					postcoh = mkcudapostcoh(pipeline, snr, instrument, detrsp_fname, autocorrelation_fname_list[i_dict], hist_trials = hist_trials, snglsnr_thresh = peak_thresh, output_skymap = output_skymap, stream_id = gtx750_list[postcoh_count % 2])
					postcoh_count += 1
				else:
					postcoh = mkcudapostcoh(pipeline, snr, instrument, detrsp_fname, autocorrelation_fname_list[i_dict], hist_trials = hist_trials, snglsnr_thresh = peak_thresh, output_skymap = output_skymap, stream_id = postcoh_count % num_k10_gpu + k10_gpu_start_id)
					postcoh_count += 1
			else:
				snr.link_pads(None, postcoh, instrument)
			bank_count += 1

		# FIXME: hard-coded to do compression
		if verbose:
			postcoh = pipeparts.mkprogressreport(pipeline, postcoh, "progress_xml_dump_bank_stream%d" % i_dict)

		postcoh = mkcohfar_accumbackground(pipeline, postcoh, ifos = ifos, output_fname = output_stats_fname, update_interval = stats_update_interval)
		#head = mkpostcohfilesink(pipeline, postcoh, location = output_prefix[i_dict], compression = 1, snapshot_interval = snapshot_interval)
		triggersrcs.append(postcoh)
	return triggersrcs

def mkPostcohSPIIROffline(pipeline, detectors, banks, psd, psd_fft_length = 8, ht_gate_threshold = None, veto_segments = None, verbose = False, nxydump_segment = None, chisq_type = 'autochisq', track_psd = False, block_duration = gst.SECOND, blind_injections = None, peak_thresh = 4, detrsp_fname = None, hist_trials = 1, output_prefix = None, output_skymap = 0, snapshot_interval = 14400, k10_gpu_start_id = 0, num_k10_gpu = 4):
#	pdb.set_trace()
	#
	# check for recognized value of chisq_type
	#

	if chisq_type not in ['autochisq']:
		raise ValueError("chisq_type must be either 'autochisq', given %s" % chisq_type)

	#
	# extract segments from the injection file for selected reconstruction
	#

	if detectors.injection_filename is not None:
		inj_seg_list = simulation.sim_inspiral_to_segment_list(detectors.injection_filename)
	else:
		inj_seg_list = None
		#
		# Check to see if we are specifying blind injections now that we know
		# we don't want real injections. Setting this
		# detectors.injection_filename will ensure that injections are added
		# but won't only reconstruct injection segments.
		#
		detectors.injection_filename = blind_injections

	#
	# construct dictionaries of whitened, conditioned, down-sampled
	# h(t) streams

	#
	#

	hoftdicts = {}
	max_instru_rates = {} 
	sngl_max_rate = 0
	for instrument in detectors.channel_dict:
		for instrument_from_bank, bank_list in [(instrument_from_bank, bank_list) for bank_dict in banks for instrument_from_bank, bank_list in bank_dict.items()]:
			if instrument_from_bank == instrument:
				sngl_max_rate = max(cbc_template_iir.get_maxrate_from_xml(bank_list[0]), sngl_max_rate)
		max_instru_rates[instrument] = sngl_max_rate
		src = datasource.mkbasicsrc(pipeline, detectors, instrument, verbose)
		if veto_segments is not None:		
			hoftdicts[instrument] = uni_datasource.mkwhitened_src(pipeline, src, sngl_max_rate, instrument, psd = psd[instrument], psd_fft_length = psd_fft_length, ht_gate_threshold = ht_gate_threshold, veto_segments = veto_segments[instrument], seekevent = detectors.seekevent, nxydump_segment = nxydump_segment, track_psd = track_psd, zero_pad = 0, width = 32)
		else:
			hoftdicts[instrument] = uni_datasource.mkwhitened_src(pipeline, src, sngl_max_rate, instrument, psd = psd[instrument], psd_fft_length = psd_fft_length, ht_gate_threshold = ht_gate_threshold, veto_segments = None, seekevent = detectors.seekevent, nxydump_segment = nxydump_segment, track_psd = track_psd, zero_pad = 0, width = 32)

	#
	# construct trigger generators
	#
	triggersrcs = []
	ifos = ""
	for instrument in banks[0].keys():
		ifos += str(instrument)

	# format of banks :	[{'H1': <H1Bank0>; 'L1': <L1Bank0>..;}
	#			 {'H1': <H1Bank1>; 'L1': <L1Bank1>..;}
	#			 ...]
	# format of bank_dict: {'H1': <H1Bank1>; 'L1': <L1Bank1>..;}
	bank_count = 0
	postcoh_count = 0
	gtx750_list = range(0, 6)
	k10_list = range(k10_gpu_start_id, k10_gpu_start_id + num_k10_gpu)
	for ele in k10_list:
		gtx750_list.remove(ele)
	autocorrelation_fname_list = []
	for bank_dict in banks:
		autocorrelation_fname = ""
		for instrument, bank_list in bank_dict.items():
			autocorrelation_fname += str(instrument)
			autocorrelation_fname += ":"
			autocorrelation_fname += str(bank_list[0])
			autocorrelation_fname += "," 
			if len(bank_list) != 1:
				raise ValueError("%s instrument: number of banks is not equal to other banks, can not do coherent analysis" % instrument)
		autocorrelation_fname = autocorrelation_fname.rstrip(',')
		print autocorrelation_fname
		autocorrelation_fname_list.append(autocorrelation_fname)

	for instrument in banks[0].keys():
		hoftdicts[instrument] = pipeparts.mktee(pipeline, hoftdicts[instrument])

	for i_dict, bank_dict in enumerate(banks):
		postcoh = None
		head = None
		output_stats_fname = "%s_stats.xml.gz" % output_prefix[i_dict]

		for instrument, bank_list in bank_dict.items():
			max_bank_rate = cbc_template_iir.get_maxrate_from_xml(bank_list[0])
			head = pipeparts.mkqueue(pipeline, hoftdicts[instrument], max_size_time=gst.SECOND * 10, max_size_buffers=0, max_size_bytes=0)
			if max_bank_rate < max_instru_rates[instrument]:
				head = pipeparts.mkcapsfilter(pipeline, pipeparts.mkresample(pipeline, head, quality = 9), "audio/x-raw-float, rate=%d" % max_bank_rate)
			suffix = "%s%s" % (instrument,  "_stream%d" % bank_count)
	
			head = pipeparts.mkreblock(pipeline, head)
			snr = pipeparts.mkcudamultiratespiir(pipeline, head, bank_list[0], gap_handle = 0, stream_id = bank_count) # treat gap as zeros
			if verbose:
				snr = pipeparts.mkprogressreport(pipeline, snr, "progress_done_gpu_filtering_%s" % suffix)

			if postcoh is None:
				# make a queue for postcoh, otherwise it will be in the same thread with the first bank	
				snr = pipeparts.mkqueue(pipeline, snr, max_size_time=gst.SECOND * 10, max_size_buffers=0, max_size_bytes=0)
				# FIXME: hard-coded to set 2 postcoh process to 2 gtx750 cards
				if bank_count > 23:
					postcoh = mkcudapostcoh(pipeline, snr, instrument, detrsp_fname, autocorrelation_fname_list[i_dict], hist_trials = hist_trials, snglsnr_thresh = peak_thresh, output_skymap = output_skymap, stream_id = gtx750_list[postcoh_count % 2])
					postcoh_count += 1
				else:
					postcoh = mkcudapostcoh(pipeline, snr, instrument, detrsp_fname, autocorrelation_fname_list[i_dict], hist_trials = hist_trials, snglsnr_thresh = peak_thresh, output_skymap = output_skymap, stream_id = postcoh_count % num_k10_gpu + k10_gpu_start_id)
					postcoh_count += 1
			else:
				snr.link_pads(None, postcoh, instrument)
			bank_count += 1

		# FIXME: hard-coded to do compression
		if verbose:
			postcoh = pipeparts.mkprogressreport(pipeline, postcoh, "progress_xml_dump_bank_stream%d" % i_dict)

		#postcoh = mkcohfar_accumbackground(pipeline, postcoh, ifos = ifos, output_fname = output_stats_fname, hist_trials = hist_trials, update_interval = 0)
		head = mkpostcohfilesink(pipeline, postcoh, location = output_prefix[i_dict], compression = 1, snapshot_interval = snapshot_interval)
		triggersrcs.append(head)
	return triggersrcs
