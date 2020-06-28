import os

from vae.vae_model import VAE
import vae.losses as lo
import inout.input_data_reader as idr
import inout.sample_factory as sf
import util.jet_sample as js
import util.experiment as ex


# ********************************************************
#               runtime params
# ********************************************************

run_n = 0
data_sample = 'img-local'
sample_id = 'GtoWW35na'

experiment = ex.Experiment(run_n).setup(result_dir=True)
paths = sf.SamplePathFactory(experiment,data_sample)

# ********************************************
#               read test data (images)
# ********************************************

data_reader = idr.InputDataReader(paths.sample_path(sample_id))
test_sample = js.JetSample.from_feature_array(sample_id, *data_reader.read_dijet_features())
test_img_j1, test_img_j2 = data_reader.read_images( )

# ********************************************
#               load model
# ********************************************

vae = VAE(run=run_n,model_dir=experiment.model_dir)
vae.load()

# *******************************************************
#               predict test data
# *******************************************************

reco_img_j1, z_mean_j1, z_log_var_j1 = vae.predict_with_latent( test_img_j1 )
reco_img_j2, z_mean_j2, z_log_var_j2 = vae.predict_with_latent( test_img_j2 )

# *******************************************************
#               compute losses
# *******************************************************

losses_j1 = lo.compute_loss_of_prediction_mse_kl(test_img_j1, reco_img_j1, z_mean_j1, z_log_var_j1)
losses_j2 = lo.compute_loss_of_prediction_mse_kl(test_img_j2, reco_img_j2, z_mean_j2, z_log_var_j2)

# *******************************************************
#               add losses to DataSample and save
# *******************************************************

for loss, label in zip( losses_j1, ['j1TotalLoss', 'j1RecoLoss', 'j1KlLoss']):
    test_sample.add_feature(label,loss)
for loss, label in zip( losses_j2, ['j2TotalLoss', 'j2RecoLoss', 'j2KlLoss']):
    test_sample.add_feature(label,loss)

test_sample.dump(paths.result_path(sample_id))

