#!/usr/bin/env python

"""
rmsynthesis.py
Written by Michael Bell, Henrik Junklewitz and Sarrvesh Sridhar

RM Synthesis software for use with sets of FITS image files.  Written in Python
with some sub-functions re-written in Cython for speed.  Standard Fourier
inversion and Hogbom style CLEAN imaging are possible.

Copyright 2012-2016 Michael Bell and Henrik Junklewitz

This file is part of the pyrmsynth package.

pyrmsynth is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

pyrmsynth is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with pyrmsynth.  If not, see <http://www.gnu.org/licenses/>.
"""

# TODO: Read in CASA images as well as FITS files using CASACORE.
#       See emails from GvD
# TODO: Read in spectral index info (from a parameter, or a FITS file)
# TODO: Optimize for speed

from optparse import OptionParser
import datetime
import csv
import math
import os
import sys

import numpy
import pyfits
import pylab
from pywcs import WCS

import rm_tools as R

VERSION = '1.3.0'


class Params:
    """

    """

    def __init__(self):
        """
        Params()

        Intitializes the parameter list with default values. Change parameters
        by directly accessing these class variables.
        """
        self.nphi = 200
        self.dphi = 1
        self.phi_min = -100
        temp = numpy.arange(self.nphi)
        self.phi = self.phi_min + temp * self.dphi
        self.niter = 500
        self.gain = 0.1
        self.cutoff = 0.
        self.do_clean = False
        self.isl2 = False
        self.weight = None
        self.outputfn = 'test_100A'
        self.input_dir = './'
        self.ra_lim = []
        self.dec_lim = []
        self.imagemask = ''
        self.threshold = 0.

    def __call__(self):
        """
        """
        print 'RM Synthesis parameters:'
        print '  Requested phi axis definition:'
        print '    phi_min:         ', self.phi_min
        print '    dphi:            ', self.dphi
        print '    nphi:            ', self.nphi
        
        if self.alphafromfile == False:
            print '  Averaged spectral index provided:'
            print '    alpha:           ', self.alpha
            if self.ref_freq:
                print '    ref_freq:        ', self.ref_freq
            else:
                print '    ref_freq:        '+'Set to mean center frequency.'
        else: 
            print '  Spectral index image provided:'
            print '    from:           ', self.alpha
            if self.ref_freq:
                print '    ref_freq:        ', self.ref_freq
            else:
                print '    ref_freq:        '+'Set to mean center frequency.'
        
        if self.imagemask == '':
            print 'No image mask is specified. Will use all sky plane pixels\
                in RM Synthesis'
        else:
            print 'Image mask specified. Will use pixels selected by mask '\
                 + str(self.imagemask)
                 
        print '  Polarized intensity detection threshold: ', self.threshold        
        
        if self.do_clean:
            print '  RM CLEAN enabled:'
            print '    niter:           ', self.niter
            print '    gain:            ', self.gain
            print '    cutoff:          ', self.cutoff
        else:
            print 'RM CLEAN not enabled'
        print '  Sky plane image limits:'
        print '    ra_lim:          ', self.ra_lim
        print '    dec_lim:         ', self.dec_lim
        print '  Reading from directory: ', self.input_dir
        print '  Writing to files starting with: ', self.outputfn

    def __disp_vect(self, vect):
        """
        """
        if vect is None:
            return None
        else:
            return len(vect)


def progress(width, percent):
    """
    """
    marks = math.floor(width * (percent / 100.0))
    spaces = math.floor(width - marks)
    loader = '[' + ('=' * int(marks)) + (' ' * int(spaces)) + ']'
    sys.stdout.write("%s %d%%\r" % (loader, percent))
    if percent >= 100:
        sys.stdout.write("\n")
    sys.stdout.flush()


def rmsynthesis(params, options, manual=False):
    """
    rmsynthesis(params, manual=False)

    Conducts RM synthesis based on the parameters provided in the params class
    for the data contained w/in the current directory.  This may be either a
    fits file containing a cube of data (indexed z,x,y when read in using
    pyfits) or a text file (freq, q,u)
    if manual=true returns the rmsynth cube class and the pol cube.
    """

    qsubdir = '/stokes_q/'
    usubdir = '/stokes_u/'

    vcube_mmfn = 'stokesv.dat'
    incube_mmfn = 'incube.dat'
    outcube_mmfn = 'outcube.dat'
    rescube_mmfn = 'outcube_res.dat'
    cleancube_mmfn = 'outcube_clean.dat'
    cccube_mmfn = 'outcube_cc.dat'
    pmap_mmfn = 'outmap_p.dat'
    phimap_mmfn = 'outmap_phi.dat'
    qmap_mmfn = 'outmap_q.dat'
    umap_mmfn = 'outmap_u.dat'


    if options.freq_last:
        freq_axnum = '4'
        stokes_axnum = '3'
    else:
        freq_axnum = '3'
        stokes_axnum = '4'    # lint:ok

    if params.phi is None:
        msg = 'Parameters not specified correctly. No phi axis defined! ' + \
            'Please double check and try again.'
        raise ValueError(msg)

    if options.stokes_v and options.separate_stokes:
        print "Stokes V output is not available when the Stokes images are " +\
            "stored in separate files.  Turning Stokes V output off."
        options.stokes_v = False

    # Gather the input file names from the directory in the parset
    if not options.separate_stokes:
        # In this case, each file contains all Stokes parameters.
        fns = os.listdir(params.input_dir)
        if len(fns) == 0:
            raise IOError('No valid files found in this directory!')

        nfns = len(fns)
        fns_copy = list(fns)
        for indx in range(nfns):  # remove any non fits files
            fn = fns_copy[indx]
            if fn[len(fn) - 4:len(fn)].lower() != 'fits':
                fns.remove(fn)

        # If a mask file is specified, above lines will add the mask fits 
        # to fns. Removing it from the list of valid fits files
        if params.imagemask != '':
            fns.remove(params.imagemask.split('/')[-1])


        if len(fns) == 0:
            raise IOError('No valid files found in this directory!')

        fns.sort()

        tdata = pyfits.getdata(params.input_dir + fns[0])
        thead = pyfits.getheader(params.input_dir + fns[0])
    else:
        # In this case, each file contains only a single Stokes parameter.
        # This is mainly here for compatability with Michiel's code.
        try:
            fns_q = os.listdir(params.input_dir + qsubdir)
            fns_u = os.listdir(params.input_dir + usubdir)
        except OSError:
            print "No Stokes sub-directories found!  Please put the Stokes " +\
                "Q and Stokes U images into the stokes_q and stokes_u " + \
                "subfolders of the input directory listed in the parset file."
            raise

        if len(fns_q) == 0 or len(fns_u) == 0:
            raise IOError('No valid files found in this directory')

        nfnsq = len(fns_q)
        nfnsu = len(fns_u)
        fns_q_copy = list(fns_q)
        fns_u_copy = list(fns_u)
        for indx in range(nfnsq):  # remove any non fits files
            fn = fns_q_copy[indx]
            if fn[len(fn) - 4:len(fn)].lower() != 'fits':
                fns_q.remove(fn)

        for indx in range(nfnsu):  # remove any non fits files
            fn = fns_u_copy[indx]
            if fn[len(fn) - 4:len(fn)].lower() != 'fits':
                fns_u.remove(fn)

        if len(fns_q) == 0 or len(fns_u) == 0:
            raise IOError('No valid files found in this directory.')

        if len(fns_q) != len(fns_u):
            raise IOError('The number of Stokes Q and U images are different.')

        fns_q.sort()
        fns_u.sort()

        tdata = pyfits.getdata(params.input_dir + qsubdir + fns_q[0])
        thead = pyfits.getheader(params.input_dir + qsubdir + fns_q[0])

    # indices 1=freq, 2=dec, 3=ra - stored values are complex

    # Validate the image bounds
    decsz = [0, len(tdata[0, 0])]
    if params.dec_lim[0] != -1:
        decsz[0] = params.dec_lim[0]
    else:
        params.dec_lim[0] = 0
    if params.dec_lim[1] != -1:
        decsz[1] = params.dec_lim[1]
    else:
        params.dec_lim[1] = len(tdata[0, 0])
    if decsz[0] >= decsz[1]:
        raise Exception('Invalid image bounds')

    rasz = [0, len(tdata[0, 0, 0])]
    if params.ra_lim[0] != -1:
        rasz[0] = params.ra_lim[0]
    else:
        params.ra_lim[0] = 0
    if params.ra_lim[1] != -1:
        rasz[1] = params.ra_lim[1]
    else:
        params.ra_lim[1] = len(tdata[0, 0, 0])
    if rasz[0] >= rasz[1]:
        raise Exception('Invalid image bounds')  
        
    # Get the appropriate mask
    if params.imagemask == '':
        # If no mask is specified, assign 1's to all pixels in the mask image
        ra_size = params.ra_lim[1] - params.ra_lim[0]
        dec_size = params.dec_lim[1] - params.dec_lim[0]
        maskimage = numpy.ones((dec_size, ra_size), dtype=numpy.int_)
    else:
        # Read in the mask file
        try:
            # mask should be in the input directory
            maskdata = pyfits.getdata(params.input_dir+params.imagemask)
            maskhead = pyfits.getheader(params.input_dir+params.imagemask)
        except:
            raise Exception('Unable to read the mask image.')
        # Check if the mask has the same shape as the input image
        if thead['NAXIS1'] != maskhead['NAXIS1'] or \
           thead['NAXIS2'] != maskhead['NAXIS2']:
            raise Exception('Mask and Stokes images have different image sizes.')
        else:
            # Check the FITS format of mask file;take care of possible extra
            # axes like correlation or frequency
            if (len(numpy.shape(maskdata))>2):
               try:
                   maskdata = maskdata.reshape(params.dec_lim[1] - \
                       params.dec_lim[0],params.ra_lim[1] - params.ra_lim[0])
               except:
                   raise Exception('Incompatible number of axes in Mask file.')
                   
            # Extract the submask as specified by ra, dec limits
            maskimage = maskdata[decsz[0]:decsz[1], rasz[0]:rasz[1]]
    
    nchan = thead.get('NAXIS' + freq_axnum)
    if options.rest_freq and nchan != 1:
        raise Exception('rest_freq option is only valid for files with one \
            frequency.')

    if options.stokes_v:
        vcube = create_memmap_file_and_array(vcube_mmfn,
            (len(fns) * nchan, decsz[1] - decsz[0], rasz[1] - rasz[0]),
            numpy.dtype('float64'))

    if options.separate_stokes:
        nsb = len(fns_q)
    else:
        nsb = len(fns)

    cube = create_memmap_file_and_array(incube_mmfn,
       (nsb * nchan, decsz[1] - decsz[0], rasz[1] - rasz[0]),
       numpy.dtype('complex128'))

    params.nu = numpy.zeros(nsb * nchan)

    # This gets overwritten later for rest_freq mode!
    # store the channel width, in Hz
    params.dnu = thead.get('CDELT' + freq_axnum)

    if (params.weight is not None and len(params.weight) != len(params.nu)):
        raise Exception('number of frequency channels in weight list is not ' +
                        'compatible with input visibilities.')
    if params.weight is None:
        params.weight = numpy.ones(len(params.nu))

    params()
    print ' '
    print '-----------------------'
    print ' '
    print 'Reading fits files into one big cube, ' +\
        'converting Q & U to complex...'
    progress(20, 0)

    if not options.separate_stokes:

        for indx in range(len(fns)):
            fn = fns[indx]
            tdata = pyfits.getdata(params.input_dir + fn)
            thead = pyfits.getheader(params.input_dir + fn)
            base_indx = nchan * indx

            if not options.freq_last:
                if tdata.shape[0] == 4:
                    # Read Stokes Q and U into the complex cube
                    cube.real[base_indx:base_indx + nchan] = \
                        tdata[1, :, decsz[0]:decsz[1], rasz[0]:rasz[1]]

                    cube.imag[base_indx:base_indx + nchan] = \
                        tdata[2, :, decsz[0]:decsz[1], rasz[0]:rasz[1]]

                    # XXX: The commented code above isn't the appropriate way
                    #   to deal with weights. Hand params.weight to the
                    #   RMSynth class init instead. This has been fixed

                else:
                    # There are not 4 stokes parameters, and that is not OK
                    raise Exception('Invalid data shape!')
                if options.stokes_v:
                    vcube[base_indx:base_indx + nchan] = \
                        tdata[3, :, decsz[0]:decsz[1], rasz[0]:rasz[1]]
            else:
                if tdata.shape[1] == 4:
                    cube.real[base_indx:base_indx + nchan] = \
                        tdata[:, 1, decsz[0]:decsz[1], rasz[0]:rasz[1]]

                    cube.imag[base_indx:base_indx + nchan] = \
                        tdata[:, 2, decsz[0]:decsz[1], rasz[0]:rasz[1]]
                else:
                    raise Exception('Invalid data shape!')
                if options.stokes_v:
                    vcube[base_indx:base_indx + nchan] = \
                        tdata[:, 3, decsz[0]:decsz[1], rasz[0]:rasz[1]]

            if options.rest_freq:
                if nchan != 1:
                    msg = 'When the rest frequency option is selected, ' + \
                        'only one channel is allowed per file!'
                    raise Exception(msg)
                params.nu[base_indx] = thead.get('RESTFREQ')
            else:
                flist = numpy.arange(nchan) * thead.get('CDELT' + freq_axnum) \
                    + thead.get('CRVAL' + freq_axnum)
                params.nu[base_indx:base_indx + nchan] = flist

            pcent = 100. * (indx + 1.) / len(fns)
            progress(20, pcent)
            del tdata

    else:
        # Separate Stokes has been requested...
        for indx in range(len(fns_q)):
            fnq = fns_q[indx]
            fnu = fns_u[indx]
            tdata_q = pyfits.getdata(params.input_dir + qsubdir + fnq)
            thead_q = pyfits.getheader(params.input_dir + qsubdir + fnq)
            tdata_u = pyfits.getdata(params.input_dir + usubdir + fnu)
            thead_u = pyfits.getheader(params.input_dir + usubdir + fnu)  
            if options.rest_freq:
                try:
                    q_restfreq = thead_q['RESTFREQ']
                    u_restfreq = thead_u['RESTFREQ']
                except KeyError:
                    q_restfreq = thead_q['RESTFRQ']
                    u_restfreq = thead_u['RESTFRQ']
                if q_restfreq != u_restfreq:
                    raise Exception('Something went wrong!  I am trying ' +
                        'to combine Q & U images at different frequencies!')
            else:
                if options.freq_last:
                    if thead_q['CRVAL4'] != thead_u['CRVAL4']:
                        raise Exception('Something went wrong!  I am ' +
                            'trying to combine Q & U images at different ' +
                            'frequencies!')
                else:
                    if thead_q['CRVAL3'] != thead_u['CRVAL3']:
                        raise Exception('Something went wrong!  I am trying ' +
                            'to combine Q & U images at different ' +
                            'frequencies!')

            base_indx = nchan * indx

            if not options.freq_last:
                if tdata_q.shape[0] == 1:
                    cube.real[base_indx:base_indx + nchan] = \
                        tdata_q[0, :, decsz[0]:decsz[1], rasz[0]:rasz[1]]

                    cube.imag[base_indx:base_indx + nchan] = \
                        tdata_u[0, :, decsz[0]:decsz[1], rasz[0]:rasz[1]]
                else:
                    raise Exception('Invalid data shape!')
            else:
                if tdata_q.shape[1] == 1:
                    cube.real[base_indx:base_indx + nchan] = \
                        tdata_q[:, 0, decsz[0]:decsz[1], rasz[0]:rasz[1]]

                    cube.imag[base_indx:base_indx + nchan] = \
                        tdata_u[:, 0, decsz[0]:decsz[1], rasz[0]:rasz[1]]
                else:
                    raise Exception('Invalid data shape!')

            if options.rest_freq:
                if nchan != 1:
                    msg = 'When the rest frequency option is selected, ' + \
                        'only one channel is allowed per file!'
                    raise Exception(msg)
                try:
                    params.nu[base_indx] = thead_q['RESTFREQ']
                except KeyError:
                    params.nu[base_indx] = thead_q['RESTFRQ']
            else:
                if nchan != 1:
                    flist = numpy.arange(nchan) *\
                        thead_q.get('CDELT' + freq_axnum) +\
                        thead_q.get('CRVAL' + freq_axnum)
                    params.nu[base_indx:base_indx + nchan] = flist
                else:
                    # When each fits file has a separate Q or U image, CDELT
                    # cannot be used to estimate the frequency values.
                    params.nu[base_indx] = thead_q.get('CRVAL'+freq_axnum)

            pcent = 100. * (indx + 1.) / len(fns_q)
            progress(20, pcent)
            del tdata_q
            del tdata_u

    if options.separate_stokes:
        thead = thead_q
        # SARRVESH'S EDIT
        if nchan == 1:
            params.dnu = thead_q['CDELT'+freq_axnum]

    if options.rest_freq:
        # SARRVESH'S EDIT
        # dnu can be estimated using optical velocity information in 
        # the FITS header. But this works only with images produced 
        # by AWImager and WSClean. Have to be tested with other imagers
        if thead_q['CTYPE'+freq_axnum] == 'VOPT' and thead_q['CUNIT'+freq_axnum] == 'm/s':
            velocity = thead_q['CDELT'+freq_axnum]
            C = 299792458. # light speed in m/s
            params.dnu = (params.nu[0])/(1-(velocity/C)) - params.nu[0]
        else:         
            # FIXME: This isn't very general and could lead to problems.
            params.dnu = params.nu[1] - params.nu[0]
    
    
    # Print out basic parameters    
    C2 = 8.98755179e16
    nus = numpy.sort(params.nu)
    dnu = params.dnu
    delta_l2 = C2 * (nus[0] ** (-2) - nus[len(nus) - 1] ** (-2))
    l2min = 0.5 * C2 * ((nus[len(nus) - 1] + dnu) ** (-2)
                        + (nus[len(nus) - 1] - dnu) ** (-2))

    res = 2. * math.sqrt(3) / delta_l2
    maxscale = numpy.pi / l2min
    
    print "\n"
    
    print "The maximum theroretical resolution for the given" +\
        " set of parameters is " +str(round(res)) + " rad/m^2"
    
    print "The maximum observable scale for the given set of parameters" +\
        " is " +str(round(maxscale)) + " rad/m^2" 
    print "\n"
    
    # If requested, produce an array containing the spectral index information
    # and apply it
    
    if params.alpha:
        
        if params.alphafromfile:
            alphadata = pyfits.getdata(params.alpha)
            if numpy.shape(alphadata) != (decsz[1]-decsz[0], rasz[1]-rasz[0]):
                try:
                    alpha = alphadata.reshape((decsz[1]-decsz[0], rasz[1]-rasz[0]))
                except ValueError:
                    raise Exception('Size of the spectral index image is inconsestent with parameter inputs.')  
            else:
                alpha=alphadata
            
        else:
            alpha = params.alpha
    
        # set rest frequency to mean frequency across band
        if params.ref_freq == None:
            #params.ref_freq = numpy.mean(nus)
            params.ref_freq = nus[0]

        # Rescale cube with spectral dependence function s, assuming 
        # separability of the spectrally dependent Faraday spectrum, 
        # following de Bruyn & Brentjens 2005. Division already by
        # lambda2 dependence despite the array still being ordered
        # in frequency.
    
        #PROBLEM: HOW TO TRANSLATE THE SPECTRUM? CORRECT THIS WAY?
        
        for k in range(len(nus)):
            cube[k] /= (nus[k]/params.ref_freq)**(-alpha)
    
        
    # initialize the RMSynth class that does all the work
    rms = R.RMSynth(params.nu, params.dnu, params.phi, params.weight)
    print "Done!"

    # Write out the RMSF to a text file
    rmsfout = numpy.zeros((len(rms.rmsf), 3))
    rmsfout[:, 0] = rms.rmsf_phi
    rmsfout[:, 1] = rms.rmsf.real
    rmsfout[:, 2] = rms.rmsf.imag
    numpy.savetxt(params.outputfn + '_rmsf.txt', rmsfout)

    if options.stokes_v:
        print 'Writing Stokes V cube...'
        hdu_v = pyfits.PrimaryHDU(vcube)
        try:
            generate_v_header(hdu_v, thead, params)
        except:
            print "Warning: There was a problem generating the header, " + \
                "no header information stored!"
            print "Unexpected error:", sys.exc_info()[0]
        hdu_v_list = pyfits.HDUList([hdu_v])
        hdu_v_list.writeto(params.outputfn + '_v.fits', clobber=True)

        f = open(params.outputfn + '_freqlist.txt', 'wb')
        Writer = csv.writer(f, delimiter=' ')
        for i in range(len(fns) * nchan):
            Writer.writerow([str(params.nu[i]), fns[i / nchan]])
        f.close()
        print 'Done!'
        print 'Cleaning up Stokes V temp files...'
        del vcube
        os.remove(vcube_mmfn)

    if options.plot_rmsf:
        plot_rmsf(rms)

    # in case i just want the RMS class and raw data back to e.g. analyze
    # single lines of sight
    if manual:
        return rms, cube

    # dirty image
    dicube = create_memmap_file_and_array(outcube_mmfn,
        (len(params.phi), len(cube[0]), len(cube[0][0])),
        numpy.dtype('complex128'))
    
    if params.do_clean:
        # To store a master list of clean components for the entire cube
        cclist = list()
        
        rescube = create_memmap_file_and_array(rescube_mmfn,
            (len(params.phi), len(cube[0]), len(cube[0][0])),
            numpy.dtype('complex128'))
            
        cleancube = create_memmap_file_and_array(cleancube_mmfn,
            (len(params.phi), len(cube[0]), len(cube[0][0])),
            numpy.dtype('complex128'))

        cccube = create_memmap_file_and_array(cccube_mmfn,
            (len(params.phi), len(cube[0]), len(cube[0][0])),
            numpy.dtype('complex128'))
            
    print 'Performing synthesis...'
    progress(20, 0)

    if params.do_clean:
        # initialize the CLEAN class once, reuse for each LOS
        # In doing so, the CLEAN beam convolution kernel is only computed once
        rmc = R.RMClean(rms, params.niter, params.gain, params.cutoff)

    for indx in range(decsz[1] - decsz[0]):
        for jndx in range(rasz[1] - rasz[0]):
            if maskimage[indx, jndx] != 0:
                los = cube[:, indx, jndx]

                if params.do_clean:
                    rmc.reset()
                    rmc.perform_clean(los)
                    rmc.restore_clean_map()
                    cleancube[:, indx, jndx] = rmc.clean_map.copy()
                    rescube[:, indx, jndx] = rmc.residual_map.copy()
                    dicube[:, indx, jndx] = rmc.dirty_image.copy()
                    for kndx in range(len(rmc.cc_phi_list)):
                        cclist.append([rmc.cc_phi_list[kndx][0], indx, jndx,
                            rmc.cc_val_list[kndx].real,
                            rmc.cc_val_list[kndx].imag])
                        # SARRVESH'S EDIT
                        cccube[:, indx, jndx] = rmc.cc_add_list.copy()
                else:
                    dicube[:, indx, jndx] = rms.compute_dirty_image(los)
            else:
                dicube[:, indx, jndx] = numpy.zeros((params.nphi,))
                if params.do_clean:
                    cleancube[:, indx, jndx] = numpy.zeros((params.nphi,))
                    rescube[:, indx, jndx] = numpy.zeros((params.nphi,))
                    
        pcent = 100. * (indx + 1.) * (jndx + 1.) / (rasz[1] - rasz[0]) /\
             (decsz[1] - decsz[0])
        progress(20, pcent)

    if params.do_clean:  
        print '\n'  
        print "The fitted FWHM of the clean beam is " +str(round(rmc.sdev,2)) + " rad/m^2"
        print '\n'

    print 'RM synthesis done!  Writing out FITS files...'
    write_output_files(dicube, params, thead, 'di')
    if params.do_clean:
        write_output_files(rescube, params, thead, 'residual')
        write_output_files(cleancube, params, thead, 'clean')
        write_output_files(cccube, params, thead, 'cc')
        print 'Writing out CC list...'
        write_output_files(cccube, params, thead, 'cc')
        # TODO: need to make this usable!
        #   it doesn't work right now because there are just way too many CCs

        #write_cc_list(cclist, params.outputfn+"_cc.txt")

    polintmap = create_memmap_file_and_array(pmap_mmfn, \
            (decsz[1]-decsz[0], rasz[1]-rasz[0]), numpy.dtype('float64'))
    phimap = create_memmap_file_and_array(phimap_mmfn, \
            (decsz[1]-decsz[0], rasz[1]-rasz[0]), numpy.dtype('float64'))
    qmap = create_memmap_file_and_array(qmap_mmfn, \
            (decsz[1]-decsz[0], rasz[1]-rasz[0]), numpy.dtype('float64'))
    umap = create_memmap_file_and_array(umap_mmfn, \
            (decsz[1]-decsz[0], rasz[1]-rasz[0]), numpy.dtype('float64'))
    print 'Computing polarized intensity and Faraday depth maps'
    for indx in range(decsz[1]-decsz[0]):
        for jndx in range(rasz[1]-rasz[0]):
            if maskimage[indx, jndx] != 0:
                if params.do_clean:
                    q_los = cleancube[:, indx, jndx].real
                    u_los = cleancube[:, indx, jndx].imag
                else:
                    q_los = dicube[:, indx, jndx].real
                    u_los = dicube[:, indx, jndx]. imag
                p_los = numpy.sqrt(numpy.add(numpy.square(q_los), numpy.square(u_los)))
                if numpy.amax(p_los) > params.threshold:
                    polintmap[indx, jndx] = numpy.amax(p_los)
                    indx_max_polint = numpy.argmax(p_los)
                    phimap[indx, jndx] = params.phi[indx_max_polint]
                    qmap[indx, jndx] = q_los[indx_max_polint]
                    umap[indx, jndx] = u_los[indx_max_polint]
                else:
                    polintmap[indx, jndx] = numpy.nan
                    phimap[indx, jndx] = numpy.nan
                    qmap[indx, jndx] = numpy.nan
                    umap[indx, jndx] = numpy.nan
            else:
                polintmap[indx, jndx] = numpy.nan
                phimap[indx, jndx] = numpy.nan
                qmap[indx, jndx] = numpy.nan
                umap[indx, jndx] = numpy.nan
    
    print 'Writing polarized intensity and Faraday depth maps'
    write_output_maps(polintmap, params, thead, 'polint')
    write_output_maps(phimap, params, thead, 'phi', 'rad/m/m')
    write_output_maps(qmap, params, thead, 'qmap')
    write_output_maps(umap, params, thead, 'umap')

    print 'Cleaning up temp files...'
    del dicube
    del cube
    if params.do_clean:
        del cleancube
        del rescube
    os.remove(incube_mmfn)
    os.remove(outcube_mmfn)
    os.remove(pmap_mmfn)
    os.remove(phimap_mmfn)
    os.remove(qmap_mmfn)
    os.remove(umap_mmfn)
    if params.do_clean:
        os.remove(cleancube_mmfn)
        os.remove(rescube_mmfn)
        os.remove(cccube_mmfn)

    print 'Done!'


def write_cc_list(cclist, fn):
    """ Pass a RMClean object that contains a cc list and write it to file.
        Now DEPRECATED with the new cc list FITS output.    
    
    """

    cclist_redux = list()
    # Add up all of the components that are at the same location.
    while len(cclist) > 0:
        entry = cclist.pop(0)
        # savetxt will not write the entire complex number, so i need to
        # store the real and imag parts separately.
#        entry = [entry[0], entry[1], entry[2], entry[3].real, entry[3].imag]

        # contains the indices of ccs that are at the same spot
        indices = list()
        for i in range(len(cclist)):
            if cclist[i][0] == entry[0] and cclist[i][1] == entry[1] and \
                cclist[i][2] == entry[2]:
                    indices.append(i)

        while len(indices) > 0:
            indx = indices.pop()
            dup = cclist.pop(indx)
            if dup[0] == entry[0] and dup[1] == entry[1] and \
                dup[2] == entry[2]:
                    entry[3] += dup[3]
                    entry[4] += dup[4]
            else:
                raise Exception('Problem when writing the cclist!')

        cclist_redux.append(entry)
    f = open(fn, 'w')
    numpy.savetxt(f, cclist_redux)
    f.close()


def plot_rmsf(rms):
    """
    """

    pylab.plot(rms.rmsf_phi, abs(rms.rmsf))
    pylab.title('RMSF')
    pylab.xlabel('$\phi$ (rad/m/m)')
    pylab.show()


def write_output_maps(image, params, inhead, typename, bunit='JY/BEAM'):
    """
    Write out 2D maps to FITS files.
    """
    hdu = pyfits.PrimaryHDU(image)
    try:
        generate_header(hdu, inhead, params)
        # set the appropriate unit for pixel values
        hdu.header['BUNIT'] = bunit
    except:
        print "Warning: There was a problem generating the header, no " + \
            "header information stored!"
        print "Unexpected error:", sys.exc_info()[0]
    try:
        # remove the 3rd axis
        hdu.header.__delitem__('CTYPE3')
        hdu.header.__delitem__('CRVAL3')
        hdu.header.__delitem__('CDELT3')
        hdu.header.__delitem__('CRPIX3')
        hdu.header.__delitem__('CROTA3')
        hdu.header.__delitem__('NAXIS3')
        hdu.header.__delitem__('CUNIT3')
    except KeyError: pass
    hdu_list = pyfits.HDUList([hdu])
    hdu_list.writeto(params.outputfn + '_' + typename + '.fits', clobber=True)

def write_output_files(cube, params, inhead, typename):
    """
    """

    hdu_q = pyfits.PrimaryHDU(cube.real)
    generate_header(hdu_q, inhead, params)
    try:
        generate_header(hdu_q, inhead, params)
    except:
        print "Warning: There was a problem generating the header, no " + \
            "header information stored!"
        print "Unexpected error:", sys.exc_info()[0]
    hdu_q_list = pyfits.HDUList([hdu_q])
    hdu_q_list.writeto(params.outputfn + '_' + typename +  '_q.fits', clobber=True)

    hdu_main = pyfits.PrimaryHDU(cube.imag)
    try:
        generate_header(hdu_main, inhead, params)
    except:
        print "Warning: There was a problem generating the header, no " + \
            "header information stored!"
        print "Unexpected error:", sys.exc_info()[0]
    hdu_list = pyfits.HDUList([hdu_main])
    hdu_list.writeto(params.outputfn + '_' + typename + '_u.fits', clobber=True)

    hdu_p = pyfits.PrimaryHDU(abs(cube))
    try:
        generate_header(hdu_p, inhead, params)
    except:
        print "Warning: There was a problem generating the header, no " + \
            "header information stored!"
        print "Unexpected error:", sys.exc_info()[0]
    hdu_p_list = pyfits.HDUList([hdu_p])
    hdu_p_list.writeto(params.outputfn + '_' + typename + '_p.fits', clobber=True)


def generate_v_header(hdu, inhead, params):
    """
    """

    today = datetime.datetime.today()

    hdu.header = inhead.copy()

    hdu.header.update('ORIGIN', 'rmsynthesis.py', 'Origin of the data set')
    hdu.header.update('DATE', str(today), 'Date when the file was created')
    hdu.header.update('NAXIS', 3,
                      'Number of axes in the data array, must be 3')
    hdu.header.update('NAXIS3', params.nu.size, 'Length of the Frequency axis')
    # In FITS, the first pixel is 1, not 0!!!
    hdu.header.update('CRPIX3', 1, 'Reference pixel')
    hdu.header.update('CRVAL3', params.nu[0])
    hdu.header.update('CDELT3', params.dnu)
    hdu.header.add_history('RMSYNTH: Stokes V cube generated by ' +
                           'rmsynthesis.py version ' +
                           str(VERSION) + '.')
    hdu.header.add_history('   WARNING! The frequency axis is not linear. ' +
                           'Look in the')
    hdu.header.add_history('   accompanying _freqlist.txt file for ' +
                           'frequency axis information')

    # Get the reference pixel for the new image
    cpix_ra = (params.ra_lim[1] - params.ra_lim[0]) / 2. + 1.
    cpix_dec = (params.dec_lim[1] - params.dec_lim[0]) / 2. + 1.
    # Get the index of the new reference pixel in the old image
    cpix_ra_old = params.ra_lim[0] + cpix_ra - 1
    cpix_dec_old = params.dec_lim[1] - cpix_dec + 1
    # Find its sky coordinate
    wcs = WCS(inhead)
    if inhead['NAXIS'] == 4:
        crval_ra = wcs.wcs_pix2sky([[cpix_ra_old, cpix_dec_old, 0, 0]], 0)[0][0]
        crval_dec= wcs.wcs_pix2sky([[cpix_ra_old, cpix_dec_old, 0, 0]], 0)[0][1]
    if inhead['NAXIS'] == 3:
        crval_ra = wcs.wcs_pix2sky([[cpix_ra_old, cpix_dec_old, 0]], 0)[0][0]
        crval_dec= wcs.wcs_pix2sky([[cpix_ra_old, cpix_dec_old, 0]], 0)[0][1]

    hdu.header.update('NAXIS1', params.ra_lim[1] - params.ra_lim[0])
    hdu.header.update('CRVAL1', crval_ra)
    hdu.header.update('CRPIX1', cpix_ra)
    hdu.header.update('NAXIS2', params.dec_lim[1] - params.dec_lim[0])
    hdu.header.update('CRVAL2', crval_dec)
    hdu.header.update('CRPIX2', cpix_dec)

    try:
       hdu.header.__delitem__('NAXIS4')
       hdu.header.__delitem__('CTYPE4')
       hdu.header.__delitem__('CRVAL4')
       hdu.header.__delitem__('CRPIX4')
       hdu.header.__delitem__('CDELT4')
       hdu.header.__delitem__('CUNIT4')
    except: pass

def generate_header(hdu, inhead, params):
    """
    """

    today = datetime.datetime.today()
    hdu.header = inhead.copy()

    hdu.header.set('ORIGIN', 'rmsynthesis.py', 'Origin of the data set')
    hdu.header.set('DATE', str(today), 'Date when the file was created')
    hdu.header.set('NAXIS', 3,
                      'Number of axes in the data array, must be 3')
    hdu.header.set('NAXIS3', params.nphi,
                      'Length of the Faraday depth axis')
    hdu.header.set('CTYPE3', 'Phi', 'Axis type')
    hdu.header.set('CUNIT3', 'rad/m/m', 'Axis units')
    # In FITS, the first pixel is 1, not 0!!!
    hdu.header.set('CRPIX3', 1, 'Reference pixel')
    hdu.header.set('CRVAL3', params.phi_min, 'Reference value')
    hdu.header.set('CDELT3', params.dphi, 'Size of pixel bin')
    
    # Get the reference pixel for the new image
    cpix_ra = (params.ra_lim[1] - params.ra_lim[0]) / 2. + 1.
    cpix_dec = (params.dec_lim[1] - params.dec_lim[0]) / 2. + 1.
    # Get the index of the new reference pixel in the old image
    cpix_ra_old = params.ra_lim[0] + cpix_ra - 1
    cpix_dec_old = params.dec_lim[1] - cpix_dec + 1
    # Find its sky coordinate
    wcs = WCS(inhead)
    if inhead['NAXIS'] == 4:
        crval_ra = wcs.wcs_pix2sky([[cpix_ra_old, cpix_dec_old, 0, 0]], 0)[0][0]
        crval_dec= wcs.wcs_pix2sky([[cpix_ra_old, cpix_dec_old, 0, 0]], 0)[0][1]
    if inhead['NAXIS'] == 3:
        crval_ra = wcs.wcs_pix2sky([[cpix_ra_old, cpix_dec_old, 0]], 0)[0][0]
        crval_dec= wcs.wcs_pix2sky([[cpix_ra_old, cpix_dec_old, 0]], 0)[0][1]

    hdu.header.set('CRVAL1', crval_ra)
    hdu.header.set('CRPIX1', cpix_ra)
    hdu.header.set('NAXIS1', params.ra_lim[1] - params.ra_lim[0])
    hdu.header.set('CRVAL2', crval_dec)
    hdu.header.set('CRPIX2', cpix_dec)
    hdu.header.set('NAXIS2', params.dec_lim[1] - params.dec_lim[0])

    C2 = 8.98755179e16
    nus = numpy.sort(params.nu)
    dnu = params.dnu
    delta_l2 = C2 * (nus[0] ** (-2) - nus[len(nus) - 1] ** (-2))
    l2min = 0.5 * C2 * ((nus[len(nus) - 1] + dnu) ** (-2)
                        + (nus[len(nus) - 1] - dnu) ** (-2))

    rmsf = 2. * math.sqrt(3) / delta_l2
    maxscale = numpy.pi / l2min

    hdu.header.set('TFFWHM', round(rmsf,2), 'Theoretical FWHM of the RMSF ' +
        ', rad/m/m')
    hdu.header.set('MAXSCL', round(maxscale, 2), 'Maximum scale in ' +
        'Faraday depth rad/m/m')

    hdu.header.add_history('RMSYNTH: RM Synthesis performed by ' +
                           'rmsynthesis.py version ' + str(VERSION) + '.')
    if params.do_clean:
        hdu.header.add_history('   RM Clean performed. niter=' +
                               str(params.niter) +
                               ', gain=' + str(params.gain) + ', cutoff=' +
                               str(params.cutoff))
    else:
        hdu.header.add_history('   No RM Clean performed.')
    hdu.header.add_history('   See the accompanying _rmsf.txt for ' +
                           'RMSF information.')
    try:
       hdu.header.__delitem__('NAXIS4')
       hdu.header.__delitem__('CTYPE4')
       hdu.header.__delitem__('CRVAL4')
       hdu.header.__delitem__('CRPIX4')
       hdu.header.__delitem__('CDELT4')
       hdu.header.__delitem__('CUNIT4')
    except: pass

def create_memmap_file_and_array(fn, SHAPE, DTYPE):
    """
    Creates an empty numpy memmap array and the associated file on disk.
    """

    if numpy.isscalar(SHAPE):
        npix = SHAPE
    else:
        npix = 1
        for i in range(len(SHAPE)):
            npix = npix * SHAPE[i]

    with open(fn, 'wb') as f:
        # OPEN THE FILE, SKIP TO THE END, AND WRITE A 0
        # Quickly creates an empty file on disk.
        f.seek(npix * DTYPE.itemsize - 1)
        f.write('\x00')

    m = numpy.memmap(fn, dtype=DTYPE, shape=SHAPE)

    return m


def parse_input_file(infile):
    """ parse the parameter file.  Does not handle weights yet."""

    params = Params()

    reader = csv.reader(open(infile, 'rb'), delimiter=" ",
                        skipinitialspace=True)
    parset = dict()

    for row in reader:
        if len(row) != 0 and row[0] != '%':
            parset[row[0]] = row[1]

    params.cutoff = float(parset['cutoff'])
    params.dec_lim = [int(parset['dec_min']), int(parset['dec_max'])]
    params.ra_lim = [int(parset['ra_min']), int(parset['ra_max'])]

    params.phi_min = float(parset['phi_min'])
    params.nphi = int(parset['nphi'])
    params.dphi = float(parset['dphi'])
    temp = numpy.arange(params.nphi)
    params.phi = params.phi_min + temp * params.dphi
    
    if 'imagemask' in parset:
        params.imagemask = parset['imagemask']
    else:
        params.imagemask = ''

    if parset['do_clean'].lower() == 'false':
        params.do_clean = False
    else:
        params.do_clean = True

    params.gain = float(parset['gain'])
    params.niter = int(parset['niter'])
    params.outputfn = parset['outputfn']
    params.input_dir = parset['input_dir']

    params.alphafromfile = False
    if 'alpha' in parset:
        try:
            params.alpha = numpy.float(parset['alpha'])
        except ValueError:
            params.alphafromfile = True
            params.alpha = parset['alpha']
    else:
        params.alpha = False

    if 'ref_freq' in parset:
        params.ref_freq = numpy.float(parset['ref_freq'])
    else:
        params.ref_freq = None
    
    if 'do_weight' in parset:
        params.weight = numpy.loadtxt(params.input_dir + parset['do_weight'])
        print 'Non-trivial weights enabled! Loaded from ' + parset['do_weight']

    return params

if __name__ == '__main__':
    """ Handle all parsing here if started from the command line"""

    parser = OptionParser(usage="%prog <input parameter file>",
                          version="%prog " + VERSION)
    parser.add_option("-p", "--plot_rmsf", action="store_true",
                      dest="plot_rmsf",
                      help="Plot the RMSF as soon as it is computed.",
                      default=False)
    parser.add_option("-V", "--stokes_v", action="store_true",
                      dest="stokes_v",
                      help="Produce a Stokes V cube after reading the " +
                      "fits files.",
                      default=False)
    parser.add_option("-s", "--separate_stokes", action="store_true",
                      dest="separate_stokes",
                      help="Indicate that the Stokes Q and U input images " +
                      "are stored in separate FITS files.",
                      default=False)
    parser.add_option("-f", "--freq_last", action="store_true",
                      dest="freq_last", help="Indicate that NAXIS4 is the " +
                      "frequency axis.",
                      default=False)
    parser.add_option("-r", "--rest_freq", action="store_true",
                      dest="rest_freq", help="Indicate that the frequency " +
                      "for an image is " +
                      "given in the RESTFREQ header keyword.", default=False)

    (options, args) = parser.parse_args()

    if len(args) != 1:
        parser.error("Incorrect number of arguments")

    print "rmsynthesis.py ver. " + VERSION
    print "Written by Michael Bell & Henrik Junklewitz"
    print ""
    print "Parsing parameter file..."
    params = parse_input_file(args[0])

    rmsynthesis(params, options)
