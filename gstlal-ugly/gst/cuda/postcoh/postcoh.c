/* 
 * Copyright (C) 2014 Qi Chu <qi.chu@ligo.org>
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Library General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Library General Public License for more details.
 *
 * You should have received a copy of the GNU Library General Public
 * License along with this library; if not, write to the
 * Free Software Foundation, Inc., 59 Temple Place - Suite 330,
 * Boston, MA 02111-1307, USA.
 */

/* This element will synchronize the snr sequencies from all detectors, find 
 * peaks from all detectors and for each peak, do null stream analysis.
 */


#include <gst/gst.h>
#include <lal/Date.h>
#include <lal/LIGOMetadataTables.h>

#include <string.h>
#include "postcoh.h"
#include "postcoh_utils.h"

#define GST_CAT_DEFAULT gstlal_postcoh_debug
GST_DEBUG_CATEGORY_STATIC(GST_CAT_DEFAULT);

#define DEFAULT_DETRSP_FNAME "L1H1V1_detrsp.xml"
gchar IFO_MAP[][2] = {"L1", "H1", "V1"};

static void additional_initializations(GType type)
{
	GST_DEBUG_CATEGORY_INIT(GST_CAT_DEFAULT, "cuda_postcoh", 0, "cuda_postcoh element");
}


GST_BOILERPLATE_FULL(
	CudaPostcoh,
	cuda_postcoh,
	GstElement,
	GST_TYPE_ELEMENT,
	additional_initializations
);

//FIXME: not support width=64 yet
static GstStaticPadTemplate cuda_postcoh_sink_template =
GST_STATIC_PAD_TEMPLATE (
		"%s",
		GST_PAD_SINK, 
		GST_PAD_REQUEST, 
		GST_STATIC_CAPS(
		"audio/x-raw-float, " \
		"rate = (int) [1, MAX], " \
		"channels = (int) [1, MAX], " \
		"endianness = (int) BYTE_ORDER, " \
		"width = (int) 32"
		));

static GstStaticPadTemplate cuda_postcoh_src_template =
GST_STATIC_PAD_TEMPLATE (
		"src",
		GST_PAD_SRC, 
		GST_PAD_ALWAYS, 
		GST_STATIC_CAPS(
		"audio/x-raw-float, " \
		"rate = (int) [1, MAX], " \
		"channels = (int) [1, MAX], " \
		"endianness = (int) BYTE_ORDER, " \
		"width = (int) 32"
		));



enum 
{
	PROP_0,
	PROP_DETRSP_FNAME,
	PROP_AUTOCORRELATION_FNAME
};


static void cuda_postcoh_set_property(GObject *object, guint id, const GValue *value, GParamSpec *pspec)
{
	CudaPostcoh *element = CUDA_POSTCOH(object);

	GST_OBJECT_LOCK(element);
	switch(id) {
		case PROP_DETRSP_FNAME:
			element->detrsp_fname = g_value_dup_string(value);
			cuda_postcoh_map_from_xml(element->detrsp_fname, element->state);
			break;

		case PROP_AUTOCORRELATION_FNAME: 
			element->autocorrelation_fname = g_value_dup_string(value);
			break;

		default:
			G_OBJECT_WARN_INVALID_PROPERTY_ID(object, id, pspec);
			break;
	}
	GST_OBJECT_UNLOCK(element);
}


static void cuda_postcoh_get_property(GObject * object, guint id, GValue * value, GParamSpec * pspec)
{
	CudaPostcoh *element = CUDA_POSTCOH(object);

	GST_OBJECT_LOCK(element);
	switch(id) {
		case PROP_DETRSP_FNAME:
			g_value_set_string(value, element->detrsp_fname);
			break;

		case PROP_AUTOCORRELATION_FNAME:
			g_value_set_string(value, element->autocorrelation_fname);
			break;

		default:
			G_OBJECT_WARN_INVALID_PROPERTY_ID(object, id, pspec);
			break;
	}
	GST_OBJECT_UNLOCK(element);
}

static void set_offset_per_nanosecond(GstPostcohCollectData *data, double offset_per_nanosecond)
{
	data->offset_per_nanosecond = offset_per_nanosecond;

}

static void set_channels(GstPostcohCollectData *data, gint channels)
{
	data->channels = channels;

}

static void set_aligned_offset0(GstPostcohCollectData *data, guint64 offset)
{
	data->aligned_offset0 = offset;

}

static gboolean
sink_event(GstPad *pad, GstEvent *event)
{
	GstPostcohCollectData *data = gst_pad_get_element_private(pad);
	switch(GST_EVENT_TYPE(event)) {
		case GST_EVENT_NEWSEGMENT:
			GST_DEBUG_OBJECT(pad, "new segment");
			break;
		default:
			break;
	}
	return TRUE;
}

/* This is copied from gstadder.c 0.10.32 */
static gboolean
cuda_postcoh_sink_setcaps(GstPad *pad, GstCaps *caps)
{
	CudaPostcoh *postcoh = CUDA_POSTCOH(GST_PAD_PARENT(pad));
	GList *sinkpads;
	GstStructure *s;
	GstPostcohCollectData *data;

	/* FIXME: this is copied from gstadder.c. Replace with new version of that file
	 * if any. */
	GST_OBJECT_LOCK(postcoh);
//	sinkpads = GST_ELEMENT(postcoh)->sinkpads;
	sinkpads = GST_ELEMENT(postcoh)->pads;

	GST_LOG_OBJECT(postcoh, "setting caps on pad %p,%s to %" GST_PTR_FORMAT, pad,
			GST_PAD_NAME(pad), caps);

	while (sinkpads) {
		GstPad *otherpad = GST_PAD(sinkpads->data);

		if (otherpad != pad) {
			gst_caps_replace(&GST_PAD_CAPS(otherpad), caps);
		}
		sinkpads = g_list_next(sinkpads);
	}
	GST_OBJECT_UNLOCK(postcoh);

	s = gst_caps_get_structure(caps, 0);
	gst_structure_get_int(s, "width", &postcoh->width);
	gst_structure_get_int(s, "rate", &postcoh->rate);
	gst_structure_get_int(s, "channels", &postcoh->channels);


	postcoh->bps = (postcoh->width/8) * postcoh->channels;	
	postcoh->offset_per_nanosecond = postcoh->bps / 1e9 * (postcoh->rate);	

	PostcohState *state = postcoh->state;
	state->nifo = GST_ELEMENT(postcoh)->numsinkpads;
	state->d_snglsnr = (COMPLEX_F **)malloc(sizeof(COMPLEX_F *)* state->nifo);
	state->ifo_mapping = (gint8 *)malloc(sizeof(gint8) * state->nifo);
	state->peak_list = (PeakList **)malloc(sizeof(PeakList*) * state->nifo);
	state->npeak = (int *)malloc(sizeof(int) * state->nifo);

	/* need to cover head and tail */
	postcoh->preserved_size = 2 * postcoh->autocorrelation_len * postcoh->bps; 
	postcoh->exe_size = postcoh->rate * postcoh->bps;

	state->ntmplt = postcoh->channels/2;
	state->head_len = postcoh->autocorrelation_len;
	state->exe_len = postcoh->rate;

	GST_DEBUG_OBJECT(postcoh, "setting GstPostcohCollectData offset_per_nanosecond %f and channels", postcoh->offset_per_nanosecond);
	gint8 i = 0, j = 0;
	GST_OBJECT_LOCK(postcoh->collect);
	for (sinkpads = GST_ELEMENT(postcoh)->sinkpads; sinkpads; sinkpads = g_list_next(sinkpads), i++) {
		GstPad *pad = GST_PAD(sinkpads->data);
		data = gst_pad_get_element_private(pad);
		set_offset_per_nanosecond(data, postcoh->offset_per_nanosecond);
		set_channels(data, postcoh->channels);
		for (j=0; j<state->nifo; j++) {
			if (strncmp(data->ifo_name, IFO_MAP[j], 2) == 0 )
				state->ifo_mapping[i] = j;
		}
		guint mem_alloc_size = postcoh->preserved_size + postcoh->exe_size;
		cudaMalloc((void **) & (state->d_snglsnr[i]), mem_alloc_size);
		cudaMemset(state->d_snglsnr[i], 0, mem_alloc_size);

		cudaMalloc((void **) &(state->peak_list[i]->sample_index), sizeof(int) * postcoh->rate);
		cudaMemset(state->peak_list[i]->sample_index, 0, sizeof(int) * postcoh->rate);
		cudaMalloc((void **) &(state->peak_list[i]->tmplt_index), sizeof(int) * postcoh->rate);
		cudaMemset(state->peak_list[i]->tmplt_index, 0, sizeof(int) * postcoh->rate);
		cudaMalloc((void **) &(state->peak_list[i]->maxsnr), sizeof(float) * postcoh->rate);
		cudaMemset(state->peak_list[i]->maxsnr, 0, sizeof(float) * postcoh->rate);

	}
	GST_OBJECT_UNLOCK(postcoh->collect);
	return TRUE;
}

static void destroy_notify(GstPostcohCollectData *data)
{
	if (data) {
		free(data->ifo_name);
		if (data->adapter) {
			g_object_unref(data->adapter);
			data->adapter = NULL;
		}
	}

}

static GstPad *cuda_postcoh_request_new_pad(GstElement *element, GstPadTemplate *templ, const gchar *name)
{
	CudaPostcoh* postcoh = CUDA_POSTCOH(element);

	GstPad* newpad;
       	newpad = gst_pad_new_from_template(templ, name);

	gst_pad_set_setcaps_function(GST_PAD(newpad), GST_DEBUG_FUNCPTR(cuda_postcoh_sink_setcaps));

	if (!gst_element_add_pad(element, newpad)) {
		gst_object_unref(newpad);
		return NULL;
	}

	GstPostcohCollectData* data;
       	data = (GstPostcohCollectData*) gst_collect_pads_add_pad_full(postcoh->collect, newpad, sizeof(GstPostcohCollectData), (GstCollectDataDestroyNotify) GST_DEBUG_FUNCPTR(destroy_notify));
	gst_pad_set_event_function(newpad, sink_event);

	if (!data) {
		gst_element_remove_pad(element, newpad);
		gst_object_unref(newpad);
		return NULL;
	}

	data->ifo_name = (gchar *)malloc(2*sizeof(gchar));
	strncpy(data->ifo_name, name, 2*sizeof(gchar));
	data->adapter = gst_adapter_new();
	data->is_aligned = FALSE;
	data->aligned_offset0 = 0;
	GST_DEBUG_OBJECT(element, "new pad for %s is added and initialised", data->ifo_name);

	return GST_PAD(newpad);
}



static void cuda_postcoh_release_pad(GstElement *element, GstPad *pad)
{
	CudaPostcoh* postcoh = CUDA_POSTCOH(element);

	gst_collect_pads_remove_pad(postcoh->collect, pad);
	gst_element_remove_pad(element, pad);
}


static GstStateChangeReturn cuda_postcoh_change_state(GstElement *element, GstStateChange transition)
{
	CudaPostcoh *postcoh = CUDA_POSTCOH(element);

	switch(transition) {
	case GST_STATE_CHANGE_NULL_TO_READY:
		break;

	case GST_STATE_CHANGE_READY_TO_PAUSED:
		gst_collect_pads_start(postcoh->collect);
		break;

	case GST_STATE_CHANGE_PAUSED_TO_PLAYING:
		break;

	case GST_STATE_CHANGE_PAUSED_TO_READY:
		/* need to unblock the collectpads before calling the
		 * parent change_state so that streaming can finish */
		gst_collect_pads_stop(postcoh->collect);
		break;

	default:
		break;
	}

	return GST_ELEMENT_CLASS(parent_class)->change_state(element, transition);
}

static gboolean cuda_postcoh_get_latest_start_time(GstCollectPads *pads, GstClockTime *t_latest_start, guint64 *offset_latest_start)
{
	GSList *collectlist;
	GstPostcohCollectData *data;
	GstClockTime t_start_cur = GST_CLOCK_TIME_NONE;
	GstBuffer *buf;

	*t_latest_start = GST_CLOCK_TIME_NONE;

	/* invalid pads */
	g_return_val_if_fail(pads != NULL, FALSE);
	g_return_val_if_fail(GST_IS_COLLECT_PADS(pads), FALSE);

	for (collectlist = pads->data; collectlist; collectlist = g_slist_next(collectlist)) {
		data = collectlist->data;
		buf = gst_collect_pads_peek(pads, (GstCollectData *)data);
		/* eos */
		if(!buf) {
			GST_ERROR_OBJECT(pads, "%s pad:EOS", data->ifo_name);
			gst_buffer_unref(buf);
			return FALSE;
		}
		/* invalid offset */
		if(!GST_BUFFER_OFFSET_IS_VALID(buf) || !GST_BUFFER_OFFSET_END_IS_VALID(buf)) {
			GST_ERROR_OBJECT(pads, "%" GST_PTR_FORMAT ": %" GST_PTR_FORMAT " does not have valid offsets", ((GstCollectData *) data)->pad, buf);
			gst_buffer_unref(buf);
			return FALSE;
		}
		/* invalid timestamp */
		if(!GST_BUFFER_TIMESTAMP_IS_VALID(buf) || !GST_BUFFER_DURATION_IS_VALID(buf)) {
			GST_ERROR_OBJECT(pads, "%" GST_PTR_FORMAT ": %" GST_PTR_FORMAT " does not have a valid timestamp and/or duration", ((GstCollectData *) data)->pad, buf);
			gst_buffer_unref(buf);
			return FALSE;
		}

		t_start_cur = GST_BUFFER_TIMESTAMP(buf);

		if (*t_latest_start == GST_CLOCK_TIME_NONE) {
			*t_latest_start = t_start_cur;
			*offset_latest_start = GST_BUFFER_OFFSET(buf);
		} else {
			if (*t_latest_start < t_start_cur) {
				*t_latest_start = t_start_cur;
				*offset_latest_start = GST_BUFFER_OFFSET(buf);
			}
		}

	}
	return TRUE;
}

static gint cuda_postcoh_push_and_get_common_size(GstCollectPads *pads)
{
	GSList *collectlist;
	GstPostcohCollectData *data;
	GstBuffer *buf;

	gint min_size = 0, size_cur;
	gboolean min_size_init = FALSE;

	for (collectlist = pads->data; collectlist; collectlist = g_slist_next(collectlist)) {
			data = collectlist->data;
			buf = gst_collect_pads_pop(pads, (GstCollectData *)data);
			GST_LOG_OBJECT (data,
				"Push buffer to adapter of (%u bytes) with timestamp %" GST_TIME_FORMAT ", duration %"
				GST_TIME_FORMAT ", offset %" G_GUINT64_FORMAT ", offset_end %"
				G_GUINT64_FORMAT,  GST_BUFFER_SIZE (buf),
				GST_TIME_ARGS (GST_BUFFER_TIMESTAMP (buf)),
				GST_TIME_ARGS (GST_BUFFER_DURATION (buf)),
				GST_BUFFER_OFFSET (buf), GST_BUFFER_OFFSET_END (buf));

			gst_adapter_push(data->adapter, buf);
			size_cur = gst_adapter_available(data->adapter);
			if(!min_size_init) {
				min_size = size_cur;
				min_size_init = TRUE;
			} else {
				if (min_size > size_cur) {
					min_size = size_cur;
				}
			}

			
	}
	return min_size;
}
static gboolean cuda_postcoh_align_collected(GstCollectPads *pads, GstClockTime t0)
{
	GSList *collectlist;
	GstPostcohCollectData *data;
	GstBuffer *buf, *subbuf;
	GstClockTime t_start_cur, t_end_cur;
	gboolean all_aligned = TRUE;
	guint64 offset_cur, offset_end_cur, aligned_offset0;

	GST_DEBUG_OBJECT(pads, "begin to align offset0");

	for (collectlist = pads->data; collectlist; collectlist = g_slist_next(collectlist)) {
		data = collectlist->data;
		GST_DEBUG_OBJECT(pads, "now at %s is aligned %d", data->ifo_name, data->is_aligned);
		if (data->is_aligned) {
			buf = gst_collect_pads_pop(pads, (GstCollectData *)data);
			gst_adapter_push(data->adapter, buf);
			continue;
		}
		buf = gst_collect_pads_peek(pads, (GstCollectData *)data);
		t_start_cur = GST_BUFFER_TIMESTAMP(buf);
		t_end_cur = t_start_cur + GST_BUFFER_DURATION(buf);
		offset_cur = GST_BUFFER_OFFSET(buf);
		offset_end_cur = GST_BUFFER_OFFSET_END(buf);
		if (t_end_cur > t0) {
			aligned_offset0 = gst_util_uint64_scale_int(GST_CLOCK_DIFF(t0, t_start_cur), data->offset_per_nanosecond, 1);
			GST_DEBUG_OBJECT(data, "aligned offset0 %u", aligned_offset0);
			subbuf = gst_buffer_create_sub(buf, (aligned_offset0 - offset_cur), (offset_end_cur - aligned_offset0) * data->channels * sizeof(float));
			GST_LOG_OBJECT (pads,
				"Created sub buffer of (%u bytes) with timestamp %" GST_TIME_FORMAT ", duration %"
				GST_TIME_FORMAT ", offset %" G_GUINT64_FORMAT ", offset_end %"
				G_GUINT64_FORMAT,  GST_BUFFER_SIZE (subbuf),
				GST_TIME_ARGS (GST_BUFFER_TIMESTAMP (subbuf)),
				GST_TIME_ARGS (GST_BUFFER_DURATION (subbuf)),
				GST_BUFFER_OFFSET (subbuf), GST_BUFFER_OFFSET_END (subbuf));
			gst_adapter_push(data->adapter, subbuf);
			data->is_aligned = TRUE;
			set_aligned_offset0(data, aligned_offset0);
			/* discard this buffer in collectpads so it can collect new one */
			gst_buffer_unref(buf);
		} else {
			all_aligned = FALSE;
		}
	}

	return all_aligned;
		
	

}
static void cuda_postcoh_flush(GstCollectPads *pads, guint64 common_size)
{
	GSList *collectlist;
	GstPostcohCollectData *data;

	for (collectlist = pads->data; collectlist; collectlist = g_slist_next(collectlist)) {
		data = collectlist->data;
		gst_adapter_flush(data->adapter, common_size);
	}

}

static GstBuffer* cuda_postcoh_new_buffer(CudaPostcoh *postcoh, gint out_len)
{
	GstBuffer *outbuf;
	GstPad *srcpad = postcoh->srcpad;
	GstCaps *caps = GST_PAD_CAPS(srcpad);
	GstFlowReturn ret;
	guint out_size = out_len * postcoh->bps;
	ret = gst_pad_alloc_buffer(srcpad, 0, out_size, caps, &outbuf);
	if (ret != GST_FLOW_OK) {
		GST_ERROR_OBJECT(srcpad, "Could not allocate postcoh-inspiral buffer %d", ret);
		return NULL;
	}
        /* set the time stamps */
        GST_BUFFER_TIMESTAMP(outbuf) = postcoh->out_t0 + gst_util_uint64_scale_int_round(postcoh->samples_out, GST_SECOND,
		       	postcoh->rate);
        GST_BUFFER_DURATION(outbuf) = (GstClockTime) gst_util_uint64_scale_int_round(GST_SECOND, out_len, postcoh->rate);

	/* set the offset */
        GST_BUFFER_OFFSET(outbuf) = postcoh->out_offset0 + postcoh->samples_out;
        GST_BUFFER_OFFSET_END(outbuf) = GST_BUFFER_OFFSET(outbuf) + out_len;

	GST_LOG_OBJECT (srcpad,
		"Processed of (%u bytes) with timestamp %" GST_TIME_FORMAT ", duration %"
		GST_TIME_FORMAT ", offset %" G_GUINT64_FORMAT ", offset_end %"
		G_GUINT64_FORMAT,  GST_BUFFER_SIZE (outbuf),
		GST_TIME_ARGS (GST_BUFFER_TIMESTAMP (outbuf)),
		GST_TIME_ARGS (GST_BUFFER_DURATION (outbuf)),
		GST_BUFFER_OFFSET (outbuf), GST_BUFFER_OFFSET_END (outbuf));

	return outbuf;
}

static void cuda_postcoh_process(GstCollectPads *pads, gint one_take_size, gint exe_size, CudaPostcoh *postcoh)
{
	GSList *collectlist;
	GstPostcohCollectData *data;
	COMPLEX_F *snglsnr, *one_d_snglsnr;

	int i = 0;
	PostcohState *state = postcoh->state;
	for (collectlist = pads->data; collectlist; collectlist = g_slist_next(collectlist), i++) {
		data = collectlist->data;
		snglsnr = (COMPLEX_F *) gst_adapter_peek(data->adapter, one_take_size);
		one_d_snglsnr = state->d_snglsnr[state->ifo_mapping[i]];
		cudaMemcpy(one_d_snglsnr, snglsnr, one_take_size, cudaMemcpyHostToDevice);
		peakfinder(one_d_snglsnr, i, state);
		/* move along */
		gst_adapter_flush(data->adapter, exe_size);
	}



	gint out_len = exe_size / postcoh->bps;

	GstBuffer *outbuf;
	outbuf = cuda_postcoh_new_buffer(postcoh, out_len);

	/* move along */
	postcoh->samples_out += out_len;
}

static GstFlowReturn collected(GstCollectPads *pads, gpointer user_data)
{
	CudaPostcoh* postcoh = CUDA_POSTCOH(user_data);
	GstElement* element = GST_ELEMENT(postcoh);
	GstClockTime t_latest_start;
	GstFlowReturn res;
	guint64 offset_latest_start = 0;
	gint common_size; 

	GST_DEBUG_OBJECT(postcoh, "collected");
	/* Assure that we have enough sink pads. */
	if (element->numsinkpads < 2)
	{
		GST_ERROR_OBJECT(postcoh, "not enough sink pads, 2 required but only %d are present", element->numsinkpads < 2);
		return GST_FLOW_ERROR;
	}

	if (!postcoh->set_starttime) {
		/* get the latest timestamp */
		if (!cuda_postcoh_get_latest_start_time(pads, &t_latest_start, &offset_latest_start)) {
			/* bad buffer : one of the buffers is at EOS or invalid timestamp/ offset */
			GST_ERROR_OBJECT(postcoh, "cannot deduce start timestamp/ offset information");
			return GST_FLOW_ERROR;
		}
		postcoh->in_t0 = t_latest_start;
		postcoh->out_t0 = t_latest_start + gst_util_uint64_scale_int_round(
				postcoh->autocorrelation_len, GST_SECOND, postcoh->rate);
		postcoh->out_offset0 = offset_latest_start + postcoh->autocorrelation_len ;
		GST_DEBUG_OBJECT(postcoh, "set the aligned time to %" GST_TIME_FORMAT 
				", start offset to %" G_GUINT64_FORMAT, GST_TIME_ARGS(postcoh->in_t0),
				postcoh->out_offset0);
		postcoh->is_all_aligned = cuda_postcoh_align_collected(pads, postcoh->in_t0);
		postcoh->set_starttime = TRUE;
		return GST_FLOW_OK;
	}

	gint exe_size = postcoh->exe_size;
		
	if (postcoh->is_all_aligned) {
		common_size = cuda_postcoh_push_and_get_common_size(pads);
		GST_DEBUG_OBJECT(postcoh, "get spanned size %d", common_size);
		gint one_take_size = postcoh->preserved_size + exe_size;
		while (common_size >= one_take_size) {
			cuda_postcoh_process(pads, one_take_size, exe_size, postcoh);
			common_size -= exe_size;
		}
	} else {
		postcoh->is_all_aligned = cuda_postcoh_align_collected(pads, postcoh->in_t0);
	}
#if 0
	if (!GST_CLOCK_TIME_IS_VALID(t_start)) {
		/* eos */
		GST_DEBUG_OBJECT(postcoh, "no data available, must be EOS");
		res = gst_pad_push_event(postcoh->srcpad, gst_event_new_eos());
		return res;
	}
	GST_LOG_OBJECT(postcoh, "t end %", GST_TIME_FORMAT, t_end);
#endif
	return GST_FLOW_OK;
}


static void cuda_postcoh_dispose(GObject *object)
{
	CudaPostcoh *element = CUDA_POSTCOH(object);
	if(element->collect)
		gst_object_unref(GST_OBJECT(element->collect));
	element->collect = NULL;

	if(element->state->d_snglsnr[0]){
		for(int i=0; i<element->state->nifo; i++)
			cudaFree(element->state->d_snglsnr[i]);
	}
	if(element->srcpad)
		gst_object_unref(element->srcpad);
	element->srcpad = NULL;

	/* destroy hashtable and its contents */
	G_OBJECT_CLASS(parent_class)->dispose(object);
}


static void cuda_postcoh_base_init(gpointer g_class)
{
	GstElementClass *element_class = GST_ELEMENT_CLASS(g_class);

	gst_element_class_set_details_simple(
		element_class,
		"Post Coherent SNR and Nullstream Generator",
		"Filter",
		"Coherent trigger generation.\n",
		"Qi Chu <qi.chu at ligo dot org>"
	);
	gst_element_class_add_pad_template(
		element_class,
		gst_static_pad_template_get(&cuda_postcoh_sink_template)
	);

	gst_element_class_add_pad_template(
		element_class,
		gst_static_pad_template_get(&cuda_postcoh_src_template)
#if 0
		gst_pad_template_new(
			"src",
			GST_PAD_SRC,
			GST_PAD_ALWAYS,
			gst_caps_new_simple(
				"application/x-lal-postcohlinspiral" ,
				NULL
			)
		)
#endif
	);
}


static void cuda_postcoh_class_init(CudaPostcohClass *klass)
{
	GObjectClass *gobject_class = G_OBJECT_CLASS(klass);
	GstElementClass *gstelement_class = GST_ELEMENT_CLASS(klass);

	parent_class = g_type_class_ref(GST_TYPE_ELEMENT);

	gobject_class->get_property = GST_DEBUG_FUNCPTR(cuda_postcoh_get_property);
	gobject_class->set_property = GST_DEBUG_FUNCPTR(cuda_postcoh_set_property);
	gobject_class->dispose = GST_DEBUG_FUNCPTR(cuda_postcoh_dispose);
	gstelement_class->request_new_pad = GST_DEBUG_FUNCPTR(cuda_postcoh_request_new_pad);
	gstelement_class->release_pad = GST_DEBUG_FUNCPTR(cuda_postcoh_release_pad);
	gstelement_class->change_state = GST_DEBUG_FUNCPTR(cuda_postcoh_change_state);

	g_object_class_install_property(
		gobject_class,
		PROP_DETRSP_FNAME,
		g_param_spec_string(
			"detrsp-fname",
			"Detector response filename",
			"Should include U map and time_diff map",
			DEFAULT_DETRSP_FNAME,
			G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS
		)
	);

	g_object_class_install_property(
		gobject_class,
		PROP_AUTOCORRELATION_FNAME,
		g_param_spec_string(
			"autocorrelation-fname",
			"Autocorrelation matrix filename",
			"Autocorrelation matrix",
			NULL,
			G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS
		)
	);
			
}


static void cuda_postcoh_init(CudaPostcoh *postcoh, CudaPostcohClass *klass)
{
	GstElement *element = GST_ELEMENT(postcoh);

	gst_element_create_all_pads(element);
	postcoh->srcpad = gst_element_get_static_pad(element, "src");
	GST_DEBUG_OBJECT(postcoh, "%s caps %" GST_PTR_FORMAT, GST_PAD_NAME(postcoh->srcpad), gst_pad_get_caps(postcoh->srcpad));

	postcoh->collect = gst_collect_pads_new();
	gst_collect_pads_set_function(postcoh->collect, GST_DEBUG_FUNCPTR(collected), postcoh);

	postcoh->in_t0 = GST_CLOCK_TIME_NONE;
	postcoh->out_t0 = GST_CLOCK_TIME_NONE;
	postcoh->out_offset0 = GST_BUFFER_OFFSET_NONE;
	//postcoh->next_in_offset = GST_BUFFER_OFFSET_NONE;
	postcoh->set_starttime = FALSE;
	postcoh->is_all_aligned = FALSE;
	postcoh->autocorrelation_len = 100;
	postcoh->samples_in = 0;
	postcoh->samples_out = 0;
	postcoh->state = (PostcohState *) malloc (sizeof(PostcohState));

}


