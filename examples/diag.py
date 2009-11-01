#!/usr/bin/python


import sys


import gobject
import pygst
pygst.require("0.10")
import gst


from pylal.datatypes import LIGOTimeGPS
from gstlal import pipeparts


#
# =============================================================================
#
#                                  Pipelines
#
# =============================================================================
#


def test_histogram(pipeline):
	head = pipeparts.mkprogressreport(pipeline, pipeparts.mkframesrc(pipeline, location = "/home/kipp/scratch_local/874100000-20000/cache/874000000-20000.cache", instrument = "H1", channel_name = "LSC-STRAIN"), "src")
	head = pipeparts.mkwhiten(pipeline, head)
	head = pipeparts.mkcapsfilter(pipeline, pipeparts.mkhistogram(pipeline, head), "video/x-raw-rgb, width=640, height=480, framerate=1/4")
	pipeparts.mkvideosink(pipeline, pipeparts.mkcolorspace(pipeline, head))


def test_firbank(pipeline):
	head = gst.element_factory_make("audiotestsrc")
	head.set_property("samplesperbuffer", 2048)
	head.set_property("wave", 0)	# sin(t)
	head.set_property("freq", 256.0)
	pipeline.add(head)

	head = pipeparts.mktee(pipeline, pipeparts.mkcapsfilter(pipeline, head, "audio/x-raw-float, width=64, rate=2048"))
	pipeparts.mknxydumpsink(pipeline, pipeparts.mkqueue(pipeline, head), "dump_in.txt")

	head = pipeparts.mkfirbank(pipeline, pipeparts.mkqueue(pipeline, head), latency = 2, fir_matrix = [[0.0, 0.0, 1.0, 0.0, 0.0]])
	pipeparts.mknxydumpsink(pipeline, head, "dump_out.txt")


#
# =============================================================================
#
#                                     Main
#
# =============================================================================
#


class Handler(object):
	def __init__(self, mainloop, pipeline):
		self.mainloop = mainloop
		self.pipeline = pipeline
		bus = pipeline.get_bus()
		bus.add_signal_watch()
		bus.connect("message", self.on_message)

	def on_message(self, bus, message):
		if message.type == gst.MESSAGE_EOS:
			self.pipeline.set_state(gst.STATE_NULL)
			self.mainloop.quit()
		elif message.type == gst.MESSAGE_ERROR:
			gerr, dbgmsg = message.parse_error()
			print >>sys.stderr, "error (%s:%d '%s'): %s" % (gerr.domain, gerr.code, gerr.message, dbgmsg)
			self.pipeline.set_state(gst.STATE_NULL)
			self.mainloop.quit()


gobject.threads_init()

mainloop = gobject.MainLoop()

pipeline = gst.Pipeline("diag")

test_firbank(pipeline)

handler = Handler(mainloop, pipeline)

pipeline.set_state(gst.STATE_PAUSED)
pipeline.seek(1.0, gst.Format(gst.FORMAT_TIME), gst.SEEK_FLAG_FLUSH, gst.SEEK_TYPE_SET, LIGOTimeGPS(874000000).ns(), gst.SEEK_TYPE_SET, LIGOTimeGPS(874020000).ns())
pipeline.set_state(gst.STATE_PLAYING)
mainloop.run()
