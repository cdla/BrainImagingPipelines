from nipype.utils.config import config
config.enable_debug_mode()
import nipype.interfaces.fsl as fsl         # fsl
import nipype.algorithms.rapidart as ra     # rapid artifact detection
from nipype.interfaces.nipy.preprocess import FmriRealign4d
from nipype.workflows.smri.freesurfer.utils import create_getmask_flow
from nipype.workflows.fmri.fsl import create_susan_smooth
from config import *
from utils import *

def create_filter_matrix(motion_params, composite_norm,
                         compcorr_components, art_outliers, selector):
    """Combine nuisance regressor components into a single file
    """
    import numpy as np
    import os
    if not len(selector) == 5:
        print "selector is not the right size!"
        return None

    def try_import(fname):
        try:
            a = np.genfromtxt(fname)
            return a
        except:
            return np.array([])

    options = np.array([motion_params, composite_norm,
                        compcorr_components, art_outliers])
    selector = np.array(selector)

    splitter = np.vectorize(lambda x: os.path.split(x)[1])
    filenames = ['%s' % item for item in \
                        splitter(options[selector[:-1]])]
    filter_file = os.path.abspath("filter+%s+outliers.txt"%"+".join(filenames))

    z = None

    for i, opt in enumerate(options[:-1][selector[:-2]]):
    # concatenate all files except art_outliers and motion_derivs
        if i ==0:
            z = try_import(opt)

        else:
            a = try_import(opt)
            if len(a.shape)==1:
                a = np.array([a]).T
            z = np.hstack((z,a))

    if selector[-2]:
        #import outlier file
        outliers = try_import(art_outliers)
        if outliers.shape[0] == 0: # empty art file
            out = z
        elif outliers.shape ==(): # 1 outlier
            art = np.zeros((z.shape[0],1))
            art[np.int_(outliers)-1,0] = 1
            out = np.hstack((z,art))
        else: # >1 outlier
            art = np.zeros((z.shape[0],outliers.shape[0]))
            for j,t in enumerate(a):
                art[np.int_(t)-1,j] = 1
            out = np.hstack((z,art))
    else:
        out = z

    if selector[-1]: # this is the motion_derivs bool
            a = try_import(motion_params)
            temp = np.zeros(a.shape)
            temp[1:,:] = np.diff(a,axis = 0)
            out = np.hstack((out,temp))

    print out.shape
    np.savetxt(filter_file,out)
    return filter_file


def create_prep(name='preproc'):
    """
    Description.
    """
    preproc = pe.Workflow(name=name)

    # Compcorr node
    compcor = create_compcorr()

    # Input node
    inputnode = pe.Node(util.IdentityInterface(fields=['fssubject_id',
                                                      'fssubject_dir',
                                                      'func',
                                                      'highpass',
                                                      'num_noise_components']),
                        name='inputspec')

    # Separate input node for FWHM
    inputnode_fwhm = pe.Node(util.IdentityInterface(fields = ['fwhm']),
                             name = 'fwhm_input')

    # convert BOLD images to float
    img2float = pe.MapNode(interface=fsl.ImageMaths(out_data_type='float',
                                                    op_string = '',
                                                    suffix='_dtype'),
                           iterfield=['in_file'],
                           name='img2float')

    # define the motion correction node
    motion_correct = pe.MapNode(interface=FmriRealign4d(),
                                name='realign',
                                iterfield=['in_file'])


    # construct motion plots
    plot_motion = pe.MapNode(interface=fsl.PlotMotionParams(in_source='fsl'),
                             name='plot_motion',
                             iterfield=['in_file'])

    # rapidArt for artifactual timepoint detection
    ad = pe.Node(ra.ArtifactDetect(),
                 name='artifactdetect')

    # extract the mean volume if the first functional run
    meanfunc = pe.Node(fsl.MeanImage(),
                       name='mean_image')

    # generate a freesurfer workflow that will return the mask
    getmask = create_getmask_flow()

    # create a SUSAN smoothing workflow, and smooth each run with
    # 75% of the median value for each run as the brightness
    # threshold.
    smooth = create_susan_smooth(name="smooth_with_susan",
                                 separate_masks=False)

    # choose susan function
    """
    The following node selects smooth or unsmoothed data 
    depending on the fwhm. This is because SUSAN defaults
    to smoothing the data with about the voxel size of 
    the input data if the fwhm parameter is less than 1/3 of 
    the voxel size.
    """
    choosesusan = pe.Node(util.Function(input_names = ['fwhm',
                                                       'motion_files',
                                                       'smoothed_files'],
                                        output_names = ['cor_smoothed_files'],
                                        function = choose_susan),
                          name = 'select_smooth')

    # scale the median value of each run to 10,000
    meanscale = pe.MapNode(interface=fsl.ImageMaths(suffix='_gms'),
                           iterfield=['in_file',
                                      'op_string'],
                           name='scale_median')

    # determine the median value of the MASKED functional runs
    medianval = pe.MapNode(interface=fsl.ImageStats(op_string='-k %s -p 50'),
                           iterfield = ['in_file'],
                           name='compute_median_val')

    # temporal highpass filtering
    highpass = pe.MapNode(interface=fsl.ImageMaths(suffix='_tempfilt'),
                          iterfield=['in_file'],
                          name='highpass')

    # declare some node inputs...
    plot_motion.iterables = ('plot_type', ['rotations', 'translations'])
    ad.inputs.norm_threshold = norm_thresh
    ad.inputs.parameter_source = 'FSL'
    ad.inputs.zintensity_threshold = z_thresh
    ad.inputs.mask_type = 'file'
    ad.inputs.use_differences = [True, False]
    getmask.inputs.inputspec.contrast_type = 't2'
    motion_correct.inputs.tr = TR
    motion_correct.inputs.interleaved = Interleaved
    motion_correct.inputs.slice_order = SliceOrder
    compcor.inputs.inputspec.selector = compcor_select
    fssource = getmask.get_node('fssource')

    # make connections...
    preproc.connect(inputnode, 'fssubject_id',
                    getmask, 'inputspec.subject_id')
    preproc.connect(inputnode, 'fssubject_dir',
                    getmask, 'inputspec.subjects_dir')
    preproc.connect(inputnode, 'func',
                    img2float, 'in_file')
    preproc.connect(img2float, ('out_file',tolist),
                    motion_correct, 'in_file')
    preproc.connect(motion_correct, 'par_file',
                    plot_motion, 'in_file')
    preproc.connect(motion_correct, ('out_file', pickfirst),
                    meanfunc, 'in_file')
    preproc.connect(meanfunc, 'out_file',
                    getmask, 'inputspec.source_file')
    preproc.connect(inputnode, 'num_noise_components',
                    compcor, 'inputspec.num_components')
    preproc.connect(motion_correct, 'out_file',
                    compcor, 'inputspec.realigned_file')
    preproc.connect(motion_correct, 'out_file',
                    compcor, 'inputspec.in_file')
    preproc.connect(fssource, 'aseg',
                    compcor, 'inputspec.fsaseg_file')
    preproc.connect(getmask, 'outputspec.reg_file',
                    compcor, 'inputspec.reg_file')
    preproc.connect(motion_correct, 'out_file',
                    ad, 'realigned_files')
    preproc.connect(motion_correct, 'par_file',
                    ad, 'realignment_parameters')
    preproc.connect(getmask, ('outputspec.mask_file',pickfirst),
                    ad, 'mask_file')
    preproc.connect(getmask, ('outputspec.mask_file',pickfirst),
                    medianval, 'mask_file')
    preproc.connect(inputnode_fwhm, 'fwhm',
                    smooth, 'inputnode.fwhm')
    preproc.connect(motion_correct, 'out_file',
                    smooth, 'inputnode.in_files')
    preproc.connect(getmask, ('outputspec.mask_file',pickfirst),
                    smooth, 'inputnode.mask_file')
    preproc.connect(smooth, 'outputnode.smoothed_files',
                    choosesusan, 'smoothed_files')
    preproc.connect(motion_correct, 'out_file',
                    choosesusan, 'motion_files')
    preproc.connect(inputnode_fwhm, 'fwhm',
                    choosesusan, 'fwhm')
    preproc.connect(choosesusan, 'cor_smoothed_files',
                    meanscale, 'in_file')
    preproc.connect(choosesusan, 'cor_smoothed_files',
                    medianval, 'in_file')
    preproc.connect(medianval, ('out_stat', getmeanscale),
                    meanscale, 'op_string')
    preproc.connect(inputnode, ('highpass', highpass_operand),
                    highpass, 'op_string')
    preproc.connect(meanscale, 'out_file',
                    highpass, 'in_file')

    # create output node
    outputnode = pe.Node(interface=util.IdentityInterface(
        fields=['reference',
                'motion_parameters',
                'realigned_files',
                'mask',
                'smoothed_files',
                'highpassed_files',
                'mean',
                'combined_motion',
                'outlier_files',
                'mask',
                'reg_cost',
                'reg_file',
                'noise_components',
                'tsnr_file',
                'stddev_file',
                'filter_file',
                'scaled_files']),
                        name='outputspec')

    # make output connection
    preproc.connect(meanfunc, 'out_file',
                    outputnode, 'reference')
    preproc.connect(motion_correct, 'par_file',
                    outputnode, 'motion_parameters')
    preproc.connect(motion_correct, 'out_file',
                    outputnode, 'realigned_files')
    preproc.connect(highpass, 'out_file',
                    outputnode, 'highpassed_files')
    preproc.connect(meanfunc, 'out_file',
                    outputnode, 'mean')
    preproc.connect(ad, 'norm_files',
                    outputnode, 'combined_motion')
    preproc.connect(ad, 'outlier_files',
                    outputnode, 'outlier_files')
    preproc.connect(compcor, 'outputspec.noise_components',
                    outputnode, 'noise_components')
    preproc.connect(getmask, 'outputspec.mask_file',
                    outputnode, 'mask')
    preproc.connect(getmask, 'outputspec.reg_file',
                    outputnode, 'reg_file')
    preproc.connect(getmask, 'outputspec.reg_cost',
                    outputnode, 'reg_cost')
    preproc.connect(choosesusan, 'cor_smoothed_files',
                    outputnode, 'smoothed_files')
    preproc.connect(compcor, 'outputspec.tsnr_file',
                    outputnode, 'tsnr_file')
    preproc.connect(compcor, 'outputspec.stddev_file',
                    outputnode, 'stddev_file')

    return preproc
    
