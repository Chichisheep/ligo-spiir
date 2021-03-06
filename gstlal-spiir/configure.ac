#
# Preamble
#


AC_INIT([gstlal-spiir],[0.9.1],[spiir-discuss@ligo.org],[gstlal-spiir])
AC_COPYRIGHT([Copyright (C) 2017 Qi Chu])
# a file whose existance can be used to use to check that we are in the
# top-level directory of the source tree
AC_CONFIG_SRCDIR([gnuscripts/ltmain.sh])
AC_CONFIG_AUX_DIR([gnuscripts])
AC_CONFIG_MACRO_DIR([gnuscripts])
AM_INIT_AUTOMAKE([1.9 tar-ustar foreign])
AUTOMAKE_OPTIONS="${AUTOMAKE_OPTIONS} --add-missing --copy"
AC_CONFIG_FILES([ \
	Makefile \
	gstlal-spiir.spec \
	debian/control \
	debian/Makefile \
	python/Makefile \
	python/pipemodules/Makefile \
	python/pipemodules/postcohtable/Makefile \
	python/spiirbank/Makefile \
	python/workflow/Makefile \
	lib/Makefile \
	bin/Makefile \
	gst/Makefile \
	gst/cuda/Makefile
])


#
# Split package version
#


AX_GSTLAL_SPLIT_VERSION([PACKAGE_VERSION])
AC_SUBST([PACKAGE_VERSION_MAJOR])
AC_SUBST([PACKAGE_VERSION_MINOR])
AC_SUBST([PACKAGE_VERSION_POINT])


#
# Move headers into a versioned sub-directory to allow more than one set of
# headers to be installed system-wide.  (commented out until this is
# needed)
#


#AC_SUBST([includedir],["\${includedir}/\${PACKAGE}-\${PACKAGE_VERSION}"])


#
# Extra directories
#


AC_SUBST([docdir], ["\${datadir}/doc"])
AC_SUBST([pkgdocdir], ["\${docdir}/\${PACKAGE_NAME}-\${PACKAGE_VERSION}"])
AC_SUBST([pkgconfigdir],["\${libdir}/pkgconfig"])


#
# force /usr/share/ package files into same directory as gstlal
#


AC_SUBST([pkgdatadir],["\${datadir}/gstlal"])


#
# Set the library API info
#
#  0.0.0   Original version
#  1.0.0   0.2.0 release (sngl_burst.h api changed)


AC_SUBST([LIBAPI], [1])
AC_SUBST([LIBREL], [0])
AC_SUBST([LIBAGE], [0])
AC_SUBST([LIBVERSION], [${LIBAPI}:${LIBREL}:${LIBAGE}])


#
# Check for programs
#

# check for c99 compiler
m4_pattern_allow([AC_PROG_CC_C99])
m4_ifdef([AC_PROG_CC_C99],[AC_PROG_CC_C99],[LALSUITE_AC_PROG_CC_C99])

AC_PROG_CXX
AC_PROG_INSTALL
# libtool incorrectly determines library path on SL6.  FIXME:  remove when
# no longer needed
case `cat /etc/redhat-release 2> /dev/null` in
  "Scientific Linux"*|"CentOS"*)
    AC_MSG_NOTICE([hacking round broken libtool multilib support on RedHat systems])
    lt_cv_sys_lib_dlsearch_path_spec="/lib64 /usr/lib64"
    ;;
esac
LT_INIT
PKG_PROG_PKG_CONFIG()

MIN_DOXYGEN_VERSION="1.8.3"
GSTLAL_DOXYGEN([$MIN_DOXYGEN_VERSION])
AM_CONDITIONAL([COND_DOXYGEN], [test "x$HAVE_DOXYGEN" == "xyes"])
AC_SUBST([MIN_DOXYGEN_VERSION])


#
# Check for Python
#


MIN_PYTHON_VERSION="2.6"
AM_PATH_PYTHON(["$MIN_PYTHON_VERSION"],,)
AX_PYTHON_DEVEL()
# hack to remove default lib dirs from PYTHON_LDFLAGS.  only tested on
# Debian and SL6.  FIXME:  find a way to do this properly
PYTHON_LDFLAGS="`echo $PYTHON_LDFLAGS | sed -e 'sX-L/usr/lib\(64\)\?\(/\)\?[[:space:]]*XXg'`"
# hack to add missing options to PYTHON_LDFLAGS.  sigh, what's the point of
# AX_PYTHON_DEVEL!?
PYTHON_LDFLAGS="-module -avoid-version $PYTHON_LDFLAGS"
AC_SUBST([MIN_PYTHON_VERSION])
# force python modules into same directory as gstlal
AC_SUBST([pkgpythondir], ["\${pythondir}/gstlal"])
AC_SUBST([pkgpyexecdir], ["\${pyexecdir}/gstlal"])


#
# CFLAGS
#


AX_CFLAGS_WARN_ALL([AM_CFLAGS])
AM_CFLAGS="$AM_CFLAGS -Wextra -Wno-missing-field-initializers -Wno-unused-parameter"	# extra gcc-specific stuff
AC_SUBST([AM_CFLAGS])


#
# LDFLAGS
#


# Turn on error messages for undefined symbols
AM_LDFLAGS="$AM_LDFLAGS -no-undefined"
AC_SUBST([AM_LDFLAGS])


#
# Check for math library
#


AC_CHECK_LIB([m], [main], , [AC_MSG_ERROR([Not found!])])


#
# Check for FFTW
#


PKG_CHECK_MODULES([FFTW], [fftw3 fftw3f])
AC_SUBST([FFTW_CFLAGS])
AC_SUBST([FFTW_LIBS])
AC_DEFINE([GSTLAL_FFTW_WISDOM_ENV], ["GSTLAL_FFTW_WISDOM"], [Set to the name of the environment variable to use for overriding the system-wide double-precision FFTW wisdom file])
AC_DEFINE([GSTLAL_FFTWF_WISDOM_ENV], ["GSTLAL_FFTWF_WISDOM"], [Set to the name of the environment variable to use for overriding the system-wide single-precision FFTW wisdom file])



#
# Check for GStreamer
#


AC_SUBST([GSTREAMER_RELEASE], [0.10])
AC_SUBST([MIN_GSTREAMER_VERSION], [0.10.32])
PKG_CHECK_MODULES([gstreamer], [gstreamer-${GSTREAMER_RELEASE} >= ${MIN_GSTREAMER_VERSION} gstreamer-base-${GSTREAMER_RELEASE} >= ${MIN_GSTREAMER_VERSION}])
AC_SUBST([gstreamer_CFLAGS])
AC_SUBST([gstreamer_LIBS])
AC_SUBST([plugindir], [${libdir}/gstreamer-${GSTREAMER_RELEASE}])
AC_MSG_NOTICE([If you have chosen to install the software in a location not included in your default gstreamer plugin search path, you might need to add the directory

	$plugindir
	
to your GST_PLUGIN_PATH environment variable.])
AC_SUBST([GSTLAL_PLUGIN_LDFLAGS], ["-module -avoid-version -export-symbols-regex [_]*\(gst_\|Gst\|GST_\|gstlal_\|GstLAL_\|GSTLAL_\).*"])

# Check for availability of GstBaseParse class (starting in 0.10.33)
CFLAGS_saved="$CFLAGS"
CFLAGS="$gstreamer_CFLAGS"
AC_COMPILE_IFELSE(
	[AC_LANG_PROGRAM([#include <gst/base/gstbaseparse.h>])],
	[HAVE_GSTBASEPARSE=yes
	AC_DEFINE([HAVE_GST_BASEPARSE], [1], [Define if GstBaseParse class is available.])],
	[HAVE_GSTBASEPARSE=no]
)
CFLAGS="$CFLAGS_saved"
AM_CONDITIONAL([COND_GSTBASEPARSE], [test "x${HAVE_GSTBASEPARSE}" == "xyes"])


#
# Check for GStreamer Video Library
#


AC_SUBST([GSTREAMER_VIDEO_RELEASE], [0.10])
AC_SUBST([MIN_GSTREAMER_VIDEO_VERSION], [0.10.32])
PKG_CHECK_MODULES([gstreamer_video], [gstreamer-video-${GSTREAMER_VIDEO_RELEASE} >= ${MIN_GSTREAMER_VIDEO_VERSION}])
AC_SUBST([gstreamer_video_CFLAGS])
AC_SUBST([gstreamer_video_LIBS])


#
# Check for GStreamer Audio Library
#


AC_SUBST([GSTREAMER_AUDIO_RELEASE], [0.10])
AC_SUBST([MIN_GSTREAMER_AUDIO_VERSION], [0.10.32])
PKG_CHECK_MODULES([gstreamer_audio], [gstreamer-audio-${GSTREAMER_AUDIO_RELEASE} >= ${MIN_GSTREAMER_AUDIO_VERSION}])
AC_SUBST([gstreamer_audio_CFLAGS])
AC_SUBST([gstreamer_audio_LIBS])


#
# Check for NumPy
#


AX_PYTHON_MODULE(numpy, fatal)
NUMPY_CFLAGS=-I`$PYTHON -c "import numpy;print (numpy.get_include());"`
old_CFLAGS="$CFLAGS"
CFLAGS="$CFLAGS ${PYTHON_CPPFLAGS} ${NUMPY_CFLAGS}"
AC_CHECK_HEADER([numpy/arrayobject.h],
	[PYTHON_CPPFLAGS="${PYTHON_CPPFLAGS} ${NUMPY_CFLAGS}"],
	[AC_MSG_ERROR([Numpy extension header not found])],
	[#include "Python.h"])
CFLAGS="$old_CFLAGS"



#
# Check for LAL
#


AC_SUBST([MIN_LAL_VERSION], [6.15.0])
AC_SUBST([MIN_LALMETAIO_VERSION], [1.2.6])
PKG_CHECK_MODULES([LAL], [lal >= ${MIN_LAL_VERSION} lalmetaio >= ${MIN_LALMETAIO_VERSION} lalsupport])
AC_SUBST([LAL_CFLAGS])
AC_SUBST([LAL_LIBS])

AX_PYTHON_MODULE([lal], fatal)


#
# Check for glue
#


AC_SUBST([MIN_GLUE_VERSION], [1.49])
AX_PYTHON_GLUE()


#
# Check for gstlal
#


AC_SUBST([MIN_GSTLAL_VERSION], [0.10.0])
PKG_CHECK_MODULES([GSTLAL], [gstlal >= ${MIN_GSTLAL_VERSION}])
AC_SUBST([GSTLAL_VERSION], [`$PKG_CONFIG --modversion gstlal`])
AX_GSTLAL_SPLIT_VERSION([GSTLAL_VERSION])
AC_SUBST([GSTLAL_VERSION_MAJOR])
AC_SUBST([GSTLAL_VERSION_MINOR])
AC_SUBST([GSTLAL_VERSION_POINT])
AC_SUBST([GSTLAL_CFLAGS])
AC_SUBST([GSTLAL_LIBS])

#
# Check for GSL
#


PKG_CHECK_MODULES([GSL], [gsl])
AC_SUBST([GSL_CFLAGS])
AC_SUBST([GSL_LIBS])


#
# Check for CUDA
#


AC_ARG_WITH(
	[cuda],
	[AS_HELP_STRING([--with-cuda], [specify location of CUDA [/usr/local/cuda]])],
	[],
	[with_cuda=no]
)
AS_IF([test "x$with_cuda" != "xno"], [
	AS_IF([test "x$build_cpu" = "xx86_64"], [
		CLIBS="lib64"
	], [
		CLIBS="lib"
	])
	AC_SUBST([NVCC], ["${with_cuda}/bin/nvcc"])
	AC_SUBST([NVCC_CFLAGS], ["-I${with_cuda}/include"])
	PKG_CHECK_MODULES([GLIB], [glib-2.0])
	AC_SUBST([NVCC_GSTLAL_CFLAGS], [$GLIB_CFLAGS])
	AC_SUBST([NVCC_LAL_CFLAGS], ["$($PKG_CONFIG --cflags-only-I lal)"])
	AC_SUBST([NVCC_gstreamer_CFLAGS], ["$($PKG_CONFIG --cflags-only-I gstreamer-0.10)"])
	AC_SUBST([NVCC_LIBS], ["-L${with_cuda}/$CLIBS -lcudart"])
	HAVE_CUDA="yes"
], [
	AC_MSG_WARN([check for cuda disabled])
	HAVE_CUDA="no"
])
AC_DEFINE([HAVE_CUDA], [test "x${HAVE_CUDA}" == "xyes"], [Defined if you have cuda])
AM_CONDITIONAL([COND_CUDA], [test "x${HAVE_CUDA}" == "xyes"])

AC_MSG_CHECKING([complex support in nvcc])
AS_IF([printf "#include <complex.h>\n int main(int argc, char **argv){complex double c; return 0;}" | ${with_cuda}/bin/nvcc -o /dev/null --compile --x cu - 2>/dev/null], [
	      AC_MSG_RESULT([yes])
], [
	      AC_MSG_RESULT([no (working around)])
	      AC_SUBST([SPIIR_FIX_COMPLEX_CFLAGS], ["-DSPIIR_FIX_COMPLEX"])])



#
# Check for lapacke vs openblas
#
AC_CHECK_LIB([lapacke], [LAPACKE_dgetrf], [
			AC_SUBST([LAPACKE_CFLAGS], ["-DSPIIR_HAVE_LAPACKE"])
			AC_SUBST([LAPACKE_LIBS], ["-llapacke"])
], [
			AC_SUBST([LAPACKE_CFLAGS], ["$($PKG_CONFIG --cflags openblas)"])
			AC_SUBST([LAPACKE_LIBS], ["$($PKG_CONFIG --libs openblas)"])
], [-llapack])


#
# Check for cython
#
AC_CHECK_PROG(have_cython, cython, yes)
AS_IF([test x"$have_cython" != x"yes"], [
	    AC_MSG_ERROR([Cython not found.])])



#
# Check for Chealpix
#


PKG_CHECK_MODULES([CHEALPIX], [chealpix], [true], [false])
AC_SUBST([CHEALPIX_CFLAGS])
AC_SUBST([CHEALPIX_LIBS])


#
# Check for libxml2
#
PKG_CHECK_MODULES([XML], [libxml-2.0], [true], [false])
AC_SUBST([XML_CFLAGS])
AC_SUBST([XML_LIBS])

#
# custom cflags and libs
#
GSTLAL_SPIIR_CFLAGS="-I\$(top_srcdir)/include -I\$(top_srcdir)/lib/include"
GSTLAL_SPIIR_LIBS="-L\$(top_srcdir)/lib -lgstlalspiir"
AC_SUBST([GSTLAL_SPIIR_CFLAGS])
AC_SUBST([GSTLAL_SPIIR_LIBS])
#
# Output configure information
#


AC_PROG_MAKE_SET
AC_OUTPUT
