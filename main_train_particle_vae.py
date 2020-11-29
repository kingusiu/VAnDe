import os
import setGPU
import numpy as np
from collections import namedtuple
import tensorflow as tf
print('tensorflow version: ', tf.__version__)

import vae.vae_particle as vap
import vae.losses as losses
import pofah.path_constants.sample_dict_file_parts_input as sdi
import pofah.util.experiment as expe
import pofah.util.sample_factory as safa
import util.data_generator as dage
import sarewt.data_reader as dare


# ********************************************************
#       runtime params
# ********************************************************

Parameters = namedtuple('Parameters', 'run_n beta train_sz batch_sz regularizer')
params = Parameters(run_n=104, beta=0.01, train_sz=1e4, batch_sz=256, regularizer=None) # 'L1L2'
loss = losses.make_threeD_kl_loss #losses.make_mse_kl_loss
reco_loss = losses.threeD_loss #losses.mse_loss
experiment = expe.Experiment(params.run_n).setup(model_dir=True, fig_dir=True)
paths = safa.SamplePathDirFactory(sdi.path_dict)

# ********************************************************
#       prepare training (generator) and validation data
# ********************************************************

#train
data_train_generator = dage.DataGenerator(paths.sample_dir_path('qcdSide')) # generate 10 M jet samples
data_train = tf.data.Dataset.from_generator(data_train_generator, output_types=(tf.float32, tf.float32)).take(int(params.train_sz)).batch(params.batch_sz, drop_remainder=True) # already shuffled
# validation
data_reader = dare.DataReader(paths.sample_dir_path('qcdSideExt'))
data_valid = tf.data.Dataset.from_tensor_slices(data_train_generator.get_next_sample_chunk(data_reader.read_constituents_from_dir(max_n=5e5))) #.batch(params.batch_sz, drop_remainder=True) # validate on half a million samples
# stats for normalization layer
mean_stdev = data_train_generator.get_mean_and_stdev()

# *******************************************************
#                       build model
# *******************************************************

vae = vap.VAEparticle(input_shape=(100,3), z_sz=10, filter_ini_n=6, kernel_sz=3, loss=loss, reco_loss=reco_loss, batch_sz=params.batch_sz, beta=params.beta, regularizer=params.regularizer)
vae.build(mean_stdev)

# *******************************************************
#                       train and save
# *******************************************************

#vae.fit(data_train, epochs=300, validation_data=data_valid, verbose=2)
vae.fit(data_train, epochs=300, verbose=2)
vae.plot_training(experiment.fig_dir)
vae.save(path=experiment.model_dir)