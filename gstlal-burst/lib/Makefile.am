pkginclude_HEADERS = gstlal_snglburst.h
pkgconfig_DATA = gstlal-burst.pc
lib_LTLIBRARIES = libgstlalburst.la

libgstlalburst_la_SOURCES = gstlal_snglburst.h gstlal_snglburst.c
libgstlalburst_la_CFLAGS = $(AM_CFLAGS) $(LAL_CFLAGS) $(GSTLAL_CFLAGS) $(gstreamer_CFLAGS)
libgstlalburst_la_LDFLAGS = -version-info $(LIBVERSION) $(AM_LDFLAGS) $(LAL_LIBS) $(GSTLAL_LIBS) $(gstreamer_LIBS)
