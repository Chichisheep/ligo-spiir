/*
 * PSD Estimation and whitener
 *
 * Copyright (C) 2008  Kipp Cannon, Chad Hanna, Drew Keppel
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
 */


/*
 * ========================================================================
 *
 *                                  Preamble
 *
 * ========================================================================
 */


/*
 * stuff from the C library
 */


#include <math.h>


/*
 * stuff from glib/gstreamer
 */


#include <glib.h>
#include <gst/gst.h>
#include <gst/base/gstadapter.h>


/*
 * stuff from LAL
 */


#include <lal/LALDatatypes.h>
#include <lal/LALStdlib.h>
#include <lal/Date.h>
#include <lal/Sequence.h>
#include <lal/TimeSeries.h>
#include <lal/FrequencySeries.h>
#include <lal/TimeFreqFFT.h>
#include <lal/Units.h>
#include <lal/LALComplex.h>
#include <lal/Window.h>
#include <lal/Units.h>


/*
 * our own stuff
 */


#include <gstlal.h>
#include <gstlal_whiten.h>


static const LIGOTimeGPS GPS_ZERO = {0, 0};


/*
 * ============================================================================
 *
 *                                 Parameters
 *
 * ============================================================================
 */


#define DEFAULT_ZERO_PAD_SECONDS 2.0
#define DEFAULT_FFT_LENGTH_SECONDS 8.0
#define DEFAULT_AVERAGE_SAMPLES 32
#define DEFAULT_MEDIAN_SAMPLES 9
#define DEFAULT_PSDMODE GSTLAL_PSDMODE_RUNNING_AVERAGE


/*
 * ============================================================================
 *
 *                                Custom Types
 *
 * ============================================================================
 */


/*
 * PSD mode enum
 */


GType gstlal_psdmode_get_type(void)
{
	static GType type = 0;

	if(!type) {
		static GEnumValue values[] = {
			{GSTLAL_PSDMODE_RUNNING_AVERAGE, "GSTLAL_PSDMODE_RUNNING_AVERAGE", "Use running average for PSD"},
			{GSTLAL_PSDMODE_FIXED, "GSTLAL_PSDMODE_FIXED", "Use fixed spectrum for PSD"},
			{0, NULL, NULL}
		};

		type = g_enum_register_static("GSTLAL_PSDMODE", values);
	}

	return type;
}


/*
 * ============================================================================
 *
 *                                Support Code
 *
 * ============================================================================
 */


static void reset_workspace_metadata(GSTLALWhiten *element)
{
	element->tdworkspace->deltaT = (double) 1.0 / element->sample_rate;
	element->tdworkspace->sampleUnits = element->sample_units;
	element->fdworkspace->deltaF = (double) 1.0 / (element->tdworkspace->deltaT * element->window->data->length);
}


static int make_window_and_fft_plans(GSTLALWhiten *element)
{
	int fft_length = round(element->fft_length_seconds * element->sample_rate);
	int zero_pad = round(element->zero_pad_seconds * element->sample_rate);

	/*
	 * build a Hann window with zero-padding.  both fft_length and
	 * zero_pad are an even number of samples (enforced in the caps
	 * negotiation phase).  we need a Hann window with an odd number of
	 * samples so that there is a middle sample (= 1) to overlap the
	 * end sample (= 0) of the next window.  we achieve this by adding
	 * 1 to the length of the envelope, and then clipping the last
	 * sample.  the result is a sequence of windows that fit together
	 * as shown below:
	 *
	 * 1.0 --------A-------B-------C-------
	 *     ------A---A---B---B---C---C-----
	 * 0.5 ----A-------A-------B-------C---
	 *     --A-------B---A---C---B-------C-
	 * 0.0 A-------B-------C---------------
	 *
	 * i.e., A is "missing" its last sample, which is where C begins,
	 * and B's first sample starts on A's middle sample, and the sum of
	 * the windows is identically 1 everywhere.
	 */

	XLALDestroyREAL8Window(element->window);
	element->window = XLALCreateHannREAL8Window(fft_length - 2 * zero_pad + 1);
	if(!element->window) {
		GST_ERROR_OBJECT(element, "failure creating Hann window");
		XLALClearErrno();
		return -1;
	}
	if(!XLALResizeREAL8Sequence(element->window->data, -zero_pad, fft_length)) {
		GST_ERROR_OBJECT(element, "failure resizing Hann window");
		XLALDestroyREAL8Window(element->window);
		element->window = NULL;
		XLALClearErrno();
		return -1;
	}

	/*
	 * allocate a tail buffer
	 */

	XLALDestroyREAL8Sequence(element->tail);
	element->tail = XLALCreateREAL8Sequence(element->window->data->length / 2 - zero_pad);
	if(!element->tail) {
		GST_ERROR_OBJECT(element, "failure allocating tail buffer");
		XLALClearErrno();
		return -1;
	}
	memset(element->tail->data, 0, element->tail->length * sizeof(*element->tail->data));

	/*
	 * construct FFT plans
	 */

	g_mutex_lock(gstlal_fftw_lock);
	XLALDestroyREAL8FFTPlan(element->fwdplan);
	XLALDestroyREAL8FFTPlan(element->revplan);

	element->fwdplan = XLALCreateForwardREAL8FFTPlan(element->window->data->length, 1);
	element->revplan = XLALCreateReverseREAL8FFTPlan(element->window->data->length, 1);
	g_mutex_unlock(gstlal_fftw_lock);

	if(!element->fwdplan || !element->revplan) {
		GST_ERROR_OBJECT(element, "failure creating FFT plans");
		g_mutex_lock(gstlal_fftw_lock);
		XLALDestroyREAL8FFTPlan(element->fwdplan);
		XLALDestroyREAL8FFTPlan(element->revplan);
		g_mutex_unlock(gstlal_fftw_lock);
		element->fwdplan = NULL;
		element->revplan = NULL;
		XLALClearErrno();
		return -1;
	}

	/*
	 * construct work spaces
	 */

	XLALDestroyREAL8TimeSeries(element->tdworkspace);
	element->tdworkspace = XLALCreateREAL8TimeSeries(NULL, &GPS_ZERO, 0.0, (double) 1.0 / element->sample_rate, &element->sample_units, element->window->data->length);
	if(!element->tdworkspace) {
		GST_ERROR_OBJECT(element, "failure creating time-domain workspace");
		XLALClearErrno();
		return -1;
	}
	XLALDestroyCOMPLEX16FrequencySeries(element->fdworkspace);
	element->fdworkspace = XLALCreateCOMPLEX16FrequencySeries(NULL, &GPS_ZERO, 0.0, (double) 1.0 / (element->tdworkspace->deltaT * element->window->data->length), &lalDimensionlessUnit, element->window->data->length / 2 + 1);
	if(!element->fdworkspace) {
		GST_ERROR_OBJECT(element, "failure creating frequency-domain workspace");
		XLALClearErrno();
		return -1;
	}

	/*
	 * reset PSD regressor
	 */

	XLALPSDRegressorReset(element->psd_regressor);

	/*
	 * done
	 */

	return 0;
}


static REAL8FrequencySeries *make_empty_psd(double f0, double deltaF, int length, LALUnit sample_units)
{
	REAL8FrequencySeries *psd;

	sample_units = gstlal_lalUnitSquaredPerHertz(sample_units);
	psd = XLALCreateREAL8FrequencySeries("PSD", &GPS_ZERO, f0, deltaF, &sample_units, length);
	if(!psd) {
		GST_ERROR("XLALCreateREAL8FrequencySeries() failed");
		XLALClearErrno();
	}

	return psd;
}


static REAL8FrequencySeries *make_psd_from_fseries(const COMPLEX16FrequencySeries *fseries)
{
	LALUnit unit;
	REAL8FrequencySeries *psd;
	unsigned i;

	/*
	 * reconstruct the time-domain sample units from the sample units
	 * of the frequency series
	 */

	XLALUnitMultiply(&unit, &fseries->sampleUnits, &lalHertzUnit);

	/*
	 * build the PSD
	 */

	psd = make_empty_psd(fseries->f0, fseries->deltaF, fseries->data->length, unit);
	if(!psd)
		return NULL;
	for(i = 0; i < psd->data->length; i++)
		psd->data->data[i] = XLALCOMPLEX16Abs2(fseries->data->data[i]) * (2 * psd->deltaF);

	/*
	 * zero the DC and Nyquist components
	 */

	if(psd->f0 == 0)
		psd->data->data[0] = 0;
	psd->data->data[psd->data->length - 1] = 0;

	return psd;
}


static REAL8FrequencySeries *get_psd(GSTLALWhiten *element)
{
	REAL8FrequencySeries *psd;

	switch(element->psdmode) {
	case GSTLAL_PSDMODE_RUNNING_AVERAGE:
		if(!element->psd_regressor->n_samples) {
			/*
			 * No data for the average yet, seed psd regressor
			 * with current frequency series.
			 */

			psd = make_psd_from_fseries(element->fdworkspace);
			if(!psd)
				return NULL;
			if(XLALPSDRegressorSetPSD(element->psd_regressor, psd, 1)) {
				GST_ERROR_OBJECT(element, "XLALPSDRegressorSetPSD() failed");
				XLALDestroyREAL8FrequencySeries(psd);
				XLALClearErrno();
				return NULL;
			}
		} else {
			psd = XLALPSDRegressorGetPSD(element->psd_regressor);
			if(!psd) {
				GST_ERROR_OBJECT(element, "XLALPSDRegressorGetPSD() failed");
				XLALClearErrno();
				return NULL;
			}
		}
		break;

	case GSTLAL_PSDMODE_FIXED:
		psd = element->psd;
		break;
	}

	psd->epoch = element->tdworkspace->epoch;

	/*
	 * done
	 */

	return psd;
}


/*
 * ============================================================================
 *
 *                                  Messages
 *
 * ============================================================================
 */


static GstMessage *psd_message_new(GSTLALWhiten *element, REAL8FrequencySeries *psd)
{
	GValueArray *va = gstlal_g_value_array_from_doubles(psd->data->data, psd->data->length);
	char units[50];
	GstStructure *s = gst_structure_new(
		"spectrum",
		"timestamp", G_TYPE_UINT64, (guint64) XLALGPSToINT8NS(&psd->epoch),
		"delta-f", G_TYPE_DOUBLE, psd->deltaF,
		"sample-units", G_TYPE_STRING, XLALUnitAsString(units, sizeof(units), &psd->sampleUnits),
		"magnitude", G_TYPE_VALUE_ARRAY, va,
		NULL
	);
	g_value_array_free(va);

	return gst_message_new_element(GST_OBJECT(element), s);
}


/*
 * ============================================================================
 *
 *                             GStreamer Element
 *
 * ============================================================================
 */


/* FIXME:  try rewriting this as a subclass of the base transform class */


/*
 * Properties
 */


enum property {
	ARG_PSDMODE = 1,
	ARG_ZERO_PAD_SECONDS,
	ARG_FFT_LENGTH,
	ARG_AVERAGE_SAMPLES,
	ARG_MEDIAN_SAMPLES,
	ARG_DELTA_F,
	ARG_PSD
};


static void set_property(GObject * object, enum property id, const GValue * value, GParamSpec * pspec)
{

	GSTLALWhiten *element = GSTLAL_WHITEN(object);

	GST_OBJECT_LOCK(element);

	switch (id) {
	case ARG_PSDMODE:
		element->psdmode = g_value_get_enum(value);
		break;

	case ARG_ZERO_PAD_SECONDS:
		element->zero_pad_seconds = g_value_get_double(value);
		/* FIXME:  if the value has changed, set sink pad's caps to
		 * NULL to force renegotiation (== check that the rate is
		 * still OK) */
		break;

	case ARG_FFT_LENGTH:
		element->fft_length_seconds = g_value_get_double(value);
		/* FIXME:  if the value has changed, set sink pad's caps to
		 * NULL to force renegotiation (== check that the rate is
		 * still OK) */
		break;

	case ARG_AVERAGE_SAMPLES:
		XLALPSDRegressorSetAverageSamples(element->psd_regressor, g_value_get_uint(value));
		break;

	case ARG_MEDIAN_SAMPLES:
		XLALPSDRegressorSetMedianSamples(element->psd_regressor, g_value_get_uint(value));
		break;

	case ARG_DELTA_F:
		/* read-only, should never get here */
		break;

	case ARG_PSD: {
		GValueArray *va = g_value_get_boxed(value);
		/* FIXME:  deltaF? */
		REAL8FrequencySeries *psd;
		if(element->psd)
			psd = make_empty_psd(0.0, element->psd->deltaF, va->n_values, element->sample_units);
		else
			psd = make_empty_psd(0.0, 1.0, va->n_values, element->sample_units);
		gstlal_doubles_from_g_value_array(va, psd->data->data, NULL);
		if(XLALPSDRegressorSetPSD(element->psd_regressor, psd, XLALPSDRegressorGetAverageSamples(element->psd_regressor))) {
			GST_ERROR_OBJECT(element, "XLALPSDRegressorSetPSD() failed");
			XLALClearErrno();
		} else {
			XLALDestroyREAL8FrequencySeries(element->psd);
			element->psd = psd;
		}
		break;
	}
	}

	GST_OBJECT_UNLOCK(element);
}


static void get_property(GObject * object, enum property id, GValue * value, GParamSpec * pspec)
{
	GSTLALWhiten *element = GSTLAL_WHITEN(object);

	GST_OBJECT_LOCK(element);

	switch (id) {
	case ARG_PSDMODE:
		g_value_set_enum(value, element->psdmode);
		break;

	case ARG_ZERO_PAD_SECONDS:
		g_value_set_double(value, element->zero_pad_seconds);
		break;

	case ARG_FFT_LENGTH:
		g_value_set_double(value, element->fft_length_seconds);
		break;

	case ARG_AVERAGE_SAMPLES:
		g_value_set_uint(value, XLALPSDRegressorGetAverageSamples(element->psd_regressor));
		break;

	case ARG_MEDIAN_SAMPLES:
		g_value_set_uint(value, XLALPSDRegressorGetMedianSamples(element->psd_regressor));
		break;

	case ARG_DELTA_F:
		if(element->psd)
			g_value_set_double(value, element->psd->deltaF);
		else
			g_value_set_double(value, 0.0);
		break;

	case ARG_PSD:
		if(element->psd)
			g_value_take_boxed(value, gstlal_g_value_array_from_doubles(element->psd->data->data, element->psd->data->length));
		else
			g_value_take_boxed(value, g_value_array_new(0));
		break;
	}

	GST_OBJECT_UNLOCK(element);
}


/*
 * getcaps()
 */


static GstCaps *getcaps(GstPad *pad)
{
	GSTLALWhiten *element = GSTLAL_WHITEN(gst_pad_get_parent(pad));
	GstCaps *caps, *peercaps;

	/*
	 * start by retrieving our own caps.  use get_fixed_caps_func() to
	 * avoid recursing back into this function.
	 */

	caps = gst_pad_get_fixed_caps_func(pad);

	/*
	 * now compute the intersection of the caps with the downstream
	 * peer's caps if known.
	 */

	peercaps = gst_pad_peer_get_caps(element->srcpad);
	if(peercaps) {
		GstCaps *result = gst_caps_intersect(peercaps, caps);
		gst_caps_unref(caps);
		gst_caps_unref(peercaps);
		caps = result;
	}

	/*
	 * done
	 */

	gst_object_unref(element);
	return caps;
}


/*
 * setcaps()
 */


static gboolean setcaps(GstPad *pad, GstCaps *caps)
{
	GSTLALWhiten *element = GSTLAL_WHITEN(gst_pad_get_parent(pad));
	GstStructure *structure;
	gint rate;
	gboolean success = TRUE;

	/*
	 * extract the sample rate, and check that it is allowed
	 */

	structure = gst_caps_get_structure(caps, 0);
	if(!gst_structure_get_int(structure, "rate", &rate)) {
		GST_ERROR_OBJECT(element, "no rate in caps");
		success = FALSE;
	} else if((int) round(element->fft_length_seconds * rate) & 1 || (int) round(element->zero_pad_seconds * rate) & 1) {
		GST_ERROR_OBJECT(element, "bad sample rate: FFT length and/or zero-padding is an odd number of samples (must be even)");
		success = FALSE;
	}

	/*
	 * try setting the new caps on the downstream peer.
	 */

	if(success)
		success = gst_pad_set_caps(element->srcpad, caps);

	/*
	 * record the sample rate and units, make a new Hann window, new
	 * FFT plans, and workspaces
	 */

	if(success && (rate != element->sample_rate)) {
		element->sample_rate = rate;
		if(make_window_and_fft_plans(element))
			success = FALSE;
	}

	/*
	 * done
	 */

	gst_object_unref(element);
	return success;
}


/*
 * sink event()
 *
 * FIXME:  handle flusing and eos (i.e. flush the adapter and send the last
 * bit of data downstream)
 */


static gboolean sink_event(GstPad *pad, GstEvent *event)
{
	GSTLALWhiten *element = GSTLAL_WHITEN(GST_PAD_PARENT(pad));
	gboolean success = TRUE;

	switch(GST_EVENT_TYPE(event)) {
	case GST_EVENT_TAG: {
		GstTagList *taglist;
		gchar *units;

		gst_event_parse_tag(event, &taglist);
		if(gst_tag_list_get_string(taglist, GSTLAL_TAG_UNITS, &units)) {
			/*
			 * tag list contains a units tag;  replace with
			 * equivalent of "dimensionless" before sending
			 * downstream
			 */
			/* FIXME:  probably shouldn't do this in-place */

			LALUnit sample_units;

			if(!XLALParseUnitString(&sample_units, units)) {
				GST_ERROR_OBJECT(element, "cannot parse units");
				sample_units = lalDimensionlessUnit;
				success = FALSE;
			} else {
				gchar dimensionless_units[16];	/* argh hard-coded length = BAD BAD BAD */
				XLALUnitAsString(dimensionless_units, sizeof(dimensionless_units), &lalDimensionlessUnit);
				/* FIXME:  gstreamer doesn't like empty strings */
				gst_tag_list_add(taglist, GST_TAG_MERGE_REPLACE, GSTLAL_TAG_UNITS, " "/*dimensionless_units*/, NULL);
			}

			g_free(units);
			element->sample_units = sample_units;
		}

		success &= gst_pad_push_event(element->srcpad, event);
		break;
	}

	default:
		success = gst_pad_event_default(pad, event);
		break;
	}

	return success;
}


/*
 * chain()
 */


static GstFlowReturn chain(GstPad *pad, GstBuffer *sinkbuf)
{
	GSTLALWhiten *element = GSTLAL_WHITEN(gst_pad_get_parent(pad));
	GstFlowReturn result = GST_FLOW_OK;
	unsigned zero_pad = round(element->zero_pad_seconds * element->sample_rate);

	/*
	 * Push the incoming buffer into the adapter.  If the buffer is a
	 * discontinuity, first clear the adapter and reset the clock
	 */

	if(!GST_CLOCK_TIME_IS_VALID(element->t0) || GST_BUFFER_IS_DISCONT(sinkbuf)) {
		/* FIXME:  if there is tail data left over, maybe it should
		 * be pushed downstream? */
		gst_adapter_clear(element->adapter);
		element->next_is_discontinuity = TRUE;
		element->t0 = GST_BUFFER_TIMESTAMP(sinkbuf);
		element->offset0 = GST_BUFFER_OFFSET(sinkbuf);
		element->next_offset_out = GST_BUFFER_OFFSET(sinkbuf);
	}
	element->next_offset_in = GST_BUFFER_OFFSET_END(sinkbuf);
	gst_adapter_push(element->adapter, sinkbuf);

	/*
	 * Iterate over the available data
	 */

	while(gst_adapter_available(element->adapter) >= element->tdworkspace->data->length * sizeof(*element->tdworkspace->data->data)) {
		REAL8FrequencySeries *newpsd;
		GstBuffer *srcbuf;
		unsigned i;

		/*
		 * Reset the workspace's metadata that gets modified
		 * through each iteration of this loop.
		 */

		reset_workspace_metadata(element);

		/*
		 * Copy data from adapter into time-domain workspace.
		 */

		memcpy(element->tdworkspace->data->data, gst_adapter_peek(element->adapter, element->tdworkspace->data->length * sizeof(*element->tdworkspace->data->data)), element->tdworkspace->data->length * sizeof(*element->tdworkspace->data->data));
		XLALINT8NSToGPS(&element->tdworkspace->epoch, element->t0);
		XLALGPSAdd(&element->tdworkspace->epoch, (double) (element->next_offset_out - element->offset0) / element->sample_rate);

		/*
		 * Transform to frequency domain
		 */

		if(!XLALUnitaryWindowREAL8Sequence(element->tdworkspace->data, element->window)) {
			GST_ERROR_OBJECT(element, "XLALUnitaryWindowREAL8Sequence() failed");
			result = GST_FLOW_ERROR;
			XLALClearErrno();
			goto done;
		}
		if(XLALREAL8TimeFreqFFT(element->fdworkspace, element->tdworkspace, element->fwdplan)) {
			GST_ERROR_OBJECT(element, "XLALREAL8TimeFreqFFT() failed");
			result = GST_FLOW_ERROR;
			XLALClearErrno();
			goto done;
		}

		/*
		 * Retrieve the PSD.
		 */

		newpsd = get_psd(element);
		if(!newpsd) {
			result = GST_FLOW_ERROR;
			goto done;
		}
		if(newpsd != element->psd) {
			XLALDestroyREAL8FrequencySeries(element->psd);
			element->psd = newpsd;
			gst_element_post_message(GST_ELEMENT(element), psd_message_new(element, element->psd));
		}

		/*
		 * Add frequency domain data to spectrum averager
		 */

		if(XLALPSDRegressorAdd(element->psd_regressor, element->fdworkspace)) {
			GST_ERROR_OBJECT(element, "XLALPSDRegressorAdd() failed");
			result = GST_FLOW_ERROR;
			XLALClearErrno();
			goto done;
		}

		/*
		 * Whiten.  After this, the frequency bins should be unit
		 * variance zero mean complex Gaussian random variables.
		 * They are *not* independent random variables because the
		 * source time series data was windowed before conversion
		 * to the frequency domain.
		 */

		if(!XLALWhitenCOMPLEX16FrequencySeries(element->fdworkspace, element->psd)) {
			GST_ERROR_OBJECT(element, "XLALWhitenCOMPLEX16FrequencySeries() failed");
			result = GST_FLOW_ERROR;
			XLALClearErrno();
			goto done;
		}

		/*
		 * Transform to time domain.
		 */

		if(XLALREAL8FreqTimeFFT(element->tdworkspace, element->fdworkspace, element->revplan)) {
			GST_ERROR_OBJECT(element, "XLALREAL8FreqTimeFFT() failed");
			result = GST_FLOW_ERROR;
			XLALClearErrno();
			goto done;
		}

		/* 
		 * Normalize the time series.
		 *
		 * After inverse transforming the frequency series to the
		 * time domain, the variance of the time series is
		 *
		 * <x_{j}^{2}> = w_{j}^{2} / (\Delta t^{2} \sigma^{2})
		 *
		 * where \sigma^{2} is the sum-of-squares of the window
		 * function, \sigma^{2} = \sum_{j} w_{j}^{2}
		 *
		 * The time series has a j-dependent variance, but we
		 * normalize it so that the variance is 1 in the middle of
		 * the window.
		 */

		for(i = 0; i < element->tdworkspace->data->length; i++)
			element->tdworkspace->data->data[i] *= element->tdworkspace->deltaT * sqrt(element->window->sumofsquares);
		/* normalization constant has units of seconds */
		XLALUnitMultiply(&element->tdworkspace->sampleUnits, &element->tdworkspace->sampleUnits, &lalSecondUnit);

		/*
		 * Verify the result is dimensionless.
		 */

		if(XLALUnitCompare(&lalDimensionlessUnit, &element->tdworkspace->sampleUnits)) {
			char units[100];
			XLALUnitAsString(units, sizeof(units), &element->tdworkspace->sampleUnits);
			GST_ERROR_OBJECT(element, "whitening process failed to produce dimensionless time series: result has units \"%s\"", units);
			result = GST_FLOW_ERROR;
			goto done;
		}

		/*
		 * Get a buffer from the downstream peer.
		 */

		result = gst_pad_alloc_buffer(element->srcpad, element->next_offset_out + zero_pad, element->tail->length * sizeof(*element->tdworkspace->data->data), GST_PAD_CAPS(element->srcpad), &srcbuf);
		if(result != GST_FLOW_OK)
			goto done;
		if(element->next_is_discontinuity) {
			GST_BUFFER_FLAG_SET(srcbuf, GST_BUFFER_FLAG_DISCONT);
			element->next_is_discontinuity = FALSE;
		}
		GST_BUFFER_OFFSET_END(srcbuf) = GST_BUFFER_OFFSET(srcbuf) + element->tail->length;
		GST_BUFFER_TIMESTAMP(srcbuf) = element->t0 + gst_util_uint64_scale_int_round(element->next_offset_out - element->offset0 + zero_pad, GST_SECOND, element->sample_rate);
		GST_BUFFER_DURATION(srcbuf) = element->t0 + gst_util_uint64_scale_int_round(element->next_offset_out - element->offset0 + zero_pad + element->tail->length, GST_SECOND, element->sample_rate) - GST_BUFFER_TIMESTAMP(srcbuf);

		/*
		 * Copy the first half of the time series into the buffer,
		 * removing the zero_pad from the start, and adding the
		 * contents of the tail.  When we add the two time series
		 * (the first half of the piece we have just whitened and
		 * the contents of the tail buffer), we do so overlapping
		 * the Hann windows so that the sum of the windows is 1.
		 */

		for(i = 0; i < element->tail->length; i++)
			((double *) GST_BUFFER_DATA(srcbuf))[i] = element->tdworkspace->data->data[zero_pad + i] + element->tail->data[i];

		/*
		 * Push the buffer downstream
		 */

		result = gst_pad_push(element->srcpad, srcbuf);
		if(result != GST_FLOW_OK)
			goto done;

		/*
		 * Save the second half of time series data minus the final
		 * zero_pad in the tail
		 */

		memcpy(element->tail->data, &element->tdworkspace->data->data[zero_pad + element->tail->length], element->tail->length * sizeof(*element->tail->data));

		/*
		 * Flush the adapter and advance the sample count and
		 * adapter clock
		 */

		gst_adapter_flush(element->adapter, element->tail->length * sizeof(*element->tdworkspace->data->data));
		element->next_offset_out += element->tail->length;
	}

	/*
	 * Done
	 */

done:
	gst_object_unref(element);
	return result;
}


/*
 * Parent class.
 */


static GstElementClass *parent_class = NULL;


/*
 * Instance finalize function.  See ???
 */


static void finalize(GObject * object)
{
	GSTLALWhiten *element = GSTLAL_WHITEN(object);

	g_object_unref(element->adapter);
	gst_object_unref(element->srcpad);
	XLALDestroyREAL8Window(element->window);
	g_mutex_lock(gstlal_fftw_lock);
	XLALDestroyREAL8FFTPlan(element->fwdplan);
	XLALDestroyREAL8FFTPlan(element->revplan);
	g_mutex_unlock(gstlal_fftw_lock);
	XLALPSDRegressorFree(element->psd_regressor);
	XLALDestroyREAL8FrequencySeries(element->psd);
	XLALDestroyREAL8TimeSeries(element->tdworkspace);
	XLALDestroyCOMPLEX16FrequencySeries(element->fdworkspace);
	XLALDestroyREAL8Sequence(element->tail);

	G_OBJECT_CLASS(parent_class)->finalize(object);
}


/*
 * Base init function.  See
 *
 * http://developer.gnome.org/doc/API/2.0/gobject/gobject-Type-Information.html#GBaseInitFunc
 */


static void base_init(gpointer class)
{
	static GstElementDetails plugin_details = {
		"Whiten",
		"Filter",
		"A PSD estimator and time series whitener",
		"Kipp Cannon <kcannon@ligo.caltech.edu>, Chad Hanna <channa@ligo.caltech.edu>, Drew Keppel <dkeppel@ligo.caltech.edu>"
	};
	GstElementClass *element_class = GST_ELEMENT_CLASS(class);

	gst_element_class_set_details(element_class, &plugin_details);

	gst_element_class_add_pad_template(
		element_class,
		gst_pad_template_new(
			"sink",
			GST_PAD_SINK,
			GST_PAD_ALWAYS,
			gst_caps_new_simple(
				"audio/x-raw-float",
				"rate", GST_TYPE_INT_RANGE, 1, G_MAXINT,
				"channels", G_TYPE_INT, 1,
				"endianness", G_TYPE_INT, G_BYTE_ORDER,
				"width", G_TYPE_INT, 64,
				NULL
			)
		)
	);

	gst_element_class_add_pad_template(
		element_class,
		gst_pad_template_new(
			"src",
			GST_PAD_SRC,
			GST_PAD_ALWAYS,
			gst_caps_new_simple(
				"audio/x-raw-float",
				"rate", GST_TYPE_INT_RANGE, 1, G_MAXINT,
				"channels", G_TYPE_INT, 1,
				"endianness", G_TYPE_INT, G_BYTE_ORDER,
				"width", G_TYPE_INT, 64,
				NULL
			)
		)
	);
}


/*
 * Class init function.  See
 *
 * http://developer.gnome.org/doc/API/2.0/gobject/gobject-Type-Information.html#GClassInitFunc
 */


static void class_init(gpointer class, gpointer class_data)
{
	GObjectClass *gobject_class = G_OBJECT_CLASS(class);

	parent_class = g_type_class_ref(GST_TYPE_ELEMENT);

	gobject_class->set_property = set_property;
	gobject_class->get_property = get_property;
	gobject_class->finalize = finalize;

	g_object_class_install_property(
		gobject_class,
		ARG_PSDMODE,
		g_param_spec_enum(
			"psd-mode",
			"PSD mode",
			"PSD estimation mode",
			GSTLAL_PSDMODE_TYPE,
			DEFAULT_PSDMODE,
			G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS
		)
	);
	g_object_class_install_property(
		gobject_class,
		ARG_ZERO_PAD_SECONDS,
		g_param_spec_double(
			"zero-pad",
			"Zero-padding",
			"Length of the zero-padding to include on both sides of the FFT in seconds",
			0, G_MAXDOUBLE, DEFAULT_ZERO_PAD_SECONDS,
			G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS
		)
	);
	g_object_class_install_property(
		gobject_class,
		ARG_FFT_LENGTH,
		g_param_spec_double(
			"fft-length",
			"FFT length",
			"Total length of the FFT convolution in seconds",
			0, G_MAXDOUBLE, DEFAULT_FFT_LENGTH_SECONDS,
			G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS
		)
	);
	g_object_class_install_property(
		gobject_class,
		ARG_AVERAGE_SAMPLES,
		g_param_spec_uint(
			"average-samples",
			"Average samples",
			"Number of FFTs used in PSD average",
			1, G_MAXUINT, DEFAULT_AVERAGE_SAMPLES,
			G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS
		)
	);
	g_object_class_install_property(
		gobject_class,
		ARG_MEDIAN_SAMPLES,
		g_param_spec_uint(
			"median-samples",
			"Median samples",
			"Number of FFTs used in PSD median history",
			1, G_MAXUINT, DEFAULT_MEDIAN_SAMPLES,
			G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS
		)
	);
	g_object_class_install_property(
		gobject_class,
		ARG_DELTA_F,
		g_param_spec_double(
			"delta-f",
			"Delta f",
			"PSD frequency resolution in Hz",
			0, G_MAXDOUBLE, 0,
			G_PARAM_READABLE | G_PARAM_STATIC_STRINGS
		)
	);
	g_object_class_install_property(
		gobject_class,
		ARG_PSD,
		g_param_spec_value_array(
			"psd",
			"PSD",
			"Power spectral density (first bin is at 0 Hz, bin spacing is delta-f)",
			g_param_spec_double(
				"bin",
				"Bin",
				"Power spectral density bin",
				-G_MAXDOUBLE, G_MAXDOUBLE, 1.0,
				G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS
			),
			G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS
		)
	);
}


/*
 * Instance init function.  See
 *
 * http://developer.gnome.org/doc/API/2.0/gobject/gobject-Type-Information.html#GInstanceInitFunc
 */


static void instance_init(GTypeInstance * object, gpointer class)
{
	GSTLALWhiten *element = GSTLAL_WHITEN(object);
	GstPad *pad;

	gst_element_create_all_pads(GST_ELEMENT(element));

	/* configure sink pad */
	pad = gst_element_get_static_pad(GST_ELEMENT(element), "sink");
	gst_pad_set_getcaps_function(pad, getcaps);
	gst_pad_set_setcaps_function(pad, setcaps);
	gst_pad_set_event_function(pad, sink_event);
	gst_pad_set_chain_function(pad, chain);
	gst_object_unref(pad);

	/* retrieve (and ref) src pad */
	element->srcpad = gst_element_get_static_pad(GST_ELEMENT(object), "src");

	/* internal data */
	element->adapter = gst_adapter_new();
	element->next_is_discontinuity = FALSE;
	element->t0 = GST_CLOCK_TIME_NONE;
	element->offset0 = GST_BUFFER_OFFSET_NONE;
	element->next_offset_in = GST_BUFFER_OFFSET_NONE;
	element->next_offset_out = GST_BUFFER_OFFSET_NONE;
	element->zero_pad_seconds = DEFAULT_ZERO_PAD_SECONDS;
	element->fft_length_seconds = DEFAULT_FFT_LENGTH_SECONDS;
	element->psdmode = DEFAULT_PSDMODE;
	element->sample_units = lalDimensionlessUnit;
	element->sample_rate = 0;
	element->window = NULL;
	element->fwdplan = NULL;
	element->revplan = NULL;
	element->psd_regressor = XLALPSDRegressorNew(DEFAULT_AVERAGE_SAMPLES, DEFAULT_MEDIAN_SAMPLES);
	element->psd = NULL;
	element->tdworkspace = NULL;
	element->fdworkspace = NULL;
	element->tail = NULL;
}


/*
 * gstlal_whiten_get_type().
 */


GType gstlal_whiten_get_type(void)
{
	static GType type = 0;

	if(!type) {
		static const GTypeInfo info = {
			.class_size = sizeof(GSTLALWhitenClass),
			.class_init = class_init,
			.base_init = base_init,
			.instance_size = sizeof(GSTLALWhiten),
			.instance_init = instance_init,
		};
		type = g_type_register_static(GST_TYPE_ELEMENT, "lal_whiten", &info, 0);
	}

	return type;
}
