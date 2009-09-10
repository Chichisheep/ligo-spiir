/*
 * GStreamer
 * Copyright (C) 2005 Thomas Vander Stichele <thomas@apestaart.org>
 * Copyright (C) 2005 Ronald S. Bultje <rbultje@ronald.bitfreak.net>
 * Copyright (C) 2009 Mireia Crispin Ortuzar <<user@hostname.org>>
 * 
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
 * DEALINGS IN THE SOFTWARE.
 *
 * Alternatively, the contents of this file may be used under the
 * GNU Lesser General Public License Version 2.1 (the "LGPL"), in
 * which case the following provisions apply instead of the ones
 * mentioned above:
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

#ifndef __GST_LAL_AUTOCHISQ_H__
#define __GST_LAL_AUTOCHISQ_H__

#include <gst/gst.h>
#include <gst/base/gstadapter.h>
#include <gst/base/gstbasetransform.h>
#include "low_latency_inspiral_functions.h"

#include <gsl/gsl_matrix.h>
#include <gsl/gsl_vector.h>


G_BEGIN_DECLS

/* #defines don't like whitespacey bits */
#define GSTLAL_AUTOCHISQ_TYPE \
  (gstlal_autochisq_get_type())
#define GST_LAL_AUTOCHISQ(obj) \
  (G_TYPE_CHECK_INSTANCE_CAST((obj),GSTLAL_AUTOCHISQ_TYPE,Gstlalautochisq))
#define GST_LAL_AUTOCHISQ_CLASS(klass) \
  (G_TYPE_CHECK_CLASS_CAST((klass),GSTLAL_AUTOCHISQ_TYPE,GstlalautochisqClass))
#define GST_IS_LAL_AUTOCHISQ(obj) \
  (G_TYPE_CHECK_INSTANCE_TYPE((obj),GSTLAL_AUTOCHISQ_TYPE))
#define GST_IS_LAL_AUTOCHISQ_CLASS(klass) \
  (G_TYPE_CHECK_CLASS_TYPE((klass),GSTLAL_AUTOCHISQ_TYPE))

typedef struct _Gstlalautochisq      Gstlalautochisq;
typedef struct _GstlalautochisqClass GstlalautochisqClass;

struct _Gstlalautochisq
{
  GstBaseTransform element;

  char *reference_psd_filename;
  char *template_bank_filename; 
  int rate;
  int channels;
  double t_start;
  double t_end;
  double t_total_duration;

  gsl_matrix_complex *A;
  gsl_vector *norm;
  GstAdapter *adapter;
  gboolean adapter_is_empty;

  GstClockTime t0;
  guint64 offset0;
  guint64 next_in_offset;
  guint64 next_out_offset;
  gboolean need_discont;
};

struct _GstlalautochisqClass 
{
  GstBaseTransformClass parent_class;
};

GType gstlal_autochisq_get_type (void);

G_END_DECLS

#endif /* __GST_LAL_AUTOCHISQ_H__ */
