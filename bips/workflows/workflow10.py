# Import Stuff
import nipype.interfaces.utility as util    # utility
import nipype.pipeline.engine as pe         # pypeline engine
import nipype.interfaces.io as nio          # input/output
from nipype.algorithms.modelgen import SpecifyModel
from .scripts.u0a14c5b5899911e1bca80023dfa375f2.base import create_first
import os
from .base import MetaWorkflow, load_config, register_workflow
from traits.api import HasTraits, Directory, Bool, Button
import traits.api as traits

# Define MetaWorkflow

mwf = MetaWorkflow()
mwf.uuid = '8efdb2a08f1711e1b160001e4fb1404c'
mwf.help="""
 First-Level Workflow
 ====================

 """
mwf.tags=['fMRI','First Level']

# Define Config

class config(HasTraits):
    uuid = traits.Str(desc="UUID")
    desc = traits.Str(desc="Workflow Description")
    # Directories
    working_dir = Directory(mandatory=True, desc="Location of the Nipype working directory")
    sink_dir = Directory(mandatory=True, desc="Location where the BIP will store the results")
    crash_dir = Directory(mandatory=False, desc="Location to store crash files")
    json_sink = Directory(mandatory=False, desc= "Location to store json_files")
    surf_dir = Directory(mandatory=True, desc= "Freesurfer subjects directory")

    # Execution

    run_using_plugin = Bool(False, usedefault=True, desc="True to run pipeline with plugin, False to run serially")
    plugin = traits.Enum("PBS", "MultiProc", "SGE", "Condor",
        usedefault=True,
        desc="plugin to use, if run_using_plugin=True")
    plugin_args = traits.Dict({"qsub_args": "-q many"},
        usedefault=True, desc='Plugin arguments.')
    test_mode = Bool(False, mandatory=False, usedefault=True,
        desc='Affects whether where and if the workflow keeps its \
                            intermediary files. True to keep intermediary files. ')

    # Subjects

    subjects= traits.List(traits.Str, mandatory=True, usedefault=True,
        desc="Subject id's. Note: These MUST match the subject id's in the \
                                Freesurfer directory. For simplicity, the subject id's should \
                                also match with the location of individual functional files.")

    # First Level

    subjectinfo = traits.Code()
    contrasts = traits.Code()
    interscan_interval = traits.Float()
    film_threshold = traits.Float()

    # preprocessing info
    preproc_config = traits.File(desc="preproc config file")

def create_config():
    c = config()
    c.uuid = mwf.uuid
    c.desc = mwf.help
    return c

mwf.config_ui = create_config

def preproc_datagrabber(name='preproc_datagrabber'):
    # create a node to obtain the preproc files
    datasource = pe.Node(interface=nio.DataGrabber(infields=['subject_id','fwhm'],
                                                   outfields=['noise_components',
                                                              'motion_parameters',
                                                               'highpassed_files',
                                                               'outlier_files']),
                         name = name)
    datasource.inputs.base_directory = os.path.join(c.sink_dir,'analyses','func')
    datasource.inputs.template ='*'
    datasource.inputs.field_template = dict(noise_components='%s/preproc/noise_components/*/noise_components.txt',
                                            motion_parameters='%s/preproc/motion/*.par',
                                            highpassed_files='%s/preproc/highpass/fwhm_%d/*/*.nii.gz',
                                            outlier_files='%s/preproc/art/*_outliers.txt')
    datasource.inputs.template_args = dict(noise_components=[['subject_id']],
                                           motion_parameters=[['subject_id']],
                                           highpassed_files=[['subject_id','fwhm']],
                                           outlier_files=[['subject_id']])
    return datasource

def trad_mot(subinfo,files):
    # modified to work with only one regressor at a time...
    import numpy as np
    motion_params = []
    mot_par_names = ['Pitch (rad)','Roll (rad)','Yaw (rad)','Tx (mm)','Ty (mm)','Tz (mm)']
    if not isinstance(files,list):
        files = [files]
    if not isinstance(subinfo,list):
        subinfo = [subinfo]
    for j,i in enumerate(files):
        motion_params.append([[],[],[],[],[],[]])
        #k = map(lambda x: float(x), filter(lambda y: y!='',open(i,'r').read().replace('\n',' ').split(' ')))
        print i
        a = np.genfromtxt(i)
        for z in range(6):
            motion_params[j][z] = a[:,z].tolist()#k[z:len(k):6]
        
    for j,i in enumerate(subinfo):
        if i.regressor_names == None: i.regressor_names = []
        if i.regressors == None: i.regressors = []
        for j3, i3 in enumerate(motion_params[j]):
            i.regressor_names.append(mot_par_names[j3])
            i.regressors.append(i3)
    return subinfo

def noise_mot(subinfo,files,num_noise_components):
    noi_reg_names = map(lambda x: 'noise_comp_'+str(x+1),range(num_noise_components))
    noise_regressors = []
    if not isinstance(files,list):
        files = [files]
    for j,i in enumerate(files):
        noise_regressors.append([[]]*num_noise_components)
        k = map(lambda x: float(x), filter(lambda y: y!='',open(i,'r').read().replace('\n',' ').split(' ')))
        for z in range(num_noise_components):
            noise_regressors[j][z] = k[z:len(k):num_noise_components]
    for j,i in enumerate(subinfo):
        if i.regressor_names == None: i.regressor_names = []
        if i.regressors == None: i.regressors = []
        for j3,i3 in enumerate(noise_regressors[j]):
            i.regressor_names.append(noi_reg_names[j3])
            i.regressors.append(i3)
    return subinfo

# First level modeling

def combine_wkflw(c,prep_c, name='work_dir'):
    
    modelflow = pe.Workflow(name=name)
    modelflow.base_dir = os.path.join(c.working_dir)
    
    preproc = preproc_datagrabber()
    
    infosource = pe.Node(util.IdentityInterface(fields=['subject_id']),
                         name='subject_names')

    if c.test_mode:
        infosource.iterables = ('subject_id', [c.subjects[0]])
    else:
        infosource.iterables = ('subject_id', c.subjects)

    modelflow.connect(infosource,'subject_id',preproc,'subject_id')
    preproc.iterables = ('fwhm', prep_c.fwhm)
    
    def getsubs(subject_id,getcontrasts,subjectinfo,fwhm):
        #from config import getcontrasts, get_run_numbers, subjectinfo, fwhm
        subs = [('_subject_id_%s/'%subject_id,''),
                ('_plot_type_',''),
                ('_fwhm','fwhm'),
                ('_dtype_mcf_mask_mean','_mean'),
                ('_dtype_mcf_mask_smooth_mask_gms_tempfilt','_smoothed_preprocessed'),
                ('_dtype_mcf_mask_gms_tempfilt','_unsmoothed_preprocessed'),
                ('_dtype_mcf','_mcf')]
        
        for i in range(4):
            subs.append(('_plot_motion%d'%i, ''))
            subs.append(('_highpass%d/'%i, ''))
            subs.append(('_realign%d/'%i, ''))
            subs.append(('_meanfunc2%d/'%i, ''))
        cons = getcontrasts(subject_id)
        info = subjectinfo(subject_id)
        runs = range(len(info))
        for i, run in enumerate(runs):
            subs.append(('_modelestimate%d/'%i, '_run_%d_%02d_'%(i,run)))
            subs.append(('_modelgen%d/'%i, '_run_%d_%02d_'%(i,run)))
            subs.append(('_conestimate%d/'%i,'_run_%d_%02d_'%(i,run)))
        for i, con in enumerate(cons):
            subs.append(('cope%d.'%(i+1), 'cope%02d_%s.'%(i+1,con[0])))
            subs.append(('varcope%d.'%(i+1), 'varcope%02d_%s.'%(i+1,con[0])))
            subs.append(('zstat%d.'%(i+1), 'zstat%02d_%s.'%(i+1,con[0])))
            subs.append(('tstat%d.'%(i+1), 'tstat%02d_%s.'%(i+1,con[0])))
        for i, name in enumerate(info[0].conditions):
            subs.append(('pe%d.'%(i+1), 'pe%02d_%s.'%(i+1,name)))
        for i in range(len(info[0].conditions), 256):
            subs.append(('pe%d.'%(i+1), 'others/pe%02d.'%(i+1)))
        for i in fwhm:
            subs.append(('_register%d/'%(i),''))
        
        return subs
    
    # create a node to create the subject info
    s = pe.Node(SpecifyModel(),name='s')
    s.inputs.input_units =                              c.input_units
    s.inputs.time_repetition =                          prep_c.TR
    s.inputs.high_pass_filter_cutoff =                  prep_c.hpcutoff
    #subjinfo =                                          subjectinfo(subj)
    
    
    # create a node to add the traditional (MCFLIRT-derived) motion regressors to 
    # the subject info
    trad_motn = pe.Node(util.Function(input_names=['subinfo',
                                                   'files'],
                                      output_names=['subinfo'],
                                      function=trad_mot),
                        name='trad_motn')

    
    #subjinfo = pe.Node(interface=util.Function(input_names=['subject_id','get_run_numbers'], output_names=['output'], function = c.subjectinfo), name='subjectinfo')
    #subjinfo.inputs.get_run_numbers = c.get_run_numbers
    #modelflow.connect(infosource,'subject_id', 
    #                  subjinfo,'subject_id' )
    #modelflow.connect(subjinfo, 'output',
    #                  trad_motn, 'subinfo')
    
    modelflow.connect(infosource, ('subject_id',c.subjectinfo), trad_motn, 'subinfo')
    
    # create a node to add the principle components of the noise regressors to 
    # the subject info
    noise_motn = pe.Node(util.Function(input_names=['subinfo',
                                                    'files',
                                                    'num_noise_components'],
                                       output_names=['subinfo'],
                                       function=noise_mot),
                         name='noise_motn')
    
    # generate first level analysis workflow
    modelfit =                                          create_first()
    modelfit.inputs.inputspec.interscan_interval =      c.interscan_interval
    modelfit.inputs.inputspec.film_threshold =          c.film_threshold
    
    
    contrasts = pe.Node(util.Function(input_names=['subject_id'], output_names=['contrasts'], function=c.getcontrasts), name='getcontrasts')
    
    modelflow.connect(infosource,'subject_id', 
                     contrasts, 'subject_id')
    modelflow.connect(contrasts,'contrasts', modelfit, 'inputspec.contrasts')
    
    modelfit.inputs.inputspec.bases =                   {'dgamma':{'derivs': False}}
    modelfit.inputs.inputspec.model_serial_correlations = True
    noise_motn.inputs.num_noise_components =           prep_c.num_noise_components
    
    # make a data sink
    sinkd = pe.Node(nio.DataSink(), name='sinkd')
    sinkd.inputs.base_directory = os.path.join(c.sink_dir)
        
    modelflow.connect(infosource, 'subject_id', sinkd, 'container')
    modelflow.connect(infosource, ('subject_id',getsubs, c.getcontrasts, c.subjectinfo, prep_c.fwhm), sinkd, 'substitutions')
    
    sinkd.inputs.regexp_substitutions = [('mask/fwhm_%d/_threshold([0-9]*)/.*nii'%x,'mask/fwhm_%d/funcmask.nii'%x) for x in fwhm]
    sinkd.inputs.regexp_substitutions.append(('realigned/fwhm_([0-9])/_copy_geom([0-9]*)/','realigned/'))
    sinkd.inputs.regexp_substitutions.append(('motion/fwhm_([0-9])/','motion/'))
    sinkd.inputs.regexp_substitutions.append(('bbreg/fwhm_([0-9])/','bbreg/'))
     
    # make connections
    modelflow.connect(preproc, 'motion_parameters',      trad_motn,  'files')
    modelflow.connect(preproc, 'noise_components',       noise_motn, 'files')
    modelflow.connect(preproc, 'highpassed_files',       s,          'functional_runs')
    modelflow.connect(preproc, 'highpassed_files',       modelfit,   'inputspec.functional_data')
    modelflow.connect(preproc, 'outlier_files',          s,          'outlier_files')
    modelflow.connect(trad_motn,'subinfo',                          noise_motn, 'subinfo')
    modelflow.connect(noise_motn,'subinfo',                         s,          'subject_info')
    modelflow.connect(s,'session_info',                             modelfit,   'inputspec.session_info')
    modelflow.connect(modelfit, 'outputspec.parameter_estimates',   sinkd,      'modelfit.estimates')
    modelflow.connect(modelfit, 'outputspec.dof_file',              sinkd,      'modelfit.dofs')
    modelflow.connect(modelfit, 'outputspec.copes',                 sinkd,      'modelfit.contrasts.@copes')
    modelflow.connect(modelfit, 'outputspec.varcopes',              sinkd,      'modelfit.contrasts.@varcopes')
    modelflow.connect(modelfit, 'outputspec.zstats',                sinkd,      'modelfit.contrasts.@zstats')
    modelflow.connect(modelfit, 'outputspec.tstats',                sinkd,      'modelfit.contrasts.@tstats')
    modelflow.connect(modelfit, 'outputspec.design_image',          sinkd,      'modelfit.design')
    modelflow.connect(modelfit, 'outputspec.design_cov',            sinkd,      'modelfit.design.@cov')
    modelflow.connect(modelfit, 'outputspec.design_file',           sinkd,      'modelfit.design.@matrix')
    return modelflow
    
def main(config_file):

    c = load_config(config_file, create_config)
    from .workflow1 import create_config as prep_config
    prep_c = load_config(c.prep_config, prep_config)

    first_level = combine_wkflw(c, prep_c)
    first_level.config = {'execution' : {'crashdump_dir' : c.crash_dir}}
    first_level.base_dir = c.base_dir

    if c.test_mode:
        first_level.write_graph()

    if c.run_using_plugin:
        first_level.run(plugin=c.plugin, plugin_args = c.plugin_args)
    else:
        first_level.run()

def create_view():
    from traitsui.api import View, Item, Group, CSVListEditor
    from traitsui.menu import OKButton, CancelButton
    view = View(Group(Item(name='uuid', style='readonly'),
        Item(name='desc', style='readonly'),
        label='Description', show_border=True),
        Group(Item(name='working_dir'),
            Item(name='sink_dir'),
            Item(name='crash_dir'),
            Item(name='json_sink'),
            label='Directories', show_border=True),
        Group(Item(name='run_using_plugin'),
            Item(name='plugin', enabled_when="run_using_plugin"),
            Item(name='plugin_args', enabled_when="run_using_plugin"),
            Item(name='test_mode'),
            label='Execution Options', show_border=True),
        Group(Item(name='subjects', editor=CSVListEditor()),
            label='Subjects', show_border=True),
        Group(Item(name='interscan_interval'),
              Item(name='film_threshold'),
              Item(name='subjectinfo'),
              Item(name='contrasts'),
            label = 'First Level'),
        Group(Item(name='preproc_config'),
            label = 'Preprocessing Info'),
        buttons = [OKButton, CancelButton],
        resizable=True,
        width=1050)
    return view

mwf.config_view = create_view
register_workflow(mwf)