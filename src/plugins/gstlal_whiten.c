/*
 * PSD Estimation and whitener
 *
 * Copyright (C) 2008  Kipp Cannon, Chad Hanna
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


/*
 * stuff from gstreamer
 */


#include <gst/gst.h>
#include <gst/base/gstadapter.h>


/*
 * stuff from LAL
 */


#include <lal/LALDatatypes.h>
#include <lal/LALStdlib.h>
#include <lal/Date.h>
#include <lal/TimeSeries.h>
#include <lal/FrequencySeries.h>
#include <lal/TimeFreqFFT.h>
#include <lal/LALNoiseModels.h>
#include <lal/Units.h>
#include <lal/LALComplex.h>


/*
 * our own stuff
 */


#include <gstlal_whiten.h>


/*
 * ============================================================================
 *
 *                                 Parameters
 *
 * ============================================================================
 */


#define DEFAULT_FILTER_LENGTH 8.0
#define DEFAULT_CONVOLUTION_LENGTH 64.0
#define DEFAULT_AVERAGE_SAMPLES 16
#define DEFAULT_PSDMODE GSTLAL_PSDMODE_INITIAL_LIGO_SRD


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
			{GSTLAL_PSDMODE_INITIAL_LIGO_SRD, "GSTLAL_PSDMODE_INITIAL_LIGO_SRD", "Use Initial LIGO SRD for PSD"},
			{GSTLAL_PSDMODE_RUNNING_AVERAGE, "GSTLAL_PSDMODE_RUNNING_AVERAGE", "Use running average for PSD"},
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


static LALUnit lalStrainSquaredPerHertz(void)
{
	LALUnit unit;

	return *XLALUnitMultiply(&unit, XLALUnitSquare(&unit, &lalStrainUnit), &lalSecondUnit);
}


static int make_fft_plans(GSTLALWhiten *element)
{
	unsigned fft_length = trunc(element->convolution_length * element->sample_rate + 0.5);

	XLALDestroyREAL8FFTPlan(element->fwdplan);
	XLALDestroyREAL8FFTPlan(element->revplan);

	element->fwdplan = XLALCreateForwardREAL8FFTPlan(fft_length, 1);
	element->revplan = XLALCreateReverseREAL8FFTPlan(fft_length, 1);

	if(!element->fwdplan || !element->revplan) {
		GST_ERROR("failure creating FFT plans");
		XLALDestroyREAL8FFTPlan(element->fwdplan);
		XLALDestroyREAL8FFTPlan(element->revplan);
		element->fwdplan = NULL;
		element->revplan = NULL;
		return -1;
	}

	return 0;
}


static int get_psd(GSTLALWhiten *element)
{
	LIGOTimeGPS gps_zero = {0, 0};
	LALUnit strain_squared_per_hertz = lalStrainSquaredPerHertz();
	unsigned segment_length = trunc(element->convolution_length * element->sample_rate + 0.5);
	unsigned psd_length = segment_length / 2 + 1;
	unsigned i;

	XLALDestroyREAL8FrequencySeries(element->psd);
	element->psd = NULL;

	switch(element->psdmode) {
	case GSTLAL_PSDMODE_INITIAL_LIGO_SRD:
		element->psd = XLALCreateREAL8FrequencySeries("PSD", &gps_zero, 0.0, 1.0 / element->convolution_length, &strain_squared_per_hertz, psd_length);
		if(!element->psd) {
			GST_ERROR("XLALCreateREAL8FrequencySeries() failed");
			return -1;
		}
		for(i = 0; i < element->psd->data->length; i++)
			element->psd->data->data[i] = XLALLIGOIPsd(element->psd->f0 + i * element->psd->deltaF);
		break;

	case GSTLAL_PSDMODE_RUNNING_AVERAGE:
		/* FIXME */
		return -1;
	}

	return 0;
}


static int make_filter(GSTLALWhiten *element)
{
	unsigned segment_length = trunc(element->convolution_length * element->sample_rate + 0.5);

	XLALDestroyREAL8FrequencySeries(element->filter);
	element->filter = XLALCutREAL8FrequencySeries(element->psd, 0, element->psd->data->length);
	if(!element->filter) {
		GST_ERROR("XLALCutREAL8FrequencySeries() failed");
		return -1;
	}
	if(XLALREAL8SpectrumInvertTruncate(element->filter, 0, segment_length, trunc(element->filter_length * element->sample_rate + 0.5), element->fwdplan, element->revplan)) {
		GST_ERROR("XLALREAL8SpectrumInvertTruncate() failed");
		XLALDestroyREAL8FrequencySeries(element->filter);
		element->filter = NULL;
		return -1;
	}

	return 0;
}


/*
 * ============================================================================
 *
 *                                  The Guts
 *
 * ============================================================================
 */


/*
 * Properties
 */


enum property {
	ARG_PSDMODE = 1,
	ARG_FILTER_LENGTH,
	ARG_CONVOLUTION_LENGTH,
	ARG_AVERAGE_SAMPLES
};


static void set_property(GObject * object, enum property id, const GValue * value, GParamSpec * pspec)
{

	GSTLALWhiten *element = GSTLAL_WHITEN(object);

	switch (id) {
	case ARG_PSDMODE:
		element->psdmode = g_value_get_enum(value);
		break;

	case ARG_FILTER_LENGTH:
		element->filter_length = g_value_get_double(value);
		break;

	case ARG_CONVOLUTION_LENGTH:
		element->convolution_length = g_value_get_double(value);
		break;

	case ARG_AVERAGE_SAMPLES:
		XLALPSDRegressorFree(element->psd_regressor);
		element->psd_regressor = XLALPSDRegressorNew(g_value_get_int(value));
		break;
	}
}


static void get_property(GObject * object, enum property id, GValue * value, GParamSpec * pspec)
{
	GSTLALWhiten *element = GSTLAL_WHITEN(object);

	switch (id) {
	case ARG_PSDMODE:
		g_value_set_enum(value, element->psdmode);
		break;

	case ARG_FILTER_LENGTH:
		g_value_set_double(value, element->filter_length);
		break;

	case ARG_CONVOLUTION_LENGTH:
		g_value_set_double(value, element->convolution_length);
		break;

	case ARG_AVERAGE_SAMPLES:
		g_value_set_int(value, element->psd_regressor->max_samples);
		break;
	}
}


/*
 * setcaps()
 */


static gboolean setcaps(GstPad *pad, GstCaps *caps)
{
	GSTLALWhiten *element = GSTLAL_WHITEN(gst_pad_get_parent(pad));
	gboolean result = TRUE;

	element->sample_rate = g_value_get_int(gst_structure_get_value(gst_caps_get_structure(caps, 0), "rate"));

	result = gst_pad_set_caps(element->srcpad, caps);

	gst_object_unref(element);
	return result;
}


/*
 * chain()
 */


static GstFlowReturn chain(GstPad *pad, GstBuffer *sinkbuf)
{
	GSTLALWhiten *element = GSTLAL_WHITEN(gst_pad_get_parent(pad));
	GstCaps *caps = gst_buffer_get_caps(sinkbuf);
	GstFlowReturn result = GST_FLOW_OK;
	gboolean is_discontinuity = FALSE;
	unsigned segment_length = trunc(element->convolution_length * element->sample_rate + 0.5);
	unsigned transient = trunc(element->filter_length * element->sample_rate + 0.5);
	REAL8TimeSeries *segment = NULL;
	COMPLEX16FrequencySeries *tilde_segment = NULL;

	/*
	 * Make sure we've got FFT plans
	 */

	if(!element->fwdplan || !element->revplan) {
		if(make_fft_plans(element)) {
			result = GST_FLOW_ERROR;
			goto done;
		}
	}

	/*
	 * Make sure we've got a PSD
	 */

	if(!element->psd) {
		if(get_psd(element)) {
			result = GST_FLOW_ERROR;
			goto done;
		}
		if(make_filter(element)) {
			result = GST_FLOW_ERROR;
			goto done;
		}
	} else {
		/* FIXME: add code to update the PSD in the moving average
		 * case */
	}

	/*
	 * Create holding area
	 */

	segment = XLALCreateREAL8TimeSeries(NULL, &(LIGOTimeGPS) {0, 0}, 0.0, (double) 1.0 / element->sample_rate, &lalStrainUnit, segment_length);
	tilde_segment = XLALCreateCOMPLEX16FrequencySeries(NULL, &(LIGOTimeGPS) {0, 0}, 0.0, element->filter->deltaF, &lalDimensionlessUnit, element->filter->data->length);
	if(!segment || !tilde_segment) {
		GST_ERROR("failure creating holding area");
		result = GST_FLOW_ERROR;
		goto done;
	}

	/*
	 * If incoming buffer is a discontinuity, clear the adapter and
	 * reset the clock
	 */

	if(GST_BUFFER_IS_DISCONT(sinkbuf)) {
		is_discontinuity = TRUE;
		gst_adapter_clear(element->adapter);
		element->adapter_head_timestamp = GST_BUFFER_TIMESTAMP(sinkbuf);
	}

	/*
	 * Iterate over the available data
	 */

	gst_adapter_push(element->adapter, sinkbuf);

	while(gst_adapter_available(element->adapter) / sizeof(*segment->data->data) >= segment_length) {
		GstBuffer *srcbuf;
		unsigned i;

		/*
		 * Copy data from adapter into holding area
		 */

		memcpy(segment->data->data, gst_adapter_peek(element->adapter, segment_length * sizeof(*segment->data->data)), segment_length * sizeof(*segment->data->data));

		/*
		 * Transform to frequency domain
		 */

		if(XLALREAL8TimeFreqFFT(tilde_segment, segment, element->fwdplan)) {
			GST_ERROR("XLALREAL8TimeFreqFFT() failed");
			result = GST_FLOW_ERROR;
			goto done;
		}

		/*
		 * FIXME:  update averaging PSD estimator here
		 */

		/*
		 * Multiply by filter
		 */

		for(i = 0; i < tilde_segment->data->length; i++)
			tilde_segment->data->data[i] = XLALCOMPLEX16MulReal(tilde_segment->data->data[i], element->filter->data->data[i]);

		/*
		 * Transform to time domain
		 */

		if(XLALREAL8FreqTimeFFT(segment, tilde_segment, element->revplan)) {
			GST_ERROR("XLALREAL8FreqTimeFFT() failed");
			result = GST_FLOW_ERROR;
			goto done;
		}

		/*
		 * Get a buffer from the downstream peer (note the size is
		 * smaller than the holding area by two filter transients)
		 */

		result = gst_pad_alloc_buffer(element->srcpad, element->next_sample, (segment_length - 2 * transient) * sizeof(*segment->data->data), GST_PAD_CAPS(element->srcpad), &srcbuf);
		if(result != GST_FLOW_OK)
			goto done;
		if(is_discontinuity) {
			GST_BUFFER_FLAG_SET(srcbuf, GST_BUFFER_FLAG_DISCONT);
			is_discontinuity = FALSE;
		}
		GST_BUFFER_OFFSET_END(srcbuf) = GST_BUFFER_OFFSET(srcbuf) + segment_length - 1;
		GST_BUFFER_TIMESTAMP(srcbuf) = element->adapter_head_timestamp + transient * GST_SECOND / element->sample_rate;
		GST_BUFFER_DURATION(srcbuf) = (GstClockTime) (segment_length - 2 * transient) * GST_SECOND / element->sample_rate;

		/*
		 * Copy data into it, removing the filter transient from
		 * the start and end
		 */

		memcpy(GST_BUFFER_DATA(srcbuf), &segment->data->data[transient], (segment_length - 2 * transient) * sizeof(*segment->data->data));

		/*
		 * Push the buffer downstream
		 */

		result = gst_pad_push(element->srcpad, srcbuf);
		if(result != GST_FLOW_OK)
			goto done;

		/*
		 * Flush the adapter and advance the sample count and
		 * adapter clock
		 */

		gst_adapter_flush(element->adapter, (segment_length - 2 * transient) * sizeof(*segment->data->data));
		element->next_sample += segment_length - 2 * transient;
		element->adapter_head_timestamp += (GstClockTime) (segment_length - 2 * transient) * GST_SECOND / element->sample_rate;
	}

	/*
	 * Done
	 */

done:
	XLALDestroyREAL8TimeSeries(segment);
	XLALDestroyCOMPLEX16FrequencySeries(tilde_segment);
	gst_caps_unref(caps);
	gst_object_unref(element);
	return result;
}


/*
 * Parent class.
 */


static GstElementClass *parent_class = NULL;


/*
 * Instance dispose function.  See ???
 */


static void dispose(GObject * object)
{
	GSTLALWhiten *element = GSTLAL_WHITEN(object);

	g_object_unref(element->adapter);
	element->adapter = NULL;
	gst_object_unref(element->srcpad);
	element->srcpad = NULL;
	XLALDestroyREAL8FFTPlan(element->fwdplan);
	XLALDestroyREAL8FFTPlan(element->revplan);
	XLALPSDRegressorFree(element->psd_regressor);
	XLALDestroyREAL8FrequencySeries(element->psd);
	XLALDestroyREAL8FrequencySeries(element->filter);

	G_OBJECT_CLASS(parent_class)->dispose(object);
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
		"Kipp Cannon <kcannon@ligo.caltech.edu>, Chan Hanna <chann@ligo.caltech.edu>"
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
	gobject_class->dispose = dispose;

	g_object_class_install_property(gobject_class, ARG_PSDMODE, g_param_spec_enum("psd-mode", "PSD mode", "PSD estimation mode", GSTLAL_PSDMODE_TYPE, DEFAULT_PSDMODE, G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
	g_object_class_install_property(gobject_class, ARG_FILTER_LENGTH, g_param_spec_double("filter-length", "Filter length", "Length of the whitening filter in seconds", 0, G_MAXDOUBLE, DEFAULT_FILTER_LENGTH, G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
	g_object_class_install_property(gobject_class, ARG_CONVOLUTION_LENGTH, g_param_spec_double("convolution-length", "Convolution length", "Length of the FFT convolution in seconds", 0, G_MAXDOUBLE, DEFAULT_CONVOLUTION_LENGTH, G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
	g_object_class_install_property(gobject_class, ARG_AVERAGE_SAMPLES, g_param_spec_int("average-samples", "Average samples", "Number of convolution-length intervals used in PSD average", 1, G_MAXINT, DEFAULT_AVERAGE_SAMPLES, G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
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
	gst_pad_set_setcaps_function(pad, setcaps);
	gst_pad_set_chain_function(pad, chain);
	gst_object_unref(pad);

	/* retrieve (and ref) src pad */
	element->srcpad = gst_element_get_static_pad(GST_ELEMENT(object), "src");

	/* internal data */
	element->adapter = gst_adapter_new();
	element->next_sample = 0;
	element->adapter_head_timestamp = 0;
	element->filter_length = DEFAULT_FILTER_LENGTH;
	element->convolution_length = DEFAULT_CONVOLUTION_LENGTH;
	element->psdmode = DEFAULT_PSDMODE;
	element->sample_rate = 0;
	element->fwdplan = NULL;
	element->revplan = NULL;
	element->psd_regressor = XLALPSDRegressorNew(DEFAULT_AVERAGE_SAMPLES);
	element->psd = NULL;
	element->filter = NULL;
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
