"""
Example inferring a single biexponential decay model
"""
import argparse
import sys

import numpy as np
import tensorflow as tf

import vaby 

cli = argparse.ArgumentParser()
cli.add_argument("--method", help="Inference method", choices=["avb", "svb"], default="avb")
cli.add_argument("--amp1", help="Ground truth amplitude 1", type=float, default=42.0)
cli.add_argument("--rate1", help="Ground truth decay rate 1", type=float, default=1.0)
cli.add_argument("--amp2", help="Ground truth amplitude 2", type=float, default=42.0)
cli.add_argument("--rate2", help="Ground truth decay rate 2", type=float, default=0.1)
cli.add_argument("--dt", help="Time resolution", type=float, default=0.1)
cli.add_argument("--nt", help="Number of time points", type=int, default=100)
cli.add_argument("--size", help="Approximate number of data examples", type=int, default=100)
cli.add_argument("--noise", help="Ground truth noise amplitude (std dev)", type=float, default=5)
cli.add_argument("--rseed", help="Random number seed to give reproducible results", type=int)
cli.add_argument("--debug", help="Debug logging", action="store_true", default=False)
cli.add_argument("--fabber", help="Run Fabber as a comparison", action="store_true", default=False)
cli.add_argument("--plot", help="Show output graphically", action="store_true", default=False)
opts = cli.parse_args()

if opts.rseed:
    np.random.seed(opts.rseed)
    tf.random.set_seed(opts.rseed)

# Ground truth parameters
PARAMS_TRUTH = [opts.amp1, opts.rate1, opts.amp2, opts.rate2]
NOISE_STD_TRUTH = opts.noise
NOISE_VAR_TRUTH = NOISE_STD_TRUTH**2
NOISE_PREC_TRUTH = 1/NOISE_VAR_TRUTH
print("Ground truth: a=%s, r=%s, noise=%f (std.dev.)" % (PARAMS_TRUTH[::2], PARAMS_TRUTH[1::2], NOISE_STD_TRUTH))

# Observed data samples are generated by Numpy from the ground truth
# Gaussian distribution. Reducing the number of samples should make
# the inference less 'confident' - i.e. the output variances for
# MU and BETA will increase
temp_model = vaby.get_model_class("biexp")(None, dt=opts.dt)
t = np.array([float(t)*opts.dt for t in range(opts.nt)])
DATA_CLEAN = temp_model.evaluate(PARAMS_TRUTH, t).numpy()
DATA_NOISY = DATA_CLEAN + np.random.normal(0, NOISE_STD_TRUTH, [opts.nt])

options = {
    "method" : opts.method,
    "dt" : opts.dt,
    "save_mean" : True,
    "save_model_fit" : True,
    "save_input_data" : True,
    "save_total_pv" : True,
    "save_native" : True,
    "save_model" : True,
    "output" : "biexp_example_out",
    "debug" : opts.debug,
    "log_stream" : sys.stdout,
}

if opts.method == "svb":
    options.update({
        "epochs" : 300,
        "learning_rate" : 0.1,
        "sample_size" : 5,
        "batch_size" : 10,
    })
elif opts.method == "avb":
    options.update({
        "max_iterations" : 200,
    })

runtime, state = vaby.run(DATA_NOISY, "biexp", **options)

if opts.fabber:
    import os
    import nibabel as nib
    niidata = DATA_NOISY.reshape((1, 1, 1, opts.nt))
    nii = nib.Nifti1Image(niidata, np.identity(4))
    nii.to_filename("data_noisy.nii.gz")
    os.system("fabber_exp --data=data_noisy --print-free-energy --save-model-fit --output=biexp_example_fabber_out --dt=%.3f --model=exp --num-exps=2 --method=vb --max-iterations=50 --noise=white --overwrite --debug" % opts.dt)
    fabber_modelfit = nib.load("exp_example_fabber_out/modelfit.nii.gz").get_fdata().reshape([opts.nt])

if opts.plot:
    from matplotlib import pyplot as plt
    plt.figure(1)
    plt.title("Example inference of biexponential")
    plt.plot(t, DATA_CLEAN, "b-", label="Ground truth")
    plt.plot(t, DATA_NOISY, "kx", label="Noisy samples", )
    plt.plot(t, state["modelfit"][0], "g--", label="Model fit")
    if opts.fabber:
        plt.plot(t, fabber_modelfit, "r--", label="Fabber model fit")
    plt.legend()
    plt.show()
