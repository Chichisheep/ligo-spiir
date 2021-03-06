etime=1012071168
start=$(shell python -c "print ${etime} - 50")
end=$(shell python -c "print ${etime} + 50")
duration=$(shell echo "${end}-${start}" | bc)
outfile=HLV-triggers-${start}-${duration}.xml.gz
blocksize=$(shell echo "512*8*16384" | bc)

coincidence: cluster
	ligolw_tisi -i H1=0:0:1 -i L1=0:0:1 -i V1=0:0:1 >| HLV_ZERO_LAG_SLIDES.xml.gz
	ligolw_add HLV_ZERO_LAG_SLIDES.xml.gz ${outfile} -o ${outfile}
	ligolw_burca --coincidence-algorithm excesspower -t H1,L1=0 -t H1,V1=0 -t V1,L1=0 --verbose ${outfile}

cluster: ${outfile}
	ligolw_bucluster --verbose --cluster-algorithm excesspower --program gstlal_excesspower ${outfile}

${outfile}: v1_ep h1_ep l1_ep
	find H1_FAKE_STRAIN -name "*.xml" | lalapps_path2cache -a > triggers.cache
	find L1_FAKE_STRAIN -name "*.xml" | lalapps_path2cache -a >> triggers.cache
	find V1_FAKE_STRAIN -name "*.xml" | lalapps_path2cache -a >> triggers.cache
	ligolw_add --input-cache triggers.cache --output ${outfile} --verbose 
	rm -rf triggers.cache

caches: l1.cache h2.cache v1.cache

l1.cache:
	ligo_data_find -o L -t L1_DMT_ERHOFT -s ${start} -e ${end}  -u file -l > l1.cache
	mkdir -p L1_FAKE_STRAIN
h1.cache:
	ligo_data_find -o H -t H1H2_DMT_ERHOFT -s ${start} -e ${end} -u file -l > h1.cache
	mkdir -p H1_FAKE_STRAIN
h2.cache:
	ligo_data_find -o H -t H1H2_DMT_ERHOFT -s ${start} -e ${end} -u file -l > h2.cache
v1.cache:
	ligo_data_find -o V -t ER1_hoft -s ${start} -e ${end} -u file -l > v1.cache
	mkdir -p V1_FAKE_STRAIN

v1_ep: v1.cache
	# Note the *required* "site" entry in the ini file for Virgo
	gstlal_excesspower  \
		--verbose  \
		--data-source frames  \
		--frame-cache v1.cache \
		--channel-name V1=FAKE_h_16384Hz_4R \
		--initialization-file gstlal_excesspower_v1_hoft.ini  \
		--gps-start-time 1012071068 \
		--gps-end-time 1012071268 \
		--block-size ${blocksize} \
		--sample-rate 2048  
	mv V1-*xml  V1_FAKE_STRAIN/

h1_ep: h1.cache
	# Show off the new "query LDR if no cache is present" mechanism
	gstlal_excesspower  \
		--verbose  \
		--data-source frames  \
		--frame-cache h1.cache \
		--channel-name H1=FAKE-STRAIN \
		--initialization-file gstlal_excesspower_h1_hoft.ini  \
		--gps-start-time ${start} \
		--gps-end-time ${end} \
		--block-size ${blocksize} \
		--sample-rate 2048  
	mv H1-*xml H1_FAKE_STRAIN/

l1_ep: l1.cache
	gstlal_excesspower  \
		--verbose  \
		--data-source frames  \
		--frame-cache l1.cache \
		--channel-name L1=FAKE-STRAIN \
		--initialization-file gstlal_excesspower_l1_hoft.ini  \
		--gps-start-time ${start} \
		--gps-end-time ${end} \
		--block-size ${blocksize} \
		--sample-rate 2048  
	mv L1-*xml L1_FAKE_STRAIN/

clean:
	rm -rf *.xml *.xml.gz *.cache *_FAKE_STRAIN

