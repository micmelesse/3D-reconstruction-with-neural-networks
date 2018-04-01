import os
import sys
import re
import json
import numpy as np
import tensorflow as tf
import matplotlib.pyplot as plt
from datetime import datetime
import lib.utils as utils
import lib.dataset as dataset
import lib.encoder_module as encoder_module
import lib.recurrent_module as recurrent_module
import lib.decoder_module as decoder_module
import lib.loss_module as loss_module

import lib.vis as vis


# Recurrent Reconstruction Neural Network (R2N2)
class Network:
    def __init__(self, params=None):
        # read params
        if params is None:
            params = utils.read_params()['TRAIN_PARAMS']

        self.LEARN_RATE = params['LEARN_RATE']
        self.BATCH_SIZE = params['BATCH_SIZE']
        self.EPOCH_COUNT = params['EPOCH_COUNT']
        self.CREATE_TIME = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
        self.MODEL_DIR = "out/model_{}_L:{}_E:{}_B:{}".format(
            self.CREATE_TIME, self.LEARN_RATE, self.EPOCH_COUNT, self.BATCH_SIZE)

        # place holders
        self.X = tf.placeholder(tf.float32, [None, 24, 137, 137, 4])

        # encoder
        print("encoder")
        encoder = encoder_module.Conv_Encoder(self.X)
        encoded_input = encoder.out_tensor

        print("recurrent_module")
        # recurrent_module
        with tf.name_scope("recurrent_module"):
            GRU_Grid = recurrent_module.GRU_Grid()
            hidden_state = None
            for t in range(24):
                hidden_state = GRU_Grid.call(
                    encoded_input[:, t, :], hidden_state)

        # decoder
        print("decoder")
        decoder = decoder_module.Conv_Decoder(hidden_state)
        self.logits = decoder.out_tensor

        # loss
        print("loss")
        self.Y = tf.placeholder(tf.uint8, [None, 32, 32, 32, 2])
        voxel_loss = loss_module.Voxel_Softmax(self.Y, self.logits)
        self.loss = voxel_loss.loss
        self.softmax = voxel_loss.softmax
        tf.summary.scalar('loss', self.loss)

        # optimizer
        print("optimizer")
        self.step_count = tf.Variable(
            0, trainable=False, name="step_count")
        optimizer = tf.train.GradientDescentOptimizer(
            learning_rate=self.LEARN_RATE)
        grads_and_vars = optimizer.compute_gradients(self.loss)
        self.apply_grad = optimizer.apply_gradients(
            grads_and_vars, global_step=self.step_count)

        # misc op
        print("misc op")
        self.print = tf.Print(
            self.loss, [self.step_count, self.LEARN_RATE, self.loss])
        self.summary_op = tf.summary.merge_all()
        self.sess = tf.InteractiveSession()

        print("initalize variables")
        tf.global_variables_initializer().run()

        # pointers to training objects
        self.train_writer = tf.summary.FileWriter(
            "{}/train".format(self.MODEL_DIR), self.sess.graph)
        self.val_writer = tf.summary.FileWriter(
            "{}/val".format(self.MODEL_DIR), self.sess.graph)
        self.test_writer = tf.summary.FileWriter(
            "{}/test".format(self.MODEL_DIR), self.sess.graph)

    def step(self, data, label, step_type):
        utils.make_dir(self.MODEL_DIR)
        cur_dir = self.get_epoch_dir()
        x, y = dataset.from_npy(data), dataset.from_npy(label)

        if step_type == "train":
            out = self.sess.run([self.apply_grad, self.loss, self.summary_op,  self.print, self.step_count], {
                self.X: x, self.Y: y})
            self.train_writer.add_summary(out[2], global_step=out[4])
        else:
            out = self.sess.run([self.softmax, self.loss, self.summary_op, self.print, self.step_count], {
                self.X: x, self.Y: y})

            if step_type == "val":
                self.val_writer.add_summary(out[2], global_step=out[4])
            elif step_type == "test":
                self.test_writer.add_summary(out[2], global_step=out[4])

            i = np.random.randint(0, len(data))
            x_name = utils.get_file_name(data[i])
            y_name = utils.get_file_name(label[i])
            f_name = x_name[0:-2]
            sequence, voxel, softmax, step_count = x[i], y[i], out[0][i], out[4]

            # save plots
            vis.sequence(
                sequence, f_name="{}/{}_{}.png".format(cur_dir, step_count, x_name))
            vis.softmax(voxel,
                        f_name="{}/{}_{}.png".format(cur_dir, step_count, y_name))
            vis.softmax(
                softmax, f_name="{}/{}_{}_p.png".format(cur_dir, step_count, f_name))
            np.save(
                "{}/{}_{}_sm.npy".format(cur_dir, step_count, f_name), softmax)

        return out[1]  # return the loss

    def save(self):
        cur_dir = self.get_epoch_dir()
        epoch_name = utils.grep_epoch_name(cur_dir)
        model_builder = tf.saved_model.builder.SavedModelBuilder(
            cur_dir + "/model")
        model_builder.add_meta_graph_and_variables(self.sess, [epoch_name])
        model_builder.save()

    def restore(self, epoch_dir):
        epoch_name = utils.grep_epoch_name(epoch_dir)
        new_sess = tf.Session(graph=tf.Graph())
        tf.saved_model.loader.load(
            new_sess, [epoch_name], epoch_dir + "/model")
        self.sess = new_sess

    def predict(self, x):
        return self.sess.run([self.softmax], {self.X: x})

    def info(self):
        print("LEARN_RATE:{}".format(
            self.LEARN_RATE))
        print("EPOCH_COUNT:{}".format(
            self.EPOCH_COUNT))
        print("BATCH_SIZE:{}".format(
            self.BATCH_SIZE))

    def create_epoch_dir(self):
        cur_ind = self.epoch_index()
        save_dir = os.path.join(self.MODEL_DIR, "epoch_{}".format(cur_ind+1))
        utils.make_dir(save_dir)
        return save_dir

    def get_epoch_dir(self):
        cur_ind = self.epoch_index()
        save_dir = os.path.join(
            self.MODEL_DIR, "epoch_{}".format(cur_ind))
        return save_dir

    def epoch_index(self):
        i = 0
        while os.path.exists(os.path.join(self.MODEL_DIR, "epoch_{}".format(i))):
            i += 1
        return i-1
