"""
Example using a hybrid model structure (1 cortical hemisphere + subcortical WM)
and simulated multi-PLD ASL with simulated variable CBF activation on cortex
"""

import os
import sys 
import argparse

import numpy as np
import scipy.interpolate
import tensorflow as tf
import nibabel as nib
import pyvista as pv

import vaby
from vaby_models_asl import AslRestModel 

cli = argparse.ArgumentParser()
cli.add_argument("--method", help="Inference method", choices=["avb", "svb"], default="svb")
cli.add_argument("--wm-cbf", help="Ground truth WM CBF", type=float, default=20.0)
cli.add_argument("--gm-cbf", help="Ground truth cortical mean CBF", type=float, default=60.0)
cli.add_argument("--gm-cbf-var", help="Variation in cortical CBF", type=float, default=60.0)
cli.add_argument("--wm-att", help="Ground truth WM ATT", type=float, default=1.6)
cli.add_argument("--gm-att", help="Ground truth cortical ATT", type=float, default=1.3)
cli.add_argument("--plds", help="PLDs", default="0.75, 1.0, 1.25, 1.5, 1.75, 2.0")
cli.add_argument("--repeats", help="Number of repeats", type=int, default=1)
cli.add_argument("--cort-inner", help="Gifti file containing cortex inner surface", default="tk/103818.L.mid.32k_fs_LR.surf.gii")
cli.add_argument("--cort-outer", help="Gifti file containing cortex outer surface", default="tk/103818.L.very_inflated.32k_fs_LR.surf.gii")
cli.add_argument("--cort-inflated", help="Gifti file containing cortex inflated surface", default="tk/103818.L.very_inflated.32k_fs_LR.surf.gii")
cli.add_argument("--projector", help="Pre-computed projection file", default="tk/103818_L_hemi.h5")
cli.add_argument("--wm-pvs", help="Nifti file containing WM partial volumes", default="tk/wm_pv.nii.gz")
cli.add_argument("--mask", help="Nifti file containing analysis mask", default="tk/mask.nii.gz")
cli.add_argument("--noise", help="Ground truth noise amplitude (std dev)", type=float, default=5)
cli.add_argument("--spatial", help="Use spatial smoothing on CBF", action="store_true", default=False)
cli.add_argument("--epochs", help="Number of epochs for SVB", type=int, default=300)
cli.add_argument("--sample-size", help="Sample size for SVB", type=int, default=20)
cli.add_argument("--learning-rate", help="Learning rate for SVB", type=float, default=0.2)
cli.add_argument("--iterations", help="Number of iterations for AVB", type=int, default=50)
cli.add_argument("--rseed", help="Random number seed to give reproducible results", type=int)
cli.add_argument("--debug", help="Debug logging", action="store_true", default=False)
cli.add_argument("--plot", help="Show output graphically", action="store_true", default=False)
opts = cli.parse_args()

if opts.rseed:
    np.random.seed(opts.rseed)
    tf.random.set_seed(opts.rseed)

opts.plds = [float(pld) for pld in opts.plds.split(",")]
options={
    "method" : opts.method,
    "mask" : opts.mask,
    "plds": opts.plds, 
    "repeats": opts.repeats, 
    "casl": True,
    "save_mean" : True,
    "save_model_fit" : True,
    "save_input_data" : True,
    "save_total_pv" : True,
    "save_native" : True,
    "save_model" : True,
    "model_structures" : [
        {
            "name" : "L",
            "type" : "CorticalSurface",
            "white" : opts.cort_inner,
            "pial" : opts.cort_outer,
            "projector" : opts.projector,
            #"save-projector" : "hybrid_example_projector.h5",
        },
        {
            "name" : "WM",
            "type" : "PartialVolumes",
            "vol_data" : opts.wm_pvs,
            "mask" : opts.mask,
        },
    ],
    "debug" : opts.debug,
    "save_log" : True,
    "log_stream" : sys.stdout,   
}

# Create data model for simulating data. Note that the acquisition data is just
# used to define the acquisition data space so doesn't need to be a proper timeseries
data_model = vaby.DataModel(opts.wm_pvs, **options)

# Generate sinusoidally modulated 3D volume. This will be used to modulate the CBF
# on the cortex to simulate variable activation
inds = np.indices(data_model.data_space.shape)
scale = 2
sine = (np.sin(inds[1] / scale) 
        + np.sin(inds[0] / scale) 
        + np.sin(inds[2] / scale))
sine = sine / sine.max()

# To assign modulated data to cortical nodes we need co-ordinates. We
# use the inflated surface for this to give a smooth variation
# FIXME maybe possible to embed co-ordinate generation into model structure?
from toblerone.classes import Surface
inflated = Surface(opts.cort_inflated, "inflated")
inflated = inflated.transform(data_model.model_space.parts[0].projector.spc.world2vox)
ctx_sine = scipy.interpolate.interpn(
        points=[ np.arange(d) for d in data_model.data_space.shape ], 
        values=sine, 
        xi=inflated.points,
    )
ctx_cbf = opts.gm_cbf + (opts.gm_cbf_var * ctx_sine)
ctx_att = opts.gm_att * np.ones_like(ctx_cbf)

# Generate simulated model data
asl_model = AslRestModel(data_model, **options)
tpts = asl_model.tpts()
wm_size = data_model.model_space.parts[1].size

cbf = np.concatenate([ctx_cbf, opts.wm_cbf * np.ones(wm_size)])[..., np.newaxis].astype(np.float32)
att = np.concatenate([ctx_att, opts.wm_att * np.ones(wm_size)])[..., np.newaxis].astype(np.float32)
data = asl_model.evaluate([cbf, att], tpts)

# Add noise in acquisition space
noise_std_truth = opts.noise
noise_var_truth = noise_std_truth**2
noise_prec_truth = 1/noise_var_truth
#SNR = 100 # realistic is about 10 - 20
#N_VAR = 42 * np.sqrt(len(opts.plds) * opts.repeats) / SNR 
data_vol = data_model.model_to_data(data, pv_scale=True)
data_vol += np.random.normal(0, noise_std_truth, data_vol.shape)
data_model.data_space.save_data(data_vol, "hybrid_example_asl_data_noisy")

# Run inference
if opts.method == "svb":
    options.update({
        "epochs" : opts.epochs,
        "learning_rate" : opts.learning_rate,
        "batch_size" : len(opts.plds),
        "sample_size" : opts.sample_size,
    })
elif opts.method == "avb":
    options.update({
        "max_iterations" : opts.iterations,
    })

if opts.spatial:
    options["param_overrides"] = {
        "ftiss" : {
            "prior_type" : "M",
        }
    }
    options["output"] = f"hybrid_asl_example_{opts.method}_spatial_out"
else:
    options["output"] = f"hybrid_asl_example_{opts.method}_nonspatial_out"

runtime, inf = vaby.run("hybrid_example_asl_data_noisy.nii.gz", "aslrest", **options)

# Save noiseless ground truth timeseries
data_model.save_model_data(data.numpy(), "hybrid_example_asl_data_clean", options['output'], save_model=True, save_native=True, pv_scale=True)

# Save ground truth cortial CBF
data_model.model_space.parts[0].save_data(ctx_cbf, 'true_ftiss', options['output'])

# Plot true and predicted CBF
if opts.plot:
    faces = 3 * np.ones((inflated.tris.shape[0], 4), dtype=int)
    faces[:,1:] = inflated.tris 

    plotter = pv.Plotter(shape=(1, 2))

    plotter.subplot(0, 0)
    plotter.add_text("Estimated CBF", font_size=10)
    cbf_output = nib.load(os.path.join(options["output"], 'mean_ftiss_L.func.gii')).darrays[0].data
    plotter.add_mesh(pv.PolyData(inflated.points, faces=faces), scalars=cbf_output, clim=(0, 100), scalar_bar_args={'title': 'Estimated CBF'}, show_scalar_bar=True)
    plotter.add_axes(interactive=True)

    plotter.subplot(0, 1)
    plotter.add_text("True CBF", font_size=10)
    plotter.add_mesh(pv.PolyData(inflated.points, faces=faces), scalars=ctx_cbf, clim=(0, 100), scalar_bar_args={'title': 'True CBF'}, show_scalar_bar=True)
    plotter.add_axes(interactive=True)

    # Display the window
    plotter.show()
    #mesh.plot(color='lightgrey', clim=(0, 100), pbr=True, scalars=cbf_output, window_size=(600, 400))
    #mesh.plot(color='lightgrey', clim=(0, 100), pbr=True, scalars=ctx_cbf, window_size=(600, 400))