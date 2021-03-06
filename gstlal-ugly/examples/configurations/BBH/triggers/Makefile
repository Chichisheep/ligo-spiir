# Misc useful definitions
empty:=
space:= $(empty) $(empty)
comma:= ,

# controls triggers
IFOS = H1 H2 L1
START = 869500000
STOP =  869510000
PSD_FILE = ../bank/reference_psd.xml.gz
BANK_CACHE_PREFIX = ../bank/
BANK_CACHE_SUFFIX = _bank.cache
# the point of this is to build the string e.g. H1=../bank/H1_bank.cache,L1=../bank/L1_bank.cache 
BANK_CACHE_STRING:= $(addprefix $(BANK_CACHE_PREFIX),$(IFOS))
BANK_CACHE_STRING:= $(addprefix =,$(BANK_CACHE_STRING))
BANK_CACHE_STRING:= $(addsuffix $(BANK_CACHE_SUFFIX),$(BANK_CACHE_STRING))
BANK_CACHE_STRING:= $(join $(IFOS),$(BANK_CACHE_STRING))
BANK_CACHE_STRING:= $(strip $(BANK_CACHE_STRING))
BANK_CACHE_STRING:= $(subst $(space),$(comma),$(BANK_CACHE_STRING))

CLUSTER_SQL = ../bank/simplify_and_cluster.sql
INJ_CLUSTER_SQL = ../bank/inj_simplify_and_cluster.sql
WEBDIR = /home/channa/public_html/BBH
NUMBANKS = 3

# Segments file names
segments_suffix := _segmentspadded.xml
SEGMENTS_FILES  := $(addsuffix $(segments_suffix),$(IFOS))

# Vetoes file names
vetoes_suffix := _vetoes.xml
VETOES_FILES  := $(addsuffix $(vetoes_suffix),$(IFOS))

# Frame cache file names
frame_suffix      := _frame.cache
FRAME_CACHE_FILES := $(addsuffix $(frame_suffix),$(IFOS))

# Injections
# The seed is the string before the suffix _injections.xml
# Change as appropriate, whitespace is important
INJECTIONS := 1_injections.xml 2_injections.xml 3_injections.xml
injections:=--injections $(space)
INJECTION_LIST := $(subst $(space), $(injections), $(INJECTIONS))
MIN_DIST = 10000
MAX_DIST = 200000
MIN_MASS1 = 10
MAX_MASS1 = 100
MIN_MASS2 = 10
MAX_MASS2 = 100
MIN_TOTAL_MASS = 20
MAX_TOTAL_MASS = 200
FLOW = 39
TRIM = 16

all : dag

plots :
	mkdir plots
	mkdir $(WEBDIR)

tisi.xml :
	ligolw_tisi --instrument=H1=0:0:0 --instrument=H2=0:0:0 --instrument=L1=0:3.14159:3.14159 tisi.xml

dag : vetoes.xml segments.xml frame.cache tisi.xml plots $(INJECTIONS)
	gstlal_s5_pbh_trigger_pipe --gps-start-time $(START) --gps-stop-time $(STOP) --reference-psd $(PSD_FILE) --frame-cache frame.cache --frame-segments-file segments.xml --frame-segments-name datasegments  --vetoes vetoes.xml --control-peak-time 4 --num-banks $(NUMBANKS) --fir-stride 4 --cluster-sql-file $(CLUSTER_SQL) --injection-sql-file $(INJ_CLUSTER_SQL) --web-dir $(WEBDIR) --time-slide-file tisi.xml $(INJECTION_LIST) --bank-cache $(BANK_CACHE_STRING)

%_vetoes.xml:
	ligolw_segment_query --segment-url=https://metaserver.phy.syr.edu -q --gps-start-time ${START} --gps-end-time ${STOP} --include-segments=$*:Injection --result-name=vetoes > $@
	ligolw_segments_compat $@

%_segmentspadded.xml:
	ligolw_segment_query --segment-url=https://metaserver.phy.syr.edu -q --gps-start-time ${START} --gps-end-time ${STOP} --include-segments=$*:Science --result-name=datasegments > $*segments.xml
	ligolw_segments_compat $*segments.xml
	gstlal_segments_trim $*segments.xml --trim $(TRIM) --output $@

vetoes.xml: $(VETOES_FILES)
	ligolw_add $(VETOES_FILES) > vetoes.xml

%_frame.cache:
	#FIXME horrible hack to get the observatory, not guaranteed to work
	$(eval OBS:=$*)
	$(eval OBS:=$(subst 1,$(empty),$(OBS)))
	$(eval OBS:=$(subst 2,$(empty),$(OBS)))
	ligo_data_find -o $(OBS) -t $*_RDS_C03_L2 -l  -s $(START) -e $(STOP) --url-type file > $@

frame.cache: $(FRAME_CACHE_FILES)
	cat $(FRAME_CACHE_FILES) > frame.cache

segments.xml: $(SEGMENTS_FILES)
	ligolw_add --output segments.xml $(SEGMENTS_FILES)
	ligolw_cut --delete-column segment:segment_def_cdb --delete-column segment:creator_db --delete-column segment_definer:insertion_time segments.xml

%_injections.xml: 
	lalapps_inspinj \
		--output $@ \
		--seed $* \
		--f-lower 10 \
		--gps-start-time $(START) \
		--gps-end-time $(STOP) \
		--t-distr uniform \
		--time-step 100 \
		--time-interval 20 \
		--i-distr uniform \
		--l-distr random \
		--d-distr log10 \
		--min-distance $(MIN_DIST) \
		--max-distance $(MAX_DIST) \
		--m-distr componentMass \
		--min-mass1 $(MIN_MASS1) \
		--max-mass1 $(MAX_MASS1) \
		--min-mass2 $(MIN_MASS2) \
		--max-mass2 $(MAX_MASS2) \
		--min-mtotal $(MIN_TOTAL_MASS) \
		--max-mtotal $(MAX_TOTAL_MASS) \
		--waveform  EOBNRpseudoFourPN \
		--taper-injection start \
		--disable-spin

realclean :
	rm -r *.sub *.dag* *.cache *.sh logs *.xml *.gz *.sqlite plots $(WEBDIR) *.html Images *.css *.js
