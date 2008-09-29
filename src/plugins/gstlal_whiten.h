/*
 * PSD Estimation and whitener
 *
 * Copyright (C) 2008  Chad Hanna, Kipp Cannon
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


#ifndef __GSTLAL_WHITEN_H__
#define __GSTLAL_WHITEN_H__


#include <gst/gst.h>
#include <gst/base/gstadapter.h>


#include <gsl/gsl_spline.h>


#include <lal/LALDatatypes.h>
#include <lal/LIGOLwXML.h>
#include <lal/TimeFreqFFT.h>


G_BEGIN_DECLS


/*
 * gstlal_psdmode_t enum
 */


enum gstlal_psdmode_t {
	GSTLAL_PSDMODE_INITIAL_LIGO_SRD,
	GSTLAL_PSDMODE_RUNNING_AVERAGE
};


#define GSTLAL_PSDMODE_TYPE  \
	(gstlal_psdmode_get_type())


GType gstlal_psdmode_get_type(void);


/*
 * lal_whiten element
 */


#define GSTLAL_WHITEN_TYPE \
	(gstlal_whiten_get_type())
#define GSTLAL_WHITEN(obj) \
	(G_TYPE_CHECK_INSTANCE_CAST((obj), GSTLAL_WHITEN_TYPE, GSTLALWhiten))
#define GSTLAL_WHITEN_CLASS(klass) \
	(G_TYPE_CHECK_CLASS_CAST((klass), GSTLAL_WHITEN_TYPE, GSTLALWhitenClass))
#define GST_IS_GSTLAL_WHITEN(obj) \
	(G_TYPE_CHECK_INSTANCE_TYPE((obj), GSTLAL_WHITEN_TYPE))
#define GST_IS_GSTLAL_WHITEN_CLASS(klass) \
	(G_TYPE_CHECK_CLASS_TYPE((klass), GSTLAL_WHITEN_TYPE))


typedef struct {
	GstElementClass parent_class;
} GSTLALWhitenClass;


typedef struct {
	GstElement element;

	GstAdapter *adapter;

	GstPad *srcpad;

	int sample_rate;
	gboolean next_is_discontinuity;
	unsigned long next_sample;
	GstClockTime adapter_head_timestamp;

	double filter_length;
	double convolution_length;
	enum gstlal_psdmode_t psdmode;

	REAL8Window *window;
	REAL8FFTPlan *fwdplan;
	REAL8FFTPlan *revplan;
	LALPSDRegressor *psd_regressor;
	REAL8FrequencySeries *psd;
	REAL8Sequence *tail;

	char *xml_filename;
	LIGOLwXMLStream *xml_stream;

	char *compensation_psd_filename;
	REAL8FrequencySeries *compensation_psd;
} GSTLALWhiten;


GType gstlal_whiten_get_type(void);


G_END_DECLS


#endif	/* __GSTLAL_WHITEN_H__ */
