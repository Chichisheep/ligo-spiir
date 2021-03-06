#!/usr/bin/env python
#
# Copyright (c) 2013-2014 David McKenzie 
#
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

from pylal import spawaveform
import sys
import time
import numpy
import scipy
import math
from scipy import integrate
from scipy import interpolate
#from pylal import lalconstants
import pdb
import csv
import pdb
import random
import lalsimulation
import lal
import gc
import matplotlib.pyplot as pplot

from subprocess import call #not sure this is needed
from optparse import OptionParser
from multiprocessing import Pool #this is not actually used at the moment

from glue.ligolw import ligolw, lsctables, array, param, utils, types
from gstlal.pipeio import repack_complex_array_to_real, repack_real_array_to_complex
from pylal.series import read_psd_xmldoc

from gstlal import cbc_template_iir 
from gstlal import cbc_template_fir 
from gstlal import templates
class XMLContentHandler(ligolw.LIGOLWContentHandler):
	pass



#def sigmasq2(mchirp, fLow, fhigh, psd_interp):
#	c = lalconstants.LAL_C_SI #299792458
#	G = lalconstants.LAL_G_SI #6.67259e-11
#	M = lalconstants.LAL_MSUN_SI #1.98892e30
#	Mpc =1e6 * lalconstants.LAL_PC_SI #3.0856775807e22
#	#mchirp = 1.221567#30787
#	const = numpy.sqrt((5.0 * math.pi)/(24.*c**3))*(G*mchirp*M)**(5./6.)*math.pi**(-7./6.)/Mpc
#	return  const * numpy.sqrt(4.*integrate.quad(lambda x: x**(-7./3.) / psd_interp(x), fLow, fhigh)[0])


def calc_amp_phase(hc,hp):
    '''Given a specific hcross and hplus waveform, calculate the amplitude and phase of the waveform.
    Strictly speaking, only one of hp or hc is necessary but both are required by this function
    This function may be slightly deprecated and the one in cbc_template_iir should be used generally.'''
    amp = numpy.sqrt(hc*hc + hp*hp)
    phase = numpy.arctan2(hc,hp)
    
    #Unwind the phase
    #Based on the unwinding codes in pycbc
    #and the old LALSimulation interface
    count=0
    prevval = None
    phaseUW = phase 

    #Pycbc uses 2*PI*0.7 for some reason
    #We use the more conventional PI (more in line with MATLAB)
    thresh = lal.PI;
    for index, val in enumerate(phase):
	if prevval is None:
	    pass
	elif prevval - val >= thresh:
	    count = count+1
	elif val - prevval >= thresh:
	    count = count-1

	phaseUW[index] = phase[index] + count*lal.TWOPI
	prevval = val

    for index, val in enumerate(phase):
	    phaseUW[index] = phaseUW[index] - phaseUW[0]

    phase = phaseUW
    return amp,phase

### Sometimes there will be negative or very low (~~0) frequencies ###
### at the start or the end of f. Clean them up ###
### Do this by going up through the first and last n (say, 100) ###
### and recording where the first and last incorrect values are and set them appropriately ###
def cleanFreq(f,fLower):
    i = 0;
    fStartFix = 0; #So if f is 0, -1, -2, 15, -3 15 16 17 18 then this will be 4
    while(i< 100): #This should be enough
	if(f[i] < fLower-5 or f[i] > fLower+5):  ##Say, 5 or 10 Hz)
	    fStartFix = i;
	i=i+1;

    if(fStartFix != 0):
	f[0:fStartFix+1] = fLower

    i=-30;
    while(i<-1):
	#require monotonicity
	if(f[i]>f[i+1]):
	    f[i+1:]=fLower; #effectively throw away the end
	    break;
	else:
	    i=i+1;
#    print "fStartFix: %d i: %d " % (fStartFix, i)

def generate_waveform(m1,m2,dist,incl,fLower,fFinal,fRef,s1x,s1y,s1z,s2x,s2y,s2z,ampphase=1):
	sampleRate = 4096 #Should pass this but its a nontrivial find and replace
	hp,hc = lalsimulation.SimInspiralChooseTDWaveform(  0,					# reference phase, phi ref
		    				    1./sampleRate,			# delta T
						    m1*lal.MSUN_SI,			# mass 1 in kg
						    m2*lal.MSUN_SI,			# mass 2 in kg
						    s1x,s1y,s1z,			# Spin 1 x, y, z
						    s2x,s2y,s2z,			# Spin 2 x, y, z
						    fLower,				# Lower frequency
						    fRef,				# Reference frequency 40?
						    dist*1.e6*lal.PC_SI,		# r - distance in M (convert to MPc)
						    incl,				# inclination
						    0,0,				# Lambda1, lambda2
						    None,				# Waveflags
						    None,				# Non GR parameters
						    0,7,				# Amplitude and phase order 2N+1
						    lalsimulation.GetApproximantFromString("SpinTaylorT4"))
	if(ampphase==1):
	    return calc_amp_phase(hc.data.data, hp.data.data)
	else:
	    return hp,hc

def variable_parameter_comparison(xmldoc,psd_interp, outfile, param_name, param_lower, param_upper, param_num = 100,  input_mass1 = 1.4, input_mass2 = 1.4):

        '''
    VPC - Variable parameter comparison. Given a single parameter (alpha, beta or epsilon) compute, over the given range, the overlap between a template and associated SPIIR response of fixed mass (1.4-1.4)
	Keyword arguments:
	xmldoc		-- The XML document containing information about the template bank. Used to get the final frequency (not actually useful but contains other information that might be useful in the future)
	psd_interp	-- An interpolated power spectral density array. This is used to weight the signal and SPIIR response from the specifications of the LIGO/VIRGO instruments (combined)
	outfile		-- Where the output is written to
	param_name	-- String of which parameter to vary (alpha, beta, epsilon or spin (z-spin only))
	param_lower	-- The lower value of the varied parameter
	param_upper	-- The upper value of the varied parameter
	param_num	-- The number of steps to take between param_lower and param_upper
	input_mass1	-- The mass of the first body of the signal (default - canonical neutron star mass 1.4 M_sol)
	input_mass2	-- The mass of the second body of the signal (default - canonical neutron star mass 1.4 M_sol)

        ''' 
	fileName = outfile
        sngl_inspiral_table=lsctables.table.get_table(xmldoc, lsctables.SnglInspiralTable.tableName)
	fFinal = max(sngl_inspiral_table.getColumnByName("f_final"))
	fLower = 40 
	
	fileID = open(fileName,"w")
	fileID.write("snr param mass1 mass2 chirpmass numFilters \n") #clear the file
	fileID.close()

	#### Initialise constants ####
	sampleRate = 4096; padding=1.1; epsilon=0.02; alpha=.99; beta=0.25; spin=0;

	paramRange = numpy.linspace(param_lower,param_upper,num=param_num);
	
	dist=20; incl = 0;
	snr=0; m1B = 0; m2B = 0
	
	length = 2**23;

	u = numpy.zeros(length, dtype=numpy.cdouble)
	h = numpy.zeros(length, dtype=numpy.cdouble)

	matchReq = 0.975
	timing=False;
	
	timePerCompStart  = 0;
	timePerCompFin = 0;
	
	m1 = input_mass1; m2 = input_mass2;

	### We loop over parameters in the pbs function, to stop the memory leak breaking it all ###
	for paramValue in paramRange:
		if(param_name == 'epsilon' or param_name == 'eps' or param_name == 'e'):
		    epsilon = paramValue;
		elif(param_name == 'alpha' or param_name == 'a'):
		    alpha = paramValue;
		elif(param_name == 'beta' or param_name == 'b'):
		    beta = paramValue;
		elif(param_name == 'spin' or param_name == 's'):
		    spin = paramValue;
		

		mChirpSignal = (m1*m2)**(0.6)/(m1+m2)**(0.2);
		h.fill(0);
		u.fill(0);

		#### Generate signal, weight by PSD, normalise, take FFT ####
		amps,phis=generate_waveform(m1,m2,dist,incl,fLower,fFinal,0,0,0,spin,0,0,0)
		fs = numpy.gradient(phis)/(2.0*numpy.pi * (1.0/sampleRate))

		cleanFreq(fs,fLower)

		if psd_interp is not None:
		    amps[0:len(fs)] /= psd_interp(fs[0:len(fs)])**0.5
		amps = amps / numpy.sqrt(numpy.dot(amps,numpy.conj(amps)));
		h[-len(amps):] = amps * numpy.exp(1j*phis);
		h *= 1/numpy.sqrt(numpy.dot(h,numpy.conj(h)))
		h = numpy.conj(numpy.fft.fft(h))
	   
		#### Now do the IIR filter for the exact mass match ####

		amp,phase=generate_waveform(m1,m2,dist,incl,fLower,fFinal,0,0,0,0,0,0,0);
		f = numpy.gradient(phase)/(2.0*numpy.pi * (1.0/sampleRate))

		cleanFreq(f,fLower)

		if psd_interp is not None:
			amp[0:len(f)] /= psd_interp(f[0:len(f)])**0.5
		amp = amp / numpy.sqrt(numpy.dot(amp,numpy.conj(amp)));

		#### Get the IIR coefficients and respose ####
		a1, b0, delay = spawaveform.iir(amp, phase, epsilon, alpha, beta, padding)
		out = spawaveform.iirresponse(length, a1, b0, delay)
		out = out[::-1]
		u[-len(out):] = out;
		u *= 1/numpy.sqrt(numpy.dot(u,numpy.conj(u)))

		#http://www.mathworks.com/matlabcentral/answers/5275-algorithm-for-coeff-scaling-of-xcorr
		crossCorr = numpy.fft.ifft(numpy.fft.fft(u)*h);
		snr = numpy.abs(crossCorr).max();

		with open(fileName,"a") as fileID:
		    fileID.write("%f %f %f %f %f %f \n" % (snr, paramValue, m1, m2, mChirpSignal, len(a1)))
		    fileID.flush();

def parameter_comparison(xmldoc,psd_interp, outfile, param_name, param_value, input_minMass=1, input_maxMass=3, input_numSignals=50):

        '''
    PC - Parameter comparison. Takes a single parameter and value (e.g. eps=0.02). Generates a random waveform and computes the overlap with SPIIR sum/response function.
	Keyword arguments:
	xmldoc		    -- The XML document containing information about the template bank. Used to get the final frequency (not actually useful but contains other information that might be useful in the future)
	psd_interp	    -- An interpolated power spectral density array. This is used to weight the signal and SPIIR response from the specifications of the LIGO/VIRGO instruments (combined)
	outfile		    -- Where the output is written to
	param_name	    -- String of which parameter to vary (alpha, beta, epsilon or spin (z-spin only))
	param_value	    -- The value to assign to the given parameter
	input_minMass	    -- Randomly distribute signals between this and the maximum mass (default 1, lower mass for proposed aLIGO BNS search)
	input_maxMass	    -- Randomly distribute signals between the minimum mass and this (default 3, upper mass for proposed aLIGO BNS search)
	input_numSignals    -- How many signals to generate and search for (default 50)
        '''
	fileName = outfile
        sngl_inspiral_table=lsctables.table.get_table(xmldoc, lsctables.SnglInspiralTable.tableName)
	fFinal = max(sngl_inspiral_table.getColumnByName("f_final"))
	fLower = 10
	
	fileID = open(fileName,"w")
	fileID.write("snr param mass1 mass2 chirpmass numFilters \n") #clear the file
	fileID.close()

	#### Initialise constants ####
	sampleRate = 4096; padding=1.1; epsilon=0.02; alpha=.99; beta=0.25;

	if(param_name == 'epsilon' or param_name == 'eps' or param_name == 'e'):
	    epsilon = paramValue;
	elif(param_name == 'alpha' or param_name == 'a'):
	    alpha = paramValue;
	elif(param_name == 'beta' or param_name == 'b'):
	    beta = paramValue;

	
        minMass = input_minMass; maxMass = input_maxMass;
	dist=1; incl = 0;
	snr=0; m1B = 0; m2B = 0
	
	length = 2**23;

	u = numpy.zeros(length, dtype=numpy.cdouble)
	h = numpy.zeros(length, dtype=numpy.cdouble)

	matchReq = 0.97
	timing=False;
	
	timePerCompStart  = 0;
	timePerCompFin = 0;
	
	numSignals = 0; numSignalsTot = input_numSignals;
	### We loop over parameters in the pbs function, to stop the memory leak breaking it all ###
	#for s_m1 in numpy.linspace(minMass,maxMass,num=stepNumMass):
	#    for s_m2 in numpy.linspace(minMass, maxMass, num=stepNumMass):
	while numSignals < numSignalsTot:
		numSignals = numSignals + 1;
		s_m1 = random.uniform(minMass,maxMass);
		s_m2 = random.uniform(minMass,maxMass);
		mChirpSignal = (s_m1*s_m2)**(0.6)/(s_m1+s_m2)**(0.2);
		h.fill(0);
		u.fill(0);
		#### Generate signal, weight by PSD, normalise, take FFT ####
		amps,phis=generate_waveform(s_m1,s_m2,dist,incl,fLower,fFinal,0,0,0,0,0,0,0)
		fs = numpy.gradient(phis)/(2.0*numpy.pi * (1.0/sampleRate))
		
		cleanFreq(fs,fLower)
		if psd_interp is not None:
		    amps[0:len(fs)] /= psd_interp(fs[0:len(fs)])**0.5

		amps = amps / numpy.sqrt(numpy.dot(amps,numpy.conj(amps)));
		h[-len(amps):] = amps * numpy.exp(1j*phis);
		h *= 1/numpy.sqrt(numpy.dot(h,numpy.conj(h)))
		h = numpy.conj(numpy.fft.fft(h))
	   
		#### Now do the IIR filter for the exact mass match ####
		m1 = s_m1 
		m2 = s_m2

		amp,phase=generate_waveform(m1,m2,dist,incl,fLower,fFinal,0,0,0,0,0,0,0);
		f = numpy.gradient(phase)/(2.0*numpy.pi * (1.0/sampleRate))
		cleanFreq(f,fLower)
		if psd_interp is not None:
			amp[0:len(f)] /= psd_interp(f[0:len(f)])**0.5
		amp = amp / numpy.sqrt(numpy.dot(amp,numpy.conj(amp)));

		#### Get the IIR coefficients and respose ####
		a1, b0, delay = spawaveform.iir(amp, phase, epsilon, alpha, beta, padding)
		out = spawaveform.iirresponse(length, a1, b0, delay)
		out = out[::-1]
		u[-len(out):] = out;
		u *= 1/numpy.sqrt(numpy.dot(u,numpy.conj(u)))

		#http://www.mathworks.com/matlabcentral/answers/5275-algorithm-for-coeff-scaling-of-xcorr
		crossCorr = numpy.fft.ifft(numpy.fft.fft(u)*h);
		snr = numpy.abs(crossCorr).max();

		with open(fileName,"a") as fileID:
		    fileID.write("%f %f %f %f %f %f \n" % (snr, paramValue, s_m1, s_m2, mChirpSignal, len(a1)))
		    fileID.flush();

def construction_comparison(xmldoc,psd_interp, outfile, input_minMass = 1, input_maxMass = 3, input_numSignals = 50):
        ''' 
    CC - Construction comparison. Testing function for the new template generation method. Given a random mass pair, generate a wave and from that the SPIIR coefficients. Compute the overlap between these
        Keyword arguments:
        xmldoc		    -- The XML document containing information about the template bank. Used to get the final frequency (not actually useful but contains other information that might be useful in the future)
        psd_interp	    -- An interpolated power spectral density array. This is used to weight the signal and SPIIR response from the specifications of the LIGO/VIRGO instruments (combined)
        outfile		    -- Where the output is written to
        input_minMass	    -- Randomly distribute signals between this and the maximum mass (default 1, lower mass for proposed aLIGO BNS search)
	input_maxMass	    -- Randomly distribute signals between the minimum mass and this (default 3, upper mass for proposed aLIGO BNS search)
        input_numSignals    -- How many signals to generate and search for (default 50)
        '''
	fileName = outfile;
        sngl_inspiral_table=lsctables.table.get_table(xmldoc, lsctables.SnglInspiralTable.tableName)
	fFinal = max(sngl_inspiral_table.getColumnByName("f_final"))
	fLower = 15

	fid=open(fileName,"w")
	fid.write("snrNSNF m1 m2 mChirp numFiltersNew \n")
	fid.close()

	#### Initialise constants ####
	sampleRate = 4096; padding=1.1; epsilon=0.02; alpha=.99; beta=0.25;

	minMass = input_minMass; maxMass = input_maxMass;
	dist=1; incl = 0;
	snr=0; m1B = 0; m2B = 0
	
	length = 2**23;

	uNew = numpy.zeros(length, dtype=numpy.cdouble)
	uOld = numpy.zeros(length,dtype=numpy.cdouble)
	hNew = numpy.zeros(length, dtype=numpy.cdouble)
	hOld = numpy.zeros(length, dtype=numpy.cdouble)
	matchReq = 0.975
	timing=False;
	
	timePerCompStart  = 0;
	timePerCompFin = 0;

	numSignals = 0 ; numSignalsTot = input_numSignals;
	### We loop over parameters in the pbs function, to stop the memory leak breaking it all ###
#	for m1 in numpy.linspace(minMass,maxMass,num=stepNumMass):
#	    for m2 in numpy.linspace(minMass, maxMass, num=stepNumMass):
	while numSignals < numSignalsTot:
		numSignals = numSignals + 1;
		m1 = random.uniform(minMass,maxMass);
		m2 = random.uniform(minMass,maxMass);
		mChirp = (m1*m2)**(0.6)/(m1+m2)**(0.2);
		hNew.fill(0);
		hOld.fill(0);
		uNew.fill(0);
		uOld.fill(0);

		#### Generate signal, weight by PSD, normalise, take FFT ####
		ampNew,phaseNew=generate_waveform(m1,m2,dist,incl,fLower,fFinal,0,0,0,0,0,0,0)
		fs = numpy.gradient(phaseNew)/(2.0*numpy.pi * (1.0/sampleRate))
		negs = numpy.nonzero(fs<fLower)
	
		cleanFreq(fs,fLower)
		if((fs<0).any()):
		    print("fs broke for masses %f %f" % (m1,m2))
		    continue
		if psd_interp is not None:
		    ampNew[0:len(fs)] /= psd_interp(fs[0:len(fs)])**0.5

		ampNew = ampNew / numpy.sqrt(numpy.dot(ampNew,numpy.conj(ampNew)));
		hNew[-len(ampNew):] = ampNew * numpy.exp(1j*phaseNew);
		hNew *= 1/numpy.sqrt(numpy.dot(hNew,numpy.conj(hNew)))
		hNew = numpy.conj(numpy.fft.fft(hNew))
	   
		#### Get the IIR coefficients and response from the new signal####
		a1New, b0New, delayNew = spawaveform.iir(ampNew, phaseNew, epsilon, alpha, beta, padding)
		outNew = spawaveform.iirresponse(length, a1New, b0New, delayNew)
		outNew = outNew[::-1]
		uNew[-len(outNew):] = outNew;
		uNew *= 1/numpy.sqrt(numpy.dot(uNew,numpy.conj(uNew)))

		#### u -> filters, h -> signal ####

		#### Overlap for new signal vs new filters ####
		crossCorr = numpy.fft.ifft(numpy.fft.fft(uNew)*hNew);
		snrNSNF = numpy.abs(crossCorr).max();

		with open(fileName,"a") as fileID:
		    fileID.write("%f %f %f %f %f\n" % (snrNSNF, m1, m2, mChirp, len(a1New)))
		    fileID.flush();

def generate_spin_mag(spinMagMax):
    return numpy.array([random.uniform(-spinMagMax,spinMagMax) for _ in range(0,6)])

def spin_comparison(xmldoc, psd_interp, outfile, input_spinMax = 0.05, input_numSignals = 2):
        ''' 
    SC - Spin comparison. Similar to parameter comparison but instead of a fixed parameter generates waves with a spin components up to a given value.
        Keyword arguments:
        xmldoc		    -- The XML document containing information about the template bank. Essentially used as a big list of mass pairs to check overlap with
        psd_interp	    -- An interpolated power spectral density array. This is used to weight the signal and SPIIR response from the specifications of the LIGO/VIRGO instruments (combined)
        outfile		    -- Where the output is written to
        input_numSignals    -- How many signals to generate and search for (default 2 - low because of memory leak)
        '''
	fileName = outfile
	sngl_inspiral_table=lsctables.table.get_table(xmldoc, lsctables.SnglInspiralTable.tableName)
	fFinal = max(sngl_inspiral_table.getColumnByName("f_final"))


	sampleRate = 4096; padding=1.1; epsilon=0.02; alpha=.99; beta=0.25; spin=0;

	spinMin = 0; spinMax = input_spinMax;
	numSignals = 0; numSignalsTotal = input_numSignals;

	fileID = open(fileName,"w")
	fileID.write("Match Signal_Mass1 Signal_Mass2 BestTmp_Mass1 BestTmp_Mass2 Signal_Chirp BestTmp_Chirp ChirpDiff SignalSymmetricMass BestTmpSym SymDiff S1x S1y S1z S2x S2y S2z TotalSpinMag BestTmpNum Tolerance TimeTakenForSignal \n") #clear the file
	fileID.close()
	
	#Does not depend on the distance
	dist=100; incl = 0;
	minMass = 1; maxMass = 3;

	fLower = 15;
	fFinal = 2047;

	length = 2**23

	matchReq = 0.97
	#timing=False
	timing=True

	timePerCompStart  = 0;
	timePerCompFin = 0;
	
	maxTmp = 20;

	debugFix = True;
	
	print("Num signals tbd: " + str(input_numSignals))

	while(numSignals < numSignalsTotal):
	    h = None;
	    h = numpy.zeros(length, dtype=numpy.cdouble)
	    numSignals += 1;

	    #Generate new parameters for the signal
	    s_m1 = random.uniform(minMass,maxMass);
	    s_m2 = random.uniform(minMass,maxMass);

	    spin = generate_spin_mag(spinMax);
	    #0 and 7 are the reference frequency (0 = maximum) and the phase nPN
	    amps,phis=generate_waveform(s_m1,s_m2,dist,incl,fLower,fFinal,0,spin[0],spin[1],spin[2],spin[3],spin[4],spin[5])

	    ##### Apply the PSD to the signal waveform ######

	    #Get the frequency in Hz
	    fs = numpy.gradient(phis)/(2.0*numpy.pi * (1.0/sampleRate))
	    
	    #Sometimes the first few few frequencies or last few are negative due to the gradient measure
	    #Manually set them - might lose a teeny bit of accuracy but breaks otherwise

	    #numpy.savetxt("signal_freq_unfixed" + str(numSignals)+".dat",fs);
	    cleanFreq(fs,fLower)
	    #numpy.savetxt("signal_freq_fixed"+ str(numSignals)+".dat",fs);

	    if psd_interp is not None:
		    amps[0:len(fs)] /= psd_interp(fs[0:len(fs)])**0.5

	    #Normalise and conjugate the signal. 
	    #This would otherwise be done repeatedly in the loop below
	    amps = amps / numpy.sqrt(numpy.dot(amps,numpy.conj(amps)));
	    h[-len(amps):] = amps * numpy.exp(1j*phis);
	    h *= 1/numpy.sqrt(numpy.dot(h,numpy.conj(h)))
	    h = numpy.conj(numpy.fft.fft(h))

	    #42 is just a debug value - it should never occur
	    snr=0; m1B = 42; m2B = 42;

	
	    mChirpSignal = (s_m1*s_m2)**(0.6)/(s_m1+s_m2)**(0.2);
	    mSymSignal = (s_m1 * s_m2) / (s_m1 + s_m2)**2

	    
	    timePerSignalStart = time.time();
	    numTmp=0;
	    tol=0.0001; oldTol = 0;
	    symTol = 0.005; oldSymTol=0;

	    bestTmp = 0; ##The template number where the best match was found
	    while(snr < matchReq and numTmp < maxTmp):
		    u = numpy.zeros(length, dtype=numpy.cdouble)
		    for tmp, row in enumerate(sngl_inspiral_table):

			    m1 = row.mass1
			    m2 = row.mass2
			    mChirp = row.mchirp
			    mSym = (m1*m2) / (m1+m2)**2

			    #Look through the list of mass pairs till we find one with a chirp and symmetric mass below the tolerance
			    #Also must be higher than the old tolerance so that we don't repeat templates
			    if ((abs(mChirpSignal - mChirp )>tol) or (abs(mChirpSignal-mChirp) < oldTol and abs(mSymSignal-mSym) < oldSymTol) or (abs(mSymSignal - mSym) > symTol)):
				continue;

			    if timing:
				timePerTmpStart = time.time()

			    u.fill(0);
			    numTmp += 1
			    if timing:
			        timePerCompStart = time.time()	
			    

			    ##### Generate template waveform #####
			    amp,phase=generate_waveform(m1,m2,dist,incl,fLower,fFinal,0,0,0,0,0,0,0);
			    #Apply the PSD to the waveform and normalise

			    f = numpy.gradient(phase)/(2.0*numpy.pi * (1.0/sampleRate))
#			    numpy.savetxt("template_freq_unfixed"+str(numTmp)+".dat",f);
			    cleanFreq(f,fLower)
#			    numpy.savetxt("template_freq_fixed"+str(numTmp)+".dat",f);
			    if psd_interp is not None:
				    amp[0:len(f)] /= psd_interp(f[0:len(f)])**0.5
			    amp = amp / numpy.sqrt(numpy.dot(amp,numpy.conj(amp)));


			    
			    if timing:
				    timePerCompFinish = time.time()
				    print("Time to generate template waveform: "  + str(timePerCompFinish-timePerCompStart))

			    ##### Generate the IIR filter coefficients for that template #####
			    if timing:
				    timePerCompStart = time.time();
			    a1, b0, delay = spawaveform.iir(amp, phase, epsilon, alpha, beta, padding)


			    if timing:
				    timePerCompFinish = time.time()
				    print("Time to generate IIR coefficients: " + str(timePerCompFinish - timePerCompStart));
			    

			    ##### Get the IIR filter response for that template #####
			    if timing:
				    timePerCompStart = time.time();
			    out = spawaveform.iirresponse(length, a1, b0, delay)
			    out = out[::-1]
			    u[-len(out):] = out;
			    u *= 1/numpy.sqrt(numpy.dot(u,numpy.conj(u)))

			    if timing:
				    timePerCompFinish = time.time()
				    print("Time to generate IIR response: " + str(timePerCompFinish - timePerCompStart));

			    

			    ##### Calculate the overlap between the signal and the template response #####
			    if timing:
				    timePerCompStart = time.time();
			    crossCorr = numpy.fft.ifft(numpy.fft.fft(u)*h);
			    snr2 = numpy.abs(crossCorr).max();
			    if timing:
				    timePerCompFinish = time.time();
				    print("Time to calculate SNR: " + str(timePerCompFinish - timePerCompStart));


			    ##### General SNR accounting and printing #####
			    if(snr < snr2):
				snr = snr2
				m1B = m1
				m2B = m2	
				bestTmp = numTmp

			    if(snr>matchReq):
				if timing:
				    timePerTmpEnd=time.time()
				    print("***Match found *** \nTime per template: " + str(timePerTmpEnd-timePerTmpStart))
				    print("SNR of template: " + str(snr2) + " cDiff: " + str(mChirpSignal-mChirp) + " symDiff: " + str(mSymSignal-mSym))
				break;
			    if timing:
				timePerTmpEnd=time.time()
				print("Time per template: " + str(timePerTmpEnd-timePerTmpStart))
				print("SNR of template: " + str(snr2) + " cDiff: " + str(mChirpSignal-mChirp) + " symDiff: " + str(mSymSignal-mSym))
				print("Signal m1: " + str(s_m1) + " m2: " + str(s_m2) + " Template m1: " +  str(m1) + " m2: " + str(m2))
		    
		    if(numTmp > maxTmp):
			if timing:
			    timePerSignalEnd = time.time()
			    print(" **** No match found ***")

		    #Get rid of everything. Just in case... doesn't really help.
		    if debugFix:
			amp = None; phase = None; f = None; negs = None;
			u = None; out = None;
			amps = None; phis = None; fs = None; negs = None;
			a1 = None; b0 = None; delay = None; crossCorr = None;

		    oldTol = tol;
		    oldSymTol = symTol;
		    tol = tol+0.0001;
		    symTol = symTol + 0.001

	    timePerSignalEnd = time.time()
	    spinMag1 = numpy.sqrt(numpy.dot(spin[:3],spin[:3]));
	    spinMag2 = numpy.sqrt(numpy.dot(spin[3:],spin[3:]));
	    
	    if not (numTmp ==0):
		with open(fileName,"a") as fileID:
			fileID.write("%f %f %f %f %f %f %f %f %f %f %f %f %f %f %f %f %f %f %f %f %f \n" % (snr, s_m1, s_m2, m1B, m2B,
										(s_m1*s_m2)**0.6/(s_m1+s_m2)**0.2,
										(m1B*m2B)**0.6/(m1B+m2B)**0.2,
										(s_m1*s_m2)**0.6/(s_m1+s_m2)**0.2 - (m1B*m2B)**0.6/(m1B+m2B)**0.2,
										mSymSignal, m1B*m2B / (m1B+m2B)**2, mSymSignal - m1B*m2B/(m1B+m2B)**2,
										spin[0],spin[1],spin[2],spin[3],
										spin[4],spin[5],
										spinMag1+spinMag2,
										bestTmp, tol, timePerSignalEnd-timePerSignalStart))
			#Print out as we go, for the impatient user or if the program breaks unexpectedly
			fileID.flush();




def smooth_and_interp(psd, width=1, length = 10):
        data = psd.data
        f = numpy.arange(len(psd.data)) * psd.deltaF
        ln = len(data)
        x = numpy.arange(-width*length, width*length)
        sfunc = numpy.exp(-x**2 / 2.0 / width**2) / (2. * numpy.pi * width**2)**0.5
        out = numpy.zeros(ln)
        for i,d in enumerate(data[width*length:ln-width*length]):
                out[i+width*length] = (sfunc * data[i:i+2*width*length]).sum()
        return interpolate.interp1d(f, out)

def compare_two(psd_interp, signal_m1, signal_m2, template_m1, template_m2,psd=None,sngl_inspiral_table=None):
        '''Compares a given template and signal
	    New: Compare using the freq domain (lalwhiten) vs time domain applied psd
	    (This is similar to coefficient vs f-band whitening but the freq domain whitening 
	    also applies some conditioning and tapering to the waveform)
	
	'''
	print("Beginning comptuations")
	fFinal = 2047; #We only go as high as the waveform anyway
	fLower = 25 


	#### Initialise constants ####
	sampleRate = 4096; padding=1.1; epsilon=0.02; alpha=.99; beta=0.25;

	dist=50
	incl = 0;
	
	length = 2**20;

	signal_TDWhitened = numpy.zeros(length, dtype=numpy.cdouble)
	template_TDWhitened = numpy.zeros(length, dtype=numpy.cdouble)
	signal_FDWhitened = numpy.zeros(length, dtype=numpy.cdouble)
	template_FDWhitened = numpy.zeros(length, dtype=numpy.cdouble)
	

	signalChirp = (signal_m1*signal_m2)**(0.6)/(signal_m1+signal_m2)**(0.2);
	templateChirp = (template_m1*template_m2)**(0.6)/(template_m1+template_m2)**(0.2);


	#### Set up the template and signal waveforms
	# hp = hplus is used for freq domain whitening, amp/phase for TD whitening
	hpTemplate, hcTemplate = generate_waveform(template_m1,template_m2,dist,incl,fLower,fFinal,0,0,0,0,0,0,0,ampphase=0)
	ampTemplate,phaseTemplate=generate_waveform(template_m1,template_m2,dist,incl,fLower,fFinal,0,0,0,0,0,0,0,ampphase=1)

	hpSignal,hcSignal=generate_waveform(signal_m1,signal_m2,dist,incl,fLower,fFinal,0,0,0,0,0,0,0,ampphase=0)
	ampSignal,phaseSignal=generate_waveform(signal_m1,signal_m2,dist,incl,fLower,fFinal,0,0,0,0,0,0,0,ampphase=1)

	##########################################################
	#							 #
	#   Time Domain Whitening of both signal and templates	 #
	#							 #
	##########################################################


	#Apply PSD in time domain to template
	fTemplate = numpy.gradient(phaseTemplate)/(2.0*numpy.pi * (1.0/sampleRate))
	cleanFreq(fTemplate,fLower)
	ampTemplate[0:len(fTemplate)] /= psd_interp(fTemplate)**0.5


	#Apply PSD in time domain to signal
	fSignal = numpy.gradient(phaseSignal)/(2.0*numpy.pi*(1.0/sampleRate))
	cleanFreq(fSignal,fLower)
	ampSignal[0:len(fSignal)] /= psd_interp(fSignal)**0.5

	#Get the IIR coefficients and response from the template
	a1, b0, delay = spawaveform.iir(ampTemplate, phaseTemplate, epsilon, alpha, beta, padding)
	outTemplate = spawaveform.iirresponse(length, a1, b0, delay)


	#Finish up
	template_TDWhitened[-len(outTemplate):] = outTemplate[::-1];
	template_TDWhitened*= 1/numpy.sqrt(numpy.dot(template_TDWhitened,numpy.conj(template_TDWhitened)))
	
	signal_TDWhitened[-len(ampSignal):] = (ampSignal * numpy.exp(1j*phaseSignal))
	signal_TDWhitened *= 1/numpy.sqrt(numpy.dot(signal_TDWhitened,numpy.conj(signal_TDWhitened)))

	crossCorr = numpy.fft.ifft(numpy.fft.fft(signal_TDWhitened)*numpy.conj(numpy.fft.fft(template_TDWhitened)));
	snr = numpy.abs(crossCorr).max();

	print("TDWT-TDWS Template masses: %f, %f. Signal Masses %f, %f. sigChirp-tmpChirp: %f.SNR: %f" % (template_m1, template_m2, signal_m1, signal_m2, signalChirp - templateChirp, snr))
	print("Beginning TD-FD")

	#################################################
	#						#
	#   Freq domain signal, time domain template	#
	#	(reuse template from above)		#
	#						#
	#################################################

	timeStart = time.time()
	### Frequency domain whitening
	working_f_low_extra_time, working_f_low = cbc_template_fir.joliens_function(fLower, sngl_inspiral_table)

	# FIXME: This is a hack to calculate the maximum length of given table, we 
	# know that working_f_low_extra_time is about 1/10 of the maximum duration
	length_max = working_f_low_extra_time * 10 * sampleRate

	# Add 32 seconds to template length for PSD ringing, round up to power of 2 count of samples
	working_length = templates.ceil_pow_2(length_max + round((32.0 + working_f_low_extra_time) * sampleRate))
	working_duration = float(working_length) / sampleRate


	timeFinish = time.time()
	print("PSD interpolation time " + str(timeFinish-timeStart))
	timeStart = time.time()
	lal_signal_whiten_amp, lal_signal_whiten_phase = cbc_template_iir.lalwhiten(psd, hpSignal, working_length, working_duration, sampleRate, length_max) #Breaks here
	timeFinish = time.time()
	print("Whitening time " + str(timeFinish - timeStart))
	#Still need to do some more work here
	lalSignal = lal_signal_whiten_amp * numpy.exp(1j * lal_signal_whiten_phase)
	lalSignal *= 1/numpy.sqrt(numpy.dot(lalSignal,numpy.conj(lalSignal)))

	signal_FDWhitened[-len(lalSignal):] = lalSignal
	signal_FDWhitened *= 1/numpy.sqrt(numpy.dot(signal_FDWhitened,numpy.conj(signal_FDWhitened)))

	crossCorr = numpy.fft.ifft(numpy.fft.fft(signal_FDWhitened)*numpy.conj(numpy.fft.fft(template_TDWhitened)));
	snr = numpy.abs(crossCorr).max();

	print("TDWT-FDWS Template masses: %f, %f. Signal Masses %f, %f. sigChirp-tmpChirp: %f.SNR: %f" % (template_m1, template_m2, signal_m1, signal_m2, signalChirp - templateChirp, snr))
	print("Beginning FD-FD")

	#############################################################
	#							    #
	#   Frequency domain whitening of both template and signal  #
	#		(reuse signal from above)		    #
	#							    #
	#############################################################

	### Frequency domain whitening
	lal_temp_whiten_amp, lal_temp_whiten_phase = cbc_template_iir.lalwhiten(psd, hpTemplate, working_length, working_duration, sampleRate, length_max)

	a1, b0, delay = spawaveform.iir(lal_temp_whiten_amp, lal_temp_whiten_phase, epsilon, alpha, beta, padding)
	outTemplate = spawaveform.iirresponse(length, a1, b0, delay)

	template_FDWhitened[-len(outTemplate):] = outTemplate[::-1]
	template_FDWhitened *= 1/numpy.sqrt(numpy.dot(template_FDWhitened,numpy.conj(template_FDWhitened)))


	crossCorr = numpy.fft.ifft(numpy.fft.fft(signal_TDWhitened)*numpy.conj(numpy.fft.fft(template_FDWhitened)));
	snr = numpy.abs(crossCorr).max();

	print("FDWT-TDWS Template masses: %f, %f. Signal Masses %f, %f. sigChirp-tmpChirp: %f.SNR: %f" % (template_m1, template_m2, signal_m1, signal_m2, signalChirp - templateChirp, snr))

	#crossCorr = numpy.fft.ifft(numpy.fft.fft(signal_FDWhitened)*numpy.conj(numpy.fft.fft(template_FDWhitened)));
	#snr = numpy.abs(crossCorr).max();

	print("FDWT-FDWS Template masses: %f, %f. Signal Masses %f, %f. sigChirp-tmpChirp: %f.SNR: %f" % (template_m1, template_m2, signal_m1, signal_m2, signalChirp - templateChirp, snr))
#	pplot.figure()
#	pplot.plot(u)
#	pplot.plot(h)
#	pplot.show()

#	pdb.set_trace()
	#### u -> filters, h -> signal ####
	### Overlap for new signal vs new filters ####

def spin_test(psd_interp, signal_m1, signal_m2, signal_spin, template_m1 = -1 , template_m2 = -1,template_spin = None):
	print("Beginning computations")
	fFinal = 2047; #We only go as high as the waveform anyway
	fLower = 25 


	#If no separate template mass is put in (or invalid)
	#Set the templae mass to the same as the signal
	if(template_m1 <= 0 ):
	    template_m1 = signal_m1
	if(template_m2 <= 0):
	    template_m2 = signal_m2
	if(template_spin == None):
	    template_spin = signal_spin

	#### Initialise constants ####
	sampleRate = 4096; padding=1.1; epsilon=0.02; alpha=.99; beta=0.25;

	dist=50
	incl = 0;
	
	length = 2**20;

	signal = numpy.zeros(length, dtype=numpy.cdouble)
	template = numpy.zeros(length, dtype=numpy.cdouble)
	

	signalChirp = (signal_m1*signal_m2)**(0.6)/(signal_m1+signal_m2)**(0.2);
	templateChirp = (template_m1*template_m2)**(0.6)/(template_m1+template_m2)**(0.2);


	#### Set up the template and signal waveforms
	# hp = hplus is used for freq domain whitening, amp/phase for TD whitening
	hpSignal, hcSignal = generate_waveform(signal_m1,signal_m2,dist,incl,fLower,fFinal,0,signal_spin[0],signal_spin[1],signal_spin[2],signal_spin[3],signal_spin[4],signal_spin[5],ampphase=0)
	ampSignal, phaseSignal = generate_waveform(signal_m1,signal_m2,dist,incl,fLower,fFinal,0,signal_spin[0],signal_spin[1],signal_spin[2],signal_spin[3],signal_spin[4],signal_spin[5],ampphase=1)
	hpTemplate,hcTemplate=generate_waveform(template_m1,template_m2,dist,incl,fLower,fFinal,0,template_spin[0],template_spin[1],template_spin[2],template_spin[3],template_spin[4],template_spin[5],ampphase=0)
	ampTemplate,phaseTemplate=generate_waveform(template_m1,template_m2,dist,incl,fLower,fFinal,0,template_spin[0],template_spin[1],template_spin[2],template_spin[3],template_spin[4],template_spin[5],ampphase=1)



	#Apply PSD in time domain to template
	fTemplate = numpy.gradient(phaseTemplate)/(2.0*numpy.pi * (1.0/sampleRate))


	cleanFreq(fTemplate,fLower)
	#and finally, just in case
        fTemplate = numpy.abs(fTemplate)
	ampTemplate[0:len(fTemplate)] /= psd_interp(fTemplate)**0.5


	#Apply PSD in time domain to signal
	fSignal = numpy.gradient(phaseSignal)/(2.0*numpy.pi*(1.0/sampleRate))
	cleanFreq(fSignal,fLower)
	fSignal = numpy.abs(fSignal)
	ampSignal[0:len(fSignal)] /= psd_interp(fSignal)**0.5


	signal[-len(ampSignal):] = ampSignal*numpy.exp(1j*phaseSignal);
	signal = numpy.real(signal)
	signal *= 1/numpy.sqrt(numpy.dot(signal,signal))

	#Get the IIR coefficients and response from the template
	a1, b0, delay = spawaveform.iir(ampTemplate, phaseTemplate, epsilon, alpha, beta, padding)
	outTemplate = spawaveform.iirresponse(length, a1, b0, delay)

	template[-len(outTemplate):] = outTemplate[::-1];
	reTemplate = numpy.real(template)
	reTemplate *= 1/numpy.sqrt(numpy.dot(reTemplate,reTemplate))
	imTemplate = numpy.imag(template)
	imTemplate *= 1/numpy.sqrt(numpy.dot(imTemplate,imTemplate))
	template = reTemplate+1j*imTemplate

	#crossCorr = numpy.fft.ifft(numpy.fft.fft(signal)*numpy.conj(numpy.fft.fft(template)));
	#snr = numpy.abs(crossCorr).max();
	overlap  = numpy.abs(numpy.dot(signal,numpy.conj(template)))

	#TBD: in the case of differing masses, print out spin information
	if(template_m1 != signal_m1 or template_m2 != signal_m2):
		print("Template masses: %f, %f. Signal Masses %f, %f. sigChirp-tmpChirp: %f.SNR: %f" % (template_m1, template_m2, signal_m1, signal_m2, signalChirp - templateChirp, overlap))
	else:
	    print("Masses: %f, %f Chirp: %f  Spin: 1x: %f, 1y: %f, 1z: %f, 2x: %f, 2y: %f, 2z: %f, overlap: %f" % (signal_m1, signal_m2, signalChirp, signal_spin[0], 
														signal_spin[1], signal_spin[2], signal_spin[3], 
														signal_spin[4], signal_spin[5], overlap))

#	pplot.figure()
#	pplot.plot(u)
#	pplot.plot(h)
#	pplot.show()

	#### u -> filters, h -> signal ####
	### Overlap for new signal vs new filters ####



def test_bank(psd_interp, sngl_inspiral_table,outname):
    sampleRate = 4096; padding=1.3; epsilon=0.02; alpha=.99; beta=0.2; fLower = 30; fFinal = 2047;

    dist=50
    incl = 0;
    
    length = 2**20;

    signal = numpy.zeros(length, dtype=numpy.cdouble)
    template = numpy.zeros(length, dtype=numpy.cdouble)
    fileName = str(outname)+".dat";
    failure_fileName = str(outname)+"_fails.dat"

    with open(fileName,"w") as fileID:
        fileID.write("overlap m1 m2 mChirpSignal numFilters s1x s1y s1z s2x s2y s2z\n")
	fileID.flush();
    with open(failure_fileName, "w") as fileID:
	fileID.write("m1 m2 mChirpSignal s1x s1y s1z s2x s2y s2z \n")
	fileID.flush();

    for tmp, row in enumerate(sngl_inspiral_table):
	signalChirp = (row.mass1*row.mass2)**(0.6)/(row.mass1+row.mass2)**(0.2);
	signal.fill(0);
	template.fill(0);
	ampSignal, phaseSignal = generate_waveform(row.mass1,row.mass2,dist,incl,fLower,fFinal,70,row.spin1x,row.spin1y,row.spin1z,row.spin2x,row.spin2y,row.spin2z,ampphase=1)

	try: 
	    #Time domain whiten signal
	    fSignal = numpy.gradient(phaseSignal)/(2.0*numpy.pi*(1.0/sampleRate))
	    cleanFreq(fSignal,fLower)
	    ampSignal[0:len(fSignal)] /= psd_interp(fSignal)**0.5

	    signal[-len(ampSignal):] = ampSignal*numpy.exp(1j*phaseSignal);

	    #Just get the h_c component
	    signal = numpy.real(signal)
	    signal *= 1/numpy.sqrt(numpy.dot(signal,signal))
	    a1, b0, delay = spawaveform.iir(ampSignal, phaseSignal, epsilon, alpha, beta, padding)
	    outTemplate = spawaveform.iirresponse(length, a1, b0, delay)

	    template[-len(outTemplate):] = outTemplate[::-1];
	    reTemplate = numpy.real(template)
	    reTemplate *= 1/numpy.sqrt(numpy.dot(reTemplate,reTemplate))
	    imTemplate = numpy.imag(template)
	    imTemplate *= 1/numpy.sqrt(numpy.dot(imTemplate,imTemplate))
	    template = reTemplate+1j*imTemplate
	    
	    #crossCorr = numpy.fft.ifft(numpy.fft.fft(signal)*numpy.conj(numpy.fft.fft(template)));
	    #overlap = numpy.abs(crossCorr).max();
	    overlap  = numpy.abs(numpy.dot(signal,numpy.conj(template)))
	    #print "m1: %f m2: %f overlap: %f" % (row.mass1, row.mass2, overlap);

	    with open(fileName,"a") as fileID:
		fileID.write("%f %f %f %f %f %f %f %f %f %f %f\n" % (overlap, row.mass1, row.mass2, signalChirp, len(a1),row.spin1x,row.spin1y,row.spin1z,row.spin2x,row.spin2y,row.spin2z))
		fileID.flush();
	except:
	    with open(failure_fileName,"a") as fileID:
		fileID.write("%f %f %f %f %f %f %f %f %f\n" % (row.mass1, row.mass2, signalChirp, row.spin1x,row.spin1y,row.spin1z,row.spin2x,row.spin2y,row.spin2z))
		fileID.flush();
	#pdb.set_trace()
#	pplot.figure()
#	pplot.plot(numpy.real(template))
#	pplot.plot(signal)
#	pplot.show()

def test_bank_cleanup(psd_interp, sngl_inspiral_table,inname,outname):
    sampleRate = 4096; padding=1.3; epsilon=0.01; alpha=.99; beta=0.25; fLower = 30; fFinal = 2047;
    dist=50
    incl = 0;
    
    length = 2**20;

    signal = numpy.zeros(length, dtype=numpy.cdouble)
    template = numpy.zeros(length, dtype=numpy.cdouble)

    with open(str(outname)+".dat","w") as outFile:
	with open(str(inname)+".dat", "r") as inFile:
	   outFile.write(inFile.readline()) #copy the file headings
	   for line in inFile:
	    #If the overlap is less than 0.99
	    #Then redo the calculation with a lower epsilon
	    if(float(line.split()[0]) <= 0.99) :
		mass1 =	float(inFile.split()[1])
		mass2 =	float(inFile.split()[2])
		spin1x= float(inFile.split()[5])
		spin1y= float(inFile.split()[6])
		spin1z= float(inFile.split()[7])
		spin2x= float(inFile.split()[8])
		spin2y= float(inFile.split()[9])
		spin2z= float(inFile.split()[10])

		signalChirp = (mass1*mass2)**(0.6)/(mass1+mass2)**(0.2);
		signal.fill(0);
		template.fill(0);
		ampSignal, phaseSignal = generate_waveform(mass1,mass2,dist,incl,fLower,fFinal,70,spin1x,spin1y,spin1z,spin2x,spin2y,spin2z,ampphase=1)

		#Time domain whiten signal
		fSignal = numpy.gradient(phaseSignal)/(2.0*numpy.pi*(1.0/sampleRate))
		cleanFreq(fSignal,fLower)
		ampSignal[0:len(fSignal)] /= psd_interp(fSignal)**0.5

		signal[-len(ampSignal):] = ampSignal*numpy.exp(1j*phaseSignal);

		#Just get the h_c component
		signal = numpy.real(signal)
		signal *= 1/numpy.sqrt(numpy.dot(signal,signal))
		a1, b0, delay = spawaveform.iir(ampSignal, phaseSignal, epsilon, alpha, beta, padding)
		outTemplate = spawaveform.iirresponse(length, a1, b0, delay)

		template[-len(outTemplate):] = outTemplate[::-1];
		reTemplate = numpy.real(template)
		reTemplate *= 1/numpy.sqrt(numpy.dot(reTemplate,reTemplate))
		imTemplate = numpy.imag(template)
		imTemplate *= 1/numpy.sqrt(numpy.dot(imTemplate,imTemplate))
		template = reTemplate+1j*imTemplate
		
		#crossCorr = numpy.fft.ifft(numpy.fft.fft(signal)*numpy.conj(numpy.fft.fft(template)));
		#overlap = numpy.abs(crossCorr).max();
		overlap  = numpy.abs(numpy.dot(signal,numpy.conj(template)))
		#print "m1: %f m2: %f overlap: %f" % (row.mass1, row.mass2, overlap);

		with open(fileName,"a") as fileID:
		    outFile.write("%f %f %f %f %f %f %f %f %f %f %f\n" % (overlap, mass1, mass2, signalChirp, len(a1),spin1x,spin1y,spin1z,spin2x,spin2y,spin2z))
		    outFile.flush();
		outFile.write('\n')
	    else:
	    #copy it over
		outFile.write(i)


	#pdb.set_trace()
#	pplot.figure()
#	pplot.plot(numpy.real(template))
#	pplot.plot(signal)
#	pplot.show()

#Hack to load template bank, apparently the old method is just outdated?
class DefaultContentHandler(ligolw.LIGOLWContentHandler):
	pass

def main():

	parser = OptionParser(description = __doc__)


	parser.add_option("--type", metavar = "string", help = "Which type of test/comparison to perform. Allowed values are \n VPC - Variable parameter comparison. Given a single parameter (alpha, beta or epsilon) compute, over the given range, the overlap between a template and associated SPIIR response of fixed mass (1.4-1.4) \n PC - Parameter comparison. Takes a single parameter and value (e.g. eps=0.02). Generates a random spin wave and computes the overlap with SPIIR responses from templates in the supplied bank until a match of 0.97 or above is found. Repeat for a specified number of signals. \n CC - Construction comparison. Testing function for the new template generation method. Given a random mass pair, generate a wave and from that the SPIIR coefficients. Compute the overlap between these \n SC - Spin comparison. Similar to parameter comparison but instead of a fixed parameter generates waves with a spin components up to a given value.")


	#Universal options
	parser.add_option("--reference-psd", metavar = "filename", help = "load the spectrum from this LIGO light-weight XML file (required).", type="string")
	parser.add_option("--template-bank", metavar = "filename", help = "Set the name of the LIGO light-weight XML file from which to load the template bank (required for most).",type="string")
	parser.add_option("--output", metavar = "filename", help = "Set the filename in which to save the template bank (required).",type="string")

	#Options for types
	parser.add_option("--param", metavar = "string", help = "VPC/PC: Which parameter to change/vary. Used in VPC (alpha, beta, epsilon or spin) and PC (alpha, beta, epsilon) can also use short hands a, b, e, eps and s",type="string")
	parser.add_option("--param-lower", metavar = "float", help = "VPC: Lower value of the parameter variation.",type="float")
	parser.add_option("--param-upper", metavar = "float", help = "VPC: Upper value of the parameter variation.",type="float")
	parser.add_option("--param-num", metavar = "float", help = "VPC: The number of steps to take between upper and lower value of the parameter variation.",type="float")
	parser.add_option("--param-value", metavar = "float", help = "PC: The value to set the specified parameter to.",type="float")
	parser.add_option("--mass1", metavar = "float", help = "VPC: The mass of the first body",type="float",default=1.4)
	parser.add_option("--mass2", metavar = "float", help = "VPC: The mass of the second body",type="float",default=1.4)
	parser.add_option("--min-mass", metavar = "float", help = "PC/CC/SC: The minimum mass (mass pair is randomly chosen between min and max)",type="float",default=1)
	parser.add_option("--max-mass", metavar = "float", help = "PC/CC/SC: The maximum mass (mass pair is randomly chosen between min and max)",type="float",default=3)
	parser.add_option("--num-signals", metavar = "int", help = "PC/CC/SC: The number of signals to test",type="int",default=2)
	parser.add_option("--spin-max", metavar = "float", help = "SC: Spin components are randomly chosen between -spin_max < x < spin_max",type="float",default=0.05)


	options, filenames = parser.parse_args()

#	required_options = ("template_bank","reference_psd","type")

#	missing_options = [option for option in required_options if getattr(options, option) is None]
#	if missing_options:
#		raise ValueError, "missing required option(s) %s" % ", ".join("--%s" % option.replace("_", "-") for option in sorted(missing_options))


	array.use_in(DefaultContentHandler)
	param.use_in(DefaultContentHandler)
	lsctables.use_in(DefaultContentHandler)
	# read bank file
	if(options.type != "spintest"):

	    tmpltbank_xmldoc = utils.load_filename(options.template_bank, verbose = True, contenthandler=DefaultContentHandler)
	    sngl_inspiral_table = lsctables.SnglInspiralTable.get_table(tmpltbank_xmldoc)

#	bank_xmldoc = utils.load_filename(options.template_bank, gz=options.template_bank.endswith('.gz'))
#	sngl_inspiral_table = lsctables.table.get_table(bank_xmldoc, lsctables.SnglInspiralTable.tableName)
#	fFinal = max(sngl_inspiral_table.getColumnByName("f_final"))

	# read psd file
	if options.reference_psd:
		# smooth and create an interp object
		ALLpsd = read_psd_xmldoc(utils.load_filename(options.reference_psd,contenthandler=DefaultContentHandler))
		psd = ALLpsd['H1']
		psd = smooth_and_interp(psd)
	else:
		psd = None
		print("Error: No PSD file given!")



	if(options.type == "VPC"):
	    if(options.param == None):
		print("Parameter not given but required. Please use --param to specify");
		exit();
	    if(options.param_lower == None or options.param_upper == None):
		print("Parameter range not completely specified. Please use BOTH --param-lower and --param-upper");
		exit();

	    if(options.output == None):
		outfile = "VPC_" + str(options.param) + "_" + str(options.param_lower) + "_to_" + str(options.param_upper) + ".dat"
	    else:
		outfile = options.output
	    variable_parameter_comparison( bank_xmldoc,
							    psd,
							    outfile,
							    options.param,
							    options.param_lower,
							    options.param_upper,
							    param_num = options.param_num,
							    input_mass1 = options.mass1,
							    input_mass2 = options.mass2)
	elif(options.type == "PC"):
	    if(options.param == None):
		print("Parameter not given but required. Please use --param to specify");
		exit();
	    if(options.param_value == None):
		print("Parameter value not given by required. Please use --param-value to specify");
	    if(options.output == None):
		outfile = "PC_" + str(options.param) + "_" + str(options.param_value) + ".dat"
	    else:
		outfile = options.output
	    parameter_comparison(  bank_xmldoc,
						    psd,
						    outfile,
						    options.param,
						    options.param_value,
						    input_minMass = options.min_mass,
						    input_maxMass = options.max_mass,
						    input_numSignals = options.num_signals)
	elif(options.type == "CC"):
	    if(options.output == None):
		outfile = "CC_minmass_" + str(options.min_mass) + "_maxmass_" + str(options.max_mass) + ".dat"
	    else:
		outfile = options.output
	    construction_comparison(	bank_xmldoc,
							psd,
							outfile,
							input_minMass = options.min_mass,
							input_maxMass = options.max_mass,
							input_numSignals = options.num_signals)
	elif(options.type == "SC"):
	    if(options.spin_max == None):
		print("Spin max must not be none. Use --spin-max to specify")
		exit()
	    if(options.output == None):
		outfile = "SC_spin_" + str(options.spin_max) + ".dat"
	    else:
		outfile = options.output
	    spin_comparison(	bank_xmldoc,
						psd,
						outfile,
						input_spinMax = options.spin_max,
						input_numSignals = options.num_signals)
	if(options.type == "C2"):
	    fLower = 25
	    sampleRate = 4096
	    working_f_low_extra_time, working_f_low = cbc_template_fir.joliens_function(fLower, sngl_inspiral_table)

	    # FIXME: This is a hack to calculate the maximum length of given table, we 
	    # know that working_f_low_extra_time is about 1/10 of the maximum duration
	    length_max = working_f_low_extra_time * 10 * sampleRate

	    # Add 32 seconds to template length for PSD ringing, round up to power of 2 count of samples
	    working_length = templates.ceil_pow_2(length_max + round((32.0 + working_f_low_extra_time) * sampleRate))
	    working_duration = float(working_length) / sampleRate
	    # Smooth the PSD and interpolate to required resolution
	    if psd is not None:
		    psdConditioned = cbc_template_fir.condition_psd(ALLpsd['H1'], 1.0 / working_duration, minfs = (working_f_low, fLower), maxfs = (sampleRate / 2.0 * 0.90, sampleRate / 2.0))
				    # This is to avoid nan amp when whitening the amp 
		    tmppsd = psdConditioned.data
		    tmppsd[numpy.isinf(tmppsd)] = 1.0
		    psdConditioned.data = tmppsd
	    signal_m1 = 1.4;
	    signal_m2 = 1.4;

	    template_m1 = 1.4;
	    template_m2 = 1.4;
	    compare_two(psd, signal_m1, signal_m2, template_m1,template_m2,psd=psdConditioned,sngl_inspiral_table=sngl_inspiral_table)

	if(options.type == "spintest"):

	    signal_spin = [0,0,0,0,0,0]
	    temp_spin= [0,0,0,0,0,0]
	    signal_m1 = 1.4;
	    signal_m2 = 1.4;
	    temp_m1 = 1.4;
	    temp_m2 = 1.4;

#	    spin_test(psd,signal_m1,signal_m2,signal_spin, template_m1 = temp_m1,template_m2 = temp_m2, template_spin = temp_spin)
	    spin_test(psd,2.3750904,1.9942362,[0,0,0,0,0,0])
#	    spin_test(psd,1.4,10,[0,0,1,0,0,1])
#	    spin_test(psd,10,1.4,[1,0,0,1,0,0])

	if(options.type == "test_bank"):
	    test_bank(psd,sngl_inspiral_table,options.output)

	if(options.type == "test_bank_cleanup"):
	    test_bank_cleanup(psd,sngl_inspiral_table,"combinednew","combinednewclean")
	## There is potential to easily multithread the program but currently the memory useage is too high for even one instance in some cases
	## This is a major issue that is still being resolved but is difficult due to the very long waveforms

	#def startJob(multi_id):
	#    makeiirbank_spincomp(bank_xmldoc, sampleRate = 4096, psd_interp = psd, verbose=options.verbose, padding=options.padding, flower=options.flow, downsample = options.downsample, output_to_xml = True, epsilon = options.epsilon,multiNum=multi_id,multiAmount=options.multiAmount,spinMaximum=options.spinMax)

	#mN = int(options.multiNum)
	#pool = Pool(processes=4);
	#pool.map(startJob,[0+mN,1+mN,2+mN,3+mN]);

if __name__ == "__main__":
    main()
