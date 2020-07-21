import tensorflow as tf
import os

from vae.vae_model import VAE
from vae.vae_model import Sampling
from vae.losses import *

# custom 1d transposed convolution that expands to 2d output for vae decoder
class Conv1DTranspose(tf.keras.layers.Layer):

    def __init__(self, filters, kernel_size, activation, **kwargs):
        super(Conv1DTranspose,self).__init__(**kwargs)
        self.kernel_size = kernel_size
        self.filters = filters
        self.activation = activation
        self.ExpandChannel = tf.keras.layers.Lambda(lambda x: tf.expand_dims(x, axis=2))
        self.ConvTranspose = tf.keras.layers.Conv2DTranspose(filters=self.filters, kernel_size=(self.kernel_size,1), activation=self.activation)
        self.SqueezeChannel = tf.keras.layers.Lambda(lambda x: tf.squeeze(x, axis=2))

    def call(self, inputs):
        # expand input and kernel to 2D
        x = self.ExpandChannel(inputs) # [ B x 98 x 4 ] -> [ B x 98 x 1 x 4 ]
        # call Conv2DTranspose
        x = self.ConvTranspose(x)
        # squeeze back to 1D and return
        x = self.SqueezeChannel(x)
        return x

    def get_config(self):
        config = super(Conv1DTranspose, self).get_config()
        config.update({'kernel_size': self.kernel_size, 'filters': self.filters, 'activation': self.activation})
        return config


class VAE_3D( VAE ):

    def __init__(self,**kwargs):
        super(VAE_3D,self).__init__(**kwargs)
        self.input_shape = (100,3)

    def load( self ):
        self.encoder = tf.keras.models.load_model(os.path.join(self.model_dir, 'encoder.h5'), custom_objects={'Conv1DTranspose':Conv1DTranspose, 'threeD_kl_loss': threeD_kl_loss, 'threeD_loss': threeD_loss, 'kl_loss': kl_loss,'sampling': self.sampling})
        self.decoder = tf.keras.models.load_model(os.path.join(self.model_dir, 'decoder.h5'), custom_objects={'Conv1DTranspose':Conv1DTranspose, 'threeD_kl_loss': threeD_kl_loss, 'threeD_loss': threeD_loss, 'kl_loss': kl_loss})
        self.model = tf.keras.models.load_model(os.path.join(self.model_dir, 'vae.h5'), custom_objects={'Conv1DTranspose':Conv1DTranspose, 'threeD_kl_loss': threeD_kl_loss, 'threeD_loss': threeD_loss, 'kl_loss': kl_loss,'loss': tf.keras.losses.mse, 'sampling': self.sampling})


    def compile(self,model):
        loss = ThreeD_KL_Loss(self.z_mean, self.z_log_var)
        model.compile(optimizer='adam', loss=loss, metrics=[loss.threeD_loss, loss.kl_loss], experimental_run_tf_function=False)  # , metrics=loss_metrics monitor mse and kl terms of loss 'rmsprop'


    # ***********************************
    #               encoder
    # ***********************************
    def build_encoder(self, inputs):
        # normalize
        self.norm_layer = tf.keras.layers.experimental.preprocessing.Normalization()
        x = self.norm_layer(inputs)
        # add channel dim
        x = tf.keras.layers.Lambda(lambda x: tf.expand_dims(x, axis=3))(x) # [B x 100 x 3] => [B x 100 x 3 x 1]
        # 2D Conv
        x = tf.keras.layers.Conv2D(filters=self.filter_n, kernel_size=self.kernel_size, activation='relu', kernel_regularizer=self.regularizer)(x)
        # Squeeze
        x = tf.keras.layers.Lambda(lambda x: tf.squeeze(x, axis=2))(x)  # remove width axis for 1D Conv [ B x 98 x 1 x filter_n ] -> [ B x 98 x filter_n ]
        # 1D Conv * 2
        self.filter_n += 4
        x = tf.keras.layers.Conv1D(filters=self.filter_n, kernel_size=self.kernel_size, activation='relu', kernel_regularizer=self.regularizer)(x) # [ B x 96 x 10 ]
        self.filter_n += 4
        x = tf.keras.layers.Conv1D(filters=self.filter_n, kernel_size=self.kernel_size, activation='relu', kernel_regularizer=self.regularizer)(x) # [ B x 94 x 14 ]
        # Pool
        x = tf.keras.layers.AveragePooling1D()(x) # [ B x 47 x 14 ]
        # shape info needed to build decoder model
        self.shape_convolved = x.get_shape().as_list()
        # Flatten
        x = tf.keras.layers.Flatten()(x)
        # Dense * 3
        x = tf.keras.layers.Dense(np.prod(self.shape_convolved[1:]) // 17, activation='relu', kernel_regularizer=self.regularizer)(x)  # reduce convolution output
        x = tf.keras.layers.Dense(np.prod(self.shape_convolved[1:]) // 42, activation='relu', kernel_regularizer=self.regularizer)(x)  # reduce again
        # x = Dense(8, activation='relu')(x)

        # *****************************
        #         latent space
        # generate latent vector Q(z|X)

        self.z_mean = tf.keras.layers.Dense(self.z_size, name='z_mean', kernel_regularizer=self.regularizer)(x)
        self.z_log_var = tf.keras.layers.Dense(self.z_size, name='z_log_var', kernel_regularizer=self.regularizer)(x)

        # use reparameterization trick to push the sampling out as input
        self.sampling = Sampling()
        z = self.sampling((self.z_mean, self.z_log_var))

        # instantiate encoder model
        encoder = tf.keras.Model(inputs, [self.z_mean, self.z_log_var, z], name='encoder')
        encoder.summary()
        # plot_model(encoder, to_file=CONFIG['plotdir']+'vae_cnn_encoder.png', show_shapes=True)
        return encoder

    # ***********************************
    #           decoder
    # ***********************************
    def build_decoder(self):
        latent_inputs = tf.keras.layers.Input(shape=(self.z_size,), name='z_sampling')
        # Dense * 3
        x = tf.keras.layers.Dense(np.prod(self.shape_convolved[1:]) // 42, activation='relu', kernel_regularizer=self.regularizer)(latent_inputs)  # inflate to input-shape/200
        x = tf.keras.layers.Dense(np.prod(self.shape_convolved[1:]) // 17, activation='relu', kernel_regularizer=self.regularizer)(x)  # double size
        x = tf.keras.layers.Dense(np.prod(self.shape_convolved[1:]), activation='relu', kernel_regularizer=self.regularizer)(x)
        # Reshape
        x = tf.keras.layers.Reshape(tuple(self.shape_convolved[1:]))(x)
        # Upsample
        x = tf.keras.layers.UpSampling1D()(x) # [ B x 94 x 16 ]
        # 1D Conv Transpose * 2
        self.filter_n -= 4
        x = Conv1DTranspose(filters=self.filter_n, kernel_size=self.kernel_size, activation='relu')(x) # [ B x 94 x 16 ] -> [ B x 96 x 8 ]
        self.filter_n -= 4
        x = Conv1DTranspose(filters=self.filter_n, kernel_size=self.kernel_size, activation='relu')(x) # [ B x 96 x 8 ] -> [ B x 98 x 4 ]
        # Expand
        x = tf.keras.layers.Lambda(lambda x: tf.expand_dims(x,axis=2))(x) #  [ B x 98 x 1 x 4 ]
        # 2D Conv Transpose
        x = tf.keras.layers.Conv2DTranspose(filters=1, kernel_size=self.kernel_size, activation=tf.keras.activations.elu, kernel_regularizer=self.regularizer, name='conv_2d_transpose')(x)
        x = tf.keras.layers.Lambda(lambda x: tf.squeeze(x, axis=3), name='decoder_output')(x)
        outputs_decoder = tf.keras.layers.Lambda(lambda x: x * tf.sqrt(self.norm_layer.variance) + self.norm_layer.mean)(x)

        # instantiate decoder model
        decoder = tf.keras.Model(latent_inputs, outputs_decoder, name='decoder')
        decoder.summary()
        # plot_model(decoder, to_file=CONFIG['plotdir'] + 'vae_cnn_decoder.png', show_shapes=True)
        return decoder


    def fit( self, x, y, epochs=3, verbose=2 ):
        callbacks = [tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=7, verbose=1),tf.keras.callbacks.ReduceLROnPlateau(monitor='val_loss', factor=0.1, patience=2, verbose=1),tf.keras.callbacks.TerminateOnNaN(),
                     ] #TensorBoard(log_dir=self.log_dir, histogram_freq=1)
        self.norm_layer.adapt(x) # compute mean and variance of Normalization Layer
        self.history = self.model.fit(x, y, batch_size=self.batch_size, epochs=epochs, verbose=verbose, callbacks=callbacks, validation_split=0.25)
        return self.history

