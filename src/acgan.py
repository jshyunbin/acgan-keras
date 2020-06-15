from __future__ import print_function, division

from keras.layers import Input, Dense, Reshape, Flatten, Dropout, concatenate
from keras.layers import BatchNormalization, Activation, Embedding, ZeroPadding2D
from keras.layers.advanced_activations import LeakyReLU
from keras.layers.convolutional import UpSampling2D, Conv2D, Conv2DTranspose
from keras.models import Sequential, Model, model_from_json
from keras.optimizers import Adam
from PIL import Image
import PIL
import h5py
import matplotlib.pyplot as plt
import tensorflow as tf
import keras
import os
import io
import numpy as np
import utils
import layers

class ACGAN():
    def __init__(self, flags):
        # Input shape
        self.flags = flags
        self.img_rows = 64
        self.img_cols = 64
        self.channels = 3
        self.img_shape = (self.img_rows, self.img_cols, self.channels)
        self.num_classes = 5
        self.latent_dim = 100
        log_path = '../logs/acgan'
        self.writer = tf.summary.FileWriter(log_path)

        dis_opt = Adam(0.0002, 0.5)
        gan_opt = Adam(0.0002, 0.5)
        losses = ['binary_crossentropy', 'binary_crossentropy']

        # Build and compile the discriminator
        if self.flags.load_model is True:
            print('Loading ACGAN model...')
            print('Using epoch %d model' % self.flags.load_model)
            json_file_gen = open('../saved_model/generator.json', 'r')
            json_file_dis = open('../saved_model/discriminator.json', 'r')
            generator_json = json_file_gen.read()
            self.generator = model_from_json(generator_json)
            self.generator.load_weights('../saved_model/generator_%dweights.hdf5' % self.flags.load_model)
            discriminator_json = json_file_dis.read()
            self.discriminator = model_from_json(discriminator_json)
            self.discriminator.load_weights('../saved_model/discriminator_%dweights.hdf5' % self.flags.load_model)
        else:
            self.discriminator = self.build_discriminator()
            self.generator = self.build_generator()
        
        self.discriminator.compile(loss=losses,
            optimizer=dis_opt,
            metrics=['accuracy'])


        # The generator takes noise and the target label as input
        # and generates the corresponding digit of that label
        noise = Input(shape=(self.latent_dim,))
        label = Input(shape=(self.num_classes,))
        img = self.generator([noise, label])

        # For the combined model we will only train the generator
        self.discriminator.trainable = False

        # The discriminator takes generated image as input and determines validity
        # and the label of that image
        valid, target_label = self.discriminator(img)

        # The combined model  (stacked generator and discriminator)
        # Trains the generator to fool the discriminator
        self.combined = Model([noise, label], [valid, target_label])
        self.combined.compile(loss=losses, optimizer=gan_opt)

    def build_generator(self):

        model = Sequential()

        model.add(Dense(512 * 4 * 4, activation="relu", input_dim=self.latent_dim+self.num_classes))
        model.add(Reshape((4, 4, 512)))
        model.add(BatchNormalization())
        model.add(UpSampling2D())
        model.add(Conv2D(256, kernel_size=3, padding='same', kernel_initializer='he_normal'))
        model.add(Activation("relu"))
        model.add(BatchNormalization())
        model.add(UpSampling2D())
        model.add(Conv2D(128, kernel_size=3, padding='same', kernel_initializer='he_normal'))
        model.add(Activation("relu"))
        model.add(BatchNormalization())
        model.add(UpSampling2D())
        model.add(Conv2D(64, kernel_size=3, padding='same', kernel_initializer='he_normal'))
        model.add(Activation("relu"))
        model.add(BatchNormalization())
        model.add(UpSampling2D())
        model.add(Conv2D(self.channels, kernel_size=3, padding='same', kernel_initializer='he_normal'))
        model.add(Activation("tanh"))

        model.summary()

        noise = Input(shape=(self.latent_dim,))
        label = Input(shape=(self.num_classes,))
        
        model_input = concatenate([noise, label], axis=1)
        img = model(model_input)

        return Model([noise, label], img)

    def build_discriminator(self):

        inp = Input([self.img_rows, self.img_rows, self.channels])

        model = Sequential()
        model = layers.d_block(model, 32, init=True)
        model = layers.d_block(model, 64)
        model = layers.d_block(model, 128)
        model = layers.d_block(model, 256)

        model.summary()

        x = model(inp)
        out = Flatten()(x)
        val = Dense(1, activation='sigmoid')(out)
        label = Dense(self.num_classes, activation='sigmoid')(out)
        
        return Model(inp, [val, label])


    def train(self, epochs, batch_size=32, sample_interval=50, start_point=0):

        # Load the dataset
        X_train, y_train = utils.load_data(self.writer)

        # Adversarial ground truths
        valid = np.ones((batch_size, 1))
        fake = np.zeros((batch_size, 1))

        for epoch in range(start_point, epochs):

            # ---------------------
            #  Train Discriminator
            # ---------------------

            # Select a random batch of images
            idx = np.random.randint(0, X_train.shape[0], batch_size)
            imgs = X_train[idx]

            # Sample noise as generator input
            noise = np.random.normal(0, 1, (batch_size, self.latent_dim))

            # The labels of the digits that the generator tries to create an
            # image representation of
            sampled_labels = np.random.uniform(0, 1, (batch_size, self.num_classes))
            sampled_labels = np.around(sampled_labels)

            # Generate a half batch of new images
            gen_imgs = self.generator.predict([noise, sampled_labels])

            # Image labels. 0-9 
            img_labels = y_train[idx]

            # Train the discriminator
            d_loss_real = self.discriminator.train_on_batch(imgs, [valid, img_labels])
            d_loss_fake = self.discriminator.train_on_batch(gen_imgs, [fake, sampled_labels])
            d_loss = 0.5 * np.add(d_loss_real, d_loss_fake)

            # ---------------------
            #  Train Generator
            # ---------------------

            # Train the generator
            g_loss = self.combined.train_on_batch([noise, sampled_labels], [valid, sampled_labels])

            # Plot the progress
            print("%d [D loss: %f, acc.: %.2f%%, op_acc: %.2f%%] [G loss: %f]" % (epoch, d_loss[0], 100*d_loss[3], 100*d_loss[4],  g_loss[0]))
            utils.write_log( self.writer, ['D loss', 'G loss', 'accuracy'], [d_loss[0], g_loss[0], 100*d_loss[3]], epoch)

            # If at save interval => save generated image samples
            if epoch % sample_interval == 0:
                utils.save_model('acgan/celeba', self.generator, self.discriminator, epoch)
                self.sample_images(epoch)

    def validate(self, glasses=False, male=False):
        noise = np.random.normal(0, 1, (10, self.latent_dim))
        
        if glasses or male:
            for j in range(10):
                noise = np.random.normal(0, 1, (10, self.latent_dim))
                fig, axs = plt.subplots(2, 10)
                label = np.array([[0, 0, 0, 0, 0] for _ in range(10)])
                img_default = 0.5 * self.generator.predict([noise, label]) + 0.5
                for i in range(10):
                    axs[0, i].imshow(img_default[i])
                    axs[0, i].axis('off')
                if glasses:
                    label = np.array([[0, 1, 0, 0, 0] for _ in range(10)])
                    img_condition = 0.5 * self.generator.predict([noise, label]) + 0.5
                elif male:
                    label = np.array([[0, 0, 1, 0, 0] for _ in range(10)])
                    img_condition = 0.5 * self.generator.predict([noise, label]) + 0.5
                for i in range(10):
                    axs[1, i].imshow(img_condition[i])
                    axs[1, i].axis('off')
                fig.savefig('../images_condition/validate{}{}.png'.format('_glasses' if glasses else '_male', j))
            return
            
        fig, axs = plt.subplots(4, 8)
        
        for i in range(2**5):
            label_str = "{:05b}".format(i)
            print(label_str)
            label = np.array([[int(label_str[j]) for j in range(len(label_str))] for _ in range(10)])
            imgs = 0.5 * self.generator.predict([noise, label]) + 0.5
            utils.write_image(self.writer, 'Image: {}'.format(label_str), imgs)
            axs[i//(2**3), i%(2**3)].imshow(imgs[0])
            axs[i//(2**3), i%(2**3)].axis('off')
        fig.savefig('../images_condition/validate{}{}.png'.format('_glasses' if glasses else '', '_male' if male else ''))
        plt.close()

    def sample_images(self, epoch):
        r, c = 10, 10
        noise = np.random.normal(0, 1, (r * c, self.latent_dim))
        sampled_labels = np.random.uniform(0, 1, (r*c, self.num_classes))
        sampled_labels = np.around(sampled_labels)
        gen_imgs = self.generator.predict([noise, sampled_labels])
        # Rescale images 0 - 1
        gen_imgs = 0.5 * gen_imgs + 0.5
        utils.write_image(self.writer, 'Generated Image', gen_imgs[:10], step=epoch)
        fig, axs = plt.subplots(r, c)
        cnt = 0
        for i in range(r):
            for j in range(c):
                axs[i,j].imshow(gen_imgs[cnt,:,:,:])
                axs[i,j].axis('off')
                cnt += 1
        fig.savefig("../images/acgan/%d.png" % epoch)
        plt.close()