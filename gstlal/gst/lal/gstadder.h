/* GStreamer
 * Copyright (C) 1999,2000 Erik Walthinsen <omega@cse.ogi.edu>
 *                    2000 Wim Taymans <wtay@chello.be>
 *
 * gstadder.h: Header for GstAdder element
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

#ifndef __GST_ADDER_H__
#define __GST_ADDER_H__

#include <gst/gst.h>
#include <gst/base/gstcollectpads.h>

G_BEGIN_DECLS

#define GST_TYPE_ADDER            (gstlal_adder_get_type())
#define GST_ADDER(obj)            (G_TYPE_CHECK_INSTANCE_CAST((obj),GST_TYPE_ADDER,GstLALAdder))
#define GST_IS_ADDER(obj)         (G_TYPE_CHECK_INSTANCE_TYPE((obj),GST_TYPE_ADDER))
#define GST_ADDER_CLASS(klass)    (G_TYPE_CHECK_CLASS_CAST((klass) ,GST_TYPE_ADDER,GstLALAdderClass))
#define GST_IS_ADDER_CLASS(klass) (G_TYPE_CHECK_CLASS_TYPE((klass) ,GST_TYPE_ADDER))
#define GST_ADDER_GET_CLASS(obj)  (G_TYPE_INSTANCE_GET_CLASS((obj) ,GST_TYPE_ADDER,GstLALAdderClass))

typedef struct _GstLALAdder             GstLALAdder;
typedef struct _GstLALAdderClass        GstLALAdderClass;
typedef struct _GstLALAdderInputChannel GstLALAdderInputChannel;

typedef enum {
  GST_ADDER_FORMAT_UNSET,
  GST_ADDER_FORMAT_INT,
  GST_ADDER_FORMAT_FLOAT,
  GST_ADDER_FORMAT_COMPLEX
} GstAdderFormat;

typedef void (*GstAdderFunction) (gpointer out, gpointer in, guint size);

/**
 * GstAdder:
 *
 * The adder object structure.
 */
struct _GstLALAdder {
  GstElement      element;

  GstPad         *srcpad;
  GstCollectPads *collect;
  /* pad counter, used for creating unique request pads */
  gint            padcount;

  /* the next are valid for both int and float */
  GstAdderFormat  format;
  gint            rate;
  gint            channels;
  gint            width;
  gint            endianness;
  int             sample_size;

  /* the next are valid only for format == GST_ADDER_FORMAT_INT */
  gint            depth;
  gboolean        is_signed;

  /* number of bytes per sample, actually width/8 * channels */
  gint            bps;

  /* function to add samples */
  GstAdderFunction func;

  /* counters to keep track of timestamps */
  GstClockTime    timestamp;
  guint64         offset;
  gboolean        synchronous;

  /* sink event handling */
  GstPadEventFunction  collect_event;
  GstSegment      segment;
  gboolean        segment_pending;
  /* src event handling */
  gboolean        flush_stop_pending;
  
  /* target caps */
  GstCaps *filter_caps;

  /* Pending inline events */
  GList *pending_events;
};

struct _GstLALAdderClass {
  GstElementClass parent_class;
};

GType    gstlal_adder_get_type (void);

G_END_DECLS


#endif /* __GST_ADDER_H__ */
